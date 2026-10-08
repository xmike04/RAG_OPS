import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ragops.db.models import QueryTrace
from ragops.db.session import get_session
from ragops.schemas.traces import QueryTraceList

router = APIRouter(prefix="/traces", tags=["operations"])


@router.get("", response_model=QueryTraceList)
async def list_traces(
    workspace_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> QueryTraceList:
    condition = QueryTrace.workspace_id == workspace_id
    items = list(
        (
            await session.scalars(
                select(QueryTrace)
                .where(condition)
                .order_by(QueryTrace.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    total = await session.scalar(select(func.count()).select_from(QueryTrace).where(condition))
    return QueryTraceList(items=items, total=int(total or 0), limit=limit, offset=offset)
