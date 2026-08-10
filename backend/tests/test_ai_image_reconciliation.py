from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import settings
from app.db.session import async_session
from app.models.ai_task import AITask
from app.models.ai_image_provider import AIImageProvider
from app.models.job import Job, JobEvent, JobStatus
from app.models.user import User
from app.services.ai_image_reconciliation_service import (
    AIImageReconciliationConflict,
    AIImageReconciliationError,
    AIImageReconciliationNotFound,
    AIImageReconciliationService,
    reconcile_ai_image_shadow_jobs_once,
)
from app.services.ai_image_service import AIImageService
from app.services.ai_image_shadow import AIImageShadowAdapter
from tests.conftest import make_auth_headers


@pytest_asyncio.fixture(autouse=True)
async def enable_ai_shadow(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "ai_image_shadow_enabled", True)
    monkeypatch.setattr(settings, "ai_image_reconciliation_enabled", False)
    yield


async def _seed_user(
    db,
    *,
    user_id: int = 1,
    role: str = "admin",
    username: str | None = None,
) -> User:
    user = User(
        id=user_id,
        username=username or f"reconcile-{user_id}",
        email=f"reconcile-{user_id}@example.com",
        hashed_password="x",
        role=role,
    )
    db.add(user)
    await db.flush()
    return user


async def _seed_review_job(
    db,
    *,
    task_id: int = 701,
    user_id: int = 1,
    attempts: list[dict] | None = None,
) -> tuple[AITask, Job]:
    await _seed_user(db, user_id=user_id)
    params = {
        "width": 768,
        "height": 1024,
        "count": 1,
        "_processing_started_at": (datetime.now() - timedelta(minutes=5)).isoformat(),
        "provider": {
            "id": 91,
            "name": "测试批处理入口",
            "provider_kind": "mentalout_batch",
            "provider_model": "gpt-image-2",
        },
    }
    if attempts is not None:
        params["_upstream_attempts"] = attempts
    task = AITask(
        id=task_id,
        user_id=user_id,
        model_name="gptimage2",
        prompt="不得出现在核对接口中的私密提示词",
        params=params,
        status="processing",
    )
    db.add(task)
    await db.commit()

    adapter = AIImageShadowAdapter(db)
    await adapter.mirror(task.id, phase="worker_started")
    task.status = "failed"
    task.error = "任务执行超时"
    task.finished_at = datetime.now()
    await db.flush()
    job = await adapter.mirror(
        task.id,
        phase="result_unknown",
        details={"reason": "platform_timeout"},
        result_unknown=True,
    )
    assert job is not None
    await db.commit()
    return task, job


def _attempt(task_id: str, *, provider_id: int | None = 91) -> dict:
    return {
        "upstream_task_id": task_id,
        "provider_id": provider_id,
        "provider_kind": (
            "mentalout_batch" if provider_id is not None else "legacy_batch_adapter"
        ),
        "provider_model": "gpt-image-2",
        "query_capability": (
            "mentalout_batch" if provider_id is not None else "legacy_batch_gateway"
        ),
        "accepted_at": "2026-08-10T01:00:00",
    }


@pytest.mark.asyncio
async def test_upstream_acceptance_is_persisted_once_in_task_and_shadow(client):
    async with async_session() as db:
        await _seed_user(db)
        task = AITask(
            id=710,
            user_id=1,
            model_name="gptimage2",
            prompt="capture id",
            params={
                "width": 768,
                "height": 1024,
                "_processing_started_at": datetime.now().isoformat(),
            },
            status="processing",
        )
        db.add(task)
        await db.commit()
        await AIImageShadowAdapter(db).mirror(task.id, phase="worker_started")
        await db.commit()

        details = _attempt("batch-710")
        service = AIImageService(db=db)
        assert await service._mark_task_upstream_accepted(db, task.id, details) is True
        assert await service._mark_task_upstream_accepted(db, task.id, details) is False

    async with async_session() as db:
        task = await db.get(AITask, 710)
        job = (await db.execute(select(Job).where(Job.source_id == "710"))).scalar_one()
        assert task is not None
        assert task.params["_upstream_attempts"] == [
            {
                **_attempt("batch-710"),
                "accepted_at": task.params["_upstream_attempts"][0]["accepted_at"],
            }
        ]
        assert len(job.result_summary["upstream_attempts"]) == 1
        accepted_phases = [
            row
            for row in job.payload["phase_history"]
            if row["phase"] == "upstream_accepted"
        ]
        assert len(accepted_phases) == 1


