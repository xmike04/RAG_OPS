"""Application service for observable hybrid retrieval."""

from __future__ import annotations

import logging
from importlib.util import find_spec
from time import perf_counter
from typing import Protocol

from ragops.providers import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    LexicalRerankingProvider,
    RerankingProvider,
    SentenceTransformersCrossEncoderProvider,
    SentenceTransformersEmbeddingProvider,
)
from ragops.retrieval import (
    HybridCandidateRepository,
    PostgreSQLHybridCandidateRepository,
    SearchResult,
    reciprocal_rank_fusion,
    rerank_shortlist,
)

logger = logging.getLogger(__name__)


class SearchService:
    """Coordinate embedding, hybrid candidate retrieval, RRF, and reranking."""

    def __init__(
        self,
        repository: HybridCandidateRepository,
        embedding_provider: EmbeddingProvider,
        reranking_provider: RerankingProvider | None = None,
        *,
        rrf_k: int = 60,
        candidate_multiplier: int = 5,
        max_candidates_per_source: int = 200,
        rerank_limit: int = 50,
    ) -> None:
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        if candidate_multiplier < 1 or max_candidates_per_source < 1:
            raise ValueError("candidate limits must be positive")
        if rerank_limit < 1:
            raise ValueError("rerank_limit must be positive")
        self.repository = repository
        self.embedding_provider = embedding_provider
        self.reranking_provider = reranking_provider
        self.rrf_k = rrf_k
        self.candidate_multiplier = candidate_multiplier
        self.max_candidates_per_source = max_candidates_per_source
        self.rerank_limit = rerank_limit

    async def search(
        self,
        session: object,
        workspace_id: object,
        query: str,
        top_k: int = 10,
        rerank: bool = True,
    ) -> SearchResult:
        """Execute search without assuming a particular ORM model or ID type."""

        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")
        if top_k < 1:
            raise ValueError("top_k must be positive")
        candidate_limit = min(
            self.max_candidates_per_source,
            max(top_k, top_k * self.candidate_multiplier),
        )
        if top_k > self.max_candidates_per_source:
            raise ValueError("top_k exceeds the configured maximum candidate count")

        total_started = perf_counter()
        stage_ms: dict[str, float] = {}

        started = perf_counter()
        embeddings = await self.embedding_provider.embed([query])
        stage_ms["embedding"] = _elapsed_ms(started)
        if len(embeddings) != 1 or not embeddings[0]:
            raise ValueError("embedding provider must return one non-empty query vector")

        # Async SQLAlchemy sessions do not allow concurrent execute calls, hence
        # these two repository operations are intentionally sequential.
        started = perf_counter()
        lexical = list(
            await self.repository.lexical_candidates(
                session, workspace_id=workspace_id, query=query, limit=candidate_limit
            )
        )
        stage_ms["lexical_retrieval"] = _elapsed_ms(started)

        started = perf_counter()
        vector = list(
            await self.repository.vector_candidates(
                session,
                workspace_id=workspace_id,
                embedding=embeddings[0],
                limit=candidate_limit,
            )
        )
        stage_ms["vector_retrieval"] = _elapsed_ms(started)

        started = perf_counter()
        fused = reciprocal_rank_fusion(
            {"lexical": lexical, "vector": vector},
            k=self.rrf_k,
            limit=candidate_limit,
        )
        stage_ms["fusion"] = _elapsed_ms(started)

        rerank_provider: str | None = None
        rerank_model: str | None = None
        if rerank and self.reranking_provider is not None and fused:
            started = perf_counter()
            ranked = await rerank_shortlist(
                query,
                fused,
                self.reranking_provider,
                limit=min(self.rerank_limit, len(fused)),
            )
            stage_ms["reranking"] = _elapsed_ms(started)
            rerank_provider = self.reranking_provider.provider_name
            rerank_model = self.reranking_provider.model
        else:
            ranked = fused
            stage_ms["reranking"] = 0.0

        stage_ms["total"] = _elapsed_ms(total_started)
        result = SearchResult(
            query=query,
            hits=tuple(ranked[:top_k]),
            stage_ms=stage_ms,
            candidate_counts={
                "lexical": len(lexical),
                "vector": len(vector),
                "fused": len(fused),
            },
            embedding_provider=self.embedding_provider.provider_name,
            embedding_model=self.embedding_provider.model,
            rerank_provider=rerank_provider,
            rerank_model=rerank_model,
        )
        logger.info(
            "hybrid search complete",
            extra={
                "workspace_id": str(workspace_id),
                "result_count": len(result.hits),
                "candidate_counts": dict(result.candidate_counts),
                "stage_ms": dict(result.stage_ms),
                "reranked": rerank_provider is not None,
            },
        )
        return result


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1_000, 3)


class SearchSettings(Protocol):
    """Narrow settings surface used by :func:`build_search_service`."""

    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    reranker_provider: str
    reranker_model: str
    retrieval_rrf_k: int
    retrieval_candidate_limit: int


def build_search_service(
    settings: SearchSettings,
    repository: HybridCandidateRepository | None = None,
) -> SearchService:
    """Build the default search pipeline from the backend settings contract."""

    embedding_name = settings.embedding_provider.casefold()
    if embedding_name == "local":
        embedding_provider: EmbeddingProvider = HashEmbeddingProvider(
            dimensions=settings.embedding_dimensions
        )
    elif embedding_name == "sentence-transformers":
        _require_sentence_transformers()
        embedding_provider = SentenceTransformersEmbeddingProvider(settings.embedding_model)
    else:
        raise ValueError(f"unsupported embedding provider: {settings.embedding_provider!r}")

    reranker_name = settings.reranker_provider.casefold()
    if reranker_name == "local":
        reranking_provider: RerankingProvider = LexicalRerankingProvider()
    elif reranker_name == "sentence-transformers":
        _require_sentence_transformers()
        reranking_provider = SentenceTransformersCrossEncoderProvider(settings.reranker_model)
    else:
        raise ValueError(f"unsupported reranker provider: {settings.reranker_provider!r}")

    return SearchService(
        repository or PostgreSQLHybridCandidateRepository(),
        embedding_provider,
        reranking_provider,
        rrf_k=settings.retrieval_rrf_k,
        max_candidates_per_source=settings.retrieval_candidate_limit,
        rerank_limit=settings.retrieval_candidate_limit,
    )


def _require_sentence_transformers() -> None:
    if find_spec("sentence_transformers") is None:
        raise ValueError(
            "sentence-transformers provider selected but optional dependency is not installed"
        )
