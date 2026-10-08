import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from ragops.api.routes.documents import submit_document
from ragops.config import Settings
from ragops.db.models import Document, IngestionJob, Workspace
from ragops.schemas.documents import DocumentCreate


class RecordingQueue:
    def __init__(self) -> None:
        self.job_ids: list[uuid.UUID] = []

    async def enqueue(self, job_id: uuid.UUID | str, *, delay_seconds: float = 0) -> bool:
        del delay_seconds
        self.job_ids.append(uuid.UUID(str(job_id)))
        return True


class InsertOrderingSession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flush_snapshots: list[tuple[type[Any], ...]] = []

    async def get(self, model: type[Any], object_id: uuid.UUID) -> None:
        del model, object_id
        return None

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_snapshots.append(tuple(type(value) for value in self.added))
        now = datetime.now(UTC)
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid.uuid4()
            if hasattr(value, "created_at") and getattr(value, "created_at", None) is None:
                value.created_at = now
                value.updated_at = now
            if isinstance(value, IngestionJob) and getattr(value, "queued_at", None) is None:
                value.queued_at = now

    async def commit(self) -> None:
        await self.flush()

    async def refresh(self, value: Any) -> None:
        del value


@pytest.mark.asyncio
async def test_new_workspace_is_flushed_before_document_insert() -> None:
    workspace_id = uuid.uuid4()
    queue = RecordingQueue()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=Settings(environment="test", _env_file=None),
                ingestion_queue=queue,
            )
        )
    )
    session = InsertOrderingSession()

    submitted = await submit_document(
        DocumentCreate(workspace_id=workspace_id, title="Runbook", content="Recovery steps"),
        request,  # type: ignore[arg-type]
        session,  # type: ignore[arg-type]
    )

    assert session.flush_snapshots[0] == (Workspace,)
    assert session.flush_snapshots[1] == (Workspace, Document)
    assert submitted.document.workspace_id == workspace_id
    assert queue.job_ids == [submitted.ingestion_job_id]