@pytest.mark.asyncio
async def test_batch_id_survives_platform_timeout_for_later_reconciliation(
    client,
    monkeypatch,
):
    accepted = asyncio.Event()

    async def fake_generate(
        self,
        prompt,
        params,
        user_id=None,
        model_name="gptimage2",
        on_provider_selected=None,
        on_upstream_accepted=None,
    ):
        if on_provider_selected:
            await on_provider_selected(
                {
                    "id": 92,
                    "name": "Timeout Batch",
                    "provider_kind": "mentalout_batch",
                    "provider_model": "gpt-image-2",
                }
            )
        if on_upstream_accepted:
            await on_upstream_accepted(_attempt("batch-before-timeout", provider_id=92))
            accepted.set()
        await asyncio.Event().wait()
        return {"status": "completed", "image_urls": []}

    async def timeout_after_acceptance(awaitable, timeout):
        pipeline = asyncio.create_task(awaitable)
        await accepted.wait()
        pipeline.cancel()
        await asyncio.gather(pipeline, return_exceptions=True)
        raise asyncio.TimeoutError

    monkeypatch.setattr(
        "app.services.ai_image_provider_service.AIImageProviderService.generate",
        fake_generate,
    )
    monkeypatch.setattr(
        "app.services.ai_image_service.asyncio.wait_for",
        timeout_after_acceptance,
    )
    async with async_session() as db:
        await _seed_user(db)
        db.add(
            AIImageProvider(
                id=92,
                name="Timeout Batch",
                model_name="gptimage2",
                provider_kind="mentalout_batch",
                provider_model="gpt-image-2",
                endpoint_url="https://image.example.com",
                api_key="test-key",
                is_enabled=True,
                is_default=True,
                supports_text_input=True,
                supports_image_input=True,
                config={},
            )
        )
        task = AITask(
            id=711,
            user_id=1,
            model_name="gptimage2",
            prompt="timeout capture",
            params={"width": 768, "height": 1024},
            status="queued",
        )
        db.add(task)
        await db.commit()
        assert await AIImageService(db=db).execute_submitted_task(task.id) == "failed"

    async with async_session() as db:
        task = await db.get(AITask, 711)
        job = (await db.execute(select(Job).where(Job.source_id == "711"))).scalar_one()
        assert task is not None
        assert task.status == "failed"
        assert task.params["_upstream_attempts"][0]["upstream_task_id"] == (
            "batch-before-timeout"
        )
        assert job.status == JobStatus.WAITING_REVIEW.value
        assert job.result_summary["upstream_task_id"] == "batch-before-timeout"
        assert job.result_summary["requires_reconciliation"] is True


@pytest.mark.asyncio
async def test_automatic_reconciliation_recovers_completed_image(client):
    fetch_calls: list[str] = []

    async def fetch(attempt: dict) -> dict:
        fetch_calls.append(attempt["upstream_task_id"])
        return {
            "task_id": attempt["upstream_task_id"],
            "status": "completed",
            "raw_status": "succeeded",
            "image_urls": ["https://images.example/result.png"],
        }

    async def persist(urls: list[str]) -> list[str]:
        assert urls == ["https://images.example/result.png"]
        return ["/uploads/ai-images/recovered.png"]

    async with async_session() as db:
        task, job = await _seed_review_job(db, attempts=[_attempt("batch-success")])
        result = await AIImageReconciliationService(
            db,
            status_fetcher=fetch,
            image_persister=persist,
        ).reconcile_job(job.id, actor_type="admin", actor_id="1")
        await db.commit()

        assert result["changed"] is True
        assert result["status"] == JobStatus.SUCCEEDED.value
        assert fetch_calls == ["batch-success"]
        await db.refresh(task)
        assert task.status == "completed"
        assert task.result_urls == ["/uploads/ai-images/recovered.png"]
        await db.refresh(job)
        assert job.error_code is None
        assert job.result_summary["result_certainty"] == "known"
        assert job.result_summary["requires_reconciliation"] is False
        assert job.result_summary["resolution"]["result_recovered"] is True
        event_types = list(
            (
                await db.execute(
                    select(JobEvent.event_type)
                    .where(JobEvent.job_id == job.id)
                    .order_by(JobEvent.id)
                )
            ).scalars()
        )
        assert "ai_image_reconciliation_checked" in event_types


