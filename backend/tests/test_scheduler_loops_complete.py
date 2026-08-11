from __future__ import annotations

from datetime import datetime

import pytest

from app.services import scheduler


class _SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *args):
        return False


def _session_factory():
    return _SessionContext()


class _StopLoop(Exception):
    pass


def _sleep_after(calls_before_stop: int):
    calls = {"count": 0}

    async def sleep(_seconds):
        calls["count"] += 1
        if calls["count"] > calls_before_stop:
            raise _StopLoop

    return sleep


@pytest.mark.asyncio
@pytest.mark.parametrize("hour", [7, 10, 21])
async def test_sync_task_loop_schedules_all_time_windows(monkeypatch, hour):
    monkeypatch.setattr(scheduler, "cst_now_naive", lambda: datetime(2026, 8, 11, hour, 0))
    monkeypatch.setattr(scheduler.asyncio, "sleep", _sleep_after(1))

    class _XHS:
        def __init__(self, _db):
            pass

        async def sync_all_posts(self):
            return 3

    monkeypatch.setattr(scheduler, "XHSService", _XHS)
    with pytest.raises(_StopLoop):
        await scheduler.sync_task_loop(_session_factory)


@pytest.mark.asyncio
async def test_sync_task_loop_survives_service_error(monkeypatch):
    monkeypatch.setattr(scheduler, "cst_now_naive", lambda: datetime(2026, 8, 11, 10, 0))
    monkeypatch.setattr(scheduler.asyncio, "sleep", _sleep_after(1))

    class _XHS:
        def __init__(self, _db):
            pass

        async def sync_all_posts(self):
            raise RuntimeError("sync failed")

    monkeypatch.setattr(scheduler, "XHSService", _XHS)
    with pytest.raises(_StopLoop):
        await scheduler.sync_task_loop(_session_factory)


@pytest.mark.asyncio
async def test_scheduled_publish_loop_success_and_migration_error(monkeypatch):
    outcomes = [2, RuntimeError("no such column: xhs_posts.scheduled_at")]

    class _XHS:
        def __init__(self, _db):
            pass

        async def execute_due_scheduled_posts(self):
            result = outcomes.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr(scheduler, "XHSService", _XHS)
    monkeypatch.setattr(scheduler.asyncio, "sleep", _sleep_after(1))
    with pytest.raises(_StopLoop):
        await scheduler.scheduled_publish_loop(_session_factory, interval_seconds=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("hour", [18, 20])
async def test_account_notes_sync_loop_success(monkeypatch, hour):
    monkeypatch.setattr(scheduler, "cst_now_naive", lambda: datetime(2026, 8, 11, hour, 0))
    monkeypatch.setattr(scheduler.asyncio, "sleep", _sleep_after(1))

    class _XHS:
        def __init__(self, _db):
            pass

        async def sync_account_notes(self, **kwargs):
            return {"synced_accounts": 2, "created_notes": 3, "updated_notes": 4, "total_notes": 7}

        async def sync_existing_account_note_stats(self):
            return {"total_notes": 7, "synced_notes": 6, "failed_notes": 1}

    monkeypatch.setattr(scheduler, "XHSService", _XHS)
    with pytest.raises(_StopLoop):
        await scheduler.account_notes_sync_loop(_session_factory)


@pytest.mark.asyncio
async def test_account_notes_sync_loop_handles_list_and_detail_errors(monkeypatch):
    monkeypatch.setattr(scheduler, "cst_now_naive", lambda: datetime(2026, 8, 11, 20, 0))
    monkeypatch.setattr(scheduler.asyncio, "sleep", _sleep_after(2))
    calls = {"list": 0}

    class _XHS:
        def __init__(self, _db):
            pass

        async def sync_account_notes(self, **kwargs):
            calls["list"] += 1
            if calls["list"] == 1:
                raise RuntimeError("no such column: xhs_account_notes.content")
            return {}

        async def sync_existing_account_note_stats(self):
            raise RuntimeError("无法获取采集环境")

    monkeypatch.setattr(scheduler, "XHSService", _XHS)
    with pytest.raises(_StopLoop):
        await scheduler.account_notes_sync_loop(_session_factory)


@pytest.mark.asyncio
async def test_configured_task_loop_launches_due_tasks(monkeypatch):
    async def due(_session):
        return ["account_data_sync", "ad_report_refresh"]

    async def trigger(task_key, **kwargs):
        return task_key == "account_data_sync"

    monkeypatch.setattr(scheduler, "due_xhs_schedule_task_keys", due)
    monkeypatch.setattr(scheduler, "trigger_xhs_scheduled_task", trigger)
    monkeypatch.setattr(scheduler.asyncio, "sleep", _sleep_after(0))
    with pytest.raises(_StopLoop):
        await scheduler.xhs_configured_task_loop(_session_factory, poll_seconds=1)


@pytest.mark.asyncio
async def test_ai_cleanup_loop_applies_minimums_and_recovers(monkeypatch):
    seen = []

    class _AIService:
        def __init__(self, db):
            pass

        async def cleanup_stale_tasks(self, stale_after_minutes):
            seen.append(stale_after_minutes)
            return 2

    monkeypatch.setattr(scheduler, "AIImageService", _AIService)
    monkeypatch.setattr(scheduler.asyncio, "sleep", _sleep_after(0))
    with pytest.raises(_StopLoop):
        await scheduler.ai_task_cleanup_loop(
            _session_factory,
            interval_seconds=1,
            stale_after_minutes=1,
        )
    assert seen == [5]
