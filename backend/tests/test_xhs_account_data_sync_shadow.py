from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select

import app.api.v1.xhs as xhs_api
from app.config import settings
from app.db.session import async_session
from app.models.job import Job, JobAttempt, JobItem, JobStatus
from app.models.user import User
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_account_sync_run import XHSAccountSyncRun, XHSAccountSyncRunItem
from app.models.xhs_environment import XHSEnvironment
from app.services.job_service import JobService
from app.services.xhs_homepage_sync_parity_service import HomepageSyncParityService
from app.services.xhs_homepage_sync_shadow import (
    SECONDARY_SYNC_KINDS,
    SHADOW_JOB_TYPES,
    SHADOW_SOURCE_TYPE,
    SHADOW_WORKER_TYPE,
    HomepageSyncShadowAdapter,
    mirror_account_data_sync_shadow_safely,
)
from app.services.xhs_service import XHSService
from app.utils.timezone import aware_or_cst_naive_to_utc_naive
from tests.conftest import make_auth_headers


@pytest_asyncio.fixture(autouse=True)
async def reset_account_data_sync_runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "xhs_engagement_detail_sync_shadow_enabled", False)
    xhs_api.XHS_BACKGROUND_JOBS.clear()
    xhs_api.XHS_BACKGROUND_JOB_TASKS.clear()
    yield
    tasks = list(xhs_api.XHS_BACKGROUND_JOB_TASKS.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    xhs_api.XHS_BACKGROUND_JOB_TASKS.clear()
    xhs_api.XHS_BACKGROUND_JOBS.clear()


async def _seed_identity(db) -> list[XHSEnvironment]:
    db.add(
        User(
            id=1,
            username="account-data-admin",
            email="account-data-admin@example.com",
            hashed_password="x",
            role="admin",
        )
    )
    environments = [
        XHSEnvironment(
            id=200 + index,
            shop_id=f"account-data-shop-{index}",
            account_name=f"数据账号{index}",
            status="active",
            is_sync_runner=False,
        )
        for index in range(1, 3)
    ]
    db.add_all(environments)
    await db.flush()
    return environments


async def _create_run(
    db,
    *,
    sync_kind: str,
    job_id: str,
    environments: list[XHSEnvironment],
    status: str = "queued",
    item_statuses: list[str] | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    error: str | None = None,
) -> int:
    run = XHSAccountSyncRun(
        job_id=job_id,
        sync_kind=sync_kind,
        source="manual",
        status=status,
        requested_by_user_id=1,
        request_config={"environment_ids": [env.id for env in environments]},
        message="同步完成" if status == "succeeded" else "任务排队中",
        error=error,
        started_at=started_at,
        finished_at=finished_at,
    )
    db.add(run)
    await db.flush()
    statuses = item_statuses or ["queued"] * len(environments)
    for environment, item_status in zip(environments, statuses):
        db.add(
            XHSAccountSyncRunItem(
                run_id=run.id,
                environment_id=environment.id,
                account_name=environment.account_name,
                status=item_status,
                message="账号同步完成" if item_status == "succeeded" else None,
                error="账号同步失败" if item_status == "failed" else None,
                result={"metric_synced_notes": 3}
                if item_status == "succeeded"
                else None,
                started_at=started_at if item_status != "queued" else None,
                finished_at=finished_at
                if item_status in {"succeeded", "failed", "cancelled"}
                else None,
            )
        )
    await db.commit()
    return int(run.id)


async def _load_shadow(db, run_id: int) -> Job:
    return (
        await db.execute(
            select(Job).where(
                Job.source_type == SHADOW_SOURCE_TYPE,
                Job.source_id == str(run_id),
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_secondary_shadow_defaults_off_and_homepage_adapter_stays_isolated(client):
    async with async_session() as db:
        environments = await _seed_identity(db)
        engagement_run_id = await _create_run(
            db,
            sync_kind="engagement",
            job_id="engagement-disabled",
            environments=environments,
        )
        posts_run_id = await _create_run(
            db,
            sync_kind="posts",
            job_id="posts-isolated",
            environments=environments,
        )

        assert await HomepageSyncShadowAdapter(db).mirror(engagement_run_id) is None
        assert (
            await HomepageSyncShadowAdapter(
                db,
                sync_kinds=SECONDARY_SYNC_KINDS,
            ).mirror(posts_run_id)
            is None
        )
        await db.commit()

    assert settings.xhs_engagement_detail_sync_shadow_enabled is False
    assert await mirror_account_data_sync_shadow_safely(engagement_run_id) is None
    async with async_session() as db:
        assert (await db.execute(select(func.count(Job.id)))).scalar_one() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("sync_kind", ["engagement", "details"])
async def test_terminal_secondary_sync_maps_to_unclaimable_durable_job(client, sync_kind):
    started_at = datetime(2026, 8, 10, 9, 0, 0)
    finished_at = datetime(2026, 8, 10, 9, 5, 0)
    async with async_session() as db:
        environments = await _seed_identity(db)
        run_id = await _create_run(
            db,
            sync_kind=sync_kind,
            job_id=f"{sync_kind}-terminal",
            environments=environments,
            status="succeeded",
            item_statuses=["succeeded", "failed"],
            started_at=started_at,
            finished_at=finished_at,
        )
        job = await HomepageSyncShadowAdapter(
            db,
            sync_kinds=SECONDARY_SYNC_KINDS,
        ).mirror(
            run_id,
            legacy_job={"status": "succeeded", "result": {"synced_accounts": 1}},
        )
        assert job is not None
        await db.commit()

        assert job.job_type == SHADOW_JOB_TYPES[sync_kind]
        assert job.worker_type == SHADOW_WORKER_TYPE
        assert job.status == JobStatus.SUCCEEDED.value
        assert job.payload["legacy_sync_kind"] == sync_kind
        assert job.result_summary["legacy_sync_kind"] == sync_kind
        assert job.result_summary["succeeded_accounts"] == 1
        assert job.result_summary["failed_accounts"] == 1
        assert job.started_at == aware_or_cst_naive_to_utc_naive(started_at)
        assert job.finished_at == aware_or_cst_naive_to_utc_naive(finished_at)

        items = list(
            (
                await db.execute(
                    select(JobItem)
                    .where(JobItem.job_id == job.id)
                    .order_by(JobItem.item_key)
                )
            )
            .scalars()
            .all()
        )
        assert [item.status for item in items] == ["succeeded", "failed"]
        assert await JobService(db).claim_next_job(
            worker_id="normal-worker",
            worker_type="server",
        ) is None
        assert (await db.execute(select(func.count(JobAttempt.id)))).scalar_one() == 0


@pytest.mark.asyncio
async def test_engagement_progress_only_updates_named_account(client):
    started_at = datetime(2026, 8, 10, 10, 0, 0)
    async with async_session() as db:
        environments = await _seed_identity(db)
        run_id = await _create_run(
            db,
            sync_kind="engagement",
            job_id="engagement-progress",
            environments=environments,
            status="running",
            item_statuses=["running", "queued"],
            started_at=started_at,
        )
        job = await HomepageSyncShadowAdapter(
            db,
            sync_kinds=SECONDARY_SYNC_KINDS,
        ).mirror(
            run_id,
            legacy_job={
                "status": "running",
                "progress": {
                    "phase": "syncing_account_engagements",
                    "account_name": "数据账号1",
                },
            },
        )
        assert job is not None
        await db.commit()

        items = list(
            (
                await db.execute(
                    select(JobItem)
                    .where(JobItem.job_id == job.id)
                    .order_by(JobItem.item_key)
                )
            )
            .scalars()
            .all()
        )
        assert len(items) == 1
        assert items[0].display_name == "数据账号1"
        assert items[0].status == "running"
        assert job.progress_total == 2


@pytest.mark.asyncio
async def test_detail_sync_avoids_per_note_shadow_writes_but_captures_terminal_items(
    client, monkeypatch
):
    monkeypatch.setattr(settings, "xhs_engagement_detail_sync_shadow_enabled", True)
    async with async_session() as db:
        environments = await _seed_identity(db)
        run_id = await _create_run(
            db,
            sync_kind="details",
            job_id="detail-batch-boundaries",
            environments=[],
        )

    await mirror_account_data_sync_shadow_safely(
        run_id,
        legacy_job={"status": "running", "progress": {"phase": "runner_processing"}},
    )
    async with async_session() as db:
        job = await _load_shadow(db, run_id)
        assert (
            await db.execute(
                select(func.count(JobItem.id)).where(JobItem.job_id == job.id)
            )
        ).scalar_one() == 0

        run = await db.get(XHSAccountSyncRun, run_id)
        run.status = "succeeded"
        run.started_at = datetime(2026, 8, 10, 10, 0, 0)
        run.finished_at = datetime(2026, 8, 10, 10, 3, 0)
        db.add(
            XHSAccountSyncRunItem(
                run_id=run_id,
                environment_id=environments[0].id,
                account_name=environments[0].account_name,
                status="succeeded",
                result={"succeeded_note_count": 4, "succeeded_note_ids": [1, 2, 3, 4]},
                started_at=run.started_at,
                finished_at=run.finished_at,
            )
        )
        await db.commit()

    await mirror_account_data_sync_shadow_safely(
        run_id,
        legacy_job={"status": "succeeded", "result": {"total_notes": 4}},
    )
    async with async_session() as db:
        job = await _load_shadow(db, run_id)
        item = (
            await db.execute(select(JobItem).where(JobItem.job_id == job.id))
        ).scalar_one()
        assert job.status == "succeeded"
        assert item.result["succeeded_note_ids"] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_secondary_shadow_failure_cannot_fail_legacy_path(client, monkeypatch, caplog):
    monkeypatch.setattr(settings, "xhs_engagement_detail_sync_shadow_enabled", True)
    async with async_session() as db:
        environments = await _seed_identity(db)
        run_id = await _create_run(
            db,
            sync_kind="engagement",
            job_id="engagement-shadow-failure",
            environments=environments,
        )

    async def fail_mirror(*args, **kwargs):
        raise RuntimeError("shadow database unavailable")

    monkeypatch.setattr(HomepageSyncShadowAdapter, "mirror", fail_mirror)
    assert await mirror_account_data_sync_shadow_safely(run_id) is None
    assert "account data sync shadow mirror failed" in caplog.text


@pytest.mark.asyncio
async def test_queued_cancel_closes_persistent_history_and_shadow(client, monkeypatch):
    monkeypatch.setattr(settings, "xhs_engagement_detail_sync_shadow_enabled", True)
    async with async_session() as db:
        environments = await _seed_identity(db)
        legacy_job = xhs_api._new_job(
            "account_note_engagement_sync",
            environment_id=None,
            target_environment_ids="201,202",
        )
        run_id = await _create_run(
            db,
            sync_kind="engagement",
            job_id=legacy_job["job_id"],
            environments=environments,
        )

    legacy_job["history_run_id"] = run_id
    sleeper = asyncio.create_task(asyncio.sleep(60))
    xhs_api.XHS_BACKGROUND_JOB_TASKS[legacy_job["job_id"]] = sleeper

    response = await client.post(
        f"/api/v1/xhs/account-notes/sync-jobs/{legacy_job['job_id']}/cancel",
        headers=make_auth_headers(1),
    )
    assert response.status_code == 200
    await asyncio.gather(sleeper, return_exceptions=True)

    async with async_session() as db:
        run = await db.get(XHSAccountSyncRun, run_id)
        items = list(
            (
                await db.execute(
                    select(XHSAccountSyncRunItem).where(
                        XHSAccountSyncRunItem.run_id == run_id
                    )
                )
            )
            .scalars()
            .all()
        )
        shadow = await _load_shadow(db, run_id)
        assert run is not None and run.status == "cancelled"
        assert all(item.status == "cancelled" for item in items)
        assert shadow.status == "cancelled"
        assert shadow.cancel_requested is True


@pytest.mark.asyncio
@pytest.mark.parametrize("sync_kind", ["engagement", "details"])
async def test_secondary_parity_exact_match_and_missing_shadow_detection(client, sync_kind):
    started_at = datetime(2026, 8, 10, 11, 0, 0)
    finished_at = datetime(2026, 8, 10, 11, 2, 0)
    async with async_session() as db:
        environments = await _seed_identity(db)
        matched_run_id = await _create_run(
            db,
            sync_kind=sync_kind,
            job_id=f"{sync_kind}-parity-match",
            environments=environments,
            status="succeeded",
            item_statuses=["succeeded", "succeeded"],
            started_at=started_at,
            finished_at=finished_at,
        )
        missing_run_id = await _create_run(
            db,
            sync_kind=sync_kind,
            job_id=f"{sync_kind}-parity-missing",
            environments=environments,
            status="failed",
            item_statuses=["failed", "failed"],
            started_at=started_at,
            finished_at=finished_at,
            error="upstream failed",
        )
        matched = await HomepageSyncShadowAdapter(
            db,
            sync_kinds=SECONDARY_SYNC_KINDS,
        ).mirror(
            matched_run_id,
            legacy_job={"status": "succeeded", "result": {"synced_accounts": 2}},
        )
        assert matched is not None
        await db.commit()

        report = await HomepageSyncParityService(
            db,
            sync_kind=sync_kind,
        ).build_report(sample_limit=10, min_samples=1)

    assert report["sync_kind"] == sync_kind
    assert report["summary"]["evaluated_count"] == 2
    samples = {row["legacy_run_id"]: row for row in report["samples"]}
    assert samples[matched_run_id]["matched"] is True
    assert samples[missing_run_id]["mismatch_codes"] == ["missing_shadow_job"]
    assert report["migration_gate"]["decision"] == "blocked_by_mismatch"


@pytest.mark.asyncio
async def test_secondary_parity_endpoint_is_admin_only_and_reports_selected_kind(
    client, monkeypatch
):
    monkeypatch.setattr(settings, "xhs_engagement_detail_sync_shadow_enabled", True)
    async with async_session() as db:
        environments = await _seed_identity(db)
        db.add(
            User(
                id=2,
                username="account-data-viewer",
                email="account-data-viewer@example.com",
                hashed_password="x",
                role="viewer",
            )
        )
        run_id = await _create_run(
            db,
            sync_kind="engagement",
            job_id="engagement-endpoint",
            environments=environments,
            status="succeeded",
            item_statuses=["succeeded", "succeeded"],
            started_at=datetime(2026, 8, 10, 12, 0, 0),
            finished_at=datetime(2026, 8, 10, 12, 1, 0),
        )
        job = await HomepageSyncShadowAdapter(
            db,
            sync_kinds=SECONDARY_SYNC_KINDS,
        ).mirror(
            run_id,
            legacy_job={"status": "succeeded", "result": {"synced_accounts": 2}},
        )
        assert job is not None
        await db.commit()

    denied = await client.get(
        "/api/v1/admin/reliability/xhs-account-data-shadow",
        params={"sync_kind": "engagement", "min_samples": 1},
        headers=make_auth_headers(2),
    )
    assert denied.status_code == 403

    response = await client.get(
        "/api/v1/admin/reliability/xhs-account-data-shadow",
        params={"sync_kind": "engagement", "min_samples": 1},
        headers=make_auth_headers(1),
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["feature_enabled"] is True
    assert payload["sync_kind"] == "engagement"
    assert payload["summary"]["matched_count"] == 1


@pytest.mark.asyncio
async def test_engagement_endpoint_executes_business_sync_once_with_shadow_enabled(
    client, monkeypatch
):
    monkeypatch.setattr(settings, "xhs_engagement_detail_sync_shadow_enabled", True)
    calls = 0

    async with async_session() as db:
        await _seed_identity(db)
        await db.commit()

    async def fake_sync(self, *, progress_callback, **kwargs):
        nonlocal calls
        calls += 1
        for account_name in ("数据账号1", "数据账号2"):
            await progress_callback(
                {
                    "phase": "account_engagement_completed",
                    "account_name": account_name,
                    "detail": f"{account_name}互动同步完成",
                    "metric_synced_notes": 3,
                }
            )
        return {"synced_accounts": 2, "metric_synced_notes": 6}

    monkeypatch.setattr(XHSService, "sync_account_note_engagements", fake_sync)
    response = await client.post(
        "/api/v1/xhs/account-notes/sync-engagement",
        params={"target_environment_ids": "201,202"},
        headers=make_auth_headers(1),
    )
    assert response.status_code == 200
    job_id = response.json()["data"]["job_id"]
    task = xhs_api.XHS_BACKGROUND_JOB_TASKS[job_id]
    await task

    assert calls == 1
    async with async_session() as db:
        run = (
            await db.execute(
                select(XHSAccountSyncRun).where(XHSAccountSyncRun.job_id == job_id)
            )
        ).scalar_one()
        shadow = await _load_shadow(db, int(run.id))
        assert shadow.status == "succeeded"
        assert shadow.job_type == SHADOW_JOB_TYPES["engagement"]
        assert shadow.progress_current == 2


@pytest.mark.asyncio
async def test_detail_endpoint_executes_business_sync_once_with_terminal_shadow(
    client, monkeypatch
):
    monkeypatch.setattr(settings, "xhs_engagement_detail_sync_shadow_enabled", True)
    calls = 0

    async with async_session() as db:
        environments = await _seed_identity(db)
        db.add(
            XHSAccountNote(
                id=901,
                environment_id=environments[0].id,
                account_name=environments[0].account_name,
                feed_id="detail-note-901",
                title="待同步详情",
                status="active",
            )
        )
        await db.commit()

    async def fake_sync(self, *, progress_callback, **kwargs):
        nonlocal calls
        calls += 1
        await progress_callback(
            {
                "phase": "runner_processing",
                "current_note_id": 901,
                "current_note_succeeded": True,
                "detail": "帖子详情同步完成",
            }
        )
        return {
            "total_notes": 1,
            "synced_notes": 1,
            "failed_notes": 0,
            "synced_note_ids": [901],
            "failed_note_ids": [],
        }

    monkeypatch.setattr(XHSService, "sync_existing_account_note_stats", fake_sync)
    response = await client.post(
        "/api/v1/xhs/account-notes/sync-details",
        params={"target_note_ids": "901", "sync_limit": 1},
        headers=make_auth_headers(1),
    )
    assert response.status_code == 200
    job_id = response.json()["data"]["job_id"]
    task = xhs_api.XHS_BACKGROUND_JOB_TASKS[job_id]
    await task

    assert calls == 1
    async with async_session() as db:
        run = (
            await db.execute(
                select(XHSAccountSyncRun).where(XHSAccountSyncRun.job_id == job_id)
            )
        ).scalar_one()
        shadow = await _load_shadow(db, int(run.id))
        items = list(
            (
                await db.execute(select(JobItem).where(JobItem.job_id == shadow.id))
            )
            .scalars()
            .all()
        )
        assert shadow.status == "succeeded"
        assert shadow.job_type == SHADOW_JOB_TYPES["details"]
        assert len(items) == 1
        assert items[0].result["succeeded_note_ids"] == [901]
