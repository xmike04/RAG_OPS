"""Ingestion job state transitions and deterministic retry metadata."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum


class JobStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"


_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.PENDING: frozenset({JobStatus.QUEUED, JobStatus.PROCESSING, JobStatus.FAILED}),
    JobStatus.QUEUED: frozenset({JobStatus.PROCESSING, JobStatus.FAILED}),
    JobStatus.PROCESSING: frozenset({JobStatus.RETRYING, JobStatus.COMPLETED, JobStatus.FAILED}),
    JobStatus.RETRYING: frozenset({JobStatus.QUEUED, JobStatus.PROCESSING, JobStatus.FAILED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.FAILED: frozenset(),
}


def validate_transition(current: JobStatus | str, target: JobStatus | str) -> None:
    current_status = JobStatus(current)
    target_status = JobStatus(target)
    if current_status == target_status:
        return
    if target_status not in _TRANSITIONS[current_status]:
        raise ValueError(
            f"invalid ingestion transition: {current_status.value} -> {target_status.value}"
        )


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays must be non-negative")

    def should_retry(self, attempt: int) -> bool:
        return attempt < self.max_attempts

    def delay_for(self, attempt: int) -> float:
        """Return capped exponential backoff after a 1-based failed attempt."""

        delay = self.base_delay_seconds * pow(2.0, max(0, attempt - 1))
        return min(delay, self.max_delay_seconds)


@dataclass(frozen=True, slots=True)
class ErrorMetadata:
    error_type: str
    message: str
    attempt: int
    max_attempts: int
    retryable: bool
    occurred_at: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def error_metadata(
    error: BaseException,
    *,
    attempt: int,
    max_attempts: int,
    retryable: bool,
    now: datetime | None = None,
) -> ErrorMetadata:
    message = str(error).strip() or error.__class__.__name__
    # Avoid unbounded database/log fields and never include a traceback or content.
    message = message[:2_000]
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    return ErrorMetadata(
        error_type=error.__class__.__name__,
        message=message,
        attempt=attempt,
        max_attempts=max_attempts,
        retryable=retryable,
        occurred_at=timestamp,
    )
