from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, func, select

from app.db.session import async_session, engine
from app.models.job import Job, JobEvent, JobItem
from app.models.user import User
from app.models.xhs_report_refresh_run import XHSReportRefreshRun
from app.services.job_service import JobService
from app.services.xhs_report_refresh_parity_service import (
    ReportRefreshParityService,
)
from app.services.xhs_report_refresh_shadow import (
    REPORT_REFRESH_JOB_TYPE,
    REPORT_REFRESH_SOURCE_TYPE,
    REPORT_REFRESH_WORKER_TYPE,
    ReportRefreshRunService,
    ReportRefreshShadowAdapter,
)
from tests.conftest import make_auth_headers


async def _seed_users(db) -> None:
    db.add_all(
        [
            User(
                id=1,
                username="report-parity-admin",
                email="report-parity-admin@example.com",
                hashed_password="x",
                role="admin",
            ),
            User(
                id=2,
                username="report-parity-viewer",
                email="report-parity-viewer@example.com",
                hashed_password="x",
                role="viewer",
            ),
        ]
    )
    await db.flush()


async def _create_terminal_run(
    db,
    *,
    job_id: str,
    status: str = "succeeded",
    report_types: list[str] | None = None,
    finished_at: datetime | None = None,
    mirror: bool = True,
) -> tuple[XHSReportRefreshRun, Job | None]:
    report_types = report_types or ["simple", "standard"]
    finished_at = finished_at or datetime(2026, 8, 10, 10, 0, 0)
    service = ReportRefreshRunService(db)
    run, _ = await service.create_run(
        job_id=job_id,
        source="manual",
        requested_by_user_id=1,
        request_config={
            "report_types": report_types,
            "start_date": "2026-08-01",
            "end_date": "2026-08-09",
            "days": 9,
        },
    )
    await service.mark_running(run, now=finished_at - timedelta(minutes=5))
    for index, report_type in enumerate(report_types):
        report_status = (
            "failed" if status == "failed" and index == len(report_types) - 1 else "succeeded"
        )
        await service.record_report_result(
            run,
            report_type=report_type,
            status=report_status,
            result={
                "updated_accounts": index + 1,
                "updated_rows": (index + 1) * 10,
                "errors": [],
            },
            error="upstream failed" if report_status == "failed" else None,
        )
    await service.finish(
        run,
        status=status,
        message="报表刷新完成" if status == "succeeded" else "报表刷新失败",
        error="upstream failed" if status == "failed" else None,
        now=finished_at,
    )
    job = await ReportRefreshShadowAdapter(db).mirror(int(run.id)) if mirror else None
    await db.flush()
    return run, job


@pytest.mark.asyncio
async def test_empty_report_requires_samples(client):
    async with async_session() as db:
        report = await ReportRefreshParityService(db).build_report(min_samples=3)
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
    assert report["migration_gate"]["execution_cutover_allowed"] is False


@pytest.mark.asyncio
async def test_exact_refresh_shadow_match_passes_automated_checks(client):
    async with async_session() as db:
        await _seed_users(db)
        run, job = await _create_terminal_run(db, job_id="parity-match")
        assert job is not None
        await db.commit()
        report = await ReportRefreshParityService(db).build_report(min_samples=1)

    assert report["summary"]["matched_count"] == 1
    assert report["summary"]["mismatch_count"] == 0
    assert report["migration_gate"]["decision"] == "manual_validation_required"
    assert report["migration_gate"]["automated_checks_passed"] is True
    assert report["migration_gate"]["execution_cutover_allowed"] is False
    sample = report["samples"][0]
    assert sample["legacy_run_id"] == run.id
    assert sample["job_id"] == job.public_id
    assert sample["report_types"] == ["simple", "standard"]
    assert sample["updated_accounts"] == 3
    assert sample["updated_rows"] == 30


@pytest.mark.asyncio
async def test_missing_shadow_is_reported_instead_of_ignored(client):
    async with async_session() as db:
        await _seed_users(db)
        run, _ = await _create_terminal_run(
            db,
            job_id="parity-missing",
            mirror=False,
        )
        await db.commit()
        report = await ReportRefreshParityService(db).build_report(min_samples=1)

    assert report["summary"]["mismatch_count"] == 1
    assert report["summary"]["mismatch_reasons"] == {"missing_shadow_job": 1}
    assert report["samples"][0]["legacy_run_id"] == run.id
    assert report["samples"][0]["job_id"] is None


