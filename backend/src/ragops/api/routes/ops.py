import math
import uuid
from collections import Counter
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragops.db.models import IngestionJob, QueryTrace
from ragops.db.session import get_session
from ragops.schemas.ops import OpsSummary

router = APIRouter(prefix="/ops", tags=["operations"])


@router.get("/summary", response_model=OpsSummary)
async def operations_summary(
    workspace_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> OpsSummary:
    traces = list(
        (
            await session.scalars(
                select(QueryTrace)
                .where(QueryTrace.workspace_id == workspace_id)
                .order_by(QueryTrace.created_at.desc())
                .limit(10_000)
            )
        ).all()
    )
    job_statuses = list(
        (
            await session.scalars(
                select(IngestionJob.status).where(IngestionJob.workspace_id == workspace_id)
            )
        ).all()
    )
    latencies = sorted(trace.total_latency_ms for trace in traces)
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
    qualities = [trace.quality_score for trace in traces if trace.quality_score is not None]
    count = len(traces)
    return OpsSummary(
        query_count=count,
        average_latency_ms=sum(latencies) / count if count else 0.0,
        p95_latency_ms=latencies[p95_index] if latencies else 0.0,
        prompt_tokens=sum(trace.prompt_tokens for trace in traces),
        completion_tokens=sum(trace.completion_tokens for trace in traces),
        estimated_cost_usd=sum((trace.estimated_cost_usd for trace in traces), start=Decimal("0")),
        cache_hit_rate=sum(trace.cache_hit for trace in traces) / count if count else 0.0,
        average_quality_score=sum(qualities) / len(qualities) if qualities else None,
        ingestion_by_status=dict(Counter(job_statuses)),
    )
