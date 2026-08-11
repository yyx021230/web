from __future__ import annotations

import pytest
from redis.exceptions import RedisError, TimeoutError as RedisTimeoutError

from app.services.ai_task_queue import AIImageTaskQueue


class _Pipeline:
    def __init__(self, redis):
        self.redis = redis
        self.commands = []

    def sadd(self, key, value):
        self.commands.append(("sadd", key, value))
        return self

    def lrem(self, key, count, value):
        self.commands.append(("lrem", key, count, value))
        return self

    def srem(self, key, value):
        self.commands.append(("srem", key, value))
        return self

    def llen(self, key):
        self.commands.append(("llen", key))
        return self

    def scard(self, key):
        self.commands.append(("scard", key))
        return self

    async def execute(self):
        results = []
        for command in self.commands:
            method = getattr(self.redis, command[0])
            results.append(await method(*command[1:]))
        return results


class _FakeRedis:
    def __init__(self):
        self.sets = {}
        self.lists = {}
        self.closed = False
        self.reserve_error = None
        self.status_error = None

    async def aclose(self):
        self.closed = True

    async def sadd(self, key, *values):
        bucket = self.sets.setdefault(key, set())
        before = len(bucket)
        bucket.update(values)
        return len(bucket) - before

    async def srem(self, key, *values):
        bucket = self.sets.setdefault(key, set())
        removed = 0
        for value in values:
            if value in bucket:
                bucket.remove(value)
                removed += 1
        return removed

    async def rpush(self, key, *values):
        self.lists.setdefault(key, []).extend(values)
        return len(self.lists[key])

    async def brpoplpush(self, source, destination, timeout):
        if self.reserve_error:
            raise self.reserve_error
        values = self.lists.setdefault(source, [])
        if not values:
            return None
        value = values.pop()
        self.lists.setdefault(destination, []).insert(0, value)
        return value

    async def lrem(self, key, count, value):
        values = self.lists.setdefault(key, [])
        original = len(values)
        if count == 0:
            self.lists[key] = [item for item in values if item != value]
        elif value in values:
            values.remove(value)
        return original - len(self.lists[key])

    async def lrange(self, key, start, end):
        return list(self.lists.setdefault(key, []))

    async def delete(self, key):
        return int(self.lists.pop(key, None) is not None)

    async def llen(self, key):
        if self.status_error:
            raise self.status_error
        return len(self.lists.setdefault(key, []))

    async def scard(self, key):
        return len(self.sets.setdefault(key, set()))

    def pipeline(self, transaction=True):
        return _Pipeline(self)


@pytest.fixture
def queue(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(
        "app.services.ai_task_queue.Redis.from_url",
        lambda *args, **kwargs: fake,
    )
    instance = AIImageTaskQueue(
        redis_url="redis://test",
        pending_key="pending",
        processing_key="processing",
        membership_key="tracked",
    )
    return instance, fake


@pytest.mark.asyncio
async def test_queue_enqueue_reserve_ack_and_status(queue):
    service, redis = queue
    assert await service.enqueue_task(10) is True
    assert await service.enqueue_task(10) is False
    assert await service.enqueue_missing_tasks([]) == 0
    assert await service.enqueue_missing_tasks([10, 11, 12]) == 2

    status = await service.get_status()
    assert status == {
        "pending": 3,
        "processing": False,
        "processing_count": 0,
        "tracked": 3,
        "redis_available": True,
    }
    reserved = await service.reserve_task(timeout=0)
    assert reserved == 12
    assert (await service.get_status())["processing"] is True
    await service.ack_task(12)
    assert "12" not in redis.sets["tracked"]
    await service.close()
    assert redis.closed is True


@pytest.mark.asyncio
async def test_queue_requeue_remove_drain_and_discard(queue):
    service, redis = queue
    assert await service.discard_tasks([]) == 0
    assert await service.requeue_drained_tasks([]) == 0
    await service.enqueue_missing_tasks([1, 2, 3])
    assert await service.remove_pending_task(2) is True
    assert await service.remove_pending_task(99) is False

    assert await service.reserve_task() == 3
    assert await service.requeue_reserved_task(3) is True
    assert await service.requeue_reserved_task(99) is False
    assert await service.reserve_task() == 3
    drained = await service.drain_processing_tasks()
    assert drained == ["3"] or drained == [3]
    assert await service.drain_processing_tasks() == []
    assert await service.requeue_drained_tasks(drained) == 1
    assert await service.discard_tasks([1, 3]) == 2
    assert redis.lists["pending"]


@pytest.mark.asyncio
async def test_queue_handles_redis_timeouts_and_status_errors(queue):
    service, redis = queue
    redis.reserve_error = RedisTimeoutError("timeout")
    assert await service.reserve_task() is None
    redis.reserve_error = None
    assert await service.reserve_task() is None

    redis.status_error = RedisError("offline")
    status = await service.get_status()
    assert status["redis_available"] is False
    assert status["pending"] == 0
    assert "offline" in status["error"]
