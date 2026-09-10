from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select

import app.api.v1.xhs as xhs_api
import app.services.xhs_schedule_service as schedule_module
from app.config import settings
from app.db.session import async_session
from app.models.job import Job, JobAttempt, JobEvent, JobItem, JobStatus
from app.models.user import User
from app.models.xhs_report_refresh_run import XHSReportRefreshRun
from app.services.job_service import JobService
from app.services.xhs_report_refresh_shadow import (
    REPORT_REFRESH_JOB_TYPE,
    REPORT_REFRESH_SOURCE_TYPE,
    REPORT_REFRESH_WORKER_TYPE,
    ReportRefreshRunService,
    ReportRefreshShadowAdapter,
    create_report_refresh_run_safely,
)
from app.services.xhs_schedule_service import (
    AD_DATA_REFRESH_TASK,
    XHSScheduleService,
)
from app.services.xhs_service import XHSService
from tests.conftest import make_auth_headers


@pytest_asyncio.fixture(autouse=True)
async def reset_report_refresh_runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "xhs_report_refresh_shadow_enabled", False)
    xhs_api.XHS_BACKGROUND_JOBS.clear()
    xhs_api.XHS_BACKGROUND_JOB_TASKS.clear()
    schedule_module._RUNNING_TASK_KEYS.clear()
    yield
    tasks = list(xhs_api.XHS_BACKGROUND_JOB_TASKS.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    xhs_api.XHS_BACKGROUND_JOB_TASKS.clear()
    xhs_api.XHS_BACKGROUND_JOBS.clear()
    schedule_module._RUNNING_TASK_KEYS.clear()


async def _seed_admin(db) -> None:
    db.add(
        User(
            id=1,
            username="report-shadow-admin",
            display_name="报表管理员",
            email="report-shadow@example.com",
            hashed_password="x",
            role="admin",
        )
    )
    await db.flush()


async def _create_run(
    db,
    *,
    job_id: str = "refresh-run-1",
    report_types: list[str] | None = None,
) -> XHSReportRefreshRun:
    run, _ = await ReportRefreshRunService(db).create_run(
        job_id=job_id,
        source="manual",
        requested_by_user_id=1,
        request_config={
            "report_types": report_types or ["simple", "standard"],
            "start_date": "2026-08-01",
            "end_date": "2026-08-09",
            "days": 9,
        },
    )
    return run


async def _load_shadow_job(db, run_id: int) -> Job:
    return (
        await db.execute(
            select(Job).where(
                Job.source_type == REPORT_REFRESH_SOURCE_TYPE,
                Job.source_id == str(run_id),
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_report_refresh_shadow_defaults_off_and_writes_nothing(client):
    assert settings.xhs_report_refresh_shadow_enabled is False
    run_id = await create_report_refresh_run_safely(
        job_id="disabled-refresh",
        source="manual",
        request_config={"report_types": ["simple"]},
        requested_by_user_id=1,
    )
    assert run_id is None
    async with async_session() as db:
        assert (
            await db.execute(select(func.count(XHSReportRefreshRun.id)))
        ).scalar_one() == 0
        assert (await db.execute(select(func.count(Job.id)))).scalar_one() == 0


@pytest.mark.asyncio
async def test_run_snapshot_is_bounded_deduplicated_and_secret_free(client):
    async with async_session() as db:
        await _seed_admin(db)
        run, created = await ReportRefreshRunService(db).create_run(
            job_id="normalized-refresh",
            source="manual",
            requested_by_user_id=1,
            request_config={
                "report_types": ["simple", "simple", "invalid", "standard"],
                "account_id": "10001",
                "account_name": "广告账户",
                "start_date": "2026-08-01-extra",
                "end_date": "2026-08-09-extra",
                "days": 999,
                "api_key": "must-not-be-stored",
            },
        )
        duplicate, duplicate_created = await ReportRefreshRunService(db).create_run(
            job_id="normalized-refresh",
            source="schedule",
            request_config={"report_types": ["creative"]},
        )
        await db.commit()

    assert created is True
    assert duplicate_created is False
    assert duplicate.id == run.id
    assert run.request_config == {
        "report_types": ["simple", "standard"],
        "account_id": "10001",
        "account_name": "广告账户",
        "start_date": "2026-08-01",
        "end_date": "2026-08-09",
        "days": 366,
    }
    assert "must-not-be-stored" not in str(run.request_config)


@pytest.mark.asyncio
async def test_queued_shadow_has_unclaimable_report_items(client):
    async with async_session() as db:
        await _seed_admin(db)
        run = await _create_run(db)
        job = await ReportRefreshShadowAdapter(db).mirror(int(run.id))
        assert job is not None
        await db.commit()

        assert job.job_type == REPORT_REFRESH_JOB_TYPE
        assert job.worker_type == REPORT_REFRESH_WORKER_TYPE
        assert job.status == JobStatus.QUEUED.value
        assert job.progress_total == 2
        assert job.payload["request_config"]["report_types"] == [
            "simple",
            "standard",
        ]
        items = list(
            (
                await db.execute(
                    select(JobItem)
                    .where(JobItem.job_id == job.id)
                    .order_by(JobItem.item_key.asc())
                )
            ).scalars()
        )
        assert [item.item_key for item in items] == [
            "report:simple",
            "report:standard",
        ]
        assert all(item.status == JobStatus.QUEUED.value for item in items)
        assert (
            await JobService(db).claim_next_job(
                worker_id="server-worker",
                worker_type="server",
            )
        ) is None
        assert (await db.execute(select(func.count(JobAttempt.id)))).scalar_one() == 0


@pytest.mark.asyncio
async def test_success_lifecycle_mirrors_progress_results_and_events(client):
    started_at = datetime(2026, 8, 10, 8, 0, 0)
    finished_at = datetime(2026, 8, 10, 8, 5, 0)
    async with async_session() as db:
        await _seed_admin(db)
        run = await _create_run(db)
        service = ReportRefreshRunService(db)
        await ReportRefreshShadowAdapter(db).mirror(int(run.id))
        await service.mark_running(run, now=started_at)
        await ReportRefreshShadowAdapter(db).mirror(int(run.id))
        await service.record_report_result(
            run,
            report_type="simple",
            status="succeeded",
            result={"updated_accounts": 4, "updated_rows": 80, "errors": []},
        )
        await ReportRefreshShadowAdapter(db).mirror(int(run.id))
        await service.record_report_result(
            run,
            report_type="standard",
            status="succeeded",
            result={
                "updated_accounts": 3,
                "updated_rows": 40,
                "errors": ["one account unavailable"],
                "failed_accounts": [
                    {
                        "account_id": "10001",
                        "account_name": "异常账户",
                        "stage": "report",
                        "error": "standard_note timeout",
                    }
                ],
                "preserved_empty_accounts": [
                    {
                        "account_id": "10002",
                        "account_name": "空响应账户",
                        "preserved_rows": "12",
                    }
                ],
            },
        )
        await service.finish(
            run,
            status="succeeded",
            message="报表缓存刷新完成",
            now=finished_at,
        )
        job = await ReportRefreshShadowAdapter(db).mirror(int(run.id))
        assert job is not None
        await db.commit()

        assert job.status == JobStatus.SUCCEEDED.value
        assert job.progress_current == 2
        assert job.progress_total == 2
        assert job.started_at == started_at
        assert job.finished_at == finished_at
        assert job.result_summary["updated_accounts"] == 7
        assert job.result_summary["updated_rows"] == 120
        assert job.result_summary["error_count"] == 1
        standard_result = next(
            item
            for item in run.result_summary["reports"]
            if item["report_type"] == "standard"
        )
        assert standard_result["failed_accounts"] == [
            {
                "account_id": "10001",
                "account_name": "异常账户",
                "stage": "report",
                "error": "standard_note timeout",
            }
        ]
        assert standard_result["preserved_empty_accounts"][0]["preserved_rows"] == 12
        items = list(
            (
                await db.execute(
                    select(JobItem)
                    .where(JobItem.job_id == job.id)
                    .order_by(JobItem.item_key.asc())
                )
            ).scalars()
        )
        assert [item.status for item in items] == ["succeeded", "succeeded"]
        assert items[0].result == {
            "updated_accounts": 4,
            "updated_rows": 80,
            "error_count": 0,
        }
        events = list(
            (
                await db.execute(
                    select(JobEvent)
                    .where(JobEvent.job_id == job.id)
                    .order_by(JobEvent.id.asc())
                )
            ).scalars()
        )
        assert [event.event_type for event in events] == [
            "job_created",
            "status_changed",
            "status_changed",
            "status_changed",
        ]


@pytest.mark.asyncio
async def test_failed_run_preserves_success_and_marks_unstarted_items(client):
    async with async_session() as db:
        await _seed_admin(db)
        run = await _create_run(
            db,
            report_types=["simple", "standard", "creative"],
        )
        service = ReportRefreshRunService(db)
        await service.mark_running(run)
        await service.record_report_result(
            run,
            report_type="simple",
            status="succeeded",
            result={"updated_accounts": 2, "updated_rows": 20, "errors": []},
        )
        await service.record_report_result(
            run,
            report_type="standard",
            status="failed",
            error="upstream failed",
        )
        await service.finish(
            run,
            status="failed",
            message="standard 报表刷新失败",
            error="upstream failed",
        )
        job = await ReportRefreshShadowAdapter(db).mirror(int(run.id))
        assert job is not None
        await db.commit()

        assert job.status == JobStatus.FAILED.value
        reports = {
            item["report_type"]: item for item in run.result_summary["reports"]
        }
        assert reports["simple"]["status"] == "succeeded"
        assert reports["standard"]["status"] == "failed"
        assert reports["creative"]["status"] == "cancelled"
        items = list(
            (
                await db.execute(
                    select(JobItem).where(JobItem.job_id == job.id)
                )
            ).scalars()
        )
        assert {item.item_key: item.status for item in items} == {
            "report:simple": "succeeded",
            "report:standard": "failed",
            "report:creative": "cancelled",
        }


@pytest.mark.asyncio
async def test_repeated_mirror_is_idempotent(client):
    async with async_session() as db:
        await _seed_admin(db)
        run = await _create_run(db)
        first = await ReportRefreshShadowAdapter(db).mirror(int(run.id))
        second = await ReportRefreshShadowAdapter(db).mirror(int(run.id))
        await db.commit()
        assert first is not None and second is not None
        assert first.id == second.id
        assert (await db.execute(select(func.count(Job.id)))).scalar_one() == 1
        assert (await db.execute(select(func.count(JobItem.id)))).scalar_one() == 2
        assert (await db.execute(select(func.count(JobEvent.id)))).scalar_one() == 1


@pytest.mark.asyncio
async def test_shadow_failure_isolated_from_legacy_submission(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "xhs_report_refresh_shadow_enabled", True)
    async with async_session() as db:
        await _seed_admin(db)
        await db.commit()
    monkeypatch.setattr(
        ReportRefreshShadowAdapter,
        "mirror",
        AsyncMock(side_effect=RuntimeError("shadow unavailable")),
    )
    run_id = await create_report_refresh_run_safely(
        job_id="isolated-failure",
        source="manual",
        requested_by_user_id=1,
        request_config={"report_types": ["simple"]},
    )
    assert run_id is None


@pytest.mark.asyncio
async def test_manual_refresh_executes_once_and_records_shadow(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "xhs_report_refresh_shadow_enabled", True)
    async with async_session() as db:
        await _seed_admin(db)
        await db.commit()

    calls: list[str] = []
    scheduled_tasks: list[asyncio.Task] = []
    original_create_task = asyncio.create_task

    async def fake_refresh(self, report_type: str, **kwargs):
        calls.append(report_type)
        return {
            "report_type": report_type,
            "updated_accounts": 5,
            "updated_rows": 50,
            "errors": [],
        }

    def capture_task(coro):
        task = original_create_task(coro)
        scheduled_tasks.append(task)
        return task

    monkeypatch.setattr(XHSService, "refresh_jg_report_cache", fake_refresh)
    monkeypatch.setattr(xhs_api.asyncio, "create_task", capture_task)
    response = await client.post(
        "/api/v1/xhs/report/refresh?report_type=simple&days=7",
        headers=make_auth_headers(1),
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "queued"
    assert payload["history_run_id"] > 0
    await asyncio.gather(*scheduled_tasks)

    assert calls == ["simple"]
    async with async_session() as db:
        run = await db.get(XHSReportRefreshRun, payload["history_run_id"])
        assert run is not None
        assert run.status == "succeeded"
        job = await _load_shadow_job(db, int(run.id))
        assert job.status == JobStatus.SUCCEEDED.value
        assert job.result_summary["updated_rows"] == 50


@pytest.mark.asyncio
async def test_scheduled_refresh_executes_each_type_once_and_records_one_batch(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "xhs_report_refresh_shadow_enabled", True)
    calls: list[str] = []

    async def fake_refresh(self, report_type: str, **kwargs):
        calls.append(report_type)
        return {
            "report_type": report_type,
            "updated_accounts": 2,
            "updated_rows": 10 if report_type == "simple" else 20,
            "errors": [],
        }

    monkeypatch.setattr(XHSService, "refresh_jg_report_cache", fake_refresh)
    async with async_session() as db:
        await XHSScheduleService(db).update_setting(
            AD_DATA_REFRESH_TASK,
            enabled=True,
            run_time="06:30",
            config={
                "date_range_mode": "absolute",
                "start_date": "2026-08-01",
                "end_date": "2026-08-02",
                "report_types": ["simple", "standard"],
            },
        )

    await schedule_module._run_task(AD_DATA_REFRESH_TASK, "manual", async_session)
    assert calls == ["simple", "standard"]
    async with async_session() as db:
        runs = list((await db.execute(select(XHSReportRefreshRun))).scalars())
        assert len(runs) == 1
        run = runs[0]
        assert run.status == "succeeded"
        assert run.source == "manual"
        assert run.schedule_run_id is not None
        assert run.request_config["report_types"] == ["simple", "standard"]
        assert run.result_summary["updated_rows"] == 30
        job = await _load_shadow_job(db, int(run.id))
        assert job.status == JobStatus.SUCCEEDED.value
        assert job.progress_current == 2
