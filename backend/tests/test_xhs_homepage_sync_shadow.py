from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select

import app.api.v1.xhs as xhs_api
from app.config import settings
from app.db.session import async_session
from app.models.job import Job, JobAttempt, JobEvent, JobItem, JobStatus
from app.models.user import User
from app.models.xhs_account_sync_run import (
    XHSAccountSyncRun,
    XHSAccountSyncRunItem,
)
from app.models.xhs_environment import XHSEnvironment
from app.services.job_service import JobService
from app.services.xhs_homepage_sync_shadow import (
    SHADOW_JOB_TYPE,
    SHADOW_SOURCE_TYPE,
    SHADOW_WORKER_TYPE,
    HomepageSyncShadowAdapter,
    mirror_homepage_sync_shadow_safely,
)
from app.services.xhs_service import XHSService
from app.utils.timezone import aware_or_cst_naive_to_utc_naive


@pytest_asyncio.fixture(autouse=True)
async def reset_homepage_sync_runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "xhs_homepage_sync_shadow_enabled", False)
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


async def _seed_identity(db, *, environment_count: int = 2) -> list[XHSEnvironment]:
    db.add(
        User(
            id=1,
            username="shadow-admin",
            email="shadow-admin@example.com",
            hashed_password="x",
            role="admin",
        )
    )
    environments = [
        XHSEnvironment(
            id=100 + index,
            shop_id=f"shadow-shop-{index}",
            account_name=f"账号{index}",
            status="active",
        )
        for index in range(1, environment_count + 1)
    ]
    db.add_all(environments)
    await db.flush()
    return environments


async def _create_legacy_run(
    db,
    *,
    job_id: str,
    environments: list[XHSEnvironment],
    sync_kind: str = "posts",
    source: str = "manual",
    status: str = "queued",
    parent_run_id: int | None = None,
    message: str = "任务排队中",
    error: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    item_statuses: list[str] | None = None,
) -> int:
    run = XHSAccountSyncRun(
        job_id=job_id,
        sync_kind=sync_kind,
        source=source,
        status=status,
        requested_by_user_id=1,
        parent_run_id=parent_run_id,
        request_config={
            "runner_account_assignments": {"runner": [env.id for env in environments]}
        },
        message=message,
        error=error,
        started_at=started_at,
        finished_at=finished_at,
    )
    db.add(run)
    await db.flush()
    statuses = item_statuses or ["queued"] * len(environments)
    assert len(statuses) == len(environments)
    for environment, item_status in zip(environments, statuses):
        db.add(
            XHSAccountSyncRunItem(
                run_id=run.id,
                environment_id=environment.id,
                account_name=environment.account_name,
                status=item_status,
                message="账号结果" if item_status != "queued" else None,
                error="账号失败" if item_status == "failed" else None,
                result={"created_notes": 2} if item_status == "succeeded" else None,
                started_at=started_at if item_status != "queued" else None,
                finished_at=finished_at
                if item_status in {"succeeded", "failed", "cancelled"}
                else None,
            )
        )
    await db.commit()
    return int(run.id)


async def _load_shadow_job(db, history_run_id: int) -> Job:
    job = (
        await db.execute(
            select(Job).where(
                Job.source_type == SHADOW_SOURCE_TYPE,
                Job.source_id == str(history_run_id),
            )
        )
    ).scalar_one()
    return job


@pytest.mark.asyncio
async def test_shadow_feature_flag_defaults_off_and_writes_nothing(client):
    async with async_session() as db:
        environments = await _seed_identity(db)
        run_id = await _create_legacy_run(
            db, job_id="legacy-disabled", environments=environments
        )

    assert settings.xhs_homepage_sync_shadow_enabled is False
    assert await mirror_homepage_sync_shadow_safely(run_id) is None

    async with async_session() as db:
        assert (await db.execute(select(func.count(Job.id)))).scalar_one() == 0


@pytest.mark.asyncio
async def test_non_homepage_history_is_ignored(client):
    async with async_session() as db:
        environments = await _seed_identity(db)
        run_id = await _create_legacy_run(
            db,
            job_id="legacy-engagement",
            environments=environments,
            sync_kind="engagement",
        )
        assert await HomepageSyncShadowAdapter(db).mirror(run_id) is None
        await db.commit()
        assert (await db.execute(select(func.count(Job.id)))).scalar_one() == 0


