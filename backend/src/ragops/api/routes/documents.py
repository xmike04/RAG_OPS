import hashlib
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ragops.db.models import Document, IngestionJob, Workspace
from ragops.db.session import get_session
from ragops.logging import get_logger
from ragops.observability import INGESTION_JOBS
from ragops.schemas.documents import DocumentCreate, DocumentList, DocumentSubmitted

router = APIRouter(prefix="/documents", tags=["documents"])
logger = get_logger(__name__)


@router.post("", response_model=DocumentSubmitted, status_code=status.HTTP_202_ACCEPTED)
async def submit_document(
    payload: DocumentCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> DocumentSubmitted:
    settings = request.app.state.settings
    if len(payload.content.encode("utf-8")) > settings.max_document_bytes:
        raise HTTPException(status_code=413, detail="Document exceeds configured size limit")

    workspace = await session.get(Workspace, payload.workspace_id)
    if workspace is None:
        workspace = Workspace(
            id=payload.workspace_id, name=f"Workspace {str(payload.workspace_id)[:8]}"
        )
        session.add(workspace)
        # These objects are intentionally not coupled by ORM relationships, so make the
        # foreign-key target durable before SQLAlchemy sees the dependent document.
        await session.flush()

    document = Document(
        workspace_id=payload.workspace_id,
        title=payload.title.strip(),
        content=payload.content,
        source_uri=payload.source_uri,
        content_sha256=hashlib.sha256(payload.content.encode("utf-8")).hexdigest(),
        status="queued",
        metadata_=payload.metadata,
    )
    session.add(document)
    await session.flush()
    job = IngestionJob(
        document_id=document.id,
        workspace_id=document.workspace_id,
        status="queued",
    )
    session.add(job)
    await session.commit()
    await session.refresh(document)
    await session.refresh(job)
    INGESTION_JOBS.labels("queued").inc()

    try:
        from ragops.services.ingest import enqueue_ingestion

        queue = getattr(request.app.state, "ingestion_queue", None)
        if queue is None:
            await enqueue_ingestion(job.id)
        else:
            await enqueue_ingestion(job.id, queue=queue)
    except Exception:
        # The durable queued record remains available to a polling worker. Queue transport
        # outages must not turn an accepted, persisted submission into an ambiguous retry.
        logger.exception("ingestion_enqueue_deferred", job_id=str(job.id))

    return DocumentSubmitted(document=document, ingestion_job_id=job.id)


@router.get("", response_model=DocumentList)
async def list_documents(
    workspace_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> DocumentList:
    base = select(Document).where(Document.workspace_id == workspace_id)
    items = list(
        (
            await session.scalars(
                base.order_by(Document.created_at.desc()).limit(limit).offset(offset)
            )
        ).all()
    )
    total = await session.scalar(
        select(func.count()).select_from(Document).where(Document.workspace_id == workspace_id)
    )
    return DocumentList(items=items, total=int(total or 0), limit=limit, offset=offset)
