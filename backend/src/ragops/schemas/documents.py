import uuid
from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from ragops.schemas.common import ApiModel


class DocumentCreate(ApiModel):
    workspace_id: uuid.UUID
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1)
    source_uri: str | None = Field(default=None, max_length=2_048)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title", "content")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class DocumentRead(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    title: str
    source_uri: str | None
    status: str
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class DocumentList(ApiModel):
    items: list[DocumentRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class DocumentSubmitted(ApiModel):
    document: DocumentRead
    ingestion_job_id: uuid.UUID
