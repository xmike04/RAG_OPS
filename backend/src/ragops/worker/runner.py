"""Long-running Redis worker loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from ragops.ingestion.pipeline import OutcomeStatus, ProcessingOutcome

from .queue import RedisJobQueue

logger = logging.getLogger(__name__)


class RedisWorker:
    def __init__(
        self,
        queue: RedisJobQueue,
        processor: Callable[[UUID], Awaitable[ProcessingOutcome]],
        *,
        poll_timeout_seconds: int = 5,
    ) -> None:
        self.queue = queue
        self.processor = processor
        self.poll_timeout_seconds = poll_timeout_seconds

    async def run(self, stop: asyncio.Event | None = None) -> None:
        stop_event = stop or asyncio.Event()
        logger.info("ingestion worker started")
        while not stop_event.is_set():
            message = await self.queue.dequeue(timeout_seconds=self.poll_timeout_seconds)
            if message is None:
                continue
            try:
                outcome = await self.processor(message.job_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                # The pipeline normally turns errors into retry outcomes. Keep the
                # lease intact on unexpected failures so it is safely redelivered.
                logger.exception(
                    "unexpected ingestion worker failure", extra={"job_id": message.raw}
                )
                continue
            if outcome.status is OutcomeStatus.RETRYING:
                await self.queue.reschedule(message, delay_seconds=outcome.retry_after_seconds or 0)
            else:
                await self.queue.ack(message)
            logger.info(
                "ingestion job handled",
                extra={
                    "job_id": message.raw,
                    "status": outcome.status.value,
                    "attempt": outcome.attempt,
                    "chunk_count": outcome.chunk_count,
                },
            )
