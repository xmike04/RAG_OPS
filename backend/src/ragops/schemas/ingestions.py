import uuid
from datetime import datetime

from ragops.schemas.common import ApiModel


class IngestionJobRead(ApiModel):
    id: uuid.UUID
    document_id: uuid.UUID
    workspace_id: uuid.UUID
    status: str
    error: str | None
    attempts: int
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
