import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragops.db.models import IngestionJob
from ragops.db.session import get_session
from ragops.schemas.ingestions import IngestionJobRead

router = APIRouter(prefix="/ingestions", tags=["ingestion"])


@router.get("/{job_id}", response_model=IngestionJobRead)
async def get_ingestion_job(
    job_id: uuid.UUID,
    workspace_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> IngestionJob:
    job = await session.scalar(
        select(IngestionJob).where(
            IngestionJob.id == job_id,
            IngestionJob.workspace_id == workspace_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    return job
