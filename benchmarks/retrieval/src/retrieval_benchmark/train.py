"""Train a SciFact reranker using train qrels and deterministic BM25 negatives only."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import random
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from .benchmark import (
    _atomic_json,
    _environment,
    _git_and_code_state,
    _model_artifact,
    stable_ranking,
    tokenize,
)
from .dataset import Document, Query, load_documents, load_qrels, load_queries
from .prepare import PROJECT_ROOT, sha256_file


@dataclass(frozen=True, slots=True)
class TrainingData:
    documents: tuple[Document, ...]
    queries: Mapping[str, Query]
    train_qrels: Mapping[str, Mapping[str, int]]
    test_query_ids: frozenset[str]
    paths: Mapping[str, Path]


@dataclass(frozen=True, slots=True)
class TrainingPair:
    query_id: str
    doc_id: str
    query_text: str
    document_text: str
    label: float


def load_training_data(dataset_dir: Path) -> TrainingData:
    paths = {
        "corpus": dataset_dir / "corpus.jsonl",
        "queries": dataset_dir / "queries.jsonl",
        "train_qrels": dataset_dir / "qrels/train.tsv",
        "test_qrels": dataset_dir / "qrels/test.tsv",
    }
    for name, path in paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"required {name} file is missing: {path}")

    documents = tuple(load_documents(paths["corpus"]))
    queries = {query.query_id: query for query in load_queries(paths["queries"])}
    train_qrels = load_qrels(paths["train_qrels"])
    test_qrels = load_qrels(paths["test_qrels"])
    train_query_ids = frozenset(train_qrels)
    test_query_ids = frozenset(test_qrels)
    overlap = train_query_ids & test_query_ids
    if overlap:
        raise ValueError(
            f"split isolation failed: {len(overlap)} query IDs occur in train and test qrels"
        )
    missing_queries = (train_query_ids | test_query_ids).difference(queries)
    if missing_queries:
        raise ValueError(f"qrels reference {len(missing_queries)} missing queries")
    corpus_ids = {document.doc_id for document in documents}
    missing_docs = {
        doc_id
        for qrels in (train_qrels, test_qrels)
        for relevance in qrels.values()
        for doc_id in relevance
        if doc_id not in corpus_ids
    }
    if missing_docs:
        raise ValueError(f"qrels reference {len(missing_docs)} missing corpus documents")
    if not train_query_ids:
        raise ValueError("training qrels contain no positively relevant queries")
    return TrainingData(
        documents=documents,
        queries=queries,
        train_qrels=train_qrels,
        test_query_ids=test_query_ids,
        paths=paths,
    )


def mine_training_pairs(
    data: TrainingData, *, negatives_per_query: int, seed: int
) -> list[TrainingPair]:
    """Create positive pairs and top non-relevant BM25 negatives for train queries."""

    if negatives_per_query < 1:
        raise ValueError("negatives_per_query must be positive")
    rank_bm25 = importlib.import_module("rank_bm25")
    documents_by_id = {document.doc_id: document for document in data.documents}
    doc_ids = [document.doc_id for document in data.documents]
    bm25 = rank_bm25.BM25Okapi(
        [tokenize(document.searchable_text) for document in data.documents],
        k1=1.5,
        b=0.75,
        epsilon=0.25,
    )
    pairs: list[TrainingPair] = []
    for query_id in sorted(data.train_qrels):
        if query_id in data.test_query_ids:
            raise AssertionError(f"test query leaked into training: {query_id}")
        query = data.queries[query_id]
        positives = sorted(
            doc_id for doc_id, score in data.train_qrels[query_id].items() if score > 0
        )
        if not positives:
            continue
        for doc_id in positives:
            pairs.append(
                TrainingPair(
                    query_id=query_id,
                    doc_id=doc_id,
                    query_text=query.text,
                    document_text=documents_by_id[doc_id].searchable_text,
                    label=1.0,
                )
            )
        scores = np.asarray(bm25.get_scores(tokenize(query.text)), dtype=np.float64)
        ranking = stable_ranking(scores, doc_ids, len(doc_ids))
        negatives = [doc_id for doc_id, _ in ranking if doc_id not in positives][
            :negatives_per_query
        ]
        if len(negatives) != negatives_per_query:
            raise ValueError(f"not enough negative documents for train query {query_id}")
        for doc_id in negatives:
            pairs.append(
                TrainingPair(
                    query_id=query_id,
                    doc_id=doc_id,
                    query_text=query.text,
                    document_text=documents_by_id[doc_id].searchable_text,
                    label=0.0,
                )
            )
    random.Random(seed).shuffle(pairs)
    if any(pair.query_id in data.test_query_ids for pair in pairs):
        raise AssertionError("test query IDs were included in mined training pairs")
    return pairs


def _dataset_config(data: TrainingData) -> dict[str, Any]:
    return {
        "corpus_sha256": sha256_file(data.paths["corpus"]),
        "queries_sha256": sha256_file(data.paths["queries"]),
        "train_qrels_sha256": sha256_file(data.paths["train_qrels"]),
        "test_qrels_sha256": sha256_file(data.paths["test_qrels"]),
        "train_query_count": len(data.train_qrels),
        "test_query_count": len(data.test_query_ids),
        "corpus_count": len(data.documents),
        "split_isolation": {
            "asserted_disjoint": True,
            "train_test_overlap_count": 0,
            "training_source": "qrels/train.tsv",
            "test_qrels_used_for_training": False,
        },
    }


def _pairs_sha256(pairs: Sequence[TrainingPair]) -> str:
    digest = hashlib.sha256()
    for pair in pairs:
        digest.update(f"{pair.query_id}\t{pair.doc_id}\t{pair.label:.1f}\n".encode())
    return digest.hexdigest()


def train(args: argparse.Namespace) -> dict[str, Any]:
    output_dir: Path = args.output_dir
    working_dir = output_dir.with_name(output_dir.name + ".working")
    if output_dir.exists() or working_dir.exists():
        raise FileExistsError(
            f"refusing to overwrite model output or working directory: {output_dir}"
        )
    base_model = Path(args.base_model)
    if not base_model.is_dir():
        raise FileNotFoundError("--base-model must be a local all-MiniLM-L6-v2 directory")

    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    started = perf_counter()
    data = load_training_data(args.dataset_dir)
    pairs = mine_training_pairs(data, negatives_per_query=args.negatives_per_query, seed=args.seed)
    positives = sum(pair.label == 1.0 for pair in pairs)
    negatives = len(pairs) - positives

    torch = importlib.import_module("torch")
    torch.set_num_threads(args.torch_threads)
    torch.manual_seed(args.seed)
    torch.use_deterministic_algorithms(True)
    sentence_transformers = importlib.import_module("sentence_transformers")
    data_loader_module = importlib.import_module("torch.utils.data")
    examples = [
        sentence_transformers.InputExample(
            texts=[pair.query_text, pair.document_text], label=pair.label
        )
        for pair in pairs
    ]
    generator = torch.Generator().manual_seed(args.seed)
    loader = data_loader_module.DataLoader(
        examples,
        shuffle=True,
        batch_size=args.batch_size,
        num_workers=0,
        generator=generator,
    )
    steps = math.ceil(len(examples) / args.batch_size) * args.epochs
    warmup_steps = math.ceil(steps * args.warmup_ratio)
    model = sentence_transformers.CrossEncoder(
        str(base_model),
        num_labels=1,
        max_length=args.max_length,
        device="cpu",
        local_files_only=True,
    )
    working_dir.parent.mkdir(parents=True, exist_ok=True)
    model.fit(
        train_dataloader=loader,
        epochs=args.epochs,
        warmup_steps=warmup_steps,
        optimizer_params={"lr": args.learning_rate},
        output_path=str(working_dir),
        save_best_model=False,
        show_progress_bar=True,
        use_amp=False,
    )
    model.save(str(working_dir))
    duration_seconds = perf_counter() - started

    model_artifact = _model_artifact(str(working_dir), "local-trained")
    config: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "duration_seconds": duration_seconds,
        "seed": args.seed,
        "device": "cpu",
        "dtype": "float32",
        "deterministic_algorithms": True,
        "dataset": _dataset_config(data),
        "base_model": _model_artifact(str(base_model), "local-base"),
        "training": {
            "implementation": "sentence_transformers.CrossEncoder.fit",
            "loss": "BCEWithLogitsLoss (CrossEncoder single-label default)",
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "learning_rate": args.learning_rate,
            "warmup_ratio": args.warmup_ratio,
            "warmup_steps": warmup_steps,
            "max_length": args.max_length,
            "torch_threads": args.torch_threads,
            "negatives_per_query": args.negatives_per_query,
            "negative_miner": {
                "implementation": "rank_bm25.BM25Okapi",
                "k1": 1.5,
                "b": 0.75,
                "epsilon": 0.25,
                "tie_breaker": "document_id ascending",
            },
            "positive_pair_count": positives,
            "negative_pair_count": negatives,
            "total_pair_count": len(pairs),
            "training_pairs_sha256": _pairs_sha256(pairs),
            "optimizer_step_count": steps,
        },
        "output_model": {
            "tree_sha256_before_training_config": model_artifact["tree_sha256"],
            "file_count_before_training_config": model_artifact["file_count"],
        },
        "code": _git_and_code_state(),
        "hardware": _environment(),
    }
    _atomic_json(working_dir / "training_config.json", config)
    working_dir.replace(output_dir)
    return config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-dir", type=Path, default=PROJECT_ROOT.parent / "datasets/scifact/v1"
    )
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--negatives-per-query", type=int, default=3)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--warmup-ratio", type=float, default=0.1)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--torch-threads", type=int, default=max(1, min(8, os.cpu_count() or 1)))
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    if any(
        value < 1
        for value in (
            args.negatives_per_query,
            args.epochs,
            args.batch_size,
            args.max_length,
            args.torch_threads,
        )
    ):
        parser.error("negative count, epochs, batch size, max length, and threads must be positive")
    if args.learning_rate <= 0:
        parser.error("learning rate must be positive")
    if not 0 <= args.warmup_ratio <= 1:
        parser.error("warmup ratio must be between 0 and 1")
    try:
        config = train(args)
    except (OSError, ValueError, RuntimeError, AssertionError) as exc:
        print(f"training failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(config, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