@pytest.mark.asyncio
async def test_generating_result_stays_in_review_and_honors_backoff(client):
    async def fetch(attempt: dict) -> dict:
        return {
            "task_id": attempt["upstream_task_id"],
            "status": "generating",
            "raw_status": "running",
            "image_urls": [],
        }

    async with async_session() as db:
        _, job = await _seed_review_job(db, attempts=[_attempt("batch-running")])
        service = AIImageReconciliationService(db, status_fetcher=fetch)
        first = await service.reconcile_job(job.id)
        await db.commit()
        assert first["changed"] is False
        assert first["status"] == JobStatus.WAITING_REVIEW.value
        assert first["upstream_attempts"][0]["status"] == "generating"

        second = await service.reconcile_job(job.id, force=False)
        assert second["skipped"] is True
        assert (
            await db.execute(
                select(func.count(JobEvent.id)).where(
                    JobEvent.job_id == job.id,
                    JobEvent.event_type == "ai_image_reconciliation_checked",
                )
            )
        ).scalar_one() == 1


@pytest.mark.asyncio
async def test_confirmed_upstream_failure_closes_review(client):
    async def fetch(attempt: dict) -> dict:
        return {
            "task_id": attempt["upstream_task_id"],
            "status": "failed",
            "raw_status": "failed",
            "image_urls": [],
            "error": "上游明确失败",
        }

    async with async_session() as db:
        task, job = await _seed_review_job(db, attempts=[_attempt("batch-failed")])
        result = await AIImageReconciliationService(
            db, status_fetcher=fetch
        ).reconcile_job(job.id)
        await db.commit()
        assert result["status"] == JobStatus.FAILED.value
        assert result["changed"] is True
        await db.refresh(task)
        assert task.status == "failed"
        assert task.error == "上游明确失败"
        await db.refresh(job)
        assert job.error_code == "upstream_confirmed_failed"


@pytest.mark.asyncio
async def test_multiple_attempts_wait_until_every_result_is_known(client):
    statuses = {"batch-a": "completed", "batch-b": "generating"}

    async def fetch(attempt: dict) -> dict:
        status = statuses[attempt["upstream_task_id"]]
        return {
            "task_id": attempt["upstream_task_id"],
            "status": status,
            "image_urls": (
                ["https://images.example/a.png"] if status == "completed" else []
            ),
            "error": "retry failed" if status == "failed" else None,
        }

    async def persist(urls: list[str]) -> list[str]:
        return ["/uploads/ai-images/a.png"]

    async with async_session() as db:
        task, job = await _seed_review_job(
            db,
            attempts=[_attempt("batch-a"), _attempt("batch-b")],
        )
        service = AIImageReconciliationService(
            db,
            status_fetcher=fetch,
            image_persister=persist,
        )
        first = await service.reconcile_job(job.id)
        await db.commit()
        assert first["status"] == JobStatus.WAITING_REVIEW.value
        assert first["duplicate_charge_risk"] is True
        await db.refresh(task)
        assert task.status == "completed"

        statuses["batch-b"] = "failed"
        second = await service.reconcile_job(job.id)
        await db.commit()
        assert second["status"] == JobStatus.SUCCEEDED.value
        assert second["duplicate_charge_risk"] is True
        assert second["resolution"]["outcome"] == "succeeded"


