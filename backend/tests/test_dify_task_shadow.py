from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select

import app.api.v1.workflows as workflows_api
from app.config import settings
from app.db.session import async_session
from app.models.dify_task import DifyTask
from app.models.dify_workflow import DifyWorkflowConfig
from app.models.job import Job, JobAttempt, JobEvent, JobStatus
from app.models.user import User
from app.services.dify.dify_client import DifyClient
from app.services.dify_task_shadow import (
    DIFY_DELETED_SOURCE_TYPE,
    DIFY_JOB_TYPE,
    DIFY_SOURCE_TYPE,
    DIFY_WORKER_TYPE,
    DifyTaskShadowAdapter,
    detach_deleted_dify_task_safely,
    mirror_dify_task_safely,
)
from app.services.job_service import JobService
from tests.conftest import make_auth_headers


@pytest_asyncio.fixture(autouse=True)
async def reset_dify_shadow_runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "dify_task_shadow_enabled", False)
    workflows_api._workflow_locks.clear()
    workflows_api._workflow_running.clear()
    yield
    workflows_api._workflow_locks.clear()
    workflows_api._workflow_running.clear()


async def _seed_user_and_workflow(
    db,
    *,
    user_id: int = 1,
    role: str = "admin",
) -> DifyWorkflowConfig:
    db.add(
        User(
            id=user_id,
            username=f"dify-user-{user_id}",
            email=f"dify-user-{user_id}@example.com",
            hashed_password="x",
            role=role,
        )
    )
    workflow = DifyWorkflowConfig(
        id=10,
        api_key="provider-secret",
        base_url="https://dify.example.test/v1",
        app_name="内容生产",
        app_type="workflow",
        inputs_schema={},
        is_enabled=True,
        created_by=user_id,
    )
    db.add(workflow)
    await db.flush()
    return workflow


async def _create_task(
    db,
    *,
    status: str = "queued",
    inputs: dict | None = None,
) -> DifyTask:
    task = DifyTask(
        workflow_id=10,
        user_id=1,
        status=status,
        inputs=inputs or {"topic": "secret topic"},
        outputs={},
        created_at=datetime(2026, 8, 10, 10, 0, 0),
    )
    db.add(task)
    await db.flush()
    return task


