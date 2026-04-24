from __future__ import annotations
"""全局异步请求队列 - 控制并发和速率"""

import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from collections import deque

logger = logging.getLogger("app")


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

    确保同一时刻只有一个请求在调用外部 API，
    并且两次请求之间有最小间隔（避免触发 QPS 限制）。
    """

    def __init__(
        self,
        max_concurrent: int = 1,
        min_interval: float = 3.0,
    ):
        self._queue: deque[asyncio.Future] = deque()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._min_interval = min_interval
        self._last_processed_at = 0.0
        self._stats = QueueStats()
        self._lock = asyncio.Lock()
        self._active: bool = False

    async def enqueue(self, coro) -> Any:
        """将协程加入队列，等待执行并返回结果"""
        async with self._lock:
            self._stats.pending += 1
            position = len(self._queue) + 1
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            self._queue.append((coro, future))

        if not self._active:
            asyncio.create_task(self._process_queue())

        try:
            return await asyncio.wait_for(future, timeout=300)
        except asyncio.TimeoutError:
            raise RuntimeError("排队超时，请稍后重试")

    async def _process_queue(self):
        """处理队列中的请求"""
        self._active = True
        try:
            while True:
                async with self._lock:
                    if not self._queue:
                        self._active = False
                        return
                    coro, future = self._queue.popleft()

                # 速率限制：等待最小间隔
                elapsed = time.monotonic() - self._last_processed_at
                if elapsed < self._min_interval:
                    wait_time = self._min_interval - elapsed
                    logger.info(f"[RateLimitQueue] 等待 {wait_time:.1f}s 后发送下一请求")
                    await asyncio.sleep(wait_time)

                async with self._semaphore:
                    try:
                        self._stats.processing = True
                        self._stats.pending = len(self._queue)
                        self._last_processed_at = time.monotonic()
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
                        self._stats.processing = False
                        self._stats.pending = len(self._queue)
        finally:
            self._active = False

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
# min_interval=3.0 表示两次请求之间至少间隔 3 秒
image_generation_queue = RateLimitedQueue(max_concurrent=1, min_interval=3.0)