@pytest.mark.asyncio
async def test_missing_upstream_id_requires_manual_review_without_retry(client):
    async with async_session() as db:
        _, job = await _seed_review_job(db, attempts=None)
        result = await AIImageReconciliationService(db).reconcile_job(job.id)
        await db.commit()
        assert result["status"] == JobStatus.WAITING_REVIEW.value
        assert result["changed"] is False
        assert result["reconciliation"] == {
            "method": "manual_required",
            "reason": "missing_upstream_task_id",
            "last_checked_at": result["reconciliation"]["last_checked_at"],
        }
        event = (
            await db.execute(
                select(JobEvent).where(
                    JobEvent.job_id == job.id,
                    JobEvent.event_type == "ai_image_reconciliation_manual_required",
                )
            )
        ).scalar_one()
        assert event.level == "warning"

        repeated = await AIImageReconciliationService(db).reconcile_job(job.id)
        await db.commit()
        assert repeated["changed"] is False
        event_count = (
            await db.execute(
                select(func.count(JobEvent.id)).where(
                    JobEvent.job_id == job.id,
                    JobEvent.event_type == "ai_image_reconciliation_manual_required",
                )
            )
        ).scalar_one()
        assert event_count == 1


@pytest.mark.asyncio
async def test_list_validation_conflict_and_terminal_reconcile_are_safe(client):
    async with async_session() as db:
        _, job = await _seed_review_job(db, attempts=None)
        service = AIImageReconciliationService(db)

        with pytest.raises(AIImageReconciliationError):
            await service.list_jobs(status="running")
        listing = await service.list_jobs(status="all", limit=9999)
        assert listing["total"] == 1
        assert listing["items"][0]["job_id"] == job.id

        job.status = JobStatus.RUNNING.value
        await db.flush()
        with pytest.raises(AIImageReconciliationConflict):
            await service.reconcile_job(job.id)

        job.status = JobStatus.WAITING_REVIEW.value
        await service.manual_resolve(
            job.id,
            outcome="failed",
            reason="人工确认上游没有结果",
            actor_id="1",
        )
        terminal = await service.reconcile_job(job.id)
        assert terminal["changed"] is False
        assert terminal["status"] == JobStatus.FAILED.value


@pytest.mark.asyncio
async def test_manual_resolution_validates_input_and_supports_success(client):
    async with async_session() as db:
        task, job = await _seed_review_job(db, attempts=None)
        service = AIImageReconciliationService(db)

        with pytest.raises(AIImageReconciliationError):
            await service.manual_resolve(
                job.id,
                outcome="unknown",
                reason="无效结果",
                actor_id="1",
            )
        with pytest.raises(AIImageReconciliationError):
            await service.manual_resolve(
                job.id,
                outcome="succeeded",
                reason="短",
                actor_id="1",
            )
        with pytest.raises(AIImageReconciliationError):
            await service.manual_resolve(
                job.id,
                outcome="succeeded",
                reason="过" * 501,
                actor_id="1",
            )

        result = await service.manual_resolve(
            job.id,
            outcome="succeeded",
            reason="供应商后台确认生成成功但图片未能回收",
            actor_id="1",
        )
        await db.commit()
        assert result["status"] == JobStatus.SUCCEEDED.value
        assert result["resolution"]["result_recovered"] is False
        await db.refresh(task)
        assert task.status == "failed"


@pytest.mark.asyncio
async def test_manual_resolution_recovers_known_images_and_supports_cancel(client):
    async with async_session() as db:
        recovered_task, recovered_job = await _seed_review_job(
            db,
            task_id=721,
            attempts=None,
        )
        summary = dict(recovered_job.result_summary or {})
        summary["recovered_image_urls"] = ["/uploads/ai-images/manual.png"]
        recovered_job.result_summary = summary
        recovered = await AIImageReconciliationService(db).manual_resolve(
            recovered_job.id,
            outcome="succeeded",
            reason="人工确认图片已经安全回收到本地",
            actor_id="1",
        )
        await db.commit()
        assert recovered["status"] == JobStatus.SUCCEEDED.value
        await db.refresh(recovered_task)
        assert recovered_task.status == "completed"
        assert recovered_task.result_urls == ["/uploads/ai-images/manual.png"]

    async with async_session() as db:
        cancelled_task, cancelled_job = await _seed_review_job(
            db,
            task_id=722,
            user_id=2,
            attempts=None,
        )
        cancelled = await AIImageReconciliationService(db).manual_resolve(
            cancelled_job.id,
            outcome="cancelled",
            reason="管理员确认该任务无需继续核对",
            actor_id="1",
        )
        await db.commit()
        assert cancelled["status"] == JobStatus.CANCELLED.value
        await db.refresh(cancelled_task)
        assert cancelled_task.status == "cancelled"


