import uuid
from datetime import datetime
from decimal import Decimal

from ragops.schemas.common import ApiModel
from ragops.schemas.query import Citation


class QueryTraceRead(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    query: str
    answer: str | None
    search_type: str
    top_k: int
    retrieval_count: int
    total_latency_ms: float
    stage_latency_ms: dict[str, float]
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: Decimal
    cache_hit: bool
    quality_score: float | None
    provider: str
    model: str
    citations: list[Citation]
    created_at: datetime


class QueryTraceList(ApiModel):
    items: list[QueryTraceRead]
    total: int
    limit: int
    offset: int
