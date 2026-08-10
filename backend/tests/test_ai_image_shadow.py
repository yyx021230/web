from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import settings
from app.db.session import async_session
from app.models.ai_task import AITask
from app.models.job import Job, JobAttempt, JobEvent, JobStatus
from app.models.user import User
from app.services.ai_image_service import AIImageService
from app.services.ai_image_shadow import (
    AI_SHADOW_JOB_TYPE,
    AI_SHADOW_SOURCE_TYPE,
    AI_SHADOW_WORKER_TYPE,
    AIImageShadowAdapter,
    mirror_ai_image_shadow_safely,
)
from app.services.ai_task_queue import ai_image_task_queue
from app.services.job_service import JobService


@pytest_asyncio.fixture(autouse=True)
async def reset_ai_shadow_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "ai_image_shadow_enabled", False)
    yield


async def _seed_user(db, *, user_id: int = 1) -> None:
    db.add(
        User(
            id=user_id,
            username=f"ai-shadow-{user_id}",
            email=f"ai-shadow-{user_id}@example.com",
            hashed_password="x",
            role="admin",
        )
    )
    await db.flush()


async def _create_task(
    db,
    *,
    task_id: int = 101,
    status: str = "queued",
    params: dict | None = None,
) -> AITask:
    task = AITask(
        id=task_id,
        user_id=1,
        client_request_id=f"request-{task_id}",
        model_name="gptimage2",
        prompt="生成一张 3:4 汽车海报",
        params=params or {"width": 768, "height": 1024, "count": 1},
        status=status,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def _load_shadow_job(db, task_id: int) -> Job:
    return (
        await db.execute(
            select(Job).where(
                Job.job_type == AI_SHADOW_JOB_TYPE,
                Job.source_type == AI_SHADOW_SOURCE_TYPE,
                Job.source_id == str(task_id),
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_ai_shadow_feature_flag_defaults_off_and_writes_nothing(client):
    async with async_session() as db:
        await _seed_user(db)
        task = await _create_task(db)

    assert settings.ai_image_shadow_enabled is False
    assert await mirror_ai_image_shadow_safely(task.id, phase="queued") is None

    async with async_session() as db:
        assert (await db.execute(select(func.count(Job.id)))).scalar_one() == 0


@pytest.mark.asyncio
async def test_queued_shadow_uses_safe_request_snapshot_and_is_not_claimable(client):
    prompt = "生成一张 3:4 汽车海报"
    async with async_session() as db:
        await _seed_user(db)
        task = await _create_task(
            db,
            params={
                "width": 768,
                "height": 1024,
                "count": 1,
                "image_data": "data:image/png;base64,very-large-private-image",
                "provider": {"id": 7, "name": "Provider A", "api_key": "secret"},
            },
        )
        job = await AIImageShadowAdapter(db).mirror(task.id, phase="queued")
        assert job is not None
        await db.commit()

        assert job.worker_type == AI_SHADOW_WORKER_TYPE
        assert job.scope_key == "user:1"
        assert job.requested_by_user_id == 1
        assert job.status == JobStatus.QUEUED.value
        assert job.max_retries == 0
        assert (
            job.payload["prompt_sha256"]
            == hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        )
        assert job.payload["prompt_length"] == len(prompt)
        assert job.payload["request"] == {
            "width": 768,
            "height": 1024,
            "count": 1,
            "has_reference": True,
        }
        payload_text = str(job.payload)
        assert "very-large-private-image" not in payload_text
        assert "secret" not in payload_text

        claimed = await JobService(db).claim_next_job(
            worker_id="server-worker",
            worker_type="server",
        )
        assert claimed is None
        assert (await db.execute(select(func.count(JobAttempt.id)))).scalar_one() == 0


@pytest.mark.asyncio
async def test_shadow_records_complete_generation_lifecycle(client):
    started_at = datetime(2026, 8, 10, 1, 0, 0)
    finished_at = datetime(2026, 8, 10, 1, 5, 0)
    async with async_session() as db:
        await _seed_user(db)
        task = await _create_task(db)
        adapter = AIImageShadowAdapter(db)
        await adapter.mirror(task.id, phase="queued")

        task.status = "processing"
        task.params = {
            **(task.params or {}),
            "_processing_started_at": started_at.isoformat(),
            "provider": {
                "id": 7,
                "name": "Provider A",
                "provider_kind": "openai_images",
                "provider_model": "gpt-image-2",
            },
        }
        await db.flush()
        await adapter.mirror(task.id, phase="worker_started")
        await adapter.mirror(task.id, phase="upstream_started")
        await adapter.mirror(
            task.id,
            phase="provider_selected",
            details={"provider_id": 7, "api_key": "must-not-leak"},
        )
        await adapter.mirror(
            task.id,
            phase="upstream_finished",
            details={"upstream_task_id": "upstream-123", "image_count": 1},
        )
        await adapter.mirror(
            task.id,
            phase="result_stored",
            details={"source_count": 1, "stored_count": 1},
        )
        await adapter.mirror(task.id, phase="watermark_finished")

        task.status = "completed"
        task.result_urls = ["/uploads/ai-images/final.png"]
        task.finished_at = finished_at
        await db.flush()
        job = await adapter.mirror(task.id, phase="completed")
        assert job is not None
        await db.commit()

        assert job.status == JobStatus.SUCCEEDED.value
        assert job.started_at == started_at
        assert job.finished_at == finished_at
        assert job.progress_current == 6
        assert job.progress_total == 6
        assert job.current_step == "completed"
        assert job.result_summary["result_certainty"] == "known"
        assert job.result_summary["requires_reconciliation"] is False
        assert job.result_summary["upstream_task_id"] == "upstream-123"
        assert job.result_summary["image_count"] == 1
        assert job.result_summary["provider"]["name"] == "Provider A"

        history = job.payload["phase_history"]
        assert [row["phase"] for row in history] == [
            "queued",
            "worker_started",
            "upstream_started",
            "provider_selected",
            "upstream_finished",
            "result_stored",
            "watermark_finished",
            "completed",
        ]
        selected = next(row for row in history if row["phase"] == "provider_selected")
        assert selected["details"]["api_key"] == "[redacted]"
        assert "must-not-leak" not in str(job.payload)

        transitions = list(
            (
                await db.execute(
                    select(JobEvent.to_status)
                    .where(
                        JobEvent.job_id == job.id,
                        JobEvent.event_type == "status_changed",
                    )
                    .order_by(JobEvent.id)
                )
            ).scalars()
        )
        assert transitions == ["leased", "running", "succeeded"]


@pytest.mark.asyncio
async def test_explicit_failure_is_terminal_and_does_not_require_reconciliation(client):
    async with async_session() as db:
        await _seed_user(db)
        task = await _create_task(db)
        adapter = AIImageShadowAdapter(db)
        task.status = "processing"
        task.params = {
            **(task.params or {}),
            "_processing_started_at": "2026-08-10T01:00:00",
        }
        await db.flush()
        await adapter.mirror(task.id, phase="worker_started")

        task.status = "failed"
        task.error = "上游明确拒绝了参数"
        task.finished_at = datetime(2026, 8, 10, 1, 1, 0)
        await db.flush()
        job = await adapter.mirror(task.id, phase="failed")
        assert job is not None
        await db.commit()

        assert job.status == JobStatus.FAILED.value
        assert job.error_code == "legacy_ai_image_failed"
        assert job.result_summary["result_certainty"] == "known"
        assert job.result_summary["requires_reconciliation"] is False
        assert job.user_message == "上游明确拒绝了参数"


@pytest.mark.asyncio
async def test_timeout_enters_waiting_review_and_cannot_be_silently_resolved(client):
    async with async_session() as db:
        await _seed_user(db)
        task = await _create_task(db)
        adapter = AIImageShadowAdapter(db)
        task.status = "processing"
        task.params = {
            **(task.params or {}),
            "_processing_started_at": "2026-08-10T01:00:00",
        }
        await db.flush()
        await adapter.mirror(task.id, phase="worker_started")

        task.status = "failed"
        task.error = "任务执行超时"
        task.finished_at = datetime(2026, 8, 10, 1, 30, 0)
        await db.flush()
        job = await adapter.mirror(
            task.id,
            phase="result_unknown",
            details={"reason": "platform_deadline"},
            result_unknown=True,
        )
        assert job is not None
        await adapter.mirror(task.id, phase="failed")
        await db.commit()

        assert job.status == JobStatus.WAITING_REVIEW.value
        assert job.error_code == "upstream_result_unknown"
        assert job.result_summary["result_certainty"] == "unknown"
        assert job.result_summary["requires_reconciliation"] is True
        assert job.finished_at is None


@pytest.mark.asyncio
async def test_worker_restart_records_unknown_result_before_legacy_retry(client):
    first_start = datetime(2026, 8, 10, 1, 0, 0)
    second_start = datetime(2026, 8, 10, 1, 10, 0)
    async with async_session() as db:
        await _seed_user(db)
        task = await _create_task(db)
        adapter = AIImageShadowAdapter(db)
        task.status = "processing"
        task.params = {
            **(task.params or {}),
            "_processing_started_at": first_start.isoformat(),
        }
        await db.flush()
        job = await adapter.mirror(task.id, phase="worker_started")
        assert job is not None

        task.status = "queued"
        await db.flush()
        await adapter.mirror(
            task.id,
            phase="worker_recovered",
            result_unknown=True,
        )
        assert job.status == JobStatus.WAITING_REVIEW.value

        task.status = "processing"
        task.params = {
            **(task.params or {}),
            "_processing_started_at": second_start.isoformat(),
        }
        await db.flush()
        await adapter.mirror(task.id, phase="worker_started")
        await db.commit()

        assert job.status == JobStatus.RUNNING.value
        assert job.result_summary["requires_reconciliation"] is True
        transitions = list(
            (
                await db.execute(
                    select(JobEvent).where(
                        JobEvent.job_id == job.id,
                        JobEvent.event_type == "status_changed",
                    )
                )
            ).scalars()
        )
        assert [event.to_status for event in transitions] == [
            "leased",
            "running",
            "waiting_review",
            "queued",
            "leased",
            "running",
        ]
        resume = next(event for event in transitions if event.to_status == "queued")
        assert resume.details["duplicate_charge_risk"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("started", [False, True])
async def test_cancelled_task_maps_without_reopening_terminal_state(client, started):
    async with async_session() as db:
        await _seed_user(db)
        task = await _create_task(db)
        adapter = AIImageShadowAdapter(db)
        if started:
            task.status = "processing"
            task.params = {
                **(task.params or {}),
                "_processing_started_at": "2026-08-10T01:00:00",
            }
            await db.flush()
            await adapter.mirror(task.id, phase="worker_started")
        task.status = "cancelled"
        task.error = "已取消"
        task.finished_at = datetime(2026, 8, 10, 1, 2, 0)
        await db.flush()
        job = await adapter.mirror(task.id, phase="cancelled")
        assert job is not None
        await adapter.mirror(task.id, phase="cancelled")
        await db.commit()

        assert job.status == JobStatus.CANCELLED.value
        assert job.finished_at == task.finished_at
        assert len(job.payload["phase_history"]) == (2 if started else 1)


@pytest.mark.asyncio
async def test_safe_shadow_failure_never_fails_legacy_path(client, monkeypatch):
    async with async_session() as db:
        await _seed_user(db)
        task = await _create_task(db)

    monkeypatch.setattr(settings, "ai_image_shadow_enabled", True)

    async def fail_mirror(*_args, **_kwargs):
        raise RuntimeError("shadow database unavailable")

    monkeypatch.setattr(AIImageShadowAdapter, "mirror", fail_mirror)
    assert await mirror_ai_image_shadow_safely(task.id, phase="queued") is None

    async with async_session() as db:
        legacy = await db.get(AITask, task.id)
        assert legacy is not None
        assert legacy.status == "queued"


@pytest.mark.asyncio
async def test_concurrent_shadow_callbacks_create_one_durable_job(client, monkeypatch):
    async with async_session() as db:
        await _seed_user(db)
        task = await _create_task(db)

    monkeypatch.setattr(settings, "ai_image_shadow_enabled", True)
    results = await asyncio.gather(
        *[mirror_ai_image_shadow_safely(task.id, phase="queued") for _ in range(8)]
    )

    async with async_session() as db:
        assert len({job_id for job_id in results if job_id is not None}) == 1
        assert (
            await db.execute(
                select(func.count(Job.id)).where(
                    Job.job_type == AI_SHADOW_JOB_TYPE,
                    Job.source_id == str(task.id),
                )
            )
        ).scalar_one() == 1


@pytest.mark.asyncio
async def test_enabled_shadow_observes_one_legacy_generation_execution(
    client,
    monkeypatch,
):
    queued_ids: list[int] = []
    generation_calls = 0

    async def fake_enqueue(task_id: int) -> bool:
        queued_ids.append(int(task_id))
        return True

    async def fake_pipeline(self, prompt, params, user_id=None, task_id=None):
        nonlocal generation_calls
        generation_calls += 1
        return (
            {"status": "completed", "image_urls": ["/uploads/raw.png"]},
            ["/uploads/raw.png"],
            ["/uploads/final.png"],
        )

    monkeypatch.setattr(settings, "ai_image_shadow_enabled", True)
    monkeypatch.setattr(ai_image_task_queue, "enqueue_task", fake_enqueue)
    monkeypatch.setattr(AIImageService, "_run_generation_pipeline", fake_pipeline)

    async with async_session() as db:
        await _seed_user(db)
        await db.commit()
        service = AIImageService(model_name="gptimage2", db=db)
        submitted = await service.submit(
            "只执行一次",
            {"width": 768, "height": 1024},
            user_id=1,
            client_request_id="one-execution",
        )
        task_id = int(submitted["task_id"])
        assert queued_ids == [task_id]

        status = await service.execute_submitted_task(task_id)
        assert status == "completed"

    async with async_session() as db:
        task = await db.get(AITask, task_id)
        job = await _load_shadow_job(db, task_id)
        assert task is not None
        assert task.status == "completed"
        assert task.result_urls == ["/uploads/final.png"]
        assert job.status == JobStatus.SUCCEEDED.value
        assert generation_calls == 1
        assert (await db.execute(select(func.count(Job.id)))).scalar_one() == 1


@pytest.mark.asyncio
async def test_legacy_execution_timeout_is_mirrored_as_unknown_result(
    client,
    monkeypatch,
):
    async def slow_pipeline(self, prompt, params, user_id=None, task_id=None):
        await asyncio.sleep(0.05)
        return ({"status": "completed", "image_urls": []}, [], [])

    monkeypatch.setattr(settings, "ai_image_shadow_enabled", True)
    monkeypatch.setattr(AIImageService, "_run_generation_pipeline", slow_pipeline)
    monkeypatch.setattr(
        AIImageService,
        "_task_timeout_seconds",
        staticmethod(lambda: 0.01),
    )

    async with async_session() as db:
        await _seed_user(db)
        task = await _create_task(db, task_id=401)
        status = await AIImageService(db=db).execute_submitted_task(task.id)
        assert status == "failed"

    async with async_session() as db:
        task = await db.get(AITask, 401)
        job = await _load_shadow_job(db, 401)
        assert task is not None
        assert task.status == "failed"
        assert "执行超时" in str(task.error)
        assert job.status == JobStatus.WAITING_REVIEW.value
        assert job.result_summary["result_certainty"] == "unknown"
        assert job.result_summary["requires_reconciliation"] is True


@pytest.mark.asyncio
async def test_recovery_marks_only_interrupted_processing_task_unknown(
    client,
    monkeypatch,
):
    async def fake_drain() -> list[int]:
        return [501, 502]

    async def fake_requeue(task_ids) -> int:
        return len(list(task_ids))

    async def fake_discard(task_ids) -> int:
        return len(list(task_ids))

    async def fake_enqueue_missing(task_ids) -> int:
        return len(list(task_ids))

    monkeypatch.setattr(settings, "ai_image_shadow_enabled", True)
    monkeypatch.setattr(ai_image_task_queue, "drain_processing_tasks", fake_drain)
    monkeypatch.setattr(ai_image_task_queue, "requeue_drained_tasks", fake_requeue)
    monkeypatch.setattr(ai_image_task_queue, "discard_tasks", fake_discard)
    monkeypatch.setattr(
        ai_image_task_queue, "enqueue_missing_tasks", fake_enqueue_missing
    )

    async with async_session() as db:
        await _seed_user(db)
        processing = await _create_task(db, task_id=501, status="processing")
        processing.params = {
            **(processing.params or {}),
            "_processing_started_at": (
                datetime.now() - timedelta(minutes=5)
            ).isoformat(),
        }
        await db.commit()
        await AIImageShadowAdapter(db).mirror(501, phase="worker_started")
        await db.commit()
        await _create_task(db, task_id=502, status="queued")

        recovery = await AIImageService(db=db).recover_incomplete_tasks()
        assert recovery["reset_processing"] == 1

    async with async_session() as db:
        interrupted = await _load_shadow_job(db, 501)
        normal_queued_count = (
            await db.execute(
                select(func.count(Job.id)).where(
                    Job.source_type == AI_SHADOW_SOURCE_TYPE,
                    Job.source_id == "502",
                )
            )
        ).scalar_one()
        assert interrupted.status == JobStatus.WAITING_REVIEW.value
        assert interrupted.result_summary["requires_reconciliation"] is True
        assert normal_queued_count == 0
