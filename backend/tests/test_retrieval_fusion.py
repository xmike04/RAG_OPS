from __future__ import annotations

import asyncio

import pytest

from ragops.providers import RerankScore
from ragops.retrieval import RetrievalCandidate, reciprocal_rank_fusion, rerank_shortlist


def candidate(chunk_id: str, score: float, text: str | None = None) -> RetrievalCandidate:
    return RetrievalCandidate(chunk_id=chunk_id, text=text or chunk_id, raw_score=score)


def test_rrf_records_each_source_contribution_and_deduplicates() -> None:
    hits = reciprocal_rank_fusion(
        {
            "lexical": [candidate("a", 0.9), candidate("b", 0.8), candidate("a", 0.1)],
            "vector": [candidate("b", 0.99), candidate("a", 0.7)],
        },
        k=10,
    )

    assert [hit.chunk_id for hit in hits] == ["a", "b"]
    assert hits[0].fused_score == pytest.approx(1 / 11 + 1 / 12)
    assert [(c.source, c.rank, c.raw_score) for c in hits[0].contributions] == [
        ("lexical", 1, 0.9),
        ("vector", 2, 0.7),
    ]


def test_rrf_supports_weights_and_deterministic_ties() -> None:
    hits = reciprocal_rank_fusion(
        {"one": [candidate("z", 1)], "two": [candidate("a", 1)]},
        k=60,
        weights={"one": 0.0, "two": 0.0},
    )
    assert [hit.chunk_id for hit in hits] == ["a", "z"]


class ReverseReranker:
    provider_name = "test"
    model = "reverse"

    async def rerank(self, query: str, documents: list[str]) -> list[RerankScore]:
        return [RerankScore(index=i, score=i / len(documents)) for i in range(len(documents))]


def test_rerank_shortlist_preserves_explanations_and_reassigns_rank() -> None:
    fused = reciprocal_rank_fusion({"lexical": [candidate("a", 1), candidate("b", 0.5)]})
    ranked = asyncio.run(rerank_shortlist("query", fused, ReverseReranker()))

    assert [hit.chunk_id for hit in ranked] == ["b", "a"]
    assert [hit.rank for hit in ranked] == [1, 2]
    assert ranked[0].rerank_provider == "test"
    assert ranked[0].contributions == fused[1].contributions


class BrokenReranker(ReverseReranker):
    async def rerank(self, query: str, documents: list[str]) -> list[RerankScore]:
        return [RerankScore(index=0, score=0.5)]


def test_rerank_rejects_incomplete_results() -> None:
    fused = reciprocal_rank_fusion({"lexical": [candidate("a", 1), candidate("b", 0.5)]})
    with pytest.raises(ValueError, match="exactly one"):
        asyncio.run(rerank_shortlist("query", fused, BrokenReranker()))


def test_rerank_shortlist_appends_unscored_fused_tail() -> None:
    fused = reciprocal_rank_fusion(
        {"lexical": [candidate("a", 1), candidate("b", 0.5), candidate("c", 0.2)]}
    )
    ranked = asyncio.run(rerank_shortlist("query", fused, ReverseReranker(), limit=2))
    assert [hit.chunk_id for hit in ranked] == ["b", "a", "c"]
    assert ranked[2].rerank_score is None
    assert ranked[2].rank == 3