@pytest.mark.asyncio
async def test_tampered_parameters_status_and_item_totals_are_detected(client):
    async with async_session() as db:
        await _seed_users(db)
        _, job = await _create_terminal_run(db, job_id="parity-tampered")
        assert job is not None
        job.status = "failed"
        payload = dict(job.payload or {})
        payload["request_config"] = {"report_types": ["creative"]}
        job.payload = payload
        first_item = (
            await db.execute(
                select(JobItem)
                .where(JobItem.job_id == job.id)
                .order_by(JobItem.id.asc())
            )
        ).scalars().first()
        assert first_item is not None
        first_item.result = {
            "updated_accounts": 999,
            "updated_rows": 999,
            "error_count": 0,
        }
        await db.commit()
        report = await ReportRefreshParityService(db).build_report(min_samples=1)

    codes = set(report["samples"][0]["mismatch_codes"])
    assert "job_status" in codes
    assert "payload_request_config" in codes
    assert "item_updated_accounts" in codes
    assert "item_updated_rows" in codes
    assert report["migration_gate"]["decision"] == "blocked_by_mismatch"


@pytest.mark.asyncio
async def test_duplicate_and_orphan_shadow_jobs_block_cutover(client):
    async with async_session() as db:
        await _seed_users(db)
        run, _ = await _create_terminal_run(db, job_id="parity-duplicate")
        await JobService(db).create_job(
            job_type=REPORT_REFRESH_JOB_TYPE,
            worker_type=REPORT_REFRESH_WORKER_TYPE,
            idempotency_key="duplicate-shadow",
            source_type=REPORT_REFRESH_SOURCE_TYPE,
            source_id=str(run.id),
        )
        await JobService(db).create_job(
            job_type=REPORT_REFRESH_JOB_TYPE,
            worker_type=REPORT_REFRESH_WORKER_TYPE,
            idempotency_key="orphan-shadow",
            source_type=REPORT_REFRESH_SOURCE_TYPE,
            source_id="999999",
        )
        await db.commit()
        report = await ReportRefreshParityService(db).build_report(min_samples=1)

    assert report["summary"]["mismatch_reasons"]["duplicate_shadow_job"] == 1
    assert report["summary"]["mismatch_reasons"]["orphan_shadow_job"] == 1
    assert report["summary"]["orphan_shadow_count"] == 1
    assert report["diagnostics"]["orphan_shadow_jobs"]["items"][0][
        "source_id"
    ] == "999999"
    assert report["migration_gate"]["automated_checks_passed"] is False


@pytest.mark.asyncio
async def test_report_filters_and_limits_terminal_runs(client):
    async with async_session() as db:
        await _seed_users(db)
        for index in range(3):
            await _create_terminal_run(
                db,
                job_id=f"parity-filter-{index}",
                finished_at=datetime(2026, 8, 8 + index, 10, 0, 0),
            )
        await db.commit()
        limited = await ReportRefreshParityService(db).build_report(
            sample_limit=2,
            min_samples=1,
        )
        filtered = await ReportRefreshParityService(db).build_report(
            finished_from=datetime(2026, 8, 9, tzinfo=timezone.utc),
            finished_to=datetime(2026, 8, 10, 23, 59, tzinfo=timezone.utc),
            sample_limit=10,
            min_samples=1,
        )

    assert limited["summary"]["total_terminal_count"] == 3
    assert limited["summary"]["evaluated_count"] == 2
    assert limited["summary"]["is_truncated"] is True
    assert [row["legacy_job_id"] for row in filtered["samples"]] == [
        "parity-filter-2",
        "parity-filter-1",
    ]
    assert filtered["scope"]["finished_from"] == "2026-08-09T00:00:00Z"


@pytest.mark.asyncio
async def test_report_validates_range_and_sample_gate(client):
    async with async_session() as db:
        service = ReportRefreshParityService(db)
        with pytest.raises(ValueError, match="finished_from"):
            await service.build_report(
                finished_from=datetime(2026, 8, 10),
                finished_to=datetime(2026, 8, 9),
            )
        with pytest.raises(ValueError, match="min_samples"):
            await service.build_report(sample_limit=2, min_samples=3)


@pytest.mark.asyncio
async def test_report_uses_fixed_batch_queries_and_is_read_only(client):
    async with async_session() as db:
        await _seed_users(db)
        for index in range(20):
            await _create_terminal_run(
                db,
                job_id=f"parity-batch-{index}",
                finished_at=datetime(2026, 8, 10, 10, 0, 0)
                + timedelta(minutes=index),
            )
        await db.commit()
        event_count_before = (
            await db.execute(select(func.count(JobEvent.id)))
        ).scalar_one()
        selects: list[str] = []

        def record_selects(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", record_selects)
        try:
            report = await ReportRefreshParityService(db).build_report(
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
        await _seed_users(db)
        await _create_terminal_run(db, job_id="parity-api")
        await db.commit()

    path = "/api/v1/admin/reliability/xhs-report-refresh-shadow"
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=make_auth_headers(2))).status_code == 403
    response = await client.get(
        path,
        params={"sample_limit": 10, "min_samples": 1},
        headers=make_auth_headers(1),
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["summary"]["matched_count"] == 1
    assert payload["migration_gate"]["execution_cutover_allowed"] is False

    invalid = await client.get(
        path,
        params={"sample_limit": 1, "min_samples": 2},
        headers=make_auth_headers(1),
    )
    assert invalid.status_code == 400