@pytest.mark.asyncio
async def test_manual_resolution_is_audited_idempotent_and_conflict_safe(client):
    async with async_session() as db:
        _, job = await _seed_review_job(db, attempts=None)
        service = AIImageReconciliationService(db)
        first = await service.manual_resolve(
            job.id,
            outcome="failed",
            reason="供应商后台确认没有生成结果",
            actor_id="99",
        )
        await db.commit()
        assert first["changed"] is True
        assert first["resolution"]["actor_id"] == "99"
        assert first["resolution"]["reason"] == "供应商后台确认没有生成结果"

        second = await service.manual_resolve(
            job.id,
            outcome="failed",
            reason="重复确认不会重复写状态",
            actor_id="99",
        )
        assert second["changed"] is False
        with pytest.raises(AIImageReconciliationConflict):
            await service.manual_resolve(
                job.id,
                outcome="succeeded",
                reason="冲突结果必须拒绝",
                actor_id="99",
            )


@pytest.mark.asyncio
async def test_reconciliation_admin_api_auth_list_and_manual_resolve(client):
    async with async_session() as db:
        _, job = await _seed_review_job(db, attempts=[_attempt("batch-api")])
        await _seed_user(db, user_id=2, role="viewer", username="viewer")
        await db.commit()
        job_id = job.id

    path = "/api/v1/admin/reliability/ai-image-shadow"
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=make_auth_headers(2))).status_code == 403

    response = await client.get(path, headers=make_auth_headers(1))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["upstream_task_id"] == "batch-api"
    assert "私密提示词" not in response.text
    assert "api_key" not in response.text

    short_reason = await client.post(
        f"{path}/{job_id}/resolve",
        headers=make_auth_headers(1),
        json={"outcome": "failed", "reason": "短"},
    )
    assert short_reason.status_code == 422
    resolved = await client.post(
        f"{path}/{job_id}/resolve",
        headers=make_auth_headers(1),
        json={"outcome": "failed", "reason": "人工后台确认失败"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["data"]["status"] == JobStatus.FAILED.value


@pytest.mark.asyncio
async def test_admin_reconcile_endpoint_marks_missing_id_once(client):
    async with async_session() as db:
        _, job = await _seed_review_job(db, attempts=None)
        job_id = job.id

    path = f"/api/v1/admin/reliability/ai-image-shadow/{job_id}/reconcile"
    first = await client.post(path, headers=make_auth_headers(1))
    second = await client.post(path, headers=make_auth_headers(1))
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["reconciliation"]["method"] == "manual_required"

    async with async_session() as db:
        count = (
            await db.execute(
                select(func.count(JobEvent.id)).where(
                    JobEvent.job_id == job_id,
                    JobEvent.event_type == "ai_image_reconciliation_manual_required",
                )
            )
        ).scalar_one()
        assert count == 1

    not_found = await client.post(
        "/api/v1/admin/reliability/ai-image-shadow/999999/reconcile",
        headers=make_auth_headers(1),
    )
    assert not_found.status_code == 404


@pytest.mark.asyncio
async def test_default_status_fetcher_uses_provider_query_and_never_resubmits(
    client,
    monkeypatch,
):
    calls: list[tuple[int, str]] = []

    async def fake_status(self, provider_id: int, upstream_task_id: str) -> dict:
        calls.append((provider_id, upstream_task_id))
        return {
            "task_id": upstream_task_id,
            "status": "failed",
            "image_urls": [],
            "error": "provider confirmed failure",
        }

    monkeypatch.setattr(
        "app.services.ai_image_reconciliation_service."
        "AIImageProviderService.get_upstream_task_status",
        fake_status,
    )
    async with async_session() as db:
        _, job = await _seed_review_job(db, attempts=[_attempt("batch-default")])
        result = await AIImageReconciliationService(db).reconcile_job(job.id)
        await db.commit()
        assert result["status"] == JobStatus.FAILED.value
        assert calls == [(91, "batch-default")]


@pytest.mark.asyncio
async def test_unsupported_upstream_attempt_stays_for_manual_review(client):
    unsupported = {
        "upstream_task_id": "opaque-id",
        "provider_kind": "openai_images",
        "query_capability": "none",
    }
    async with async_session() as db:
        _, job = await _seed_review_job(db, attempts=[unsupported])
        result = await AIImageReconciliationService(db).reconcile_job(job.id)
        await db.commit()
        assert result["status"] == JobStatus.WAITING_REVIEW.value
        assert result["upstream_attempts"][0]["status"] == "unsupported"
        assert result["changed"] is False

        with pytest.raises(AIImageReconciliationNotFound):
            await AIImageReconciliationService(db).reconcile_job(999999)


@pytest.mark.asyncio
async def test_worker_tick_resolves_jobs_independently(client, monkeypatch):
    async def fake_fetch(self, attempt: dict) -> dict:
        return {
            "task_id": attempt["upstream_task_id"],
            "status": "failed",
            "image_urls": [],
            "error": "worker confirmed failure",
        }

    monkeypatch.setattr(
        AIImageReconciliationService,
        "_fetch_upstream_status",
        fake_fetch,
    )
    async with async_session() as db:
        _, job = await _seed_review_job(
            db,
            task_id=799,
            attempts=[_attempt("batch-worker")],
        )
        job_id = job.id

    result = await reconcile_ai_image_shadow_jobs_once(limit=5)
    assert result == {
        "candidates": 1,
        "checked": 1,
        "resolved": 1,
        "skipped": 0,
        "errors": 0,
    }
    async with async_session() as db:
        job = await db.get(Job, job_id)
        assert job is not None
        assert job.status == JobStatus.FAILED.value


@pytest.mark.asyncio
async def test_worker_tick_isolates_one_upstream_query_failure(client, monkeypatch):
    async def fake_fetch(self, attempt: dict) -> dict:
        if attempt["upstream_task_id"] == "batch-query-error":
            raise RuntimeError("temporary provider outage")
        return {
            "task_id": attempt["upstream_task_id"],
            "status": "failed",
            "image_urls": [],
            "error": "worker confirmed failure",
        }

    monkeypatch.setattr(
        AIImageReconciliationService,
        "_fetch_upstream_status",
        fake_fetch,
    )
    async with async_session() as db:
        _, failed_query_job = await _seed_review_job(
            db,
            task_id=801,
            attempts=[_attempt("batch-query-error")],
        )
        _, resolved_job = await _seed_review_job(
            db,
            task_id=802,
            user_id=2,
            attempts=[_attempt("batch-resolved")],
        )
        failed_query_job_id = failed_query_job.id
        resolved_job_id = resolved_job.id

    result = await reconcile_ai_image_shadow_jobs_once(limit=5)
    assert result == {
        "candidates": 2,
        "checked": 1,
        "resolved": 1,
        "skipped": 0,
        "errors": 1,
    }
    async with async_session() as db:
        failed_query_job = await db.get(Job, failed_query_job_id)
        resolved_job = await db.get(Job, resolved_job_id)
        assert failed_query_job is not None
        assert failed_query_job.status == JobStatus.WAITING_REVIEW.value
        assert resolved_job is not None
        assert resolved_job.status == JobStatus.FAILED.value


@pytest.mark.asyncio
async def test_worker_tick_skips_manual_required_job_without_duplicate_event(client):
    async with async_session() as db:
        _, job = await _seed_review_job(db, attempts=None)
        await AIImageReconciliationService(db).reconcile_job(job.id)
        await db.commit()
        job_id = job.id

    result = await reconcile_ai_image_shadow_jobs_once(limit=5)
    assert result == {
        "candidates": 1,
        "checked": 0,
        "resolved": 0,
        "skipped": 1,
        "errors": 0,
    }
    async with async_session() as db:
        count = (
            await db.execute(
                select(func.count(JobEvent.id)).where(
                    JobEvent.job_id == job_id,
                    JobEvent.event_type == "ai_image_reconciliation_manual_required",
                )
            )
        ).scalar_one()
        assert count == 1
