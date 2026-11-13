"""Opt-in real PostgreSQL: native homepage/detail lifecycle with fake browser/MCP."""

import asyncio
from datetime import datetime
import os

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import session as db_session
from app.models.xhs_account import XHSAccount
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_account_sync_run import XHSAccountSyncRun
from app.models.xhs_environment import XHSEnvironment
from app.schemas.xhs_account_master import MasterSyncRequest
from app.services.xhs_master_sync import XHSMasterSync
from app.services.xhs_service import XHSService
from tests.test_xhs_master_cutover import roster


@pytest.mark.asyncio
async def test_pg_native_parallel_homepage_detail_and_failure_retry(monkeypatch):
    dsn = os.environ.get("XHS_CUTOVER_TEST_POSTGRES_URL")
    if not dsn:
        pytest.skip("requires a separate disposable local PostgreSQL database")
    url = make_url(dsn)
    assert url.host == "127.0.0.1" and url.database.startswith("xhs_cloud_test_")
    engine = create_async_engine(dsn)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    import app.services.xhs_service as service_module
    import app.services.yundeng_sync_coordinator as coordinator_module
    from app.services.yundeng_sync_coordinator import YunDengSyncCoordinator

    monkeypatch.setattr(settings, "xhs_account_master_enabled", True)
    monkeypatch.setattr(db_session, "async_session", sessions)
    monkeypatch.setattr(service_module, "async_session", sessions)
    monkeypatch.setattr(service_module, "XHS_MCP_EXTERNAL_API", "")
    monkeypatch.setattr(
        coordinator_module,
        "yundeng_sync_coordinator",
        YunDengSyncCoordinator(
            redis_url="redis://invalid",
            distributed_enabled=False,
            start_stagger_seconds=0,
        ),
    )
    monkeypatch.setattr(
        XHSService, "_should_delegate_browser_ops", staticmethod(lambda: False)
    )
    active = 0
    peak = 0
    closed = []
    opened = []

    async def no_op(*args, **kwargs):
        pass

    async def port(*args):
        return 19000

    async def browser(self, runner_id, **kwargs):
        opened.append(runner_id)
        return await self.db.get(XHSEnvironment, runner_id), "ws://fake.invalid"

    async def start(self, *args):
        return object()

    async def stop(self, pid):
        closed.append(pid)

    async def fetch(self, profile_url, *args, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.15)
        index = 0 if profile_url.endswith("abcd0") else 1
        active -= 1
        return {
            "red_id": "123456789" if index == 0 else "10000002",
            "profile_nickname": "Remote name",
            "feeds": [
                {
                    "feed_id": str(index + 1) * 24,
                    "title": "Post " + str(index),
                    "published_at": datetime(2026, 11, 12, 2, 30),
                    "cover_image_url": None,
                    "sort_index": 0,
                }
            ],
        }

    async def detail(self, feed_id, *args, **kwargs):
        return {
            "content": "Full body from homepage detail",
            "image_urls": [],
            "liked_count": 8,
            "comment_count": 2,
            "collected_count": 3,
            "share_count": 1,
        }

    monkeypatch.setattr(XHSService, "_allocate_free_port", port)
    monkeypatch.setattr(
        XHSService, "_acquire_ready_sync_browser_ws_with_fallback", browser
    )
    monkeypatch.setattr(XHSService, "_start_mcp", start)
    monkeypatch.setattr(XHSService, "_stop_mcp", stop)
    for name in (
        "_wait_mcp_ready",
        "_run_sync_browser_warmup",
        "_sleep_sync_profile_prep",
        "_sleep_between_account_note_details",
        "_sleep_between_account_note_context_switch",
        "_sleep_between_sync_batches",
    ):
        monkeypatch.setattr(XHSService, name, no_op)
    monkeypatch.setattr(XHSService, "_fetch_profile_account_notes", fetch)
    monkeypatch.setattr(XHSService, "_fetch_account_note_detail_metrics", detail)
    try:
        async with sessions() as db:
            _, accounts = await roster(db)
            ids = [a.id for a in accounts]
            run = await XHSMasterSync(db).prepare(
                MasterSyncRequest(
                    kind="posts",
                    account_ids=ids,
                    runner_ids=[100, 101],
                    concurrency=2,
                    homepage_sync_mode="create_missing",
                )
            )
            result = await XHSMasterSync(db).execute(run.id)
            assert result["synced_accounts"] == 2, result
            assert result["created_notes"] == 2 and result["total_notes"] == 2
            assert peak == 2 and sorted(opened) == [100, 101]
            assert len(closed) == 2
            assert (
                await db.scalar(select(func.count()).select_from(XHSAccountNote)) == 2
            )
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(XHSAccountNote)
                    .where(XHSAccountNote.environment_id.is_not(None))
                )
                == 0
            )
            # A single global note limit, not the old limit multiplied by account count.
            detail_run = await XHSMasterSync(db).prepare(
                MasterSyncRequest(
                    kind="details",
                    account_ids=ids,
                    runner_ids=[100, 101],
                    sync_limit=1,
                    pause_seconds_min=0,
                    pause_seconds_max=0,
                )
            )
            result = await XHSMasterSync(db).execute(detail_run.id)
            assert not result["failed_accounts"], result
            assert result["synced_notes"] == 1 and result["total_notes"] == 1
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(XHSAccountNote)
                    .where(XHSAccountNote.content == "Full body from homepage detail")
                )
                == 1
            )
            # Missing locator fails before browser startup, and only that account retries.
            account = await db.get(XHSAccount, ids[0])
            account.profile_url = None
            account.revision += 1
            await db.commit()
            run = await XHSMasterSync(db).prepare(
                MasterSyncRequest(kind="posts", account_ids=ids, runner_ids=[100, 101])
            )
            result = await XHSMasterSync(db).execute(run.id)
            assert (
                result["status"] == "partial_failed"
                and result["failed_accounts"][0]["account_id"] == ids[0]
            )
            saved = await db.scalar(
                select(XHSAccountSyncRun)
                .where(XHSAccountSyncRun.id == run.id)
                .options(selectinload(XHSAccountSyncRun.items))
                .execution_options(populate_existing=True)
            )
            retry = await XHSMasterSync(db).retry_request(saved)
            assert retry.account_ids == [ids[0]]
            assert (
                await db.scalar(text("SELECT version_num FROM alembic_version"))
                == "e61113b0b002"
            )
    finally:
        await engine.dispose()