@pytest.mark.asyncio
async def test_queued_run_creates_request_snapshot_and_unclaimable_items(client):
    async with async_session() as db:
        environments = await _seed_identity(db)
        run_id = await _create_legacy_run(
            db, job_id="legacy-queued", environments=environments
        )
        job = await HomepageSyncShadowAdapter(db).mirror(
            run_id,
            legacy_job={"status": "queued", "custom": object()},
        )
        assert job is not None
        await db.commit()

        assert job.job_type == SHADOW_JOB_TYPE
        assert job.worker_type == SHADOW_WORKER_TYPE
        assert job.status == JobStatus.QUEUED.value
        assert job.requested_by_user_id == 1
        assert job.progress_total == 2
        assert job.payload["shadow_mode"] is True
        assert job.payload["legacy_job_id"] == "legacy-queued"
        assert job.payload["request_config"]["runner_account_assignments"] == {
            "runner": [101, 102]
        }

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
        assert [item.item_key for item in items] == [
            "environment:101",
            "environment:102",
        ]
        assert [item.display_name for item in items] == ["账号1", "账号2"]
        assert all(item.status == JobStatus.QUEUED.value for item in items)

        claim = await JobService(db).claim_next_job(
            worker_id="server-worker", worker_type="server"
        )
        assert claim is None
        assert (await db.execute(select(func.count(JobAttempt.id)))).scalar_one() == 0


@pytest.mark.asyncio
async def test_running_run_maps_progress_without_creating_worker_attempt(client):
    started_at = datetime(2026, 8, 10, 9, 30, 0)
    async with async_session() as db:
        environments = await _seed_identity(db)
        run_id = await _create_legacy_run(
            db,
            job_id="legacy-running",
            environments=environments,
            status="running",
            message="正在同步第二个账号",
            started_at=started_at,
            item_statuses=["succeeded", "running"],
        )
        job = await HomepageSyncShadowAdapter(db).mirror(
            run_id, legacy_job={"status": "running"}
        )
        assert job is not None
        await db.commit()

        assert job.status == JobStatus.RUNNING.value
        assert job.progress_current == 1
        assert job.progress_total == 2
        assert job.current_step == "正在同步第二个账号"
        assert job.started_at == aware_or_cst_naive_to_utc_naive(started_at)
        assert (await db.execute(select(func.count(JobAttempt.id)))).scalar_one() == 0
        transitions = (
            (
                await db.execute(
                    select(JobEvent.to_status)
                    .where(
                        JobEvent.job_id == job.id,
                        JobEvent.event_type == "status_changed",
                    )
                    .order_by(JobEvent.id)
                )
            )
            .scalars()
            .all()
        )
        assert transitions == [JobStatus.LEASED.value, JobStatus.RUNNING.value]


@pytest.mark.asyncio
async def test_account_progress_updates_only_the_current_shadow_item(client):
    async with async_session() as db:
        environments = await _seed_identity(db, environment_count=3)
        run_id = await _create_legacy_run(
            db,
            job_id="legacy-targeted-progress",
            environments=environments,
            status="running",
            item_statuses=["running", "succeeded", "queued"],
        )
        adapter = HomepageSyncShadowAdapter(db)
        await adapter.mirror(run_id, legacy_job={"status": "running"})

        real_add_item = adapter.jobs.add_item
        adapter.jobs.add_item = AsyncMock(wraps=real_add_item)
        await adapter.mirror(
            run_id,
            legacy_job={
                "status": "running",
                "progress": {
                    "phase": "account_posts_completed",
                    "account_name": "账号2",
                },
            },
        )
        await db.commit()

        adapter.jobs.add_item.assert_awaited_once()
        assert adapter.jobs.add_item.await_args.kwargs["item_key"] == "environment:102"
        assert (await db.execute(select(func.count(JobItem.id)))).scalar_one() == 3


