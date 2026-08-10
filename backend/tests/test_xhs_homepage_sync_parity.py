from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, event, func, select

from app.db.session import async_session, engine
from app.models.job import Job, JobEvent, JobItem, JobStatus
from app.models.user import User
from app.models.xhs_account_sync_run import (
    XHSAccountSyncRun,
    XHSAccountSyncRunItem,
)
from app.models.xhs_environment import XHSEnvironment
from app.services.job_service import JobService
from app.services.xhs_homepage_sync_parity_service import HomepageSyncParityService
from app.services.xhs_homepage_sync_shadow import (
    SHADOW_JOB_TYPE,
    SHADOW_SOURCE_TYPE,
    SHADOW_WORKER_TYPE,
    HomepageSyncShadowAdapter,
)
from tests.conftest import make_auth_headers


async def _seed_users_and_environments(
    db,
    *,
    environment_count: int = 2,
) -> list[XHSEnvironment]:
    db.add_all(
        [
            User(
                id=1,
                username="parity-admin",
                email="parity-admin@example.com",
                hashed_password="x",
                role="admin",
            ),
            User(
                id=2,
                username="parity-viewer",
                email="parity-viewer@example.com",
                hashed_password="x",
                role="viewer",
            ),
        ]
    )
    environments = [
        XHSEnvironment(
            id=200 + index,
            shop_id=f"parity-shop-{index}",
            account_name=f"验收账号{index}",
            status="active",
        )
        for index in range(1, environment_count + 1)
    ]
    db.add_all(environments)
    await db.flush()
    return environments


async def _create_terminal_shadow(
    db,
    *,
    job_id: str,
    environments: list[XHSEnvironment],
    status: str = "succeeded",
    item_statuses: list[str] | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    source: str = "manual",
    parent_run_id: int | None = None,
) -> tuple[XHSAccountSyncRun, Job]:
    started_at = started_at or datetime(2026, 8, 10, 9, 0, 0)
    finished_at = finished_at or datetime(2026, 8, 10, 9, 5, 0)
    statuses = item_statuses or ["succeeded"] * len(environments)
    assert len(statuses) == len(environments)
    run = XHSAccountSyncRun(
        job_id=job_id,
        sync_kind="posts",
        source=source,
        status=status,
        requested_by_user_id=1,
        parent_run_id=parent_run_id,
        request_config={
            "runner_account_assignments": {"runner": [env.id for env in environments]}
        },
        message="主页同步完成" if status == "succeeded" else "主页同步失败",
        error="批次失败" if status == "failed" else None,
        started_at=started_at,
        finished_at=finished_at,
    )
    db.add(run)
    await db.flush()
    for environment, item_status in zip(environments, statuses):
        db.add(
            XHSAccountSyncRunItem(
                run_id=run.id,
                environment_id=environment.id,
                account_name=environment.account_name,
                status=item_status,
                message="账号同步完成"
                if item_status == "succeeded"
                else "账号同步失败",
                error="账号抓取失败" if item_status == "failed" else None,
                result={"created_notes": 2} if item_status == "succeeded" else None,
                started_at=started_at,
                finished_at=finished_at,
            )
        )
    await db.flush()
    succeeded_count = sum(item_status == "succeeded" for item_status in statuses)
    job = await HomepageSyncShadowAdapter(db).mirror(
        int(run.id),
        legacy_job={
            "status": status,
            "result": {
                "synced_accounts": succeeded_count,
                "created_notes": succeeded_count * 2,
            },
        },
    )
    assert job is not None
    await db.commit()
    return run, job


