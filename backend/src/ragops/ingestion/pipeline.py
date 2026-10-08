"""Provider- and persistence-agnostic ingestion orchestration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Protocol
from uuid import UUID

from .chunking import Chunk, TokenAwareChunker
from .metadata import validate_metadata
from .normalization import ContentFormat, normalize_document
from .state import RetryPolicy, error_metadata


class EmbeddingProvider(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(frozen=True, slots=True)
class IngestionWorkItem:
    job_id: UUID
    document_id: UUID
    workspace_id: UUID
    content: str
    content_format: str = ContentFormat.TEXT.value
    metadata: Mapping[str, object] | None = None
    attempt: int = 1


@dataclass(frozen=True, slots=True)
class StoredChunk:
    position: int
    content: str
    token_count: int
    embedding: list[float]
    metadata: dict[str, object]
    content_sha256: str


class IngestionRepository(Protocol):
    """Persistence callbacks; ``claim`` must atomically increment attempts.

    Returning ``None`` means that another worker owns the job or that it is
    terminal. This makes repeated and concurrent queue delivery harmless.
    """

    async def claim(self, job_id: UUID, *, max_attempts: int) -> IngestionWorkItem | None: ...

    async def find_duplicate(
        self, workspace_id: UUID, content_sha256: str, *, exclude_document_id: UUID
    ) -> UUID | None: ...

    async def store_chunks(
        self, item: IngestionWorkItem, chunks: Sequence[StoredChunk]
    ) -> None: ...

    async def complete(
        self,
        item: IngestionWorkItem,
        *,
        content: str,
        content_sha256: str,
        chunk_count: int,
        duplicate_of: UUID | None,
    ) -> None: ...

    async def retry(self, item: IngestionWorkItem, *, error: str, delay_seconds: float) -> None: ...

    async def fail(self, item: IngestionWorkItem, *, error: str) -> None: ...


class OutcomeStatus(StrEnum):
    NOOP = "noop"
    COMPLETED = "completed"
    RETRYING = "retrying"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ProcessingOutcome:
    status: OutcomeStatus
    job_id: UUID
    attempt: int = 0
    chunk_count: int = 0
    duplicate_of: UUID | None = None
    retry_after_seconds: float | None = None


class IngestionPipeline:
    def __init__(
        self,
        repository: IngestionRepository,
        embedder: EmbeddingProvider,
        *,
        chunker: TokenAwareChunker | None = None,
        retry_policy: RetryPolicy = RetryPolicy(),
        embedding_batch_size: int = 32,
        max_content_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        if embedding_batch_size < 1:
            raise ValueError("embedding_batch_size must be positive")
        self.repository = repository
        self.embedder = embedder
        self.chunker = chunker or TokenAwareChunker()
        self.retry_policy = retry_policy
        self.embedding_batch_size = embedding_batch_size
        self.max_content_bytes = max_content_bytes

    async def process(self, job_id: UUID | str) -> ProcessingOutcome:
        parsed_id = UUID(str(job_id))
        item = await self.repository.claim(parsed_id, max_attempts=self.retry_policy.max_attempts)
        if item is None:
            return ProcessingOutcome(OutcomeStatus.NOOP, parsed_id)

        try:
            metadata = validate_metadata(item.metadata)
            normalized = normalize_document(
                item.content, item.content_format, max_bytes=self.max_content_bytes
            )
            duplicate = await self.repository.find_duplicate(
                item.workspace_id,
                normalized.content_sha256,
                exclude_document_id=item.document_id,
            )
            if duplicate is not None:
                await self.repository.complete(
                    item,
                    content=normalized.content,
                    content_sha256=normalized.content_sha256,
                    chunk_count=0,
                    duplicate_of=duplicate,
                )
                return ProcessingOutcome(
                    OutcomeStatus.COMPLETED,
                    parsed_id,
                    attempt=item.attempt,
                    duplicate_of=duplicate,
                )

            raw_chunks = self.chunker.chunk(
                normalized.content,
                markdown=normalized.content_format is ContentFormat.MARKDOWN,
            )
            stored_chunks = await self._embed_chunks(raw_chunks, metadata)
            await self.repository.store_chunks(item, stored_chunks)
            await self.repository.complete(
                item,
                content=normalized.content,
                content_sha256=normalized.content_sha256,
                chunk_count=len(stored_chunks),
                duplicate_of=None,
            )
            return ProcessingOutcome(
                OutcomeStatus.COMPLETED,
                parsed_id,
                attempt=item.attempt,
                chunk_count=len(stored_chunks),
            )
        except Exception as exc:
            # Validation errors are deterministic and should not consume retries.
            retryable = not isinstance(exc, (ValueError, TypeError))
            retryable = retryable and self.retry_policy.should_retry(item.attempt)
            rendered = error_metadata(
                exc,
                attempt=item.attempt,
                max_attempts=self.retry_policy.max_attempts,
                retryable=retryable,
            ).to_json()
            if retryable:
                delay = self.retry_policy.delay_for(item.attempt)
                await self.repository.retry(item, error=rendered, delay_seconds=delay)
                return ProcessingOutcome(
                    OutcomeStatus.RETRYING,
                    parsed_id,
                    attempt=item.attempt,
                    retry_after_seconds=delay,
                )
            await self.repository.fail(item, error=rendered)
            return ProcessingOutcome(OutcomeStatus.FAILED, parsed_id, attempt=item.attempt)

    async def _embed_chunks(
        self, chunks: Sequence[Chunk], document_metadata: Mapping[str, object]
    ) -> list[StoredChunk]:
        result: list[StoredChunk] = []
        expected_dimension: int | None = None
        for offset in range(0, len(chunks), self.embedding_batch_size):
            batch = chunks[offset : offset + self.embedding_batch_size]
            embeddings = await self.embedder.embed([chunk.content for chunk in batch])
            if len(embeddings) != len(batch):
                raise RuntimeError("embedding provider returned an unexpected number of vectors")
            for chunk, embedding in zip(batch, embeddings, strict=True):
                vector = [float(value) for value in embedding]
                if not vector:
                    raise RuntimeError("embedding provider returned an empty vector")
                if not all(isfinite(value) for value in vector):
                    raise RuntimeError("embedding provider returned a non-finite vector")
                if expected_dimension is None:
                    expected_dimension = len(vector)
                elif len(vector) != expected_dimension:
                    raise RuntimeError("embedding provider returned inconsistent vector dimensions")
                chunk_metadata = dict(document_metadata)
                chunk_metadata.update(chunk.metadata)
                chunk_metadata.update(
                    {
                        "char_start": chunk.char_start,
                        "char_end": chunk.char_end,
                        "content_sha256": chunk.content_sha256,
                    }
                )
                result.append(
                    StoredChunk(
                        position=chunk.position,
                        content=chunk.content,
                        token_count=chunk.token_count,
                        embedding=vector,
                        metadata=chunk_metadata,
                        content_sha256=chunk.content_sha256,
                    )
                )
        return result
