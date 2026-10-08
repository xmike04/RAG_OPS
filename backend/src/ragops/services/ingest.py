"""Database adapter and public enqueue API for document ingestion."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete, select

from ragops.db.models import Chunk as ChunkModel
from ragops.db.models import Document, IngestionJob
from ragops.ingestion.pipeline import IngestionWorkItem, StoredChunk
from ragops.ingestion.state import JobStatus
from ragops.worker.queue import JobQueue

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class QueueNotConfiguredError(RuntimeError):
    pass


_default_queue: JobQueue | None = None


def configure_ingestion_queue(queue: JobQueue | None) -> None:
    """Set the process-wide queue used when a caller does not pass one."""

    global _default_queue
    _default_queue = queue


async def enqueue_ingestion(job_id: UUID | str, *, queue: JobQueue | None = None) -> bool:
    """Idempotently enqueue an ingestion job.

    API callers should pass ``request.app.state.ingestion_queue``. The global
    fallback exists for simple scripts and is explicitly configured at startup.
    """

    selected = queue or _default_queue
    if selected is None:
        raise QueueNotConfiguredError("ingestion queue has not been configured")
    return await selected.enqueue(UUID(str(job_id)))


class SQLAlchemyIngestionRepository:
    """SQLAlchemy implementation of the pipeline persistence callbacks."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        processing_timeout_seconds: float = 300,
    ) -> None:
        if processing_timeout_seconds <= 0:
            raise ValueError("processing_timeout_seconds must be positive")
        self.session_factory = session_factory
        self.processing_timeout = timedelta(seconds=processing_timeout_seconds)

    async def claim(self, job_id: UUID, *, max_attempts: int) -> IngestionWorkItem | None:
        async with self.session_factory() as session, session.begin():
            job = await session.scalar(
                select(IngestionJob).where(IngestionJob.id == job_id).with_for_update()
            )
            if job is None or job.status in {
                JobStatus.COMPLETED.value,
                JobStatus.FAILED.value,
            }:
                return None
            if job.status == JobStatus.PROCESSING.value:
                started_at = job.started_at
                cutoff = datetime.now(UTC) - self.processing_timeout
                if started_at is not None and started_at.tzinfo is None:
                    cutoff = cutoff.replace(tzinfo=None)
                if started_at is None or started_at > cutoff:
                    return None
            document = await session.get(Document, job.document_id)
            if document is None:
                job.status = JobStatus.FAILED.value
                job.error = (
                    '{"error_type":"MissingDocument","message":"document not found",'
                    '"retryable":false}'
                )
                job.completed_at = datetime.now(UTC)
                return None
            if job.attempts >= max_attempts:
                job.status = JobStatus.FAILED.value
                job.error = (
                    '{"error_type":"AttemptsExhausted","message":"retry limit reached",'
                    '"retryable":false}'
                )
                job.completed_at = datetime.now(UTC)
                document.status = JobStatus.FAILED.value
                return None

            job.attempts += 1
            job.status = JobStatus.PROCESSING.value
            job.started_at = datetime.now(UTC)
            job.error = None
            document.status = JobStatus.PROCESSING.value
            metadata = dict(document.metadata_ or {})
            content_format = str(metadata.pop("content_format", "text"))
            return IngestionWorkItem(
                job_id=job.id,
                document_id=document.id,
                workspace_id=document.workspace_id,
                content=document.content,
                content_format=content_format,
                metadata=metadata,
                attempt=job.attempts,
            )

    async def find_duplicate(
        self, workspace_id: UUID, content_sha256: str, *, exclude_document_id: UUID
    ) -> UUID | None:
        async with self.session_factory() as session:
            return await session.scalar(
                select(Document.id)
                .where(
                    Document.workspace_id == workspace_id,
                    Document.content_sha256 == content_sha256,
                    Document.id != exclude_document_id,
                    Document.status.in_([JobStatus.COMPLETED.value, "ready"]),
                )
                .order_by(Document.created_at, Document.id)
                .limit(1)
            )

    async def store_chunks(self, item: IngestionWorkItem, chunks: Sequence[StoredChunk]) -> None:
        async with self.session_factory() as session, session.begin():
            # Replacement makes a retry after a partial prior transaction deterministic.
            await session.execute(
                delete(ChunkModel).where(ChunkModel.document_id == item.document_id)
            )
            session.add_all(
                [
                    ChunkModel(
                        document_id=item.document_id,
                        workspace_id=item.workspace_id,
                        position=chunk.position,
                        content=chunk.content,
                        token_count=chunk.token_count,
                        embedding=chunk.embedding,
                        metadata_=chunk.metadata,
                    )
                    for chunk in chunks
                ]
            )

    async def complete(
        self,
        item: IngestionWorkItem,
        *,
        content: str,
        content_sha256: str,
        chunk_count: int,
        duplicate_of: UUID | None,
    ) -> None:
        del chunk_count
        async with self.session_factory() as session, session.begin():
            job = await session.get(IngestionJob, item.job_id, with_for_update=True)
            document = await session.get(Document, item.document_id, with_for_update=True)
            if job is None or document is None:
                raise RuntimeError("ingestion job or document disappeared during processing")
            document.content = content
            document.content_sha256 = content_sha256
            document.status = "duplicate" if duplicate_of else JobStatus.COMPLETED.value
            if duplicate_of:
                metadata = dict(document.metadata_ or {})
                metadata["duplicate_of"] = str(duplicate_of)
                document.metadata_ = metadata
            job.status = JobStatus.COMPLETED.value
            job.error = None
            job.completed_at = datetime.now(UTC)

    async def retry(self, item: IngestionWorkItem, *, error: str, delay_seconds: float) -> None:
        del delay_seconds
        async with self.session_factory() as session, session.begin():
            job = await session.get(IngestionJob, item.job_id, with_for_update=True)
            document = await session.get(Document, item.document_id, with_for_update=True)
            if job is None or document is None:
                return
            job.status = JobStatus.RETRYING.value
            job.error = error
            document.status = JobStatus.RETRYING.value

    async def fail(self, item: IngestionWorkItem, *, error: str) -> None:
        async with self.session_factory() as session, session.begin():
            job = await session.get(IngestionJob, item.job_id, with_for_update=True)
            document = await session.get(Document, item.document_id, with_for_update=True)
            if job is None or document is None:
                return
            job.status = JobStatus.FAILED.value
            job.error = error
            job.completed_at = datetime.now(UTC)
            document.status = JobStatus.FAILED.value
