from decimal import Decimal

from ragops.schemas.common import ApiModel


class OpsSummary(ApiModel):
    query_count: int
    average_latency_ms: float
    p95_latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: Decimal
    cache_hit_rate: float
    average_quality_score: float | None
    ingestion_by_status: dict[str, int]
