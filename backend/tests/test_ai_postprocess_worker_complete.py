from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.scripts import ai_postprocess_worker as module
from app.scripts.ai_postprocess_worker import AIImagePostprocessWorker


class _SessionContext:
    async def __aenter__(self):
        return SimpleNamespace()

    async def __aexit__(self, *args):
        return None


def test_postprocess_worker_uses_configured_watermark_concurrency(monkeypatch):
    monkeypatch.setattr(settings, "ai_postprocess_worker_concurrency", 12)
    worker = AIImagePostprocessWorker()
    assert worker._concurrency == 12
    assert worker._stop_event.is_set() is False
    worker.request_stop()
    assert worker._stop_event.is_set() is True


@pytest.mark.asyncio
async def test_postprocess_worker_recovers_processes_and_requeues(monkeypatch):
    recovery = {
        "requeued_processing": 1,
        "enqueued_missing": 2,
        "discarded_processing": 3,
    }
    service = SimpleNamespace(
        recover_postprocessing_tasks=AsyncMock(return_value=recovery),
        execute_postprocessing_task=AsyncMock(return_value="completed"),
    )
    monkeypatch.setattr(module, "async_session", lambda: _SessionContext())
    monkeypatch.setattr(module, "AIImageService", lambda db: service)
    monkeypatch.setattr(module.ai_image_postprocess_queue, "ack_task", AsyncMock())
    monkeypatch.setattr(module.ai_image_postprocess_queue, "requeue_reserved_task", AsyncMock())

    worker = AIImagePostprocessWorker()
    await worker._recover_tasks()
    service.recover_postprocessing_tasks.assert_awaited_once()

    await worker._process_reserved_task(20)
    service.execute_postprocessing_task.assert_awaited_once_with(20)
    module.ai_image_postprocess_queue.ack_task.assert_awaited_once_with(20)

    service.execute_postprocessing_task.side_effect = RuntimeError("watermark unavailable")
    await worker._process_reserved_task(21)
    module.ai_image_postprocess_queue.requeue_reserved_task.assert_awaited_once_with(21)
