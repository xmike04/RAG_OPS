import uuid
from typing import Any

from pydantic import Field

from ragops.schemas.common import ApiModel


class SearchRequest(ApiModel):
    workspace_id: uuid.UUID
    query: str = Field(min_length=1, max_length=8_000)
    top_k: int = Field(default=10, ge=1, le=100)
    rerank: bool = True


class ScoreContribution(ApiModel):
    source: str
    rank: int = Field(ge=1)
    raw_score: float
    rrf_score: float


class SearchHit(ApiModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    rank: int = Field(ge=1)
    fused_score: float
    final_score: float
    lexical_score: float | None = None
    vector_score: float | None = None
    rerank_score: float | None = None
    rrf_contributions: dict[str, float] = Field(default_factory=dict)
    contributions: list[ScoreContribution] = Field(default_factory=list)


class SearchResponse(ApiModel):
    results: list[SearchHit]
    total: int = Field(ge=0)
    latency_ms: dict[str, float] = Field(default_factory=dict)
    providers: dict[str, str] = Field(default_factory=dict)
