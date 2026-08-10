from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, func, select

from app.db.session import async_session, engine
from app.models.dify_task import DifyTask
from app.models.dify_workflow import DifyWorkflowConfig
from app.models.job import Job, JobEvent
from app.models.user import User
from app.services.dify_task_parity_service import DifyTaskParityService
from app.services.dify_task_shadow import (
    DIFY_JOB_TYPE,
    DIFY_SOURCE_TYPE,
    DIFY_WORKER_TYPE,
    DifyTaskShadowAdapter,
)
from app.services.job_service import JobService
from tests.conftest import make_auth_headers


async def _seed_users_and_workflow(db) -> None:
    db.add_all(
        [
            User(
                id=1,
                username="dify-parity-admin",
                email="dify-parity-admin@example.com",
                hashed_password="x",
                role="admin",
            ),
            User(
                id=2,
                username="dify-parity-viewer",
                email="dify-parity-viewer@example.com",
                hashed_password="x",
                role="viewer",
            ),
            DifyWorkflowConfig(
                id=10,
                api_key="provider-secret",
                app_name="内容生产",
                app_type="workflow",
                inputs_schema={},
                is_enabled=True,
                created_by=1,
            ),
        ]
    )
    await db.flush()


async def _create_terminal_task(
    db,
    *,
    status: str = "succeeded",
    finished_at: datetime | None = None,
    mirror: bool = True,
) -> tuple[DifyTask, Job | None]:
    finished_at = finished_at or datetime(2026, 8, 10, 10, 0, 0)
    task = DifyTask(
        workflow_id=10,
        user_id=1,
        task_id="dify-upstream-1" if status != "cancelled" else None,
        status=status,
        inputs={"topic": "private input"},
        outputs={"content": "private output"} if status == "succeeded" else {},
        error="upstream failed" if status == "failed" else None,
        progress="",
        elapsed_ms=1500.0 if status != "cancelled" else None,
        created_at=finished_at - timedelta(seconds=2),
        finished_at=finished_at,
    )
    db.add(task)
    await db.flush()
    job = await DifyTaskShadowAdapter(db).mirror(int(task.id)) if mirror else None
    await db.flush()
    return task, job


@pytest.mark.asyncio
async def test_empty_dify_parity_report_requires_samples(client):
    async with async_session() as db:
        report = await DifyTaskParityService(db).build_report(min_samples=3)
    assert report["summary"]["evaluated_count"] == 0
    assert report["summary"]["match_rate"] == 0.0
    assert report["migration_gate"]["decision"] == "insufficient_samples"
    assert report["migration_gate"]["execution_cutover_allowed"] is False


@pytest.mark.asyncio
async def test_exact_dify_shadow_match_requires_manual_validation(client):
    async with async_session() as db:
        await _seed_users_and_workflow(db)
        task, job = await _create_terminal_task(db)
        assert job is not None
        await db.commit()
        report = await DifyTaskParityService(db).build_report(min_samples=1)

    assert report["summary"]["matched_count"] == 1
    assert report["summary"]["mismatch_count"] == 0
    assert report["migration_gate"]["automated_checks_passed"] is True
    assert report["migration_gate"]["decision"] == "manual_validation_required"
    sample = report["samples"][0]
    assert sample["legacy_task_id"] == task.id
    assert sample["job_id"] == job.public_id
    assert "private input" not in str(job.payload)
    assert "private output" not in str(job.result_summary)


@pytest.mark.asyncio
async def test_missing_and_tampered_dify_shadows_are_reported(client):
    async with async_session() as db:
        await _seed_users_and_workflow(db)
        missing, _ = await _create_terminal_task(db, mirror=False)
        _, job = await _create_terminal_task(
            db,
            finished_at=datetime(2026, 8, 10, 10, 1, 0),
        )
        assert job is not None
        job.status = "failed"
        job.payload = {"shadow_mode": False}
        job.result_summary = {"legacy_status": "failed"}
        await db.commit()
        report = await DifyTaskParityService(db).build_report(min_samples=1)

    assert report["summary"]["mismatch_count"] == 2
    by_task = {sample["legacy_task_id"]: sample for sample in report["samples"]}
    assert by_task[int(missing.id)]["mismatch_codes"] == ["missing_shadow_job"]
    tampered_codes = set(
        next(
            sample["mismatch_codes"]
            for sample in report["samples"]
            if sample["legacy_task_id"] != int(missing.id)
        )
    )
    assert {"job_status", "payload", "result_summary"} <= tampered_codes
    assert report["migration_gate"]["decision"] == "blocked_by_mismatch"