@pytest.mark.asyncio
async def test_empty_report_requires_samples(client):
    async with async_session() as db:
        report = await HomepageSyncParityService(db).build_report(min_samples=3)

    assert report["summary"] == {
        "total_terminal_count": 0,
        "evaluated_count": 0,
        "matched_count": 0,
        "mismatch_count": 0,
        "orphan_shadow_count": 0,
        "match_rate": 0.0,
        "mismatch_reasons": {},
        "is_truncated": False,
    }
    assert report["migration_gate"]["decision"] == "insufficient_samples"
    assert report["migration_gate"]["automated_checks_passed"] is False
    assert report["migration_gate"]["execution_cutover_allowed"] is False
    assert len(report["migration_gate"]["manual_checks_required"]) == 3
    assert report["diagnostics"]["orphan_shadow_jobs"] == {
        "total_count": 0,
        "items": [],
        "is_truncated": False,
    }


@pytest.mark.asyncio
async def test_independent_report_accepts_exact_legacy_shadow_match(client):
    async with async_session() as db:
        environments = await _seed_users_and_environments(db)
        run, job = await _create_terminal_shadow(
            db,
            job_id="parity-match",
            environments=environments,
            item_statuses=["succeeded", "failed"],
        )
        report = await HomepageSyncParityService(db).build_report(min_samples=1)

    assert report["summary"]["total_terminal_count"] == 1
    assert report["summary"]["matched_count"] == 1
    assert report["summary"]["mismatch_count"] == 0
    assert report["summary"]["match_rate"] == 1.0
    assert report["migration_gate"]["decision"] == "manual_validation_required"
    assert report["migration_gate"]["automated_checks_passed"] is True
    assert report["migration_gate"]["execution_cutover_allowed"] is False

    sample = report["samples"][0]
    assert sample["job_id"] == job.public_id
    assert sample["legacy_run_id"] == run.id
    assert sample["legacy_job_id"] == "parity-match"
    assert sample["account_count"] == 2
    assert sample["shadow_item_count"] == 2
    assert sample["matched"] is True
    assert sample["mismatches"] == []
    assert sample["started_at"] == "2026-08-10T01:00:00Z"
    assert sample["finished_at"] == "2026-08-10T01:05:00Z"


@pytest.mark.asyncio
async def test_cancelled_run_and_item_match_exactly(client):
    async with async_session() as db:
        environments = await _seed_users_and_environments(db, environment_count=1)
        _, job = await _create_terminal_shadow(
            db,
            job_id="parity-cancelled",
            environments=environments,
            status="cancelled",
            item_statuses=["cancelled"],
        )
        report = await HomepageSyncParityService(db).build_report(min_samples=1)

    assert job.cancel_requested is True
    assert report["summary"]["matched_count"] == 1
    assert report["samples"][0]["job_status"] == "cancelled"
    assert report["samples"][0]["matched"] is True


@pytest.mark.asyncio
async def test_legacy_item_without_environment_uses_stable_fallback_key(client):
    async with async_session() as db:
        await _seed_users_and_environments(db, environment_count=1)
        run = XHSAccountSyncRun(
            job_id="parity-no-environment",
            sync_kind="posts",
            source="manual",
            status="succeeded",
            requested_by_user_id=1,
            request_config={},
            message="同步完成",
            started_at=datetime(2026, 8, 10, 9, 0, 0),
            finished_at=datetime(2026, 8, 10, 9, 1, 0),
        )
        db.add(run)
        await db.flush()
        legacy_item = XHSAccountSyncRunItem(
            run_id=run.id,
            environment_id=None,
            account_name="历史账号",
            status="succeeded",
            message="完成",
            result={"created_notes": 1},
            started_at=run.started_at,
            finished_at=run.finished_at,
        )
        db.add(legacy_item)
        await db.flush()
        job = await HomepageSyncShadowAdapter(db).mirror(
            int(run.id),
            legacy_job={
                "status": "succeeded",
                "result": {"synced_accounts": 1, "created_notes": 1},
            },
        )
        assert job is not None
        await db.commit()

        report = await HomepageSyncParityService(db).build_report(min_samples=1)
        shadow_item = (
            await db.execute(select(JobItem).where(JobItem.job_id == job.id))
        ).scalar_one()

    assert shadow_item.item_key == f"legacy-item:{legacy_item.id}"
    assert report["summary"]["matched_count"] == 1


