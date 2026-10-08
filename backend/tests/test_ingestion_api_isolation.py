import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

from ragops.api.routes.ingestions import get_ingestion_job
from ragops.db.models import IngestionJob


class WorkspaceFilteringSession:
    def __init__(self, job: IngestionJob) -> None:
        self.job = job

    async def scalar(self, statement: Any) -> IngestionJob | None:
        values = set(statement.compile().params.values())
        if self.job.id in values and self.job.workspace_id in values:
            return self.job
        return None


def _job(workspace_id: uuid.UUID) -> IngestionJob:
    now = datetime.now(UTC)
    return IngestionJob(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        workspace_id=workspace_id,
        status="queued",
        attempts=0,
        queued_at=now,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_ingestion_job_cannot_be_read_from_another_workspace() -> None:
    actual_workspace = uuid.uuid4()
    job = _job(actual_workspace)
    session = WorkspaceFilteringSession(job)

    with pytest.raises(HTTPException) as raised:
        await get_ingestion_job(
            job.id,
            uuid.uuid4(),
            session,  # type: ignore[arg-type]
        )

    assert raised.value.status_code == 404
    assert (
        await get_ingestion_job(
            job.id,
            actual_workspace,
            session,  # type: ignore[arg-type]
        )
        is job
    )
