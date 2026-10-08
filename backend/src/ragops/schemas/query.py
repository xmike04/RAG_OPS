import uuid

from pydantic import Field

from ragops.schemas.common import ApiModel


class QueryRequest(ApiModel):
    workspace_id: uuid.UUID
    query: str = Field(min_length=1, max_length=8_000)
    top_k: int = Field(default=5, ge=1, le=50)
    rerank: bool = True


class Citation(ApiModel):
    index: int = Field(ge=1)
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    quote: str


class QueryResponse(ApiModel):
    trace_id: uuid.UUID
    answer: str
    citations: list[Citation]
    latency_ms: dict[str, float]
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    provider: str
    model: str