@pytest.mark.asyncio
async def test_success_mirrors_exact_items_metrics_and_parity(client):
    started_at = datetime(2026, 8, 10, 10, 0, 0)
    finished_at = datetime(2026, 8, 10, 10, 5, 0)
    async with async_session() as db:
        environments = await _seed_identity(db)
        run_id = await _create_legacy_run(
            db,
            job_id="legacy-success",
            environments=environments,
            status="succeeded",
            message="同步完成",
            started_at=started_at,
            finished_at=finished_at,
            item_statuses=["succeeded", "failed"],
        )
        job = await HomepageSyncShadowAdapter(db).mirror(
            run_id,
            legacy_job={
                "status": "succeeded",
                "result": {
                    "synced_accounts": 1,
                    "created_notes": 2,
                    "updated_notes": 3,
                },
            },
        )
        assert job is not None
        await db.commit()

        assert job.status == JobStatus.SUCCEEDED.value
        assert job.progress_current == 2
        assert job.finished_at == aware_or_cst_naive_to_utc_naive(finished_at)
        assert job.result_summary is not None
        assert job.result_summary["legacy_metrics"] == {
            "synced_accounts": 1,
            "created_notes": 2,
            "updated_notes": 3,
        }
        assert job.result_summary["parity"] == {
            "status": "matched",
            "checks": {
                "legacy_history_status": True,
                "durable_job_status": True,
                "synced_accounts": True,
            },
            "mismatches": [],
        }

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
        assert items[0].result == {"created_notes": 2}
        assert items[1].error_code == "legacy_sync_failed"
        assert items[1].internal_error == "账号失败"


@pytest.mark.asyncio
async def test_failure_and_cancellation_are_mirrored(client):
    async with async_session() as db:
        environments = await _seed_identity(db)
        failed_run_id = await _create_legacy_run(
            db,
            job_id="legacy-failed",
            environments=environments[:1],
            status="failed",
            message="同步失败",
            error="上游连接失败",
            finished_at=datetime(2026, 8, 10, 11, 0, 0),
            item_statuses=["failed"],
        )
        failed_job = await HomepageSyncShadowAdapter(db).mirror(
            failed_run_id,
            legacy_job={"status": "failed", "error": "上游连接失败"},
        )
        assert failed_job is not None
        assert failed_job.status == JobStatus.FAILED.value
        assert failed_job.error_code == "legacy_sync_failed"
        assert failed_job.internal_error == "上游连接失败"

        cancelled_run_id = await _create_legacy_run(
            db,
            job_id="legacy-cancelled",
            environments=environments[1:],
            status="running",
            message="正在中止",
            item_statuses=["running"],
        )
        cancelled_job = await HomepageSyncShadowAdapter(db).mirror(
            cancelled_run_id,
            legacy_job={"status": "cancelling", "cancel_requested": True},
        )
        assert cancelled_job is not None
        assert cancelled_job.status == JobStatus.RUNNING.value
        assert cancelled_job.cancel_requested is True

        run = await db.get(XHSAccountSyncRun, cancelled_run_id)
        assert run is not None
        run.status = "cancelled"
        run.message = "任务已中止"
        run.finished_at = datetime(2026, 8, 10, 11, 5, 0)
        item = (
            await db.execute(
                select(XHSAccountSyncRunItem).where(
                    XHSAccountSyncRunItem.run_id == cancelled_run_id
                )
            )
        ).scalar_one()
        item.status = "cancelled"
        item.finished_at = run.finished_at
        await db.flush()

        cancelled_job = await HomepageSyncShadowAdapter(db).mirror(
            cancelled_run_id,
            legacy_job={"status": "cancelled", "cancel_requested": True},
        )
        await db.commit()
        assert cancelled_job is not None
        assert cancelled_job.status == JobStatus.CANCELLED.value
        assert cancelled_job.result_summary["parity"]["status"] == "matched"


@pytest.mark.asyncio
async def test_queued_cancel_history_drift_is_visible_in_parity(client):
    async with async_session() as db:
        environments = await _seed_identity(db, environment_count=1)
        run_id = await _create_legacy_run(
            db,
            job_id="legacy-queued-cancel",
            environments=environments,
            status="queued",
        )
        job = await HomepageSyncShadowAdapter(db).mirror(
            run_id,
            legacy_job={"status": "cancelled", "cancel_requested": True},
        )
        await db.commit()

        assert job is not None
        assert job.status == JobStatus.CANCELLED.value
        assert job.cancel_requested is True
        assert job.result_summary["parity"]["status"] == "mismatch"
        assert job.result_summary["parity"]["mismatches"] == ["legacy_history_status"]