async def _load_shadow_job(db, task_id: int) -> Job:
    return (
        await db.execute(
            select(Job).where(
                Job.source_type.in_((DIFY_SOURCE_TYPE, DIFY_DELETED_SOURCE_TYPE)),
                Job.source_id == str(task_id),
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_dify_shadow_defaults_off_and_writes_nothing(client):
    assert settings.dify_task_shadow_enabled is False
    await mirror_dify_task_safely(123)
    async with async_session() as db:
        assert (await db.execute(select(func.count(Job.id)))).scalar_one() == 0


@pytest.mark.asyncio
async def test_dify_shadow_snapshot_keeps_shape_not_input_values(client):
    async with async_session() as db:
        await _seed_user_and_workflow(db)
        task = await _create_task(
            db,
            inputs={
                "topic": "private campaign",
                "api_key": "must-not-be-stored",
                "references": ["private-image"],
            },
        )
        job = await DifyTaskShadowAdapter(db).mirror(int(task.id))
        assert job is not None
        await db.commit()

    payload_text = str(job.payload)
    assert job.job_type == DIFY_JOB_TYPE
    assert job.worker_type == DIFY_WORKER_TYPE
    assert job.payload["inputs"] == {
        "field_count": 3,
        "field_names": ["api_key", "references", "topic"],
        "field_types": {
            "api_key": "string",
            "references": "array",
            "topic": "string",
        },
        "is_truncated": False,
    }
    assert "must-not-be-stored" not in payload_text
    assert "private campaign" not in payload_text
    assert "private-image" not in payload_text


@pytest.mark.asyncio
async def test_dify_success_lifecycle_is_unclaimable_and_idempotent(client):
    async with async_session() as db:
        await _seed_user_and_workflow(db)
        task = await _create_task(db)
        adapter = DifyTaskShadowAdapter(db)
        first = await adapter.mirror(int(task.id))
        assert first is not None
        task.status = "running"
        task.progress = "正在执行..."
        await adapter.mirror(int(task.id))
        task.status = "succeeded"
        task.progress = ""
        task.task_id = "dify-run-100"
        task.outputs = {"article": "private output", "images": ["secret"]}
        task.elapsed_ms = 1250.5
        task.finished_at = datetime(2026, 8, 10, 10, 0, 2)
        final = await adapter.mirror(int(task.id))
        repeated = await adapter.mirror(int(task.id))
        assert final is not None and repeated is not None
        await db.commit()

        assert final.id == repeated.id == first.id
        assert final.status == JobStatus.SUCCEEDED.value
        assert final.progress_current == 1
        assert final.result_summary["upstream_task_id"] == "dify-run-100"
        assert final.result_summary["outputs"]["field_names"] == [
            "article",
            "images",
        ]
        assert "private output" not in str(final.result_summary)
        assert (await db.execute(select(func.count(Job.id)))).scalar_one() == 1
        assert (await db.execute(select(func.count(JobAttempt.id)))).scalar_one() == 0
        assert (
            await JobService(db).claim_next_job(
                worker_id="server-worker",
                worker_type="server",
            )
        ) is None
        events = list(
            (
                await db.execute(
                    select(JobEvent)
                    .where(JobEvent.job_id == final.id)
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
async def test_dify_failure_and_cancellation_map_to_terminal_states(client):
    async with async_session() as db:
        await _seed_user_and_workflow(db)
        failed = await _create_task(db, status="failed")
        failed.error = "token=must-redact-on-read"
        failed.finished_at = datetime(2026, 8, 10, 10, 1, 0)
        failed_job = await DifyTaskShadowAdapter(db).mirror(int(failed.id))
        assert failed_job is not None

        cancelled = await _create_task(db, status="cancelled")
        cancelled.finished_at = datetime(2026, 8, 10, 10, 2, 0)
        cancelled_job = await DifyTaskShadowAdapter(db).mirror(int(cancelled.id))
        assert cancelled_job is not None
        await db.commit()

    assert failed_job.status == JobStatus.FAILED.value
    assert failed_job.error_code == "dify_workflow_failed"
    assert cancelled_job.status == JobStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_deleted_legacy_task_keeps_detached_audit_snapshot(client, monkeypatch):
    monkeypatch.setattr(settings, "dify_task_shadow_enabled", True)
    async with async_session() as db:
        await _seed_user_and_workflow(db)
        task = await _create_task(db, status="succeeded")
        task.finished_at = datetime(2026, 8, 10, 10, 3, 0)
        await db.commit()
        task_id = int(task.id)

    await mirror_dify_task_safely(task_id)
    async with async_session() as db:
        task = await db.get(DifyTask, task_id)
        assert task is not None
        await db.delete(task)
        await db.commit()
    await detach_deleted_dify_task_safely(task_id)

    async with async_session() as db:
        job = await _load_shadow_job(db, task_id)
        assert job.source_type == DIFY_DELETED_SOURCE_TYPE
        assert job.payload["legacy_source_deleted"] is True
        events = list(
            (
                await db.execute(
                    select(JobEvent).where(JobEvent.job_id == job.id)
                )
            ).scalars()
        )
        assert events[-1].event_type == "legacy_source_deleted"


@pytest.mark.asyncio
async def test_dify_shadow_failure_does_not_escape_safe_wrapper(client, monkeypatch):
    monkeypatch.setattr(settings, "dify_task_shadow_enabled", True)
    monkeypatch.setattr(
        DifyTaskShadowAdapter,
        "mirror",
        AsyncMock(side_effect=RuntimeError("shadow unavailable")),
    )
    await mirror_dify_task_safely(1)


def _capture_background_tasks(monkeypatch: pytest.MonkeyPatch):
    tasks: list[asyncio.Task] = []
    original_create_task = asyncio.create_task

    def capture(coro):
        task = original_create_task(coro)
        tasks.append(task)
        return task

    monkeypatch.setattr(asyncio, "create_task", capture)
    return tasks


@pytest.mark.asyncio
async def test_user_dify_endpoint_executes_upstream_once_and_mirrors(client, monkeypatch):
    monkeypatch.setattr(settings, "dify_task_shadow_enabled", True)
    async with async_session() as db:
        await _seed_user_and_workflow(db, role="viewer")
        await db.commit()

    calls: list[dict] = []

    async def fake_run(self, *, inputs, streaming):
        calls.append(inputs)
        return {
            "workflow_run_id": "user-run-1",
            "data": {"outputs": {"content": "generated"}},
        }

    monkeypatch.setattr(DifyClient, "run_workflow", fake_run)
    tasks = _capture_background_tasks(monkeypatch)
    response = await client.post(
        "/api/v1/workflows/10/tasks",
        json={"inputs": {"topic": "cars"}},
        headers=make_auth_headers(1),
    )
    assert response.status_code == 200
    await asyncio.gather(*tasks)
    assert calls == [{"topic": "cars"}]

    async with async_session() as db:
        task = (await db.execute(select(DifyTask))).scalar_one()
        assert task.status == "succeeded"
        job = await _load_shadow_job(db, int(task.id))
        assert job.status == JobStatus.SUCCEEDED.value
        assert job.result_summary["upstream_task_id"] == "user-run-1"


@pytest.mark.asyncio
async def test_admin_dify_endpoint_executes_upstream_once_and_mirrors(client, monkeypatch):
    monkeypatch.setattr(settings, "dify_task_shadow_enabled", True)
    async with async_session() as db:
        await _seed_user_and_workflow(db, role="admin")
        await db.commit()

    calls: list[dict] = []

    async def fake_run(self, *, inputs, streaming):
        calls.append(inputs)
        return {
            "workflow_run_id": "admin-run-1",
            "data": {"outputs": {"content": "generated"}},
        }

    monkeypatch.setattr(DifyClient, "run_workflow", fake_run)
    tasks = _capture_background_tasks(monkeypatch)
    response = await client.post(
        "/api/v1/admin/workflows/10/tasks",
        json={"inputs": {"topic": "cars"}},
        headers=make_auth_headers(1),
    )
    assert response.status_code == 200
    await asyncio.gather(*tasks)
    assert calls == [{"topic": "cars"}]

    async with async_session() as db:
        task = (await db.execute(select(DifyTask))).scalar_one()
        assert task.status == "succeeded"
        job = await _load_shadow_job(db, int(task.id))
        assert job.status == JobStatus.SUCCEEDED.value
        assert job.result_summary["upstream_task_id"] == "admin-run-1"


@pytest.mark.asyncio
async def test_user_stop_then_delete_keeps_cancelled_audit_snapshot(client, monkeypatch):
    monkeypatch.setattr(settings, "dify_task_shadow_enabled", True)
    async with async_session() as db:
        await _seed_user_and_workflow(db, role="viewer")
        task = await _create_task(db, status="queued")
        await db.commit()
        task_id = int(task.id)

    stop_response = await client.post(
        f"/api/v1/workflows/tasks/{task_id}/stop",
        headers=make_auth_headers(1),
    )
    assert stop_response.status_code == 200
    async with async_session() as db:
        task = await db.get(DifyTask, task_id)
        assert task is not None and task.status == "cancelled"
        job = await _load_shadow_job(db, task_id)
        assert job.status == JobStatus.CANCELLED.value

    delete_response = await client.delete(
        f"/api/v1/workflows/tasks/{task_id}",
        headers=make_auth_headers(1),
    )
    assert delete_response.status_code == 200
    async with async_session() as db:
        assert await db.get(DifyTask, task_id) is None
        job = await _load_shadow_job(db, task_id)
        assert job.status == JobStatus.CANCELLED.value
        assert job.source_type == DIFY_DELETED_SOURCE_TYPE


@pytest.mark.asyncio
async def test_admin_fail_endpoint_mirrors_terminal_failure(client, monkeypatch):
    monkeypatch.setattr(settings, "dify_task_shadow_enabled", True)
    async with async_session() as db:
        await _seed_user_and_workflow(db, role="admin")
        task = await _create_task(db, status="pending")
        await db.commit()
        task_id = int(task.id)

    response = await client.post(
        f"/api/v1/admin/workflows/tasks/{task_id}/fail",
        json={"reason": "人工确认终止"},
        headers=make_auth_headers(1),
    )
    assert response.status_code == 200
    async with async_session() as db:
        task = await db.get(DifyTask, task_id)
        assert task is not None and task.status == "failed"
        job = await _load_shadow_job(db, task_id)
        assert job.status == JobStatus.FAILED.value
        assert job.error_code == "dify_workflow_failed"
        assert job.current_step == "管理员已手动终止"
