from collections.abc import Sequence
from uuid import UUID

from ragops.ingestion.chunking import ChunkingConfig, TokenAwareChunker
from ragops.ingestion.pipeline import (
    IngestionPipeline,
    IngestionWorkItem,
    OutcomeStatus,
    StoredChunk,
)
from ragops.ingestion.state import RetryPolicy
from ragops.worker.queue import InlineJobQueue

JOB_ID = UUID("00000000-0000-0000-0000-000000000010")
DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000000020")
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000030")
DUPLICATE_ID = UUID("00000000-0000-0000-0000-000000000040")


class FakeRepository:
    def __init__(self, content: str = "one two three four five six") -> None:
        self.content = content
        self.status = "queued"
        self.attempts = 0
        self.duplicate: UUID | None = None
        self.stored: list[StoredChunk] = []
        self.completed: dict[str, object] | None = None
        self.errors: list[str] = []

    async def claim(self, job_id: UUID, *, max_attempts: int) -> IngestionWorkItem | None:
        assert job_id == JOB_ID
        if self.status in {"processing", "completed", "failed"} or self.attempts >= max_attempts:
            return None
        self.status = "processing"
        self.attempts += 1
        return IngestionWorkItem(
            job_id=JOB_ID,
            document_id=DOCUMENT_ID,
            workspace_id=WORKSPACE_ID,
            content=self.content,
            content_format="markdown",
            metadata={"source": "test"},
            attempt=self.attempts,
        )

    async def find_duplicate(
        self, workspace_id: UUID, content_sha256: str, *, exclude_document_id: UUID
    ) -> UUID | None:
        assert workspace_id == WORKSPACE_ID
        assert exclude_document_id == DOCUMENT_ID
        assert len(content_sha256) == 64
        return self.duplicate

    async def store_chunks(self, item: IngestionWorkItem, chunks: Sequence[StoredChunk]) -> None:
        assert item.document_id == DOCUMENT_ID
        self.stored = list(chunks)

    async def complete(
        self,
        item: IngestionWorkItem,
        *,
        content: str,
        content_sha256: str,
        chunk_count: int,
        duplicate_of: UUID | None,
    ) -> None:
        self.status = "completed"
        self.completed = {
            "content": content,
            "hash": content_sha256,
            "count": chunk_count,
            "duplicate_of": duplicate_of,
        }

    async def retry(self, item: IngestionWorkItem, *, error: str, delay_seconds: float) -> None:
        assert delay_seconds >= 0
        self.status = "retrying"
        self.errors.append(error)

    async def fail(self, item: IngestionWorkItem, *, error: str) -> None:
        self.status = "failed"
        self.errors.append(error)


class DeterministicEmbedder:
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(len(text)), float(index)] for index, text in enumerate(texts)]


class FlakyEmbedder(DeterministicEmbedder):
    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary provider outage")
        return await super().embed(texts)


def build_pipeline(repository: FakeRepository, embedder: object) -> IngestionPipeline:
    return IngestionPipeline(
        repository,
        embedder,  # type: ignore[arg-type]
        chunker=TokenAwareChunker(ChunkingConfig(max_tokens=4, overlap_tokens=1)),
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0),
    )


async def test_pipeline_embeds_stores_and_is_idempotent() -> None:
    repository = FakeRepository()
    pipeline = build_pipeline(repository, DeterministicEmbedder())

    outcome = await pipeline.process(JOB_ID)
    repeated = await pipeline.process(JOB_ID)

    assert outcome.status is OutcomeStatus.COMPLETED
    assert outcome.chunk_count == 2
    assert repeated.status is OutcomeStatus.NOOP
    assert [chunk.position for chunk in repository.stored] == [0, 1]
    assert repository.stored[0].metadata["source"] == "test"
    assert repository.completed is not None
    assert len(str(repository.completed["hash"])) == 64


async def test_content_hash_duplicate_skips_embedding_and_chunks() -> None:
    repository = FakeRepository()
    repository.duplicate = DUPLICATE_ID
    pipeline = build_pipeline(repository, DeterministicEmbedder())

    outcome = await pipeline.process(JOB_ID)

    assert outcome.status is OutcomeStatus.COMPLETED
    assert outcome.duplicate_of == DUPLICATE_ID
    assert outcome.chunk_count == 0
    assert repository.stored == []


async def test_inline_queue_retries_transient_error_to_completion() -> None:
    repository = FakeRepository()
    embedder = FlakyEmbedder()
    pipeline = build_pipeline(repository, embedder)
    queue = InlineJobQueue(pipeline.process)

    queued = await queue.enqueue(JOB_ID)

    assert queued is True
    assert repository.status == "completed"
    assert repository.attempts == 2
    assert embedder.calls == 2
    assert '"retryable":true' in repository.errors[0]


async def test_invalid_content_fails_without_retry() -> None:
    repository = FakeRepository("\x00")
    pipeline = build_pipeline(repository, DeterministicEmbedder())

    outcome = await pipeline.process(JOB_ID)

    assert outcome.status is OutcomeStatus.FAILED
    assert repository.attempts == 1
    assert '"error_type":"ContentValidationError"' in repository.errors[0]
    assert '"retryable":false' in repository.errors[0]