@pytest.mark.asyncio
async def test_repeated_mirror_is_idempotent(client):
    async with async_session() as db:
        environments = await _seed_identity(db)
        run_id = await _create_legacy_run(
            db,
            job_id="legacy-repeat",
            environments=environments,
            status="succeeded",
            item_statuses=["succeeded", "succeeded"],
        )
        adapter = HomepageSyncShadowAdapter(db)
        first = await adapter.mirror(
            run_id,
            legacy_job={"status": "succeeded", "result": {"synced_accounts": 2}},
        )
        second = await adapter.mirror(
            run_id,
            legacy_job={"status": "succeeded", "result": {"synced_accounts": 2}},
        )
        await db.commit()
        assert first is not None and second is not None
        assert first.id == second.id
        assert (await db.execute(select(func.count(Job.id)))).scalar_one() == 1
        assert (await db.execute(select(func.count(JobItem.id)))).scalar_one() == 2
        assert (await db.execute(select(func.count(JobEvent.id)))).scalar_one() == 4


@pytest.mark.asyncio
async def test_concurrent_safe_mirrors_do_not_duplicate_records(client, monkeypatch):
    async with async_session() as db:
        environments = await _seed_identity(db)
        run_id = await _create_legacy_run(
            db, job_id="legacy-concurrent", environments=environments
        )

    monkeypatch.setattr(settings, "xhs_homepage_sync_shadow_enabled", True)
    first_id, second_id = await asyncio.gather(
        mirror_homepage_sync_shadow_safely(run_id, legacy_job={"status": "queued"}),
        mirror_homepage_sync_shadow_safely(run_id, legacy_job={"status": "queued"}),
    )
    assert first_id is not None
    assert second_id == first_id

    async with async_session() as db:
        assert (await db.execute(select(func.count(Job.id)))).scalar_one() == 1
        assert (await db.execute(select(func.count(JobItem.id)))).scalar_one() == 2
        assert (await db.execute(select(func.count(JobEvent.id)))).scalar_one() == 1


@pytest.mark.asyncio
async def test_retry_run_links_to_parent_shadow_job(client):
    async with async_session() as db:
        environments = await _seed_identity(db)
        parent_run_id = await _create_legacy_run(
            db,
            job_id="legacy-parent",
            environments=environments,
            status="failed",
            item_statuses=["failed", "succeeded"],
        )
        parent_job = await HomepageSyncShadowAdapter(db).mirror(
            parent_run_id, legacy_job={"status": "failed"}
        )
        assert parent_job is not None
        child_run_id = await _create_legacy_run(
            db,
            job_id="legacy-child",
            environments=environments[:1],
            source="retry_failed",
            parent_run_id=parent_run_id,
        )
        child_job = await HomepageSyncShadowAdapter(db).mirror(
            child_run_id, legacy_job={"status": "queued"}
        )
        await db.commit()

        assert child_job is not None
        assert child_job.parent_job_id == parent_job.id
        assert child_job.payload["legacy_parent_run_id"] == parent_run_id
        assert child_job.payload["legacy_source"] == "retry_failed"


@pytest.mark.asyncio
async def test_shadow_transaction_can_roll_back_cleanly(client):
    async with async_session() as db:
        environments = await _seed_identity(db)
        run_id = await _create_legacy_run(
            db, job_id="legacy-rollback", environments=environments
        )
        assert await HomepageSyncShadowAdapter(db).mirror(run_id) is not None
        await db.rollback()

    async with async_session() as db:
        assert (await db.execute(select(func.count(Job.id)))).scalar_one() == 0
        assert (await db.execute(select(func.count(JobItem.id)))).scalar_one() == 0
        assert (await db.execute(select(func.count(JobEvent.id)))).scalar_one() == 0


@pytest.mark.asyncio
async def test_safe_wrapper_isolates_adapter_failure(client, monkeypatch, caplog):
    async with async_session() as db:
        environments = await _seed_identity(db)
        run_id = await _create_legacy_run(
            db, job_id="legacy-isolated", environments=environments
        )

    async def fail_mirror(self, history_run_id: int, *, legacy_job=None):
        raise RuntimeError("shadow storage unavailable")

    monkeypatch.setattr(settings, "xhs_homepage_sync_shadow_enabled", True)
    monkeypatch.setattr(HomepageSyncShadowAdapter, "mirror", fail_mirror)
    assert await mirror_homepage_sync_shadow_safely(run_id) is None
    assert "homepage sync shadow mirror failed" in caplog.text


