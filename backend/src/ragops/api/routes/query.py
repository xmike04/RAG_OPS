from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ragops.api.dependencies import get_query_service
from ragops.db.session import get_session
from ragops.schemas.query import QueryRequest, QueryResponse
from ragops.services.query import QueryService

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def grounded_query(
    payload: QueryRequest,
    session: AsyncSession = Depends(get_session),
    service: QueryService = Depends(get_query_service),
) -> QueryResponse:
    return await service.query(
        session,
        workspace_id=payload.workspace_id,
        query=payload.query,
        top_k=payload.top_k,
        rerank=payload.rerank,
    )
