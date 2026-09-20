from __future__ import annotations

import asyncio
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
        batch_pending_key: str | None = None,
        processing_key: str,
        membership_key: str,
    ):
        self._redis_url = redis_url
        self._redis: Redis | None = None
        self._redis_loop: asyncio.AbstractEventLoop | None = None
        self.pending_key = pending_key
        self.batch_pending_key = batch_pending_key or f"{pending_key}:batch"
        self.processing_key = processing_key
        self.membership_key = membership_key

    def _client(self) -> Redis:
        """Create the async Redis client inside the loop that will use it."""
        loop = asyncio.get_running_loop()
        if self._redis is None or self._redis_loop is not loop:
            self._redis = Redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            self._redis_loop = loop
        return self._redis

    @staticmethod
    def normalize_lane(lane: str | None) -> str:
        return "batch" if str(lane or "").strip().lower() == "batch" else "interactive"

    def pending_key_for_lane(self, lane: str | None) -> str:
        return self.batch_pending_key if self.normalize_lane(lane) == "batch" else self.pending_key

    async def close(self) -> None:
        redis = self._redis
        self._redis = None
        self._redis_loop = None
        if redis is not None:
            await redis.aclose()

    async def enqueue_task(self, task_id: int, *, lane: str = "interactive") -> bool:
        redis = self._client()
        task_value = str(int(task_id))
        added = await redis.sadd(self.membership_key, task_value)
        if added:
            await redis.rpush(self.pending_key_for_lane(lane), task_value)
            return True
        return False

    async def enqueue_missing_tasks(
        self,
        task_ids: Iterable[int],
        *,
        lane: str = "interactive",
    ) -> int:
        normalized_ids = [str(int(task_id)) for task_id in task_ids]
        if not normalized_ids:
            return 0

        redis = self._client()
        pipe = redis.pipeline(transaction=True)
        for task_value in normalized_ids:
            pipe.sadd(self.membership_key, task_value)
        added_results = await pipe.execute()

        to_enqueue = [
            task_value
            for task_value, was_added in zip(normalized_ids, added_results)
            if was_added
        ]
        if to_enqueue:
            await redis.rpush(self.pending_key_for_lane(lane), *to_enqueue)
        return len(to_enqueue)

    async def reserve_task(self, timeout: int = 5, *, lane: str = "interactive") -> int | None:
        try:
            value = await self._client().blmove(
                self.pending_key_for_lane(lane),
                self.processing_key,
                timeout=max(1, int(timeout)),
                src="LEFT",
                dest="RIGHT",
            )
        except RedisTimeoutError:
            return None
        if value is None:
            return None
        return int(value)

    async def ack_task(self, task_id: int) -> None:
        task_value = str(int(task_id))
        pipe = self._client().pipeline(transaction=True)
        pipe.lrem(self.processing_key, 1, task_value)
        pipe.srem(self.membership_key, task_value)
        await pipe.execute()

    async def discard_tasks(self, task_ids: Iterable[int]) -> int:
        normalized_ids = [str(int(task_id)) for task_id in task_ids]
        if not normalized_ids:
            return 0
        return int(await self._client().srem(self.membership_key, *normalized_ids) or 0)

    async def requeue_reserved_task(self, task_id: int, *, lane: str = "interactive") -> bool:
        redis = self._client()
        task_value = str(int(task_id))
        removed = await redis.lrem(self.processing_key, 1, task_value)
        if removed:
            await redis.rpush(self.pending_key_for_lane(lane), task_value)
            return True
        return False

    async def remove_pending_task(self, task_id: int) -> bool:
        redis = self._client()
        task_value = str(int(task_id))
        pipe = redis.pipeline(transaction=True)
        pipe.lrem(self.pending_key, 0, task_value)
        pipe.lrem(self.batch_pending_key, 0, task_value)
        removed_interactive, removed_batch = await pipe.execute()
        removed = int(removed_interactive or 0) + int(removed_batch or 0)
        if removed:
            await redis.srem(self.membership_key, task_value)
            return True
        return False

    async def drain_processing_tasks(self) -> list[int]:
        redis = self._client()
        values = await redis.lrange(self.processing_key, 0, -1)
        if values:
            await redis.delete(self.processing_key)
        return [int(value) for value in values]

    async def requeue_drained_tasks(
        self,
        task_ids: Iterable[int],
        *,
        lane: str = "interactive",
    ) -> int:
        normalized_ids = [str(int(task_id)) for task_id in task_ids]
        if not normalized_ids:
            return 0
        await self._client().rpush(self.pending_key_for_lane(lane), *normalized_ids)
        return len(normalized_ids)

    async def get_status(self) -> dict:
        try:
            pending_interactive, pending_batch, processing, tracked = await self._client().pipeline(transaction=True).llen(
                self.pending_key
            ).llen(self.batch_pending_key
            ).llen(self.processing_key).scard(self.membership_key).execute()
        except (OSError, RedisError) as exc:
            logger.warning("[AIImageTaskQueue] Redis unavailable while reading status: %s", exc)
            return {
                "pending": 0,
                "pending_interactive": 0,
                "pending_batch": 0,
                "processing": False,
                "processing_count": 0,
                "tracked": 0,
                "redis_available": False,
                "error": str(exc),
            }
        processing_count = int(processing or 0)
        interactive_count = int(pending_interactive or 0)
        batch_count = int(pending_batch or 0)
        return {
            "pending": interactive_count + batch_count,
            "pending_interactive": interactive_count,
            "pending_batch": batch_count,
            "processing": processing_count > 0,
            "processing_count": processing_count,
            "tracked": int(tracked or 0),
            "redis_available": True,
        }


ai_image_task_queue = AIImageTaskQueue(
    redis_url=settings.redis_url,
    pending_key=settings.ai_task_queue_key,
    batch_pending_key=settings.ai_task_batch_queue_key,
    processing_key=settings.ai_task_processing_key,
    membership_key=settings.ai_task_membership_key,
)


ai_image_postprocess_queue = AIImageTaskQueue(
    redis_url=settings.redis_url,
    pending_key=settings.ai_postprocess_queue_key,
    processing_key=settings.ai_postprocess_processing_key,
    membership_key=settings.ai_postprocess_membership_key,
)