@pytest.mark.asyncio
async def test_duplicate_orphan_and_deleted_sources_have_distinct_diagnostics(client):
    async with async_session() as db:
        await _seed_users_and_workflow(db)
        task, job = await _create_terminal_task(db)
        assert job is not None
        await JobService(db).create_job(
            job_type=DIFY_JOB_TYPE,
            worker_type=DIFY_WORKER_TYPE,
            idempotency_key="duplicate-dify-shadow",
            source_type=DIFY_SOURCE_TYPE,
            source_id=str(task.id),
        )
        await JobService(db).create_job(
            job_type=DIFY_JOB_TYPE,
            worker_type=DIFY_WORKER_TYPE,
            idempotency_key="orphan-dify-shadow",
            source_type=DIFY_SOURCE_TYPE,
            source_id="999999",
        )

        deleted_task, _ = await _create_terminal_task(
            db,
            finished_at=datetime(2026, 8, 10, 10, 2, 0),
        )
        await DifyTaskShadowAdapter(db).detach_deleted(int(deleted_task.id))
        await db.delete(deleted_task)
        await db.commit()
        report = await DifyTaskParityService(db).build_report(min_samples=1)

    reasons = report["summary"]["mismatch_reasons"]
    assert reasons["duplicate_shadow_job"] == 1
    assert reasons["orphan_shadow_job"] == 1
    assert report["summary"]["orphan_shadow_count"] == 1
    assert report["summary"]["deleted_source_snapshot_count"] == 1
    assert report["diagnostics"]["orphan_shadow_jobs"]["items"][0][
        "source_id"
    ] == "999999"


@pytest.mark.asyncio
async def test_cancelled_then_succeeded_legacy_drift_is_not_hidden(client):
    async with async_session() as db:
        await _seed_users_and_workflow(db)
        task, job = await _create_terminal_task(db, status="cancelled")
        assert job is not None
        assert job.status == "cancelled"
        task.status = "succeeded"
        task.task_id = "late-success"
        task.outputs = {"content": "charged result"}
        task.elapsed_ms = 2000.0
        await DifyTaskShadowAdapter(db).mirror(int(task.id))
        await db.commit()
        report = await DifyTaskParityService(db).build_report(min_samples=1)

    sample = report["samples"][0]
    assert sample["legacy_status"] == "succeeded"
    assert sample["durable_status"] == "cancelled"
    assert "job_status" in sample["mismatch_codes"]
    assert report["migration_gate"]["decision"] == "blocked_by_mismatch"


@pytest.mark.asyncio
async def test_dify_parity_filters_limits_and_validates(client):
    async with async_session() as db:
        await _seed_users_and_workflow(db)
        for index in range(3):
            await _create_terminal_task(
                db,
                finished_at=datetime(2026, 8, 8 + index, 10, 0, 0),
            )
        await db.commit()
        limited = await DifyTaskParityService(db).build_report(
            sample_limit=2,
            min_samples=1,
        )
        filtered = await DifyTaskParityService(db).build_report(
            finished_from=datetime(2026, 8, 9, tzinfo=timezone.utc),
            finished_to=datetime(2026, 8, 10, 23, 59, tzinfo=timezone.utc),
            min_samples=1,
        )
        with pytest.raises(ValueError, match="finished_from"):
            await DifyTaskParityService(db).build_report(
                finished_from=datetime(2026, 8, 10),
                finished_to=datetime(2026, 8, 9),
            )
        with pytest.raises(ValueError, match="min_samples"):
            await DifyTaskParityService(db).build_report(
                sample_limit=2,
                min_samples=3,
            )

    assert limited["summary"]["total_terminal_count"] == 3
    assert limited["summary"]["evaluated_count"] == 2
    assert limited["summary"]["is_truncated"] is True
    assert [sample["finished_at"] for sample in filtered["samples"]] == [
        "2026-08-10T02:00:00Z",
        "2026-08-09T02:00:00Z",
    ]


@pytest.mark.asyncio
async def test_dify_parity_uses_five_queries_and_is_read_only(client):
    async with async_session() as db:
        await _seed_users_and_workflow(db)
        for index in range(20):
            await _create_terminal_task(
                db,
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
            report = await DifyTaskParityService(db).build_report(
                sample_limit=100,
                min_samples=20,
            )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", record_selects)
        event_count_after = (
            await db.execute(select(func.count(JobEvent.id)))
        ).scalar_one()

    assert report["summary"]["matched_count"] == 20
    assert len(selects) == 5
    assert event_count_after == event_count_before


@pytest.mark.asyncio
async def test_dify_parity_endpoint_requires_admin(client):
    async with async_session() as db:
        await _seed_users_and_workflow(db)
        await _create_terminal_task(db)
        await db.commit()

    path = "/api/v1/admin/reliability/dify-task-shadow"
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=make_auth_headers(2))).status_code == 403
    response = await client.get(
        path,
        params={"min_samples": 1},
        headers=make_auth_headers(1),
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["summary"]["matched_count"] == 1
    assert payload["migration_gate"]["execution_cutover_allowed"] is False