@pytest.mark.asyncio
async def test_malformed_legacy_metrics_and_long_step_remain_observable(client):
    async with async_session() as db:
        environments = await _seed_identity(db, environment_count=1)
        run_id = await _create_legacy_run(
            db,
            job_id="legacy-malformed",
            environments=environments,
            status="succeeded",
            message="进" * 300,
            item_statuses=["succeeded"],
        )
        job = await HomepageSyncShadowAdapter(db).mirror(
            run_id,
            legacy_job={
                "status": "succeeded",
                "result": {"synced_accounts": "bad", "created_notes": "2"},
            },
        )
        await db.commit()

        assert job is not None
        assert len(job.current_step or "") == 160
        assert job.result_summary["legacy_metrics"] == {
            "synced_accounts": 0,
            "created_notes": 2,
        }
        assert job.result_summary["parity"]["status"] == "mismatch"
        assert job.result_summary["parity"]["mismatches"] == ["synced_accounts"]


@pytest.mark.asyncio
async def test_terminal_durable_status_drift_is_reported(client):
    async with async_session() as db:
        environments = await _seed_identity(db, environment_count=1)
        run_id = await _create_legacy_run(
            db,
            job_id="legacy-drift",
            environments=environments,
            status="succeeded",
            item_statuses=["succeeded"],
        )
        adapter = HomepageSyncShadowAdapter(db)
        job = await adapter.mirror(
            run_id,
            legacy_job={"status": "succeeded", "result": {"synced_accounts": 1}},
        )
        assert job is not None

        run = await db.get(XHSAccountSyncRun, run_id)
        assert run is not None
        run.status = "failed"
        run.error = "legacy status changed unexpectedly"
        await db.flush()
        job = await adapter.mirror(run_id, legacy_job={"status": "failed"})
        await db.commit()

        assert job is not None
        assert job.status == JobStatus.SUCCEEDED.value
        assert job.result_summary["parity"]["status"] == "mismatch"
        assert job.result_summary["parity"]["mismatches"] == ["durable_job_status"]


@pytest.mark.asyncio
async def test_legacy_executor_runs_once_and_shadow_matches_final_result(
    client, monkeypatch
):
    async with async_session() as db:
        environments = await _seed_identity(db, environment_count=1)
        job = xhs_api._new_job(
            "account_notes_sync",
            environment_id=None,
            scrape_environment_id=None,
            scrape_environment_ids=None,
            sync_account_limit=1,
            runner_account_assignments='{"runner": [101]}',
        )
        history = await xhs_api._create_sync_history_run(
            db,
            job=job,
            sync_kind="posts",
            source="manual",
            requested_by_user_id=1,
            request_config={"runner_account_assignments": '{"runner": [101]}'},
            targets=environments,
        )
        history_run_id = int(history.id)

    calls = 0

    async def fake_sync_account_notes(
        self: XHSService,
        *,
        progress_callback,
        **kwargs: Any,
    ) -> dict[str, int]:
        nonlocal calls
        calls += 1
        await progress_callback(
            {
                "phase": "opening_runner",
                "account_name": "账号1",
                "detail": "正在打开主页",
            }
        )
        await progress_callback(
            {
                "phase": "processing_account_posts",
                "account_name": "账号1",
                "detail": "正在处理第 1 条帖子",
            }
        )
        await progress_callback(
            {
                "phase": "fetching_account_posts",
                "account_name": "账号1",
                "detail": "正在拉取主页帖子",
            }
        )
        await progress_callback(
            {
                "phase": "account_posts_completed",
                "account_name": "账号1",
                "detail": "账号同步完成",
                "created_notes": 2,
                "updated_notes": 1,
                "metric_synced_notes": 3,
            }
        )
        return {
            "synced_accounts": 1,
            "created_notes": 2,
            "updated_notes": 1,
            "metric_synced_notes": 3,
            "total_notes": 3,
        }

    monkeypatch.setattr(settings, "xhs_homepage_sync_shadow_enabled", True)
    monkeypatch.setattr(XHSService, "sync_account_notes", fake_sync_account_notes)
    mirrored_phases: list[str] = []
    real_mirror = xhs_api.mirror_homepage_sync_shadow_safely

    async def recording_mirror(history_run_id, *, legacy_job=None):
        mirrored_phases.append(str((legacy_job or {}).get("progress", {}).get("phase")))
        return await real_mirror(history_run_id, legacy_job=legacy_job)

    monkeypatch.setattr(xhs_api, "mirror_homepage_sync_shadow_safely", recording_mirror)

    await xhs_api._run_account_note_sync_job(
        job["job_id"],
        user_id=1,
        environment_id=None,
        scrape_environment_id=None,
        scrape_environment_ids=None,
        sync_account_limit=1,
        runner_account_assignments='{"runner": [101]}',
        details=False,
        history_run_id=history_run_id,
    )

    assert calls == 1
    assert job["status"] == "succeeded"
    assert job["result"]["synced_accounts"] == 1
    assert mirrored_phases == [
        "running",
        "fetching_account_posts",
        "account_posts_completed",
        "succeeded",
    ]

    async with async_session() as db:
        run = await db.get(XHSAccountSyncRun, history_run_id)
        shadow = await _load_shadow_job(db, history_run_id)
        item = (
            await db.execute(select(JobItem).where(JobItem.job_id == shadow.id))
        ).scalar_one()

        assert run is not None and run.status == "succeeded"
        assert shadow.status == JobStatus.SUCCEEDED.value
        assert shadow.worker_type == SHADOW_WORKER_TYPE
        assert shadow.result_summary["parity"]["status"] == "matched"
        assert shadow.result_summary["legacy_metrics"]["total_notes"] == 3
        assert item.status == JobStatus.SUCCEEDED.value
        assert item.result == {
            "created_notes": 2,
            "updated_notes": 1,
            "metric_synced_notes": 3,
        }
        assert (await db.execute(select(func.count(JobAttempt.id)))).scalar_one() == 0


