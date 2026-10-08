"""Run the pinned CPU-only SciFact hybrid retrieval benchmark."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import re
import statistics
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import numpy as np
import numpy.typing as npt

from .dataset import Dataset, load_dataset
from .metrics import evaluate_ranking, reciprocal_rank_fusion
from .prepare import PROJECT_ROOT, sha256_file

SCHEMA_VERSION = 1
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_REVISION = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
DEFAULT_RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
DEFAULT_RERANK_REVISION = "c5ee24cb16019beea0895867c17ab30d22fd12ee"
_TOKEN_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.casefold())


def stable_ranking(
    scores: npt.NDArray[np.floating[Any]], doc_ids: Sequence[str], depth: int
) -> list[tuple[str, float]]:
    if scores.ndim != 1 or len(scores) != len(doc_ids):
        raise ValueError("scores and document IDs must be aligned one-dimensional arrays")
    if depth < 1:
        raise ValueError("ranking depth must be positive")
    # Full lexsort is cheap for SciFact (5K documents) and gives deterministic ID
    # tie-breaking that argpartition alone cannot guarantee.
    ids = np.asarray(doc_ids, dtype=str)
    indexes = np.lexsort((ids, -scores))[:depth]
    return [(doc_ids[int(index)], float(scores[int(index)])) for index in indexes]


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _model_artifact(reference: str, revision: str) -> dict[str, Any]:
    path = Path(reference)
    if not path.exists():
        return {
            "kind": "huggingface",
            "model_id": reference,
            "revision": revision,
            "artifact_sha": revision,
        }
    if not path.is_dir():
        raise ValueError(f"local model reference is not a directory: {path}")
    digest = hashlib.sha256()
    files: dict[str, str] = {}
    for file_path in sorted(path.rglob("*")):
        if not file_path.is_file() or ".git" in file_path.relative_to(path).parts:
            continue
        relative = str(file_path.relative_to(path))
        file_digest = sha256_file(file_path)
        files[relative] = file_digest
        digest.update(relative.encode())
        digest.update(file_digest.encode())
    if not files:
        raise ValueError(f"local model directory contains no files: {path}")
    return {
        "kind": "local-directory",
        "path": str(path.resolve()),
        "tree_sha256": digest.hexdigest(),
        "file_count": len(files),
        "files_sha256": files,
    }


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _environment() -> dict[str, Any]:
    try:
        physical_ram_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (OSError, ValueError):
        physical_ram_bytes = None
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "physical_ram_bytes": physical_ram_bytes,
        "packages": {
            name: _package_version(name)
            for name in ("numpy", "rank-bm25", "sentence-transformers", "torch", "transformers")
        },
    }


def _git_and_code_state() -> dict[str, Any]:
    repository_root = PROJECT_ROOT.parents[1]

    def git(*arguments: str) -> str | None:
        try:
            completed = subprocess.run(
                ["git", *arguments],
                cwd=repository_root,
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None
        return completed.stdout.strip()

    revision = git("rev-parse", "HEAD")
    status = git("status", "--porcelain", "--untracked-files=normal")
    digest = hashlib.sha256()
    included = [PROJECT_ROOT / "pyproject.toml", PROJECT_ROOT / "uv.lock"]
    included.extend(sorted((PROJECT_ROOT / "src").rglob("*.py")))
    for path in included:
        digest.update(str(path.relative_to(PROJECT_ROOT)).encode())
        digest.update(path.read_bytes())
    return {
        "repository_revision": revision,
        "repository_dirty": None if status is None else bool(status),
        "benchmark_tree_sha256": digest.hexdigest(),
    }


def _dataset_provenance(dataset_dir: Path, dataset: Dataset) -> dict[str, Any]:
    provenance: dict[str, Any] = {
        "name": "BEIR SciFact",
        "split": "test",
        "fingerprint": dataset.fingerprint,
    }
    state_path = dataset_dir / "dataset_state.json"
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("dataset_fingerprint") != dataset.fingerprint:
            raise ValueError("dataset_state.json fingerprint does not match loaded files")
        source = str(state.pop("source", ""))
        provenance["preparation_source"] = (
            source if source.startswith(("https://", "http://")) else "local-verified-copy"
        )
        provenance["prepared_state"] = state
        provenance["dataset_state_sha256"] = sha256_file(state_path)
    for name in ("metadata.json", "manifest.sha256"):
        path = dataset_dir / name
        if path.is_file():
            provenance[f"{name}_sha256"] = sha256_file(path)
    return provenance


def _embedding_cache_key(config: Mapping[str, Any], dataset: Dataset) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_fingerprint": dataset.fingerprint,
        "doc_ids_sha256": hashlib.sha256(
            "\n".join(document.doc_id for document in dataset.documents).encode()
        ).hexdigest(),
        "model": config["embedding_model"],
        "revision": config["embedding_revision"],
        "normalized": True,
        "dtype": "float32",
    }


def _load_or_encode_corpus(
    embedder: Any,
    dataset: Dataset,
    config: Mapping[str, Any],
    cache_dir: Path,
) -> npt.NDArray[np.float32]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    matrix_path = cache_dir / "corpus_embeddings.npy"
    metadata_path = cache_dir / "corpus_embeddings.json"
    expected = _embedding_cache_key(config, dataset)
    if matrix_path.is_file() and metadata_path.is_file():
        actual = json.loads(metadata_path.read_text(encoding="utf-8"))
        if actual == expected:
            matrix = np.load(matrix_path, mmap_mode="r")
            if matrix.ndim == 2 and matrix.shape[0] == len(dataset.documents):
                return cast(npt.NDArray[np.float32], matrix)

    texts = [document.searchable_text for document in dataset.documents]
    encoded = embedder.encode(
        texts,
        batch_size=int(config["embedding_batch_size"]),
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    matrix = np.asarray(encoded, dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[0] != len(texts) or not np.isfinite(matrix).all():
        raise ValueError("embedding model returned an invalid corpus matrix")
    temporary = matrix_path.with_suffix(".npy.part")
    with temporary.open("wb") as stream:
        np.save(stream, matrix, allow_pickle=False)
    temporary.replace(matrix_path)
    _atomic_json(metadata_path, expected)
    return cast(npt.NDArray[np.float32], np.load(matrix_path, mmap_mode="r"))


def _load_models(config: Mapping[str, Any], offline: bool) -> tuple[Any, Any]:
    module = importlib.import_module("sentence_transformers")
    embedder = module.SentenceTransformer(
        config["embedding_model"],
        revision=config["embedding_revision"],
        device="cpu",
        local_files_only=offline,
    )
    reranker = module.CrossEncoder(
        config["rerank_model"],
        revision=config["rerank_revision"],
        device="cpu",
        local_files_only=offline,
    )
    return embedder, reranker


def _load_bm25(dataset: Dataset) -> Any:
    module = importlib.import_module("rank_bm25")
    corpus_tokens = [tokenize(document.searchable_text) for document in dataset.documents]
    return module.BM25Okapi(corpus_tokens, k1=1.5, b=0.75, epsilon=0.25)


def _read_completed(path: Path, run_id: str) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    completed: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid partial result at {path}:{line_number}") from exc
            if record.get("run_id") != run_id:
                raise ValueError("per-query results belong to a different run configuration")
            query_id = str(record["query_id"])
            if query_id in completed:
                raise ValueError(f"duplicate completed query {query_id!r}")
            completed[query_id] = record
    return completed


def _rank_payload(ranking: Sequence[tuple[str, float]], depth: int) -> list[dict[str, Any]]:
    return [
        {"rank": rank, "doc_id": doc_id, "score": score}
        for rank, (doc_id, score) in enumerate(ranking[:depth], start=1)
    ]


def _run_query(
    *,
    query_id: str,
    query_text: str,
    relevant: Mapping[str, int],
    dataset: Dataset,
    bm25: Any,
    embedder: Any,
    reranker: Any,
    corpus_embeddings: npt.NDArray[np.float32],
    config: Mapping[str, Any],
    run_id: str,
) -> dict[str, Any]:
    doc_ids = [document.doc_id for document in dataset.documents]
    texts_by_id = {document.doc_id: document.searchable_text for document in dataset.documents}
    candidate_depth = int(config["candidate_depth"])
    metric_cutoff = int(config["metric_cutoff"])

    started = perf_counter()
    bm25_scores = np.asarray(bm25.get_scores(tokenize(query_text)), dtype=np.float64)
    bm25_ranking = stable_ranking(bm25_scores, doc_ids, candidate_depth)
    bm25_ms = (perf_counter() - started) * 1000

    started = perf_counter()
    query_embedding = np.asarray(
        embedder.encode(
            [query_text],
            batch_size=1,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )[0],
        dtype=np.float32,
    )
    if query_embedding.ndim != 1 or not np.isfinite(query_embedding).all():
        raise ValueError("embedding model returned an invalid query vector")
    vector_scores = np.asarray(corpus_embeddings @ query_embedding, dtype=np.float32)
    vector_ranking = stable_ranking(vector_scores, doc_ids, candidate_depth)
    vector_ms = (perf_counter() - started) * 1000

    started = perf_counter()
    fused_ids, contributions = reciprocal_rank_fusion(
        {
            "bm25": [doc_id for doc_id, _ in bm25_ranking],
            "vector": [doc_id for doc_id, _ in vector_ranking],
        },
        k=int(config["rrf_k"]),
        depth=candidate_depth,
    )
    fused_ids = fused_ids[:candidate_depth]
    fused_ranking = [(doc_id, sum(contributions[doc_id].values())) for doc_id in fused_ids]
    fusion_ms = (perf_counter() - started) * 1000

    started = perf_counter()
    rerank_ids = fused_ids[: int(config["rerank_depth"])]
    pairs = [(query_text, texts_by_id[doc_id]) for doc_id in rerank_ids]
    predicted = np.asarray(
        reranker.predict(
            pairs,
            batch_size=int(config["rerank_batch_size"]),
            show_progress_bar=False,
        ),
        dtype=np.float64,
    ).reshape(-1)
    if len(predicted) != len(rerank_ids) or not np.isfinite(predicted).all():
        raise ValueError("cross-encoder returned invalid reranking scores")
    reranked = stable_ranking(predicted, rerank_ids, len(rerank_ids))
    rerank_ms = (perf_counter() - started) * 1000

    rankings = {
        "bm25": bm25_ranking,
        "vector": vector_ranking,
        "rrf": fused_ranking,
        "rerank": reranked,
    }
    stage_latency = {
        "bm25": bm25_ms,
        "vector": vector_ms,
        "fusion": fusion_ms,
        "rerank": rerank_ms,
    }
    end_to_end = {
        "bm25": bm25_ms,
        "vector": vector_ms,
        "rrf": bm25_ms + vector_ms + fusion_ms,
        "rerank": bm25_ms + vector_ms + fusion_ms + rerank_ms,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "query_id": query_id,
        "relevant_count": sum(score > 0 for score in relevant.values()),
        "relevant_ids": sorted(doc_id for doc_id, score in relevant.items() if score > 0),
        "metrics": {
            method: evaluate_ranking(
                [doc_id for doc_id, _ in ranking], relevant, cutoff=metric_cutoff
            ).as_dict(metric_cutoff)
            for method, ranking in rankings.items()
        },
        "stage_latency_ms": stage_latency,
        "end_to_end_latency_ms": end_to_end,
        "rankings": {
            method: _rank_payload(ranking, candidate_depth) for method, ranking in rankings.items()
        },
    }


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("cannot compute a percentile of an empty sequence")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _summarize(
    records: Sequence[Mapping[str, Any]],
    run_config: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    methods = ("bm25", "vector", "rrf", "rerank")
    cutoff = int(run_config["benchmark"]["metric_cutoff"])
    metric_names = (f"recall@{cutoff}", f"mrr@{cutoff}", f"ndcg@{cutoff}")
    aggregate: dict[str, Any] = {}
    for method in methods:
        latencies = [float(record["end_to_end_latency_ms"][method]) for record in records]
        aggregate[method] = {
            "metrics": {
                metric: statistics.fmean(
                    float(record["metrics"][method][metric]) for record in records
                )
                for metric in metric_names
            },
            "latency_ms": {
                "p50": _percentile(latencies, 0.50),
                "p95": _percentile(latencies, 0.95),
                "mean": statistics.fmean(latencies),
            },
        }
    per_query_path = output_dir / "per_query.jsonl"
    config_path = output_dir / "run_config.json"
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_config["run_id"],
        "dataset": run_config["dataset"],
        "corpus_count": run_config["corpus_count"],
        "query_count": len(records),
        "methods": aggregate,
        "config": run_config["benchmark"],
        "environment": run_config["environment"],
        "code": run_config["code"],
        "artifacts_sha256": {
            "run_config.json": sha256_file(config_path),
            "per_query.jsonl": sha256_file(per_query_path),
        },
    }


def _markdown(summary: Mapping[str, Any]) -> str:
    cutoff = summary["config"]["metric_cutoff"]
    lines = [
        "# SciFact retrieval benchmark",
        "",
        f"Run ID: `{summary['run_id']}`  ",
        f"Corpus: {summary['corpus_count']} documents; {summary['query_count']} test queries.",
        "",
        f"| Method | Recall@{cutoff} | MRR@{cutoff} | nDCG@{cutoff} | p50 ms | p95 ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for method in ("bm25", "vector", "rrf", "rerank"):
        result = summary["methods"][method]
        metrics = result["metrics"]
        latency = result["latency_ms"]
        lines.append(
            f"| {method} | {metrics[f'recall@{cutoff}']:.4f} | "
            f"{metrics[f'mrr@{cutoff}']:.4f} | {metrics[f'ndcg@{cutoff}']:.4f} | "
            f"{latency['p50']:.2f} | {latency['p95']:.2f} |"
        )
    lines.extend(
        [
            "",
            "Latency is per query on CPU. BM25/vector are standalone; RRF includes both candidate "
            "retrievers and fusion; rerank includes retrieval, fusion, and cross-encoder scoring. "
            "Model loading, corpus indexing/embedding, and warmup are excluded.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    dataset = load_dataset(args.dataset_dir)
    benchmark_config = {
        "embedding_model": args.embedding_model,
        "embedding_revision": args.embedding_revision,
        "embedding_batch_size": args.embedding_batch_size,
        "embedding_normalized": True,
        "similarity": "cosine-via-normalized-dot-product",
        "bm25": {"implementation": "rank_bm25.BM25Okapi", "k1": 1.5, "b": 0.75},
        "candidate_depth": args.candidate_depth,
        "rrf_k": args.rrf_k,
        "rerank_model": args.rerank_model,
        "rerank_revision": args.rerank_revision,
        "rerank_depth": args.rerank_depth,
        "rerank_batch_size": args.rerank_batch_size,
        "model_artifacts": {
            "embedding": _model_artifact(args.embedding_model, args.embedding_revision),
            "reranker": _model_artifact(args.rerank_model, args.rerank_revision),
        },
        "metric_cutoff": args.metric_cutoff,
        "device": "cpu",
        "effective_dtype": {
            "embeddings": "float32",
            "cosine_scores": "float32",
            "bm25_scores": "float64",
            "reranker_scores": "float64",
        },
        "torch_threads": args.torch_threads,
        "hardware_note": args.hardware_note,
        "seed": 0,
        "timing": "perf_counter; warmup/model-load/index/corpus-embedding excluded",
    }
    identity = {
        "schema_version": SCHEMA_VERSION,
        "dataset": _dataset_provenance(args.dataset_dir, dataset),
        "benchmark": benchmark_config,
        "environment": _environment(),
        "code": _git_and_code_state(),
    }
    run_id = _canonical_hash(identity)[:16]
    run_config = {
        **identity,
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "dataset": identity["dataset"],
        "dataset_dir": str(args.dataset_dir.resolve()),
        "corpus_count": len(dataset.documents),
        "query_count": len(dataset.queries),
    }
    output_dir = args.output_dir or PROJECT_ROOT / "results/scifact" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / "run_config.json"
    if config_path.exists():
        previous = json.loads(config_path.read_text(encoding="utf-8"))
        if previous.get("run_id") != run_id:
            raise ValueError("output directory contains a different run configuration")
        run_config = previous
    else:
        _atomic_json(config_path, run_config)

    per_query_path = output_dir / "per_query.jsonl"
    completed = _read_completed(per_query_path, run_id)
    expected_ids = {query.query_id for query in dataset.queries}
    unknown = set(completed).difference(expected_ids)
    if unknown:
        raise ValueError(f"partial results contain {len(unknown)} unknown query IDs")

    pending = [query for query in dataset.queries if query.query_id not in completed]
    if pending:
        torch = importlib.import_module("torch")
        torch.set_num_threads(args.torch_threads)
        torch.manual_seed(0)
        bm25 = _load_bm25(dataset)
        embedder, reranker = _load_models(benchmark_config, args.offline)
        corpus_embeddings = _load_or_encode_corpus(
            embedder, dataset, benchmark_config, args.cache_dir
        )
        # Warm both neural providers and BM25 before measuring query latency.
        bm25.get_scores(tokenize(pending[0].text))
        embedder.encode([pending[0].text], show_progress_bar=False, normalize_embeddings=True)
        reranker.predict([(pending[0].text, dataset.documents[0].searchable_text)])
        with per_query_path.open("a", encoding="utf-8", buffering=1) as output:
            for number, query in enumerate(pending, start=1):
                record = _run_query(
                    query_id=query.query_id,
                    query_text=query.text,
                    relevant=dataset.qrels[query.query_id],
                    dataset=dataset,
                    bm25=bm25,
                    embedder=embedder,
                    reranker=reranker,
                    corpus_embeddings=corpus_embeddings,
                    config=benchmark_config,
                    run_id=run_id,
                )
                output.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
                completed[query.query_id] = record
                print(f"[{number}/{len(pending)}] query={query.query_id}", file=sys.stderr)

    records = [completed[query.query_id] for query in dataset.queries]
    summary = _summarize(records, run_config, output_dir)
    _atomic_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(_markdown(summary), encoding="utf-8")
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=PROJECT_ROOT / ".cache/data/scifact")
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_ROOT / ".cache/models")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--embedding-revision", default=DEFAULT_EMBEDDING_REVISION)
    parser.add_argument("--embedding-batch-size", type=int, default=64)
    parser.add_argument("--rerank-model", default=DEFAULT_RERANK_MODEL)
    parser.add_argument("--rerank-revision", default=DEFAULT_RERANK_REVISION)
    parser.add_argument("--rerank-batch-size", type=int, default=32)
    parser.add_argument("--candidate-depth", type=int, default=100)
    parser.add_argument("--rerank-depth", type=int, default=100)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--metric-cutoff", type=int, default=10)
    parser.add_argument("--torch-threads", type=int, default=max(1, min(8, os.cpu_count() or 1)))
    parser.add_argument(
        "--hardware-note",
        default=None,
        help="Optional CPU/VM details not discoverable from the operating system",
    )
    parser.add_argument("--offline", action="store_true", help="Require models in local HF cache")
    return parser


def main() -> None:
    args = _parser().parse_args()
    positive = (
        "embedding_batch_size",
        "rerank_batch_size",
        "candidate_depth",
        "rerank_depth",
        "rrf_k",
        "metric_cutoff",
        "torch_threads",
    )
    if any(getattr(args, name) < 1 for name in positive):
        _parser().error("batch sizes, depths, cutoff, RRF k, and thread count must be positive")
    if args.rerank_depth > args.candidate_depth:
        _parser().error("rerank depth cannot exceed candidate depth")
    try:
        summary = run(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