@pytest.mark.asyncio
async def test_report_detects_independent_job_item_and_summary_tampering(client):
    async with async_session() as db:
        environments = await _seed_users_and_environments(db)
        _, job = await _create_terminal_shadow(
            db,
            job_id="parity-tampered",
            environments=environments,
        )
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
        await db.delete(items[0])
        items[1].result = {"created_notes": 999}
        job.status = JobStatus.FAILED.value
        job.payload = {**job.payload, "request_config": {"tampered": True}}
        job.result_summary = {**job.result_summary, "total_accounts": 999}
        db.add(
            JobItem(
                job_id=job.id,
                item_key="environment:9999",
                status=JobStatus.SUCCEEDED.value,
                payload={"environment_id": 9999},
                attempt_count=1,
            )
        )
        await db.commit()

        report = await HomepageSyncParityService(db).build_report(min_samples=1)

    assert report["migration_gate"]["decision"] == "blocked_by_mismatch"
    assert report["summary"]["matched_count"] == 0
    assert report["summary"]["mismatch_count"] == 1
    reasons = report["summary"]["mismatch_reasons"]
    assert reasons["job_status"] == 1
    assert reasons["request_config"] == 1
    assert reasons["missing_shadow_item"] == 1
    assert reasons["extra_shadow_item"] == 1
    assert reasons["item_result"] == 1
    assert reasons["summary_total_accounts"] == 1

    sample = report["samples"][0]
    assert sample["matched"] is False
    assert sample["mismatched_item_count"] == 3
    assert {row.get("item_key") for row in sample["mismatches"]} >= {
        "environment:201",
        "environment:202",
        "environment:9999",
    }


@pytest.mark.asyncio
async def test_mismatch_details_are_bounded(client):
    async with async_session() as db:
        environments = await _seed_users_and_environments(db, environment_count=1)
        _, job = await _create_terminal_shadow(
            db,
            job_id="parity-bounded-details",
            environments=environments,
        )
        db.add_all(
            [
                JobItem(
                    job_id=job.id,
                    item_key=f"extra:{index:03d}",
                    status=JobStatus.SUCCEEDED.value,
                    payload={},
                    attempt_count=1,
                )
                for index in range(60)
            ]
        )
        await db.commit()
        report = await HomepageSyncParityService(db).build_report(min_samples=1)

    sample = report["samples"][0]
    assert sample["matched"] is False
    assert sample["mismatches_truncated"] is True
    assert len(sample["mismatches"]) == 50
    assert "extra_shadow_item" in sample["mismatch_codes"]


@pytest.mark.asyncio
async def test_report_detects_missing_and_invalid_legacy_sources(client):
    async with async_session() as db:
        environments = await _seed_users_and_environments(db, environment_count=1)
        run, _ = await _create_terminal_shadow(
            db,
            job_id="parity-missing-source",
            environments=environments,
        )
        await db.execute(
            delete(XHSAccountSyncRunItem).where(XHSAccountSyncRunItem.run_id == run.id)
        )
        await db.execute(
            delete(XHSAccountSyncRun).where(XHSAccountSyncRun.id == run.id)
        )

        invalid, _ = await JobService(db).create_job(
            job_type=SHADOW_JOB_TYPE,
            worker_type=SHADOW_WORKER_TYPE,
            source_type=SHADOW_SOURCE_TYPE,
            source_id="not-an-integer",
            idempotency_key="invalid-shadow-source",
        )
        service = JobService(db)
        await service.transition(invalid, JobStatus.LEASED)
        await service.transition(invalid, JobStatus.RUNNING)
        await service.transition(invalid, JobStatus.SUCCEEDED)
        await db.commit()

        report = await HomepageSyncParityService(db).build_report(
            min_samples=1, sample_limit=10
        )

    assert report["summary"]["evaluated_count"] == 0
    assert report["summary"]["mismatch_count"] == 0
    assert report["summary"]["orphan_shadow_count"] == 2
    assert report["summary"]["mismatch_reasons"] == {"orphan_shadow_job": 2}
    assert report["samples"] == []
    diagnostics = report["diagnostics"]["orphan_shadow_jobs"]
    assert diagnostics["total_count"] == 2
    assert {item["code"] for item in diagnostics["items"]} == {
        "invalid_source_id",
        "missing_legacy_run",
    }
    assert report["migration_gate"]["decision"] == "blocked_by_mismatch"
    assert report["migration_gate"]["automated_checks_passed"] is False


