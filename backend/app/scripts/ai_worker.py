from __future__ import annotations

import asyncio
import logging
import signal
import time

from app.config import settings
from app.db.session import async_session
from app.services.ai_image_service import AIImageService
from app.services.ai_image_reconciliation_service import (
    reconcile_ai_image_shadow_jobs_once,
)
from app.services.ai_task_queue import ai_image_task_queue

logger = logging.getLogger("app")


class AIImageWorker:
    def __init__(self):
        self._stop_event = asyncio.Event()
        self._active_tasks: set[asyncio.Task] = set()
        self._semaphore = asyncio.Semaphore(
            max(1, int(getattr(settings, "ai_task_worker_concurrency", 15) or 15))
        )
        self._poll_timeout = max(
            1,
            int(getattr(settings, "ai_task_worker_poll_timeout_seconds", 5) or 5),
        )
        self._min_interval = max(
            0.0,
            float(getattr(settings, "ai_task_worker_min_interval_seconds", 10.0) or 0.0),
        )
        self._last_started_at = 0.0
        self._rate_lock = asyncio.Lock()
        self._reconciliation_enabled = bool(
            getattr(settings, "ai_image_shadow_enabled", False)
            and getattr(settings, "ai_image_reconciliation_enabled", False)
        )
        self._reconciliation_interval = max(
            10,
            int(
                getattr(
                    settings,
                    "ai_image_reconciliation_interval_seconds",
                    60,
                )
                or 60
            ),
        )
        self._reconciliation_batch_size = max(
            1,
            min(
                100,
                int(
                    getattr(settings, "ai_image_reconciliation_batch_size", 20)
                    or 20
                ),
            ),
        )

    def request_stop(self) -> None:
        self._stop_event.set()

    async def _wait_rate_limit(self) -> None:
        if self._min_interval <= 0:
            return
        async with self._rate_lock:
            elapsed = time.monotonic() - self._last_started_at
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_started_at = time.monotonic()

    async def _recover_tasks(self) -> None:
        async with async_session() as session:
            recovery = await AIImageService(db=session).recover_incomplete_tasks()
        logger.info(
            "AI worker recovery: reset_processing=%d waiting_review=%d requeued_processing=%d enqueued_missing=%d discarded_processing=%d",
            recovery.get("reset_processing", 0),
            recovery.get("waiting_review", 0),
            recovery.get("requeued_processing", 0),
            recovery.get("enqueued_missing", 0),
            recovery.get("discarded_processing", 0),
        )

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._active_tasks.discard(task)
        self._semaphore.release()
        try:
            task.result()
        except Exception:
            logger.exception("AI worker task exited unexpectedly")

    async def _process_reserved_task(self, task_id: int) -> None:
        await self._wait_rate_limit()
        try:
            async with async_session() as session:
                status = await AIImageService(db=session).execute_submitted_task(task_id)
            await ai_image_task_queue.ack_task(task_id)
            logger.info("AI task %s finished with status=%s", task_id, status)
        except Exception:
            logger.exception("AI worker failed while processing task %s; requeueing", task_id)
            await ai_image_task_queue.requeue_reserved_task(task_id)

    async def _reconciliation_loop(self) -> None:
        logger.info(
            "AI image reconciliation started: interval=%ds batch_size=%d",
            self._reconciliation_interval,
            self._reconciliation_batch_size,
        )
        while not self._stop_event.is_set():
            try:
                result = await reconcile_ai_image_shadow_jobs_once(
                    self._reconciliation_batch_size
                )
                if result.get("checked") or result.get("resolved") or result.get("errors"):
                    logger.info(
                        "AI image reconciliation tick: candidates=%d checked=%d resolved=%d skipped=%d errors=%d",
                        result.get("candidates", 0),
                        result.get("checked", 0),
                        result.get("resolved", 0),
                        result.get("skipped", 0),
                        result.get("errors", 0),
                    )
            except Exception:
                logger.exception("AI image reconciliation loop failed")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._reconciliation_interval,
                )
            except asyncio.TimeoutError:
                continue

    async def run(self) -> None:
        await self._recover_tasks()
        reconciliation_task = (
            asyncio.create_task(self._reconciliation_loop())
            if self._reconciliation_enabled
            else None
        )
        logger.info(
            "AI worker started: concurrency=%d poll_timeout=%ds min_interval=%.1fs",
            max(1, int(getattr(settings, "ai_task_worker_concurrency", 15) or 15)),
            self._poll_timeout,
            self._min_interval,
        )

        try:
            while not self._stop_event.is_set():
                await self._semaphore.acquire()
                if self._stop_event.is_set():
                    self._semaphore.release()
                    break

                try:
                    task_id = await ai_image_task_queue.reserve_task(timeout=self._poll_timeout)
                except Exception:
                    self._semaphore.release()
                    logger.exception("AI worker failed to reserve task from Redis")
                    await asyncio.sleep(2.0)
                    continue

                if task_id is None:
                    self._semaphore.release()
                    continue

                task = asyncio.create_task(self._process_reserved_task(task_id))
                self._active_tasks.add(task)
                task.add_done_callback(self._on_task_done)
        finally:
            self._stop_event.set()
            if reconciliation_task is not None:
                await reconciliation_task

        if self._active_tasks:
            logger.info("AI worker is draining %d in-flight task(s) before exit", len(self._active_tasks))
            await asyncio.gather(*self._active_tasks, return_exceptions=True)


async def _async_main() -> None:
    worker = AIImageWorker()
    loop = asyncio.get_running_loop()

    def _request_stop() -> None:
        logger.info("AI worker received stop signal, draining in-flight tasks")
        worker.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_args: worker.request_stop())

    try:
        await worker.run()
    finally:
        await ai_image_task_queue.close()


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
