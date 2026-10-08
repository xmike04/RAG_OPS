"""Idempotent Redis and bounded inline ingestion queues."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from ragops.ingestion.pipeline import OutcomeStatus, ProcessingOutcome


class JobQueue(Protocol):
    async def enqueue(self, job_id: UUID | str, *, delay_seconds: float = 0) -> bool: ...


@dataclass(frozen=True, slots=True)
class QueueMessage:
    job_id: UUID
    raw: str


class InlineJobQueue:
    """Run jobs in-process without Redis.

    This mode is intended for tests and the local demo only. Calls for the same
    job are serialized, retries are bounded by the pipeline's retry policy, and
    no retry sleep is performed. Production deployments should use RedisJobQueue.
    """

    def __init__(
        self,
        processor: Callable[[UUID], Awaitable[ProcessingOutcome]],
        *,
        max_inline_attempts: int = 10,
    ) -> None:
        if max_inline_attempts < 1:
            raise ValueError("max_inline_attempts must be positive")
        self.processor = processor
        self.max_inline_attempts = max_inline_attempts
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def enqueue(self, job_id: UUID | str, *, delay_seconds: float = 0) -> bool:
        del delay_seconds  # Inline retry delay is intentionally skipped.
        parsed_id = UUID(str(job_id))
        async with self._locks_guard:
            lock = self._locks.setdefault(parsed_id, asyncio.Lock())
        if lock.locked():
            return False
        try:
            async with lock:
                for _ in range(self.max_inline_attempts):
                    outcome = await self.processor(parsed_id)
                    if outcome.status is not OutcomeStatus.RETRYING:
                        break
                else:
                    raise RuntimeError("inline ingestion exceeded its bounded retry limit")
            return True
        finally:
            async with self._locks_guard:
                if not lock.locked():
                    self._locks.pop(parsed_id, None)


class RedisJobQueue:
    """Small Redis queue with deduplication, delayed retries, and leases.

    The supplied client is duck-typed to ``redis.asyncio.Redis`` so importing the
    core package does not require Redis. Database-level atomic claiming remains
    the final idempotency boundary.
    """

    def __init__(
        self,
        redis: Any,
        *,
        namespace: str = "ragops:ingestion",
        visibility_timeout_seconds: float = 300,
    ) -> None:
        if visibility_timeout_seconds <= 0:
            raise ValueError("visibility_timeout_seconds must be positive")
        self.redis = redis
        self.ready_key = f"{namespace}:ready"
        self.pending_key = f"{namespace}:pending"
        self.delayed_key = f"{namespace}:delayed"
        self.leased_key = f"{namespace}:leased"
        self.visibility_timeout_seconds = visibility_timeout_seconds

    async def enqueue(self, job_id: UUID | str, *, delay_seconds: float = 0) -> bool:
        raw = str(UUID(str(job_id)))
        added = int(await self.redis.sadd(self.pending_key, raw))
        if not added:
            return False
        try:
            if delay_seconds > 0:
                await self.redis.zadd(self.delayed_key, {raw: time.time() + delay_seconds})
            else:
                await self.redis.lpush(self.ready_key, raw)
        except BaseException:
            await self.redis.srem(self.pending_key, raw)
            raise
        return True

    async def dequeue(self, *, timeout_seconds: int = 5) -> QueueMessage | None:
        await self.promote_due()
        value = await self.redis.brpop(self.ready_key, timeout=timeout_seconds)
        if value is None:
            return None
        raw_value = value[1] if isinstance(value, (tuple, list)) else value
        raw = raw_value.decode() if isinstance(raw_value, bytes) else str(raw_value)
        job_id = UUID(raw)
        await self.redis.zadd(self.leased_key, {raw: time.time() + self.visibility_timeout_seconds})
        return QueueMessage(job_id=job_id, raw=raw)

    async def ack(self, message: QueueMessage) -> None:
        transaction = self.redis.pipeline(transaction=True)
        transaction.zrem(self.leased_key, message.raw)
        transaction.srem(self.pending_key, message.raw)
        await transaction.execute()

    async def reschedule(self, message: QueueMessage, *, delay_seconds: float) -> None:
        transaction = self.redis.pipeline(transaction=True)
        transaction.zrem(self.leased_key, message.raw)
        transaction.zadd(self.delayed_key, {message.raw: time.time() + max(0, delay_seconds)})
        await transaction.execute()

    async def promote_due(self) -> int:
        now = time.time()
        delayed = await self.redis.zrangebyscore(self.delayed_key, "-inf", now)
        expired = await self.redis.zrangebyscore(self.leased_key, "-inf", now)
        values = {
            value.decode() if isinstance(value, bytes) else str(value)
            for value in delayed + expired
        }
        if not values:
            return 0
        transaction = self.redis.pipeline(transaction=True)
        for raw in sorted(values):
            transaction.zrem(self.delayed_key, raw)
            transaction.zrem(self.leased_key, raw)
            transaction.lpush(self.ready_key, raw)
        await transaction.execute()
        return len(values)