@pytest.mark.asyncio
async def test_orphan_summary_remains_complete_when_diagnostics_are_bounded(client):
    async with async_session() as db:
        await _seed_users_and_environments(db, environment_count=1)
        service = JobService(db)
        for index in range(25):
            orphan, _ = await service.create_job(
                job_type=SHADOW_JOB_TYPE,
                worker_type=SHADOW_WORKER_TYPE,
                source_type=SHADOW_SOURCE_TYPE,
                source_id=f"invalid-{index}",
                idempotency_key=f"bounded-orphan-{index}",
            )
            await service.transition(orphan, JobStatus.LEASED)
            await service.transition(orphan, JobStatus.RUNNING)
            await service.transition(orphan, JobStatus.SUCCEEDED)
        await db.commit()

        report = await HomepageSyncParityService(db).build_report(min_samples=1)

    assert report["summary"]["orphan_shadow_count"] == 25
    assert report["summary"]["mismatch_reasons"] == {"orphan_shadow_job": 25}
    diagnostics = report["diagnostics"]["orphan_shadow_jobs"]
    assert diagnostics["total_count"] == 25
    assert len(diagnostics["items"]) == 20
    assert diagnostics["is_truncated"] is True


@pytest.mark.asyncio
async def test_report_detects_terminal_legacy_run_without_shadow_job(client):
    async with async_session() as db:
        environments = await _seed_users_and_environments(db, environment_count=2)
        run = XHSAccountSyncRun(
            job_id="parity-shadow-write-missed",
            sync_kind="posts",
            source="manual",
            status="succeeded",
            requested_by_user_id=1,
            request_config={},
            message="旧任务已完成，但影子写入失败",
            started_at=datetime(2026, 8, 10, 9, 0, 0),
            finished_at=datetime(2026, 8, 10, 9, 5, 0),
        )
        db.add(run)
        await db.flush()
        db.add_all(
            [
                XHSAccountSyncRunItem(
                    run_id=run.id,
                    environment_id=environment.id,
                    account_name=environment.account_name,
                    status="succeeded",
                    result={"created_notes": 1},
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                )
                for environment in environments
            ]
        )
        await db.commit()

        report = await HomepageSyncParityService(db).build_report(min_samples=1)

    assert report["summary"]["evaluated_count"] == 1
    assert report["summary"]["mismatch_count"] == 1
    assert report["summary"]["mismatch_reasons"] == {"missing_shadow_job": 1}
    assert report["migration_gate"]["decision"] == "blocked_by_mismatch"
    sample = report["samples"][0]
    assert sample["legacy_run_id"] == run.id
    assert sample["job_id"] is None
    assert sample["matched"] is False
    assert sample["shadow_item_count"] == 0
    assert sample["mismatched_item_count"] == 2


