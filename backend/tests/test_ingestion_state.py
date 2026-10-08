from datetime import UTC, datetime

import pytest

from ragops.ingestion.state import JobStatus, RetryPolicy, error_metadata, validate_transition


def test_state_machine_accepts_retry_path_and_rejects_terminal_transition() -> None:
    validate_transition(JobStatus.QUEUED, JobStatus.PROCESSING)
    validate_transition(JobStatus.PROCESSING, JobStatus.RETRYING)
    validate_transition(JobStatus.RETRYING, JobStatus.PROCESSING)
    validate_transition(JobStatus.PROCESSING, JobStatus.COMPLETED)

    with pytest.raises(ValueError, match="completed -> processing"):
        validate_transition(JobStatus.COMPLETED, JobStatus.PROCESSING)


def test_retry_policy_has_capped_deterministic_backoff() -> None:
    policy = RetryPolicy(max_attempts=4, base_delay_seconds=2, max_delay_seconds=5)

    assert [policy.delay_for(attempt) for attempt in range(1, 5)] == [2, 4, 5, 5]
    assert policy.should_retry(3)
    assert not policy.should_retry(4)


def test_error_metadata_is_stable_and_bounded() -> None:
    metadata = error_metadata(
        RuntimeError("x" * 3_000),
        attempt=2,
        max_attempts=3,
        retryable=True,
        now=datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert len(metadata.message) == 2_000
    assert metadata.to_json().startswith('{"attempt":2,"error_type":"RuntimeError"')
    assert metadata.occurred_at == "2025-01-01T00:00:00+00:00"
