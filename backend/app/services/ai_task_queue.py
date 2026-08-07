from __future__ import annotations

import logging
from typing import Iterable

from redis.exceptions import RedisError, TimeoutError as RedisTimeoutError
from redis.asyncio import Redis

from app.config import settings

logger = logging.getLogger("app")


class AIImageTaskQueue:
    """Redis-backed durable queue for AI image tasks."""

    def __init__(
        self,
        *,
        redis_url: str,
        pending_key: str,
        processing_key: str,
        membership_key: str,
    ):
        self._redis = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
        self.pending_key = pending_key
        self.processing_key = processing_key
        self.membership_key = membership_key

    async def close(self) -> None:
        await self._redis.aclose()

    async def enqueue_task(self, task_id: int) -> bool:
        task_value = str(int(task_id))
        added = await self._redis.sadd(self.membership_key, task_value)
        if added:
            await self._redis.rpush(self.pending_key, task_value)
            return True
        return False

    async def enqueue_missing_tasks(self, task_ids: Iterable[int]) -> int:
        normalized_ids = [str(int(task_id)) for task_id in task_ids]
        if not normalized_ids:
            return 0

        pipe = self._redis.pipeline(transaction=True)
        for task_value in normalized_ids:
            pipe.sadd(self.membership_key, task_value)
        added_results = await pipe.execute()

        to_enqueue = [
            task_value
            for task_value, was_added in zip(normalized_ids, added_results)
            if was_added
        ]
        if to_enqueue:
            await self._redis.rpush(self.pending_key, *to_enqueue)
        return len(to_enqueue)

    async def reserve_task(self, timeout: int = 5) -> int | None:
        try:
            value = await self._redis.brpoplpush(
                self.pending_key,
                self.processing_key,
                timeout=max(1, int(timeout)),
            )
        except RedisTimeoutError:
            return None
        if value is None:
            return None
        return int(value)

    async def ack_task(self, task_id: int) -> None:
        task_value = str(int(task_id))
        pipe = self._redis.pipeline(transaction=True)
        pipe.lrem(self.processing_key, 1, task_value)
        pipe.srem(self.membership_key, task_value)
        await pipe.execute()

    async def discard_tasks(self, task_ids: Iterable[int]) -> int:
        normalized_ids = [str(int(task_id)) for task_id in task_ids]
        if not normalized_ids:
            return 0
        return int(await self._redis.srem(self.membership_key, *normalized_ids) or 0)

    async def requeue_reserved_task(self, task_id: int) -> bool:
        task_value = str(int(task_id))
        removed = await self._redis.lrem(self.processing_key, 1, task_value)
        if removed:
            await self._redis.rpush(self.pending_key, task_value)
            return True
        return False

    async def remove_pending_task(self, task_id: int) -> bool:
        task_value = str(int(task_id))
        removed = await self._redis.lrem(self.pending_key, 0, task_value)
        if removed:
            await self._redis.srem(self.membership_key, task_value)
            return True
        return False

    async def drain_processing_tasks(self) -> list[int]:
        values = await self._redis.lrange(self.processing_key, 0, -1)
        if values:
            await self._redis.delete(self.processing_key)
        return [int(value) for value in values]

    async def requeue_drained_tasks(self, task_ids: Iterable[int]) -> int:
        normalized_ids = [str(int(task_id)) for task_id in task_ids]
        if not normalized_ids:
            return 0
        await self._redis.rpush(self.pending_key, *normalized_ids)
        return len(normalized_ids)

    async def get_status(self) -> dict:
        try:
            pending, processing, tracked = await self._redis.pipeline(transaction=True).llen(
                self.pending_key
            ).llen(self.processing_key).scard(self.membership_key).execute()
        except (OSError, RedisError) as exc:
            logger.warning("[AIImageTaskQueue] Redis unavailable while reading status: %s", exc)
            return {
                "pending": 0,
                "processing": False,
                "processing_count": 0,
                "tracked": 0,
                "redis_available": False,
                "error": str(exc),
            }
        processing_count = int(processing or 0)
        return {
            "pending": int(pending or 0),
            "processing": processing_count > 0,
            "processing_count": processing_count,
            "tracked": int(tracked or 0),
            "redis_available": True,
        }


ai_image_task_queue = AIImageTaskQueue(
    redis_url=settings.redis_url,
    pending_key=settings.ai_task_queue_key,
    processing_key=settings.ai_task_processing_key,
    membership_key=settings.ai_task_membership_key,
)