@pytest.mark.asyncio
async def test_report_detects_duplicate_shadow_jobs_for_one_legacy_run(client):
    async with async_session() as db:
        environments = await _seed_users_and_environments(db, environment_count=1)
        run, _ = await _create_terminal_shadow(
            db,
            job_id="parity-duplicate-shadow",
            environments=environments,
        )
        duplicate, _ = await JobService(db).create_job(
            job_type=SHADOW_JOB_TYPE,
            worker_type=SHADOW_WORKER_TYPE,
            source_type=SHADOW_SOURCE_TYPE,
            source_id=str(run.id),
            idempotency_key="duplicate-shadow-job",
        )
        service = JobService(db)
        await service.transition(duplicate, JobStatus.LEASED)
        await service.transition(duplicate, JobStatus.RUNNING)
        await service.transition(duplicate, JobStatus.SUCCEEDED)
        await db.commit()

        report = await HomepageSyncParityService(db).build_report(min_samples=1)

    assert report["summary"]["mismatch_reasons"]["duplicate_shadow_jobs"] == 1
    assert report["migration_gate"]["decision"] == "blocked_by_mismatch"
    sample = report["samples"][0]
    assert sample["matched"] is False
    duplicate_mismatch = next(
        row for row in sample["mismatches"] if row["code"] == "duplicate_shadow_jobs"
    )
    assert duplicate_mismatch["expected"] == 1
    assert duplicate_mismatch["actual"] == 2


@pytest.mark.asyncio
async def test_retry_parent_link_is_verified(client):
    async with async_session() as db:
        environments = await _seed_users_and_environments(db, environment_count=1)
        parent_run, parent_job = await _create_terminal_shadow(
            db,
            job_id="parity-parent",
            environments=environments,
            status="failed",
            item_statuses=["failed"],
        )
        child_run, child_job = await _create_terminal_shadow(
            db,
            job_id="parity-child",
            environments=environments,
            source="retry_failed",
            parent_run_id=int(parent_run.id),
        )
        assert child_job.parent_job_id == parent_job.id

        report = await HomepageSyncParityService(db).build_report(min_samples=1)
        child_sample = next(
            sample
            for sample in report["samples"]
            if sample["legacy_run_id"] == child_run.id
        )
        assert child_sample["matched"] is True

        child_job.parent_job_id = None
        await db.commit()
        report = await HomepageSyncParityService(db).build_report(min_samples=1)

    child_sample = next(
        sample
        for sample in report["samples"]
        if sample["legacy_run_id"] == child_run.id
    )
    assert child_sample["matched"] is False
    assert "missing_parent_job" in child_sample["mismatch_codes"]


@pytest.mark.asyncio
async def test_report_filters_limits_and_marks_truncated_samples(client):
    async with async_session() as db:
        environments = await _seed_users_and_environments(db, environment_count=1)
        finishes = [
            datetime(2026, 8, 8, 12, 0, 0),
            datetime(2026, 8, 9, 12, 0, 0),
            datetime(2026, 8, 10, 12, 0, 0),
        ]
        for index, finished_at in enumerate(finishes, start=1):
            await _create_terminal_shadow(
                db,
                job_id=f"parity-filter-{index}",
                environments=environments,
                started_at=finished_at - timedelta(minutes=5),
                finished_at=finished_at,
            )

        limited = await HomepageSyncParityService(db).build_report(
            sample_limit=2, min_samples=1
        )
        filtered = await HomepageSyncParityService(db).build_report(
            finished_from=datetime(2026, 8, 9, 4, 0, 0, tzinfo=timezone.utc),
            finished_to=datetime(2026, 8, 10, 4, 0, 0, tzinfo=timezone.utc),
            sample_limit=10,
            min_samples=1,
        )

    assert limited["summary"]["total_terminal_count"] == 3
    assert limited["summary"]["evaluated_count"] == 2
    assert limited["summary"]["is_truncated"] is True
    assert [sample["legacy_job_id"] for sample in limited["samples"]] == [
        "parity-filter-3",
        "parity-filter-2",
    ]
    assert filtered["summary"]["evaluated_count"] == 2
    assert [sample["legacy_job_id"] for sample in filtered["samples"]] == [
        "parity-filter-3",
        "parity-filter-2",
    ]
    assert filtered["scope"]["finished_from"] == "2026-08-09T04:00:00Z"


