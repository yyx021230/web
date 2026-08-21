"""Tests for splitting browser work across independent sync runners."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.db.session import async_session
from app.models.xhs_environment import XHSEnvironment
from app.services.xhs_service import XHSService


@pytest.mark.asyncio
async def test_account_note_runners_are_dispatched_concurrently(monkeypatch):
    service = XHSService(db=None)
    both_requests_started = asyncio.Event()
    started_runners: set[int] = set()
    calls: list[tuple[int, list[int]]] = []

    async def fake_worker_request(cls, *args, **kwargs):
        runner_id = int(kwargs["scrape_environment_id"])
        assignment = json.loads(kwargs["runner_account_assignments"])
        account_ids = assignment[str(runner_id)]
        calls.append((runner_id, account_ids))
        started_runners.add(runner_id)
        if len(started_runners) == 2:
            both_requests_started.set()
        await asyncio.wait_for(both_requests_started.wait(), timeout=0.2)
        return {"synced_accounts": len(account_ids), "created_notes": 1, "updated_notes": 2}

    monkeypatch.setattr(
        XHSService,
        "trigger_worker_sync_account_notes",
        classmethod(fake_worker_request),
    )

    result = await service._delegate_account_note_sync_by_runner(
        envs=[SimpleNamespace(id=101), SimpleNamespace(id=102), SimpleNamespace(id=103)],
        runner_ids=[44, 45],
        runner_assignments={44: [101, 103], 45: [102]},
    )

    assert sorted(calls) == [(44, [101, 103]), (45, [102])]
    assert result["synced_accounts"] == 3
    assert result["created_notes"] == 2
    assert result["updated_notes"] == 4


@pytest.mark.asyncio
async def test_local_account_note_runner_buckets_do_not_wait_on_legacy_publish_lock(monkeypatch, client):
    service = XHSService(db=None)
    both_requests_started = asyncio.Event()
    started_runners: set[int] = set()

    async with async_session() as db:
        db.add_all([
            XHSEnvironment(id=9043, shop_id="runner-9043", account_name="测试5", status="active"),
            XHSEnvironment(id=9045, shop_id="runner-9045", account_name="测试4", status="active"),
            XHSEnvironment(id=9101, shop_id="target-9101", account_name="发布账号A", status="active"),
            XHSEnvironment(id=9102, shop_id="target-9102", account_name="发布账号B", status="active"),
        ])
        await db.commit()

    async def fake_batch(self, envs, *, scrape_env, **kwargs):
        started_runners.add(int(scrape_env.id))
        if len(started_runners) == 2:
            both_requests_started.set()
        await asyncio.wait_for(both_requests_started.wait(), timeout=0.2)
        return {
            "synced_accounts": len(envs),
            "created_notes": 0,
            "updated_notes": 0,
            "metric_synced_notes": 0,
            "total_notes": 0,
        }

    monkeypatch.setattr(XHSService, "_sync_account_notes_batch_locked", fake_batch)

    legacy_lock = await service._get_env_publish_lock(9043)
    await legacy_lock.acquire()
    try:
        result = await service._sync_account_notes_with_strategy(
            envs=[SimpleNamespace(id=9101), SimpleNamespace(id=9102)],
            scrape_envs=[SimpleNamespace(id=9043), SimpleNamespace(id=9045)],
            limit=60,
            persona=SimpleNamespace(),
            runner_buckets=[
                (SimpleNamespace(id=9043), [SimpleNamespace(id=9101)]),
                (SimpleNamespace(id=9045), [SimpleNamespace(id=9102)]),
            ],
            concurrency=2,
        )
    finally:
        legacy_lock.release()

    assert started_runners == {9043, 9045}
    assert result["synced_accounts"] == 2


@pytest.mark.asyncio
async def test_account_note_runners_propagate_worker_account_failures(monkeypatch):
    service = XHSService(db=None)

    async def fake_worker_request(cls, *args, **kwargs):
        runner_id = int(kwargs["scrape_environment_id"])
        assignment = json.loads(kwargs["runner_account_assignments"])
        account_ids = assignment[str(runner_id)]
        return {
            "synced_accounts": 0,
            "created_notes": 0,
            "updated_notes": 0,
            "failed_accounts": [
                {
                    "environment_id": account_ids[0],
                    "account_name": "失败账号",
                    "error": "获取账号主页超时",
                }
            ],
        }

    monkeypatch.setattr(
        XHSService,
        "trigger_worker_sync_account_notes",
        classmethod(fake_worker_request),
    )

    result = await service._delegate_account_note_sync_by_runner(
        envs=[SimpleNamespace(id=101)],
        runner_ids=[44],
        runner_assignments={44: [101]},
    )

    assert result["synced_accounts"] == 0
    assert result["failed_accounts"] == [
        {
            "environment_id": 101,
            "account_name": "失败账号",
            "error": "获取账号主页超时",
        }
    ]


@pytest.mark.asyncio
async def test_note_detail_runners_split_notes_without_overlap(monkeypatch):
    service = XHSService(db=None)
    both_requests_started = asyncio.Event()
    started_runners: set[int] = set()
    calls: dict[int, list[int]] = {}

    async def fake_worker_request(cls, *args, **kwargs):
        runner_id = int(kwargs["scrape_environment_id"])
        note_ids = [int(item) for item in kwargs["target_note_ids"].split(",")]
        calls[runner_id] = note_ids
        started_runners.add(runner_id)
        if len(started_runners) == 2:
            both_requests_started.set()
        await asyncio.wait_for(both_requests_started.wait(), timeout=0.2)
        return {"synced_notes": len(note_ids), "failed_notes": 0, "synced_note_ids": note_ids}

    monkeypatch.setattr(
        XHSService,
        "trigger_worker_sync_account_note_details",
        classmethod(fake_worker_request),
    )

    result = await service._delegate_account_note_detail_sync_by_runner(
        active_note_ids=[201, 202, 203, 204, 205],
        matched_notes=5,
        skipped_notes=0,
        runner_ids=[44, 45],
        sync_limit_per_runner=None,
        pause_seconds_min=None,
        pause_seconds_max=None,
        max_post_age_days=None,
    )

    assert calls == {44: [201, 203, 205], 45: [202, 204]}
    assert result["synced_notes"] == 5
    assert result["failed_notes"] == 0
    assert sorted(result["synced_note_ids"]) == [201, 202, 203, 204, 205]
