from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.db.session import async_session
from app.models.ai_task import AITask
from app.models.job import Job
from app.services.ai_image_provider_service import AIImageProviderService
from app.services.ai_image_reconciliation_service import AIImageReconciliationService
from app.services.ai_image_service import AIImageService
from tests.test_ai_image_reconciliation import _seed_review_job, _seed_user


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_protocol_is_opt_in_and_old_providers_remain_synchronous(
    monkeypatch, enabled
):
    provider = SimpleNamespace(
        id=5,
        provider_kind="openai_images",
        model_name="gptimage2",
        provider_model="gpt-image-2",
        config={"api_mode": "sub2api_async"} if enabled else {},
    )
    service = AIImageProviderService(None)
    async_call = AsyncMock(
        return_value={"status": "completed", "image_urls": ["/async.png"]}
    )
    sync_call = AsyncMock(
        return_value={"status": "completed", "image_urls": ["/sync.png"]}
    )
    monkeypatch.setattr(
        "app.services.ai_image_provider_service.generate_async_images", async_call
    )
    monkeypatch.setattr(service, "_call_openai_images", sync_call)
    accepted = AsyncMock()
    await service._call_provider(
        provider, "prompt", {"count": 1}, on_upstream_accepted=accepted
    )
    assert async_call.await_count == int(enabled)
    assert sync_call.await_count == int(not enabled)
    if enabled:
        assert async_call.call_args.kwargs["on_upstream_accepted"] is accepted


@pytest.mark.asyncio
async def test_saved_async_capability_queries_after_config_is_rolled_back(monkeypatch):
    provider = SimpleNamespace(id=5, provider_kind="openai_images", config={})
    service = AIImageProviderService(None)
    monkeypatch.setattr(service, "get_provider", AsyncMock(return_value=provider))
    query = AsyncMock(return_value={"status": "generating", "image_urls": []})
    monkeypatch.setattr(
        "app.services.ai_image_provider_service.get_async_image_task_status", query
    )
    await service.get_upstream_task_status(
        5, "imgtask_saved", expected_count=1, query_capability="openai_images_async"
    )
    assert query.call_args.args[:3] == (provider, "imgtask_saved", 1)


@pytest.mark.asyncio
async def test_async_expected_count_is_durable_in_task_and_shadow(client, monkeypatch):
    monkeypatch.setattr(settings, "ai_image_shadow_enabled", True)
    async with async_session() as db:
        await _seed_user(db)
        task = AITask(
            id=750,
            user_id=1,
            model_name="gptimage2",
            prompt="count four",
            params={"count": 4},
            status="processing",
        )
        db.add(task)
        await db.commit()
        service = AIImageService(db=db)
        details = {
            "upstream_task_id": "imgtask_part",
            "provider_id": 5,
            "provider_kind": "openai_images",
            "query_capability": "openai_images_async",
            "expected_count": 1,
        }
        await service._mark_task_upstream_accepted(db, task.id, details)
        await db.refresh(task)
        assert task.params["_upstream_attempts"][0]["expected_count"] == 1
        job = (
            await db.get(Job, task.params.get("_shadow_job_id"))
            if task.params.get("_shadow_job_id")
            else None
        )
        if job is None:
            from sqlalchemy import select

            job = (
                await db.execute(select(Job).where(Job.source_id == str(task.id)))
            ).scalar_one()
        assert job.result_summary["upstream_attempts"][0]["expected_count"] == 1


@pytest.mark.asyncio
async def test_reconciliation_recovers_four_single_images_across_poll_rounds(
    client, monkeypatch
):
    monkeypatch.setattr(settings, "ai_image_shadow_enabled", True)
    attempts = [
        {
            "upstream_task_id": f"imgtask_{i}",
            "provider_id": 5,
            "provider_kind": "openai_images",
            "query_capability": "openai_images_async",
            "expected_count": 1,
        }
        for i in range(4)
    ]
    async with async_session() as db:
        task, job = await _seed_review_job(db, attempts=attempts)
        task.params = {**task.params, "count": 4}
        await db.commit()
        first_round = True

        async def fetch(attempt):
            assert attempt["expected_count"] == 1
            index = int(attempt["upstream_task_id"].rsplit("_", 1)[1])
            if first_round and index > 1:
                return {"status": "generating", "image_urls": []}
            return {"status": "completed", "image_urls": [f"/up/{index}.png"]}

        async def persist(urls):
            return [url.replace("/up/", "/clean/") for url in urls]

        service = AIImageReconciliationService(
            db, status_fetcher=fetch, image_persister=persist
        )
        result = await service.reconcile_job(job.id)
        assert result["changed"] is False
        await db.commit()
        first_round = False
        # Exercise reloading saved state, not just in-memory attempt objects.
        job_id = job.id
        db.expire_all()
        result = await service.reconcile_job(job_id)
        await db.refresh(task)
        assert result["status"] == "succeeded"
        assert task.status == "completed" and len(task.result_urls) == 4
        assert set(task.result_urls) == {f"/clean/{i}.png" for i in range(4)}


