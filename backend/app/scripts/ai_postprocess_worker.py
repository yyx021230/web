from __future__ import annotations

import asyncio
import logging
import signal

from app.config import settings
from app.db.session import async_session
from app.services.ai_image_service import AIImageService
from app.services.ai_task_queue import ai_image_postprocess_queue

logger = logging.getLogger("app")


class AIImagePostprocessWorker:
    def __init__(self):
        self._stop_event = asyncio.Event()
        self._active_tasks: set[asyncio.Task] = set()
        self._concurrency = max(
            1,
            int(getattr(settings, "ai_postprocess_worker_concurrency", 12) or 12),
        )
        self._semaphore = asyncio.Semaphore(self._concurrency)
        self._poll_timeout = max(
            1,
            int(getattr(settings, "ai_task_worker_poll_timeout_seconds", 5) or 5),
        )

    def request_stop(self) -> None:
        self._stop_event.set()

    async def _recover_tasks(self) -> None:
        async with async_session() as session:
            recovery = await AIImageService(db=session).recover_postprocessing_tasks()
        logger.info(
            "AI postprocess recovery: requeued_processing=%d enqueued_missing=%d discarded_processing=%d",
            recovery.get("requeued_processing", 0),
            recovery.get("enqueued_missing", 0),
            recovery.get("discarded_processing", 0),
        )

    async def _repair_handoff_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=60)
                continue
            except asyncio.TimeoutError:
                pass
            try:
                async with async_session() as session:
                    repaired = await AIImageService(db=session).enqueue_missing_postprocessing_tasks()
                if repaired:
                    logger.info("AI postprocess repaired %d missing queue handoff(s)", repaired)
            except Exception:
                logger.exception("AI postprocess handoff repair failed")

    async def _process_reserved_task(self, task_id: int) -> None:
        try:
            async with async_session() as session:
                status = await AIImageService(db=session).execute_postprocessing_task(task_id)
            await ai_image_postprocess_queue.ack_task(task_id)
            logger.info("AI postprocess task %s finished with status=%s", task_id, status)
        except Exception:
            logger.exception("AI postprocess worker failed on task %s; requeueing", task_id)
            await ai_image_postprocess_queue.requeue_reserved_task(task_id)

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._active_tasks.discard(task)
        self._semaphore.release()
        try:
            task.result()
        except Exception:
            logger.exception("AI postprocess task exited unexpectedly")

    async def run(self) -> None:
        await self._recover_tasks()
        repair_task = asyncio.create_task(self._repair_handoff_loop())
        logger.info("AI postprocess worker started: concurrency=%d", self._concurrency)
        try:
            while not self._stop_event.is_set():
                await self._semaphore.acquire()
                if self._stop_event.is_set():
                    self._semaphore.release()
                    break
                try:
                    task_id = await ai_image_postprocess_queue.reserve_task(timeout=self._poll_timeout)
                except Exception:
                    self._semaphore.release()
                    logger.exception("AI postprocess worker failed to reserve task")
                    await asyncio.sleep(2)
                    continue
                if task_id is None:
                    self._semaphore.release()
                    continue
                task = asyncio.create_task(self._process_reserved_task(task_id))
                self._active_tasks.add(task)
                task.add_done_callback(self._on_task_done)
        finally:
            self._stop_event.set()
            await repair_task

        if self._active_tasks:
            logger.info("AI postprocess worker draining %d task(s)", len(self._active_tasks))
            await asyncio.gather(*self._active_tasks, return_exceptions=True)


async def _async_main() -> None:
    worker = AIImagePostprocessWorker()
    loop = asyncio.get_running_loop()

    def _request_stop() -> None:
        logger.info("AI postprocess worker received stop signal")
        worker.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_args: worker.request_stop())
    try:
        await worker.run()
    finally:
        await ai_image_postprocess_queue.close()


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
