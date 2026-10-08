"""Rank fusion and reranking utilities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from math import isfinite

from ragops.providers.base import RerankingProvider

from .models import RetrievalCandidate, ScoreContribution, SearchHit


@dataclass(slots=True)
class _FusionState:
    candidate: RetrievalCandidate
    score: float
    contributions: list[ScoreContribution]


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[RetrievalCandidate]],
    *,
    k: int = 60,
    weights: Mapping[str, float] | None = None,
    limit: int | None = None,
) -> list[SearchHit]:
    """Fuse rankings while retaining each source's exact contribution.

    Duplicate chunk IDs in one source are ignored after their first (best) rank.
    Ties are resolved by the best source rank and then stable chunk ID, making
    results repeatable across processes.
    """

    if k < 1:
        raise ValueError("k must be at least 1")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")

    by_chunk: dict[str, _FusionState] = {}
    for source, candidates in rankings.items():
        if not source:
            raise ValueError("retrieval source names must not be empty")
        weight = 1.0 if weights is None else weights.get(source, 1.0)
        if not isfinite(weight) or weight < 0:
            raise ValueError(f"weight for {source!r} must be finite and non-negative")
        seen: set[str] = set()
        for rank, candidate in enumerate(candidates, start=1):
            if candidate.chunk_id in seen:
                continue
            seen.add(candidate.chunk_id)
            contribution = weight / (k + rank)
            state = by_chunk.setdefault(
                candidate.chunk_id,
                _FusionState(candidate=candidate, score=0.0, contributions=[]),
            )
            state.score += contribution
            state.contributions.append(
                ScoreContribution(
                    source=source,
                    rank=rank,
                    raw_score=candidate.raw_score,
                    rrf_score=contribution,
                )
            )

    def sort_key(item: tuple[str, _FusionState]) -> tuple[float, int, str]:
        chunk_id, state = item
        best_rank = min(contribution.rank for contribution in state.contributions)
        return (-state.score, best_rank, chunk_id)

    ordered = sorted(by_chunk.items(), key=sort_key)
    if limit is not None:
        ordered = ordered[:limit]

    hits: list[SearchHit] = []
    for rank, (_, state) in enumerate(ordered, start=1):
        hits.append(
            SearchHit(
                chunk_id=state.candidate.chunk_id,
                text=state.candidate.text,
                document_id=state.candidate.document_id,
                metadata=state.candidate.metadata,
                fused_score=state.score,
                final_score=state.score,
                rank=rank,
                contributions=tuple(state.contributions),
            )
        )
    return hits


async def rerank_shortlist(
    query: str,
    hits: Sequence[SearchHit],
    provider: RerankingProvider,
    *,
    limit: int | None = None,
) -> list[SearchHit]:
    """Rerank a fused shortlist and validate the provider's index contract."""

    shortlist = list(hits if limit is None else hits[:limit])
    tail = [] if limit is None else list(hits[limit:])
    if not shortlist:
        return []
    scores = await provider.rerank(query, [hit.text for hit in shortlist])
    if len(scores) != len(shortlist):
        raise ValueError("reranker must return exactly one score per document")
    score_by_index = {score.index: score.score for score in scores}
    if set(score_by_index) != set(range(len(shortlist))):
        raise ValueError("reranker returned missing, duplicate, or invalid indexes")

    enriched = [
        replace(
            hit,
            final_score=score_by_index[index],
            rerank_score=score_by_index[index],
            rerank_provider=provider.provider_name,
            rerank_model=provider.model,
        )
        for index, hit in enumerate(shortlist)
    ]
    enriched.sort(key=lambda hit: (-hit.final_score, -hit.fused_score, hit.chunk_id))
    # Hits outside the provider shortlist remain in fused order. Appending them
    # preserves the contract that search can still return the requested top_k.
    return [replace(hit, rank=rank) for rank, hit in enumerate([*enriched, *tail], start=1)]