@pytest.mark.asyncio
async def test_report_uses_fixed_batch_queries_and_is_read_only(client):
    async with async_session() as db:
        environments = await _seed_users_and_environments(db, environment_count=3)
        for index in range(20):
            await _create_terminal_shadow(
                db,
                job_id=f"parity-batch-{index}",
                environments=environments,
                finished_at=datetime(2026, 8, 10, 10, 0, 0) + timedelta(minutes=index),
            )
        event_count_before = (
            await db.execute(select(func.count(JobEvent.id)))
        ).scalar_one()

        selects: list[str] = []

        def record_selects(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", record_selects)
        try:
            report = await HomepageSyncParityService(db).build_report(
                sample_limit=100,
                min_samples=20,
            )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", record_selects)

        event_count_after = (
            await db.execute(select(func.count(JobEvent.id)))
        ).scalar_one()

    assert report["summary"]["evaluated_count"] == 20
    assert report["summary"]["matched_count"] == 20
    assert report["migration_gate"]["automated_checks_passed"] is True
    assert len(selects) == 5
    assert event_count_after == event_count_before


@pytest.mark.asyncio
async def test_parity_endpoint_requires_admin_and_serializes_report(client):
    async with async_session() as db:
        environments = await _seed_users_and_environments(db, environment_count=1)
        await _create_terminal_shadow(
            db,
            job_id="parity-api",
            environments=environments,
        )

    unauthenticated = await client.get("/api/v1/admin/reliability/xhs-homepage-shadow")
    viewer = await client.get(
        "/api/v1/admin/reliability/xhs-homepage-shadow",
        headers=make_auth_headers(2),
    )
    admin = await client.get(
        "/api/v1/admin/reliability/xhs-homepage-shadow",
        params={"sample_limit": 10, "min_samples": 1},
        headers=make_auth_headers(1),
    )

    assert unauthenticated.status_code in {401, 403}
    assert viewer.status_code == 403
    assert admin.status_code == 200
    payload = admin.json()
    assert payload["code"] == 0
    assert payload["data"]["summary"]["matched_count"] == 1
    assert payload["data"]["samples"][0]["finished_at"].endswith("Z")


@pytest.mark.asyncio
async def test_parity_endpoint_validates_limits(client):
    async with async_session() as db:
        await _seed_users_and_environments(db, environment_count=1)
        await db.commit()

    response = await client.get(
        "/api/v1/admin/reliability/xhs-homepage-shadow",
        params={"sample_limit": 501, "min_samples": 0},
        headers=make_auth_headers(1),
    )
    assert response.status_code == 422

    reversed_range = await client.get(
        "/api/v1/admin/reliability/xhs-homepage-shadow",
        params={
            "finished_from": "2026-08-10T00:00:00Z",
            "finished_to": "2026-08-09T00:00:00Z",
        },
        headers=make_auth_headers(1),
    )
    assert reversed_range.status_code == 400
    assert reversed_range.json()["detail"] == (
        "finished_from must not be later than finished_to"
    )

    too_small_sample = await client.get(
        "/api/v1/admin/reliability/xhs-homepage-shadow",
        params={"sample_limit": 10, "min_samples": 20},
        headers=make_auth_headers(1),
    )
    assert too_small_sample.status_code == 400
    assert too_small_sample.json()["detail"] == (
        "sample_limit must be greater than or equal to min_samples"
    )


@pytest.mark.asyncio
async def test_service_rejects_invalid_limits_and_accepts_naive_filter(client):
    async with async_session() as db:
        service = HomepageSyncParityService(db)
        with pytest.raises(ValueError, match="sample_limit must be between"):
            await service.build_report(sample_limit=0)
        with pytest.raises(ValueError, match="min_samples must be between"):
            await service.build_report(min_samples=0)
        with pytest.raises(ValueError, match="greater than or equal"):
            await service.build_report(sample_limit=10, min_samples=20)

        report = await service.build_report(
            finished_from=datetime(2026, 8, 1, 0, 0, 0),
            sample_limit=1,
            min_samples=1,
        )

    assert report["scope"]["finished_from"] == "2026-08-01T00:00:00Z"
