from __future__ import annotations

import asyncio
from collections.abc import Sequence
from types import SimpleNamespace

from ragops.providers import HashEmbeddingProvider, LexicalRerankingProvider
from ragops.retrieval import RetrievalCandidate
from ragops.services.search import SearchService, build_search_service


class FakeRepository:
    def __init__(self) -> None:
        self.limits: list[int] = []

    async def lexical_candidates(
        self, session: object, *, workspace_id: object, query: str, limit: int
    ) -> Sequence[RetrievalCandidate]:
        self.limits.append(limit)
        return [
            RetrievalCandidate(chunk_id="shared", text="hybrid retrieval", raw_score=0.9),
            RetrievalCandidate(chunk_id="lexical", text="other", raw_score=0.8),
        ]

    async def vector_candidates(
        self,
        session: object,
        *,
        workspace_id: object,
        embedding: Sequence[float],
        limit: int,
    ) -> Sequence[RetrievalCandidate]:
        self.limits.append(limit)
        assert embedding
        return [
            RetrievalCandidate(chunk_id="shared", text="hybrid retrieval", raw_score=0.95),
            RetrievalCandidate(chunk_id="vector", text="another", raw_score=0.7),
        ]


def test_search_service_runs_full_pipeline_and_reports_timings() -> None:
    repository = FakeRepository()
    service = SearchService(
        repository,
        HashEmbeddingProvider(dimensions=16),
        LexicalRerankingProvider(),
    )
    result = asyncio.run(service.search(object(), "workspace", "hybrid retrieval", 2, True))

    assert result.hits[0].chunk_id == "shared"
    assert result.hits[0].content == "hybrid retrieval"
    assert result.hits[0].rerank_score is not None
    assert result.candidate_counts == {"lexical": 2, "vector": 2, "fused": 3}
    assert set(result.stage_ms) == {
        "embedding",
        "lexical_retrieval",
        "vector_retrieval",
        "fusion",
        "reranking",
        "total",
    }
    assert repository.limits == [10, 10]
    assert result.results is result.hits


def test_search_service_can_skip_reranking() -> None:
    service = SearchService(FakeRepository(), HashEmbeddingProvider(dimensions=16))
    result = asyncio.run(service.search(object(), "workspace", "query", rerank=False))
    assert all(hit.rerank_score is None for hit in result.hits)
    assert result.rerank_provider is None


def test_build_search_service_uses_credential_free_defaults() -> None:
    settings = SimpleNamespace(
        embedding_provider="local",
        embedding_model="ignored-for-hash-provider",
        embedding_dimensions=24,
        reranker_provider="local",
        reranker_model="ignored-for-lexical-provider",
        retrieval_rrf_k=42,
        retrieval_candidate_limit=30,
    )
    repository = FakeRepository()
    service = build_search_service(settings, repository)  # type: ignore[arg-type]
    assert service.repository is repository
    assert service.embedding_provider.model == "feature-hash-24"
    assert service.reranking_provider is not None
    assert service.rrf_k == 42
    assert service.max_candidates_per_source == 30
