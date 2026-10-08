"""Dependency-light IR metrics with graded nDCG."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QueryMetrics:
    recall: float
    reciprocal_rank: float
    ndcg: float

    def as_dict(self, cutoff: int) -> dict[str, float]:
        return {
            f"recall@{cutoff}": self.recall,
            f"mrr@{cutoff}": self.reciprocal_rank,
            f"ndcg@{cutoff}": self.ndcg,
        }


def evaluate_ranking(
    ranked_ids: Sequence[str], relevance: Mapping[str, int], *, cutoff: int = 10
) -> QueryMetrics:
    if cutoff < 1:
        raise ValueError("cutoff must be positive")
    relevant = {doc_id: score for doc_id, score in relevance.items() if score > 0}
    if not relevant:
        raise ValueError("at least one positively relevant document is required")
    ranking = list(ranked_ids[:cutoff])
    recalled = sum(doc_id in relevant for doc_id in ranking) / len(relevant)
    first_rank = next((rank for rank, doc_id in enumerate(ranking, 1) if doc_id in relevant), None)
    reciprocal_rank = 0.0 if first_rank is None else 1.0 / first_rank
    dcg = sum(
        ((2 ** relevant.get(doc_id, 0)) - 1) / math.log2(rank + 1)
        for rank, doc_id in enumerate(ranking, 1)
    )
    ideal_scores = sorted(relevant.values(), reverse=True)[:cutoff]
    ideal_dcg = sum(
        ((2**score) - 1) / math.log2(rank + 1) for rank, score in enumerate(ideal_scores, 1)
    )
    return QueryMetrics(recall=recalled, reciprocal_rank=reciprocal_rank, ndcg=dcg / ideal_dcg)


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[str]], *, k: int = 60, depth: int | None = None
) -> tuple[list[str], dict[str, dict[str, float]]]:
    if k < 1:
        raise ValueError("RRF k must be positive")
    scores: dict[str, float] = {}
    contributions: dict[str, dict[str, float]] = {}
    best_rank: dict[str, int] = {}
    for source, ranking in rankings.items():
        seen: set[str] = set()
        source_ranking = ranking if depth is None else ranking[:depth]
        for rank, doc_id in enumerate(source_ranking, start=1):
            if doc_id in seen:
                continue
            seen.add(doc_id)
            value = 1.0 / (k + rank)
            scores[doc_id] = scores.get(doc_id, 0.0) + value
            contributions.setdefault(doc_id, {})[source] = value
            best_rank[doc_id] = min(best_rank.get(doc_id, rank), rank)
    ordered = sorted(scores, key=lambda doc_id: (-scores[doc_id], best_rank[doc_id], doc_id))
    return ordered, contributions
