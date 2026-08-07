from __future__ import annotations
"""全局异步请求队列 - 控制并发和速率"""

import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from collections import deque

from app.config import settings

logger = logging.getLogger("app")
_QUEUE_WAIT_TIMEOUT_SECONDS = 600


@dataclass
class QueueStats:
    """队列统计信息"""
    pending: int = 0           # 等待中
    processing: bool = False   # 是否有正在处理的
    last_request_time: float = 0.0
    total_processed: int = 0
    total_failed: int = 0


class RateLimitedQueue:
    """
    带速率限制的异步请求队列。

    控制同一时刻调用外部 API 的请求数，
    并且两次请求启动之间有最小间隔（避免触发 QPS 限制）。
    """

    def __init__(
        self,
        max_concurrent: int = 1,
        min_interval: float = 3.0,
    ):
        self._queue: deque[asyncio.Future] = deque()
        self._max_concurrent = max(1, int(max_concurrent))
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._min_interval = min_interval
        self._last_processed_at = 0.0
        self._stats = QueueStats()
        self._lock = asyncio.Lock()
        self._rate_lock = asyncio.Lock()
        self._workers: set[asyncio.Task] = set()
        self._processing_count = 0

    async def enqueue(self, coro) -> Any:
        """将协程加入队列，等待执行并返回结果"""
        async with self._lock:
            self._stats.pending += 1
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            self._queue.append((coro, future))

        self._ensure_workers()

        try:
            return await asyncio.wait_for(future, timeout=_QUEUE_WAIT_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            raise RuntimeError(f"排队超时（>{_QUEUE_WAIT_TIMEOUT_SECONDS // 60}分钟），请稍后重试")

    def _ensure_workers(self):
        while len(self._workers) < self._max_concurrent:
            task = asyncio.create_task(self._worker_loop())
            self._workers.add(task)
            task.add_done_callback(self._workers.discard)

    async def _wait_rate_limit(self):
        async with self._rate_lock:
            elapsed = time.monotonic() - self._last_processed_at
            if elapsed < self._min_interval:
                wait_time = self._min_interval - elapsed
                logger.info(f"[RateLimitQueue] 等待 {wait_time:.1f}s 后发送下一请求")
                await asyncio.sleep(wait_time)
            now = time.monotonic()
            self._last_processed_at = now
            self._stats.last_request_time = now

    async def _worker_loop(self):
        """并发 worker：从队列中取任务并执行"""
        while True:
            async with self._lock:
                if not self._queue:
                    return
                coro, future = self._queue.popleft()
                self._stats.pending = len(self._queue)

            # 速率限制：控制“发车”间隔，不影响已在执行中的并发任务
            await self._wait_rate_limit()

            async with self._semaphore:
                self._processing_count += 1
                self._stats.processing = self._processing_count > 0
                logger.info(
                    "[RateLimitQueue] 请求开始 (并发运行: %d/%d, 队列剩余: %d)",
                    self._processing_count,
                    self._max_concurrent,
                    len(self._queue),
                )
                try:
                    result = await coro
                    if not future.cancelled():
                        future.set_result(result)
                    self._stats.total_processed += 1
                    logger.info(f"[RateLimitQueue] 请求完成 (队列剩余: {len(self._queue)})")
                except Exception as e:
                    logger.error(f"[RateLimitQueue] 请求失败: {e}")
                    if not future.cancelled():
                        future.set_exception(e)
                    self._stats.total_failed += 1
                finally:
                    self._processing_count = max(0, self._processing_count - 1)
                    self._stats.processing = self._processing_count > 0
                    self._stats.pending = len(self._queue)

    @property
    def stats(self) -> QueueStats:
        return self._stats

    def get_status(self) -> dict:
        return {
            "pending": self._stats.pending,
            "processing": self._stats.processing,
            "total_processed": self._stats.total_processed,
            "total_failed": self._stats.total_failed,
            "last_request_time": round(time.monotonic() - self._stats.last_request_time, 1)
            if self._stats.last_request_time > 0 else None,
        }


# 全局单例 - 生图请求队列
# min_interval=10.0 表示两次请求之间至少间隔 10 秒（避免触发 Seedream API 速率限制）
image_generation_queue = RateLimitedQueue(max_concurrent=15, min_interval=10.0)

# 全局单例 - 小红书发布队列
# 默认允许多个 worker，让不同账号可以并发排队；同账号是否串行由业务层锁控制
xhs_publish_queue = RateLimitedQueue(
    max_concurrent=max(1, int(getattr(settings, "xhs_publish_queue_workers", 2))),
    min_interval=0.0,
)