@pytest.mark.asyncio
async def test_reconciliation_dispatches_async_query_without_new_generation(
    monkeypatch,
):
    query = AsyncMock(return_value={"status": "generating", "image_urls": []})
    monkeypatch.setattr(AIImageProviderService, "get_upstream_task_status", query)
    result = await AIImageReconciliationService(None)._fetch_upstream_status(
        {
            "provider_id": 5,
            "upstream_task_id": "imgtask_recover",
            "query_capability": "openai_images_async",
            "expected_count": 1,
        }
    )
    assert result["status"] == "generating"
    query.assert_awaited_once_with(
        5, "imgtask_recover", expected_count=1, query_capability="openai_images_async"
    )


@pytest.mark.asyncio
async def test_unknown_second_dispatch_cannot_be_resolved_by_first_image(
    client, monkeypatch
):
    monkeypatch.setattr(settings, "ai_image_shadow_enabled", True)
    async with async_session() as db:
        attempt = {
            "upstream_task_id": "imgtask_first",
            "provider_id": 5,
            "provider_kind": "openai_images",
            "query_capability": "openai_images_async",
            "expected_count": 1,
        }
        task, job = await _seed_review_job(db, attempts=[attempt])
        task.params = {**task.params, "count": 2, "_async_submission_pending": True}
        await db.commit()
        fetch = AsyncMock(
            return_value={"status": "completed", "image_urls": ["/one.png"]}
        )
        result = await AIImageReconciliationService(
            db,
            status_fetcher=fetch,
            image_persister=AsyncMock(return_value=["/clean/one.png"]),
        ).reconcile_job(job.id)
        assert (
            result["result_certainty"] == "unknown"
            and result["requires_reconciliation"]
        )
        assert result["reconciliation"]["method"] == "manual_required"
        fetch.assert_awaited_once()
        assert task.result_urls == ["/clean/one.png"]


@pytest.mark.asyncio
async def test_double_cancellation_still_finishes_receipt_persistence():
    import asyncio
    from app.services.ai_image_service import (
        _complete_critical_write_before_cancellation,
    )

    started, finish, written = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def persist():
        started.set()
        await finish.wait()
        written.set()

    operation = asyncio.create_task(
        _complete_critical_write_before_cancellation(persist())
    )
    await started.wait()
    operation.cancel()
    await asyncio.sleep(0)
    operation.cancel()
    await asyncio.sleep(0)
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert written.is_set()


@pytest.mark.asyncio
async def test_pending_dispatch_is_saved_before_post_and_cleared_only_on_receipt(
    client, monkeypatch
):
    monkeypatch.setattr(settings, "ai_image_shadow_enabled", True)
    async with async_session() as db:
        await _seed_user(db)
        task = AITask(
            id=751,
            user_id=1,
            model_name="gptimage2",
            prompt="prompt",
            params={"count": 2},
            status="processing",
        )
        db.add(task)
        await db.commit()
        service = AIImageService(db=db)
        details = {
            "query_capability": "openai_images_async",
            "provider_id": 5,
            "provider_kind": "openai_images",
        }
        await service._mark_task_upstream_accepted(
            db, task.id, {**details, "submission_pending": True}
        )
        await db.refresh(task)
        assert task.params["_async_submission_pending"] is True
        await service._mark_task_upstream_accepted(
            db,
            task.id,
            {**details, "upstream_task_id": "imgtask_saved", "expected_count": 1},
        )
        await db.refresh(task)
        assert task.params["_async_submission_pending"] is False
        task.status = "cancelled"
        await db.commit()
        with pytest.raises(RuntimeError, match="取消"):
            await service._mark_task_upstream_accepted(
                db, task.id, {**details, "submission_pending": True}
            )
