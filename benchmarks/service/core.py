"""Document attribution, scoring, provenance checks, and paired analysis."""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from pathlib import Path

from benchmarks.retrieval.src.retrieval_benchmark.metrics import evaluate_ranking

METRICS = ("recall@10", "recall@100", "mrr@10", "ndcg@10")


def finite_nonnegative(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("timing must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("timing must be finite and nonnegative")
    return number


def percentiles(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(finite_nonnegative(value) for value in values)

    def at(fraction: float) -> float:
        position = (len(ordered) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    return {"count": len(values), "p50": at(.50), "p95": at(.95), "p99": at(.99),
            "min": ordered[0], "max": ordered[-1]}


def score_response(query_id: str, response: dict, relevance: dict[str, int],
                   document_map: dict[str, str], *, elapsed_ms: float) -> dict:
    """Collapse ranked chunks by first document occurrence, never by qrel knowledge."""
    hits = response.get("results")
    if not isinstance(hits, list) or response.get("total") != len(hits) or len(hits) > 100:
        raise ValueError("invalid search results envelope")
    ranking, attribution, seen_chunks = [], [], set()
    for item in hits:
        chunk_id, document_id = item.get("chunk_id"), item.get("document_id")
        if not isinstance(chunk_id, str) or not chunk_id or chunk_id in seen_chunks:
            raise ValueError("missing or duplicate chunk ID")
        original_id = document_map.get(document_id)
        if original_id is None or item.get("metadata", {}).get("scifact_doc_id") != original_id:
            raise ValueError("unknown or conflicting chunk-to-document attribution")
        seen_chunks.add(chunk_id)
        attribution.append({"chunk_id": chunk_id, "document_id": document_id,
                            "scifact_doc_id": original_id})
        if original_id not in ranking:
            ranking.append(original_id)
    at10 = evaluate_ranking(ranking, relevance, cutoff=10)
    at100 = evaluate_ranking(ranking, relevance, cutoff=100)
    stages = response.get("latency_ms")
    providers = response.get("providers")
    if not isinstance(stages, dict) or not isinstance(providers, dict) or not providers:
        raise ValueError("missing timing or provider metadata")
    return {
        "query_id": query_id, "ranked_document_ids": ranking,
        "chunk_to_document": attribution, "returned_chunks": len(hits),
        "returned_unique_documents": len(ranking),
        "metrics": {"recall@10": at10.recall, "recall@100": at100.recall,
                    "mrr@10": at10.reciprocal_rank, "ndcg@10": at10.ndcg},
        "elapsed_ms": finite_nonnegative(elapsed_ms),
        "stage_ms": {key: finite_nonnegative(value) for key, value in stages.items()},
        "providers": dict(providers), "error": None,
    }


def aggregate(records: list[dict], expected_query_ids: list[str]) -> dict:
    ids = [row["query_id"] for row in records]
    if (not expected_query_ids or len(set(ids)) != len(ids)
            or len(set(expected_query_ids)) != len(expected_query_ids)
            or set(ids) != set(expected_query_ids)):
        raise ValueError("missing, duplicate, or unexpected query IDs")
    successful = [row for row in records if not row.get("error")]
    providers = {json.dumps(row["providers"], sort_keys=True) for row in successful}
    if len(providers) > 1:
        raise ValueError("provider configuration drifted during evaluation")
    quality = {
        metric: sum(row["metrics"][metric] if not row.get("error") else 0.0
                    for row in records) / len(records)
        for metric in METRICS
    }
    stages = sorted({key for row in successful for key in row["stage_ms"]})
    errors: dict[str, int] = {}
    for row in records:
        if row.get("error"):
            errors[row["error"]] = errors.get(row["error"], 0) + 1
    return {
        "query_count": len(records), "successful_queries": len(successful),
        "failed_queries": len(records) - len(successful), "errors": errors,
        "complete_without_errors": len(successful) == len(records),
        "quality_all_queries": quality,
        "http_latency_ms_successful": percentiles([row["elapsed_ms"] for row in successful]),
        "stage_latency_ms_successful": {
            key: percentiles([row["stage_ms"][key] for row in successful if key in row["stage_ms"]])
            for key in stages
        },
        "providers": json.loads(next(iter(providers))) if providers else None,
        "unique_document_window": percentiles([row["returned_unique_documents"] for row in successful]),
    }


def validate_runtime(runtime: dict, *, request_top_k: int) -> None:
    if not 1 <= request_top_k <= 100:
        raise ValueError("request_top_k must be within the API's 1..100 chunk window")
    query, ingestion = runtime["query_embedding"], runtime["ingestion_embedding"]
    if any(query.get(key) != ingestion.get(key) for key in ("provider", "model", "dimensions")):
        raise ValueError("query and ingestion embedding spaces differ; refusing a misleading run")
    if runtime["settings"]["retrieval_candidate_limit"] < request_top_k:
        raise ValueError("candidate limit is smaller than the requested chunk depth")


def verify_manifest(root: Path, expected_manifest_sha256: str) -> dict[str, str]:
    root = root.resolve()
    raw = (root / "manifest.sha256").read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_manifest_sha256:
        raise ValueError("dataset manifest differs from the frozen protocol")
    hashes = {}
    for line in raw.decode("utf-8").splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  (.+)", line)
        if not match:
            raise ValueError("malformed dataset manifest")
        digest, relative = match.groups()
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or Path(relative).is_absolute() or relative in hashes:
            raise ValueError("unsafe or duplicate dataset manifest path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"dataset checksum mismatch: {relative}")
        hashes[relative] = digest
    if not hashes:
        raise ValueError("empty dataset manifest")
    return hashes


def paired_comparison(current: dict, baseline: dict, metric: str, *,
                      samples: int = 2000, seed: int = 0) -> dict:
    for key in ("dataset_fingerprint", "split"):
        if current[key] != baseline[key]:
            raise ValueError(f"paired comparison requires an identical {key}")
    if samples < 1:
        raise ValueError("bootstrap sample count must be positive")

    def scores(run: dict) -> dict[str, float]:
        result = {}
        for row in run["per_query"]:
            if row["query_id"] in result:
                raise ValueError("duplicate query ID in paired run")
            result[row["query_id"]] = 0.0 if row.get("error") else float(row["metrics"][metric])
        return result

    left, right = scores(current), scores(baseline)
    if not left or left.keys() != right.keys():
        raise ValueError("paired comparison requires identical nonempty query IDs")
    deltas = {key: left[key] - right[key] for key in sorted(left)}
    values = list(deltas.values())
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(samples))
    return {
        "metric": metric, "mean_delta": sum(values) / len(values),
        "bootstrap_95_percent_interval": [means[int((samples - 1) * .025)], means[int((samples - 1) * .975)]],
        "bootstrap_samples": samples, "seed": seed, "per_query_delta": deltas,
        "method": "paired query bootstrap; percentile interval; not adjusted for multiple comparisons",
    }