@pytest.mark.asyncio
async def test_legacy_executor_marks_parent_and_history_failed_when_account_failed(
    client, monkeypatch
):
    async with async_session() as db:
        environments = await _seed_identity(db, environment_count=1)
        job = xhs_api._new_job(
            "account_notes_sync",
            environment_id=None,
            scrape_environment_id=None,
            scrape_environment_ids=None,
            sync_account_limit=1,
            runner_account_assignments='{"runner": [101]}',
        )
        history = await xhs_api._create_sync_history_run(
            db,
            job=job,
            sync_kind="posts",
            source="manual",
            requested_by_user_id=1,
            request_config={"runner_account_assignments": '{"runner": [101]}'},
            targets=environments,
        )
        history_run_id = int(history.id)

    async def fake_sync_account_notes(
        self: XHSService,
        *,
        progress_callback,
        **kwargs: Any,
    ) -> dict[str, Any]:
        await progress_callback(
            {
                "phase": "account_posts_failed",
                "account_name": "账号1",
                "detail": "账号1 的账号帖子同步失败",
                "error": "获取账号主页超时",
            }
        )
        return {
            "synced_accounts": 0,
            "created_notes": 0,
            "updated_notes": 0,
            "total_notes": 0,
            "failed_accounts": [
                {
                    "environment_id": 101,
                    "account_name": "账号1",
                    "error": "获取账号主页超时",
                }
            ],
        }

    monkeypatch.setattr(XHSService, "sync_account_notes", fake_sync_account_notes)

    await xhs_api._run_account_note_sync_job(
        job["job_id"],
        user_id=1,
        environment_id=None,
        scrape_environment_id=None,
        scrape_environment_ids=None,
        sync_account_limit=1,
        runner_account_assignments='{"runner": [101]}',
        details=False,
        history_run_id=history_run_id,
    )

    assert job["status"] == "failed"
    assert job["error"] == "1 个账号失败"
    assert job["result"]["failed_accounts"][0]["environment_id"] == 101

    async with async_session() as db:
        run = await db.get(XHSAccountSyncRun, history_run_id)
        item = (
            await db.execute(
                select(XHSAccountSyncRunItem).where(
                    XHSAccountSyncRunItem.run_id == history_run_id
                )
            )
        ).scalar_one()
        assert run is not None and run.status == "failed"
        assert run.error == "1 个账号失败"
        assert item.status == "failed"
        assert item.error == "获取账号主页超时"
