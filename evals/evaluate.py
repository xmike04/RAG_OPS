"""Evaluate a ranked retrieval run without services or external dependencies."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class EvaluationError(ValueError):
    """Raised when an evaluation artifact violates the documented contract."""


_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "what",
    "when",
    "with",
}


@dataclass(frozen=True)
class Threshold:
    path: str
    minimum: float


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load non-empty JSON objects from a UTF-8 JSONL file."""
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise EvaluationError(
                        f"{path}:{line_number}: invalid JSON: {exc.msg}"
                    ) from exc
                if not isinstance(value, dict):
                    raise EvaluationError(
                        f"{path}:{line_number}: each row must be a JSON object"
                    )
                rows.append(value)
    except OSError as exc:
        raise EvaluationError(f"cannot read {path}: {exc}") from exc
    if not rows:
        raise EvaluationError(f"{path}: no data rows")
    return rows


def _required_string(row: dict[str, Any], field: str, context: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError(f"{context}: {field} must be a non-empty string")
    return value


def _unique_by(
    rows: Iterable[dict[str, Any]], field: str, kind: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows, start=1):
        key = _required_string(row, field, f"{kind} row {index}")
        if key in result:
            raise EvaluationError(f"duplicate {kind} {field}: {key}")
        result[key] = row
    return result


def _string_list(value: Any, context: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise EvaluationError(f"{context} must be a list of non-empty strings")
    if not allow_empty and not value:
        raise EvaluationError(f"{context} must not be empty")
    if len(value) != len(set(value)):
        raise EvaluationError(f"{context} must not contain duplicates")
    return value


def _validate_inputs(
    queries: Sequence[dict[str, Any]],
    corpus: Sequence[dict[str, Any]],
    run: Sequence[dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    query_by_id = _unique_by(queries, "query_id", "query")
    chunk_by_id = _unique_by(corpus, "chunk_id", "corpus")
    run_by_id = _unique_by(run, "query_id", "run")

    for chunk_id, chunk in chunk_by_id.items():
        _required_string(chunk, "document_id", f"corpus chunk {chunk_id}")
        _required_string(chunk, "text", f"corpus chunk {chunk_id}")

    for query_id, query in query_by_id.items():
        _required_string(query, "query", f"query {query_id}")
        relevant = _string_list(
            query.get("relevant_chunk_ids"),
            f"query {query_id} relevant_chunk_ids",
            allow_empty=False,
        )
        unknown = sorted(set(relevant) - chunk_by_id.keys())
        if unknown:
            raise EvaluationError(
                f"query {query_id} references unknown relevant chunks: {unknown}"
            )

    missing = sorted(query_by_id.keys() - run_by_id.keys())
    unexpected = sorted(run_by_id.keys() - query_by_id.keys())
    if missing or unexpected:
        raise EvaluationError(
            f"run/query mismatch: missing={missing or 'none'}, "
            f"unexpected={unexpected or 'none'}"
        )

    for query_id, row in run_by_id.items():
        latency = row.get("latency_ms")
        if isinstance(latency, bool) or not isinstance(latency, (int, float)):
            raise EvaluationError(f"run {query_id} latency_ms must be a number")
        if not math.isfinite(float(latency)) or latency < 0:
            raise EvaluationError(
                f"run {query_id} latency_ms must be finite and non-negative"
            )
        results = row.get("results")
        if not isinstance(results, list):
            raise EvaluationError(f"run {query_id} results must be a list")
        result_ids: list[str] = []
        for rank, result in enumerate(results, start=1):
            if not isinstance(result, dict):
                raise EvaluationError(
                    f"run {query_id} result at rank {rank} must be an object"
                )
            result_ids.append(
                _required_string(result, "chunk_id", f"run {query_id} rank {rank}")
            )
            score = result.get("score")
            if score is not None and (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(float(score))
            ):
                raise EvaluationError(
                    f"run {query_id} rank {rank} score must be a finite number"
                )
        if len(result_ids) != len(set(result_ids)):
            raise EvaluationError(f"run {query_id} contains duplicate result chunks")
        unknown_results = sorted(set(result_ids) - chunk_by_id.keys())
        if unknown_results:
            raise EvaluationError(
                f"run {query_id} references unknown result chunks: {unknown_results}"
            )

        answer = row.get("answer")
        if answer is not None:
            if not isinstance(answer, dict) or not isinstance(answer.get("claims"), list):
                raise EvaluationError(
                    f"run {query_id} answer must be an object with a claims list"
                )
            for claim_index, claim in enumerate(answer["claims"], start=1):
                context = f"run {query_id} claim {claim_index}"
                if not isinstance(claim, dict):
                    raise EvaluationError(f"{context} must be an object")
                _required_string(claim, "text", context)
                _string_list(claim.get("citations"), f"{context} citations")

    return query_by_id, chunk_by_id, run_by_id


def _dcg(relevance: Sequence[int]) -> float:
    return sum(value / math.log2(rank + 1) for rank, value in enumerate(relevance, 1))


def _percentile(values: Sequence[float], percentile: float) -> float:
    """Return a deterministic nearest-rank percentile."""
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _content_tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN.findall(text)
        if len(token) > 1 and token.lower() not in _STOP_WORDS
    }


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate(
    queries: Sequence[dict[str, Any]],
    corpus: Sequence[dict[str, Any]],
    run: Sequence[dict[str, Any]],
    cutoffs: Sequence[int],
) -> dict[str, Any]:
    """Validate artifacts and calculate retrieval, citation, and latency metrics."""
    if not cutoffs or any(isinstance(k, bool) or not isinstance(k, int) or k < 1 for k in cutoffs):
        raise EvaluationError("cutoffs must be positive integers")
    normalized_cutoffs = sorted(set(cutoffs))
    query_by_id, chunk_by_id, run_by_id = _validate_inputs(queries, corpus, run)

    recall: dict[int, list[float]] = {k: [] for k in normalized_cutoffs}
    ndcg: dict[int, list[float]] = {k: [] for k in normalized_cutoffs}
    reciprocal_ranks: list[float] = []
    latencies: list[float] = []
    claim_coverage: list[float] = []
    claim_faithfulness: list[float] = []
    citation_validity: list[float] = []
    per_query: list[dict[str, Any]] = []

    for query_id, query in query_by_id.items():
        row = run_by_id[query_id]
        relevant = set(query["relevant_chunk_ids"])
        result_ids = [result["chunk_id"] for result in row["results"]]
        query_metrics: dict[str, Any] = {"query_id": query_id}

        for k in normalized_cutoffs:
            hits = len(relevant.intersection(result_ids[:k]))
            recall_value = hits / len(relevant)
            relevance = [int(chunk_id in relevant) for chunk_id in result_ids[:k]]
            relevance.extend([0] * (k - len(relevance)))
            ideal = [1] * min(len(relevant), k)
            ndcg_value = _dcg(relevance) / _dcg(ideal)
            recall[k].append(recall_value)
            ndcg[k].append(ndcg_value)
            query_metrics[f"recall@{k}"] = recall_value
            query_metrics[f"ndcg@{k}"] = ndcg_value

        first_rank = next(
            (rank for rank, chunk_id in enumerate(result_ids, start=1) if chunk_id in relevant),
            None,
        )
        rr = 1.0 / first_rank if first_rank is not None else 0.0
        reciprocal_ranks.append(rr)
        query_metrics["reciprocal_rank"] = rr
        latencies.append(float(row["latency_ms"]))
        query_metrics["latency_ms"] = float(row["latency_ms"])

        answer = row.get("answer")
        if answer is not None:
            for claim in answer["claims"]:
                citations = claim["citations"]
                claim_coverage.append(float(bool(citations)))
                valid_citations = [
                    chunk_id
                    for chunk_id in citations
                    if chunk_id in chunk_by_id and chunk_id in result_ids
                ]
                citation_validity.extend(
                    float(chunk_id in chunk_by_id and chunk_id in result_ids)
                    for chunk_id in citations
                )
                claim_tokens = _content_tokens(claim["text"])
                evidence_tokens: set[str] = set()
                for chunk_id in valid_citations:
                    evidence_tokens.update(_content_tokens(chunk_by_id[chunk_id]["text"]))
                overlap = (
                    len(claim_tokens.intersection(evidence_tokens)) / len(claim_tokens)
                    if claim_tokens
                    else 0.0
                )
                claim_faithfulness.append(overlap)

        per_query.append(query_metrics)

    metrics: dict[str, Any] = {
        "query_count": len(query_by_id),
        "retrieval": {
            **{f"recall@{k}": _mean(recall[k]) for k in normalized_cutoffs},
            "mrr": _mean(reciprocal_ranks),
            **{f"ndcg@{k}": _mean(ndcg[k]) for k in normalized_cutoffs},
        },
        "citations": {
            "claim_count": len(claim_coverage),
            "coverage": _mean(claim_coverage) if claim_coverage else None,
            "validity": _mean(citation_validity) if citation_validity else None,
            "faithfulness_proxy": (
                _mean(claim_faithfulness) if claim_faithfulness else None
            ),
        },
        "latency_ms": {
            "count": len(latencies),
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": max(latencies),
        },
        "per_query": per_query,
    }
    return metrics


def _parse_cutoffs(value: str) -> list[int]:
    try:
        cutoffs = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("cutoffs must be comma-separated integers") from exc
    if not cutoffs or any(cutoff < 1 for cutoff in cutoffs):
        raise argparse.ArgumentTypeError("cutoffs must be positive integers")
    return cutoffs


def _parse_threshold(value: str) -> Threshold:
    try:
        path, raw_minimum = value.rsplit("=", 1)
        minimum = float(raw_minimum)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("threshold must use metric.path=minimum") from exc
    if not path or not math.isfinite(minimum):
        raise argparse.ArgumentTypeError("threshold must use metric.path=finite-number")
    return Threshold(path=path, minimum=minimum)


def _metric_at_path(metrics: dict[str, Any], path: str) -> float:
    value: Any = metrics
    for component in path.split("."):
        if not isinstance(value, dict) or component not in value:
            raise EvaluationError(f"unknown threshold metric: {path}")
        value = value[component]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError(f"threshold metric is not numeric: {path}")
    return float(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--k", type=_parse_cutoffs, default=[1, 3, 5])
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--fail-below",
        action="append",
        default=[],
        type=_parse_threshold,
        metavar="METRIC=VALUE",
        help="fail when a numeric metric is below a floor; may be repeated",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        metrics = evaluate(
            load_jsonl(args.queries),
            load_jsonl(args.corpus),
            load_jsonl(args.run),
            args.k,
        )
        rendered = json.dumps(metrics, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        sys.stdout.write(rendered)
        failures = []
        for threshold in args.fail_below:
            actual = _metric_at_path(metrics, threshold.path)
            if actual < threshold.minimum:
                failures.append(
                    f"{threshold.path}={actual:.6f} is below {threshold.minimum:.6f}"
                )
        if failures:
            for failure in failures:
                print(f"quality gate failed: {failure}", file=sys.stderr)
            return 1
        return 0
    except EvaluationError as exc:
        print(f"evaluation error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"evaluation error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
