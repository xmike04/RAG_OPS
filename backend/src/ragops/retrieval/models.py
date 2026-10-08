"""Value objects shared by candidate retrieval, fusion, and search services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType


def _immutable_metadata(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    """One candidate emitted by one retrieval source."""

    chunk_id: str
    text: str
    raw_score: float
    document_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.chunk_id:
            raise ValueError("chunk_id must not be empty")
        if not isfinite(self.raw_score):
            raise ValueError("raw_score must be finite")
        object.__setattr__(self, "metadata", _immutable_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class ScoreContribution:
    """Explainable contribution made by a source to an RRF score."""

    source: str
    rank: int
    raw_score: float
    rrf_score: float


@dataclass(frozen=True, slots=True)
class SearchHit:
    """A fused (and optionally reranked) chunk."""

    chunk_id: str
    text: str
    document_id: str | None
    metadata: Mapping[str, object]
    fused_score: float
    final_score: float
    rank: int
    contributions: tuple[ScoreContribution, ...]
    rerank_score: float | None = None
    rerank_provider: str | None = None
    rerank_model: str | None = None

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ValueError("rank must be positive")
        if not isfinite(self.fused_score) or not isfinite(self.final_score):
            raise ValueError("scores must be finite")
        object.__setattr__(self, "metadata", _immutable_metadata(self.metadata))

    @property
    def content(self) -> str:
        """API/model compatibility alias for the canonical chunk text."""

        return self.text


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Service result with operational information suitable for query traces."""

    query: str
    hits: tuple[SearchHit, ...]
    stage_ms: Mapping[str, float]
    candidate_counts: Mapping[str, int]
    embedding_provider: str
    embedding_model: str
    rerank_provider: str | None = None
    rerank_model: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage_ms", MappingProxyType(dict(self.stage_ms)))
        object.__setattr__(self, "candidate_counts", MappingProxyType(dict(self.candidate_counts)))

    @property
    def results(self) -> tuple[SearchHit, ...]:
        """Compatibility-friendly name for API serializers."""

        return self.hits
