"""Lifecycle, recovery and failure-path tests for the standalone AI worker."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.scripts import ai_worker as module
from app.scripts.ai_worker import AIImageWorker


class _SessionContext:
    async def __aenter__(self):
        return SimpleNamespace()

    async def __aexit__(self, *args):
        return None


def test_worker_initialization_clamps_configuration_and_stop(monkeypatch):
    monkeypatch.setattr(settings, "ai_task_worker_concurrency", 0)
    monkeypatch.setattr(settings, "ai_task_worker_poll_timeout_seconds", 0)
    monkeypatch.setattr(settings, "ai_task_worker_min_interval_seconds", -2)
    monkeypatch.setattr(settings, "ai_image_shadow_enabled", True)
    monkeypatch.setattr(settings, "ai_image_reconciliation_enabled", True)
    monkeypatch.setattr(settings, "ai_image_reconciliation_interval_seconds", 1)
    monkeypatch.setattr(settings, "ai_image_reconciliation_batch_size", 999)
    worker = AIImageWorker()
    assert worker._poll_timeout == 5
    assert worker._min_interval == 0
    assert worker._reconciliation_enabled is True
    assert worker._reconciliation_interval == 10
    assert worker._reconciliation_batch_size == 100
    assert worker._stop_event.is_set() is False
    worker.request_stop()
    assert worker._stop_event.is_set() is True


@pytest.mark.asyncio
async def test_worker_rate_limit_recovery_and_processing_paths(monkeypatch):
    worker = AIImageWorker()
    worker._min_interval = 0
    await worker._wait_rate_limit()

    worker._min_interval = 2
    worker._last_started_at = module.time.monotonic()
    sleep = AsyncMock()
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    await worker._wait_rate_limit()
    sleep.assert_awaited_once()
    assert worker._last_started_at > 0

    recovery = {
        "reset_processing": 1,
        "waiting_review": 2,
        "requeued_processing": 3,
        "enqueued_missing": 4,
        "discarded_processing": 5,
    }
    fake_service = SimpleNamespace(
        recover_incomplete_tasks=AsyncMock(return_value=recovery),
        execute_submitted_task=AsyncMock(return_value="completed"),
    )
    monkeypatch.setattr(module, "async_session", lambda: _SessionContext())
    monkeypatch.setattr(module, "AIImageService", lambda db: fake_service)
    monkeypatch.setattr(module.ai_image_task_queue, "ack_task", AsyncMock())
    monkeypatch.setattr(module.ai_image_task_queue, "requeue_reserved_task", AsyncMock())

    await worker._recover_tasks()
    fake_service.recover_incomplete_tasks.assert_awaited_once()
    worker._min_interval = 0
    await worker._process_reserved_task(10)
    fake_service.execute_submitted_task.assert_awaited_once_with(10)
    module.ai_image_task_queue.ack_task.assert_awaited_once_with(10)

    fake_service.execute_submitted_task.side_effect = RuntimeError("provider down")
    await worker._process_reserved_task(11)
    module.ai_image_task_queue.requeue_reserved_task.assert_awaited_once_with(11)


@pytest.mark.asyncio
async def test_worker_done_callback_handles_success_and_failure():
    worker = AIImageWorker()
    success = asyncio.create_task(asyncio.sleep(0))
    worker._active_tasks.add(success)
    await success
    worker._on_task_done(success)
    assert success not in worker._active_tasks

    async def fail():
        raise RuntimeError("task failed")

    failed = asyncio.create_task(fail())
    worker._active_tasks.add(failed)
    await asyncio.gather(failed, return_exceptions=True)
    worker._on_task_done(failed)
    assert failed not in worker._active_tasks


@pytest.mark.asyncio
async def test_reconciliation_loop_logs_results_and_recovers_from_error(monkeypatch):
    worker = AIImageWorker()

    async def reconcile_once(batch_size):
        assert batch_size == worker._reconciliation_batch_size
        worker.request_stop()
        return {"candidates": 2, "checked": 2, "resolved": 1, "skipped": 0, "errors": 0}

    monkeypatch.setattr(module, "reconcile_ai_image_shadow_jobs_once", reconcile_once)
    await worker._reconciliation_loop()

    worker = AIImageWorker()

    async def reconcile_error(batch_size):
        worker.request_stop()
        raise RuntimeError("reconcile failed")

    monkeypatch.setattr(module, "reconcile_ai_image_shadow_jobs_once", reconcile_error)
    await worker._reconciliation_loop()


@pytest.mark.asyncio
async def test_worker_run_handles_empty_queue_reserve_error_and_drains(monkeypatch):
    worker = AIImageWorker()
    worker._recover_tasks = AsyncMock()
    worker._process_reserved_task = AsyncMock()
    calls = 0

    async def reserve_with_task(timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            return 42
        worker.request_stop()
        return None

    monkeypatch.setattr(module.ai_image_task_queue, "reserve_task", reserve_with_task)
    await worker.run()
    worker._recover_tasks.assert_awaited_once()
    worker._process_reserved_task.assert_awaited_once_with(42)

    empty_worker = AIImageWorker()
    empty_worker._recover_tasks = AsyncMock()

    async def reserve_empty(timeout):
        empty_worker.request_stop()
        return None

    monkeypatch.setattr(module.ai_image_task_queue, "reserve_task", reserve_empty)
    await empty_worker.run()

    error_worker = AIImageWorker()
    error_worker._recover_tasks = AsyncMock()

    async def reserve_error(timeout):
        raise RuntimeError("redis down")

    async def stop_after_error(seconds):
        error_worker.request_stop()

    monkeypatch.setattr(module.ai_image_task_queue, "reserve_task", reserve_error)
    monkeypatch.setattr(module.asyncio, "sleep", stop_after_error)
    await error_worker.run()


@pytest.mark.asyncio
async def test_async_main_registers_signals_runs_and_closes(monkeypatch):
    fake_worker = SimpleNamespace(run=AsyncMock(), request_stop=lambda: None)
    monkeypatch.setattr(module, "AIImageWorker", lambda: fake_worker)
    close = AsyncMock()
    monkeypatch.setattr(module.ai_image_task_queue, "close", close)
    loop = asyncio.get_running_loop()
    def add_handler(*args, **kwargs):
        return None

    monkeypatch.setattr(loop, "add_signal_handler", add_handler)
    await module._async_main()
    fake_worker.run.assert_awaited_once()
    close.assert_awaited_once()
