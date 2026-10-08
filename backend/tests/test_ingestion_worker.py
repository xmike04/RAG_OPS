from uuid import UUID

from ragops.worker.queue import RedisJobQueue

JOB_ID = UUID("00000000-0000-0000-0000-000000000050")


class FakePipeline:
    def __init__(self, redis: "FakeRedis") -> None:
        self.redis = redis
        self.operations: list[tuple[str, tuple[object, ...]]] = []

    def sadd(self, *args: object) -> "FakePipeline":
        self.operations.append(("sadd", args))
        return self

    def srem(self, *args: object) -> "FakePipeline":
        self.operations.append(("srem", args))
        return self

    def zadd(self, *args: object) -> "FakePipeline":
        self.operations.append(("zadd", args))
        return self

    def zrem(self, *args: object) -> "FakePipeline":
        self.operations.append(("zrem", args))
        return self

    def lpush(self, *args: object) -> "FakePipeline":
        self.operations.append(("lpush", args))
        return self

    async def execute(self) -> None:
        for name, args in self.operations:
            await getattr(self.redis, name)(*args)


class FakeRedis:
    def __init__(self) -> None:
        self.sets: dict[str, set[str]] = {}
        self.lists: dict[str, list[str]] = {}
        self.sorted_sets: dict[str, dict[str, float]] = {}

    async def sadd(self, key: str, value: str) -> int:
        values = self.sets.setdefault(key, set())
        if value in values:
            return 0
        values.add(value)
        return 1

    async def srem(self, key: str, value: str) -> int:
        values = self.sets.setdefault(key, set())
        existed = value in values
        values.discard(value)
        return int(existed)

    async def lpush(self, key: str, value: str) -> int:
        values = self.lists.setdefault(key, [])
        values.insert(0, value)
        return len(values)

    async def brpop(
        self, key: str, *, timeout: int  # noqa: ASYNC109 - mirrors redis-py's public API
    ) -> tuple[str, str] | None:
        del timeout
        values = self.lists.setdefault(key, [])
        return (key, values.pop()) if values else None

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        values = self.sorted_sets.setdefault(key, {})
        values.update(mapping)
        return len(mapping)

    async def zrem(self, key: str, value: str) -> int:
        values = self.sorted_sets.setdefault(key, {})
        existed = value in values
        values.pop(value, None)
        return int(existed)

    async def zrangebyscore(self, key: str, minimum: object, maximum: float) -> list[str]:
        del minimum
        return [
            value
            for value, score in self.sorted_sets.setdefault(key, {}).items()
            if score <= maximum
        ]

    def pipeline(self, *, transaction: bool) -> FakePipeline:
        assert transaction
        return FakePipeline(self)


async def test_redis_queue_deduplicates_until_message_is_acknowledged() -> None:
    redis = FakeRedis()
    queue = RedisJobQueue(redis)

    assert await queue.enqueue(JOB_ID) is True
    assert await queue.enqueue(JOB_ID) is False

    message = await queue.dequeue(timeout_seconds=0)
    assert message is not None
    assert message.job_id == JOB_ID
    assert await queue.enqueue(JOB_ID) is False

    await queue.ack(message)
    assert await queue.enqueue(JOB_ID) is True


async def test_redis_queue_promotes_due_retry() -> None:
    redis = FakeRedis()
    queue = RedisJobQueue(redis)
    assert await queue.enqueue(JOB_ID, delay_seconds=60) is True
    redis.sorted_sets[queue.delayed_key][str(JOB_ID)] = 0

    assert await queue.promote_due() == 1
    message = await queue.dequeue(timeout_seconds=0)

    assert message is not None
    assert message.job_id == JOB_ID
