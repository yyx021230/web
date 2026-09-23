from __future__ import annotations

import asyncio
import base64
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
import httpx

from app.adapters import storage as storage_module
from app.config import settings
from app.db.session import async_session, engine
from app.models.ai_image_provider import AIImageProvider
from app.models.ai_task import AITask
from app.models.user import User
from app.services import ai_image_provider_service as module
from app.services.ai_image_provider_service import AIImageProviderService
from app.services.ai_image_service import AIImageService
from app.services.ai_image_progress import definitely_not_dispatched, image_task_progress
from app.services.ai_task_queue import ai_image_postprocess_queue, ai_image_task_queue
from tests.conftest import make_auth_headers


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "timeout", "disable"])
async def test_waiting_task_finishes_without_an_upstream_request(client, monkeypatch, action):
    monkeypatch.setattr(settings, "ai_provider_wait_timeout_seconds", 1)
    monkeypatch.setattr(ai_image_task_queue, "enqueue_task", AsyncMock(return_value=True))
    monkeypatch.setattr(ai_image_task_queue, "remove_pending_task", AsyncMock())
    monkeypatch.setattr(ai_image_postprocess_queue, "remove_pending_task", AsyncMock())
    upstream = AsyncMock()
    monkeypatch.setattr(AIImageProviderService, "_call_provider", upstream)
    async with async_session() as seed:
        seed.add(User(id=81, username="wait_user", email="wait@example.test", hashed_password="x"))
        seed.add(provider(1))
        await seed.commit()
    module._PROVIDER_RUNNING[1] = 1
    headers = make_auth_headers(81)
    response = await client.post("/api/v1/ai-image/generate", headers=headers, json={
        "model": "gptimage2", "prompt": "do not send", "client_request_id": action,
    })
    assert response.status_code == 202
    task_id = int(response.json()["data"]["task_id"])
    entered = asyncio.Event()
    original_wait = AIImageService._mark_task_waiting

    async def observe_wait(self, *args, **kwargs):
        result = await original_wait(self, *args, **kwargs)
        entered.set()
        return result

    monkeypatch.setattr(AIImageService, "_mark_task_waiting", observe_wait)

    async def execute():
        async with async_session() as db:
            return await AIImageService(db=db).execute_submitted_task(task_id)

    running = asyncio.create_task(execute())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        progress = (await client.get(f"/api/v1/ai-image/tasks/{task_id}", headers=headers)).json()["data"]
        assert progress["progress"]["phase"] == "waiting_provider"
        if action == "cancel":
            cancelled = await client.post(f"/api/v1/ai-image/tasks/{task_id}/cancel", headers=headers)
            assert cancelled.status_code == 200
        elif action == "disable":
            async with async_session() as db:
                await AIImageProviderService(db).toggle_provider(1, False)
        await asyncio.wait_for(running, 3)
        response = (await client.get(f"/api/v1/ai-image/tasks/{task_id}", headers=headers)).json()["data"]
        assert response["status"] == ("cancelled" if action == "cancel" else "failed")
        if action == "timeout":
            assert "尚未发送到上游" in response["error"]
        upstream.assert_not_awaited()
        assert module._PROVIDER_RUNNING == {1: 1}
        async with async_session() as db:
            saved_provider = await db.get(AIImageProvider, 1)
            assert saved_provider.failure_count == 0
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("shadow_enabled", [False, True])
async def test_restart_recovers_only_proven_unsent_including_redis_orphans(client, monkeypatch, shadow_enabled):
    monkeypatch.setattr(settings, "ai_image_shadow_enabled", shadow_enabled)
    monkeypatch.setattr(ai_image_task_queue, "drain_processing_tasks", AsyncMock(return_value=[]))
    requeue = AsyncMock(return_value=1)
    monkeypatch.setattr(ai_image_task_queue, "requeue_drained_tasks", requeue)
    monkeypatch.setattr(ai_image_task_queue, "discard_tasks", AsyncMock())
    monkeypatch.setattr(ai_image_task_queue, "enqueue_missing_tasks", AsyncMock(return_value=0))
    params = [
        {"_routing": {"phase": "waiting_provider"}},
        {"_routing": {"phase": "preparing"}, "_upstream_dispatch_started_at": "2026-09-21T00:00:00"},
        {"_upstream_attempts": [{"upstream_task_id": "accepted-1"}]},
        {},
        {"provider": {"id": 1}},
    ]
    async with async_session() as db:
        db.add(User(id=81, username="restart_user", email="restart@example.test", hashed_password="x"))
        for index, item in enumerate(params, 1):
            db.add(AITask(id=index, user_id=81, model_name="gptimage2", prompt="no duplicate", status="processing", params=item))
        await db.commit()
        recovery = await AIImageService(db=db).recover_incomplete_tasks()
        assert recovery["reset_processing"] == 1
        assert recovery["waiting_review"] == 4
        requeue.assert_awaited_once_with([1])
        for index in range(2, 6):
            task = await db.get(AITask, index)
            assert task.status == "failed"
            assert image_task_progress(task.status, task.params)["phase"] == "review_required"
        assert definitely_not_dispatched((await db.get(AITask, 1)).params)


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type,calls", [(httpx.ReadTimeout, 1), (httpx.WriteError, 1), (httpx.ConnectError, 3)])
async def test_transport_failure_never_resends_possibly_accepted_post(error_type, calls):
    seen = []
    async def upstream(request):
        seen.append(request)
        raise error_type("isolated network failure", request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        with pytest.raises(error_type):
            await module._request_with_retries(client, "POST", "https://unused.invalid/images/generations", retries=3, retry_delay=0)
    assert len(seen) == calls


@pytest.mark.asyncio
async def test_provider_callback_cancellation_and_local_failure_never_send(client, monkeypatch):
    async with async_session() as db:
        db.add(provider(1))
        await db.commit()
        service = AIImageProviderService(db)
        upstream = AsyncMock()
        monkeypatch.setattr(service, "_call_provider", upstream)
        for callback in [AsyncMock(return_value=False), AsyncMock(side_effect=RuntimeError("db unavailable"))]:
            result = await service.generate("do not send", {}, on_provider_selected=callback)
            assert result["status"] in {"cancelled", "failed"}
            assert not result.get("result_unknown")
            assert module._PROVIDER_RUNNING == {}
        upstream.assert_not_awaited()
        assert (await db.get(AIImageProvider, 1)).failure_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type,unknown", [(httpx.ReadTimeout, True), (httpx.ConnectTimeout, False)])
async def test_routing_distinguishes_unsent_connection_failure_from_unknown_response(client, monkeypatch, error_type, unknown):
    async with async_session() as db:
        db.add(provider(1))
        await db.commit()
        service = AIImageProviderService(db)
        monkeypatch.setattr(service, "_call_provider", AsyncMock(side_effect=error_type("test transport failure")))
        result = await service.generate("no production request", {})
        assert result["status"] == "failed"
        assert result["result_unknown"] is unknown
        assert module._PROVIDER_RUNNING == {}


@pytest.mark.asyncio
async def test_provider_metrics_failure_keeps_completed_task(client, monkeypatch):
    async with async_session() as seed:
        seed.add(provider(1))
        seed.add(User(id=81, username="stats_user", email="stats@example.test", hashed_password="x"))
        seed.add(AITask(id=1, user_id=81, model_name="gptimage2", prompt="keep paid result", status="queued"))
        await seed.commit()
    upstream = AsyncMock(return_value={"status": "completed", "image_urls": ["/uploads/generated.png"]})
    monkeypatch.setattr(AIImageProviderService, "_call_provider", upstream)
    async def failed_metrics(self, *args):
        await self.db.rollback()  # SQL failures also expire identity-map objects.
        raise RuntimeError("metrics unavailable")
    monkeypatch.setattr(AIImageProviderService, "_mark_success", failed_metrics)
    monkeypatch.setattr(settings, "remove_ai_watermarks_enabled", False)
    async with async_session() as db:
        assert await AIImageService(db=db).execute_submitted_task(1) == "completed"
        task = await db.get(AITask, 1)
        assert task.result_urls == ["/uploads/generated.png"]
    upstream.assert_awaited_once()
    assert module._PROVIDER_RUNNING == {}


@pytest.mark.asyncio
async def test_waiters_above_connection_pool_capacity_leave_database_available(client):
    # pytest uses a new event loop per test; a saturated pool must be created
    # on this loop rather than reuse the previous test's asyncio Queue.
    await engine.dispose()
    async with async_session() as seed:
        seed.add(provider(1))
        await seed.commit()
    module._PROVIDER_RUNNING[1] = 1
    reached = set()
    all_waiting = asyncio.Event()
    release = asyncio.Event()

    async def wait(index):
        async with async_session() as db:
            async def on_wait(_details):
                assert not db.in_transaction()
                reached.add(index)
                if len(reached) == 36:
                    all_waiting.set()
                await release.wait()
                return False
            result = await AIImageProviderService(db).generate("pool safety", {}, on_routing_wait=on_wait)
            assert result["status"] == "cancelled"

    tasks = [asyncio.create_task(wait(index)) for index in range(36)]
    try:
        try:
            await asyncio.wait_for(all_waiting.wait(), 5)
        except asyncio.TimeoutError:
            errors = [repr(task.exception()) for task in tasks if task.done() and not task.cancelled()]
            pytest.fail(f"Only {len(reached)} waiters released their DB connection: {errors}")
        async with async_session() as admin:
            await asyncio.wait_for(AIImageProviderService(admin).toggle_provider(1, False), 2)
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 3)
    finally:
        release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await engine.dispose()


@pytest.mark.asyncio
async def test_watermark_failure_keeps_private_source_and_does_not_regenerate(client, monkeypatch):
    async with async_session() as seed:
        seed.add(User(id=81, username="wm_user", email="wm@example.test", hashed_password="x"))
        seed.add(AITask(id=1, user_id=81, model_name="gptimage2", prompt="preserve source",
                        status="postprocessing", params={"_postprocess_source_urls": ["/uploads/original.png"]}))
        await seed.commit()
    upstream = AsyncMock()
    monkeypatch.setattr(AIImageProviderService, "_call_provider", upstream)
    monkeypatch.setattr(AIImageService, "_remove_watermarks", AsyncMock(side_effect=RuntimeError("watermark unavailable")))
    async with async_session() as db:
        assert await AIImageService(db=db).execute_postprocessing_task(1) == "failed"
        task = await db.get(AITask, 1)
        assert task.params["_generated_source_urls"] == ["/uploads/original.png"]
        assert image_task_progress(task.status, task.params)["phase"] == "postprocess_failed"
    history = (await client.get("/api/v1/ai-image/history", headers=make_auth_headers(81))).json()["data"]["items"][0]
    assert history["result_urls"] == []
    assert "original.png" not in str(history)
    upstream.assert_not_awaited()


def provider(provider_id: int, **overrides) -> AIImageProvider:
    values = dict(
        id=provider_id,
        name=f"Isolated provider {provider_id}",
        model_name="gptimage2",
        provider_kind="openai_images",
        provider_model="gpt-image-2",
        endpoint_url="https://unused.invalid/v1",
        api_key="isolated-test-key",
        is_enabled=True,
        is_default=False,
        priority=100,
        weight=1,
        supports_text_input=True,
        supports_image_input=True,
        last_health_status="healthy",
        config={"max_concurrent": 1},
    )
    values.update(overrides)
    return AIImageProvider(**values)


@pytest.fixture(autouse=True)
def isolated_provider_runtime(monkeypatch):
    monkeypatch.setattr(module, "_PROVIDER_RUNNING", {})
    monkeypatch.setattr(module, "_PROVIDER_FAILURE_STREAK", {})
    monkeypatch.setattr(module, "_PROVIDER_SLOT_LOCK", asyncio.Lock())


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["enabled", "health", "circuit_recovery", "capacity", "image_input", "mode"])
async def test_waiting_generation_observes_admin_changes(client, monkeypatch, change):
    model = "gptimage25" if change == "mode" else "gptimage2"
    family = dict(model_name=model, provider_model="gpt-image-2.5-flare") if change == "mode" else {}
    alternate = provider(2, **family)
    updates = {}
    if change == "enabled":
        alternate.is_enabled = False
        updates = {"is_enabled": True}
    elif change in {"health", "circuit_recovery"}:
        alternate.last_health_status = "unhealthy"
        alternate.last_checked_at = datetime.utcnow()
        alternate.config = {"max_concurrent": 15}
        module._PROVIDER_RUNNING[2] = 1
        module._PROVIDER_FAILURE_STREAK[2] = 3 if change == "circuit_recovery" else 1
        updates = {"last_health_status": "healthy"}
    elif change == "capacity":
        module._PROVIDER_RUNNING[2] = 1
        updates = {"config": {"max_concurrent": 3}}
    elif change == "image_input":
        alternate.supports_image_input = False
        updates = {"supports_image_input": True}
    else:
        alternate.config = {"max_concurrent": 1, "generation_modes": ["fast"]}
        updates = {"config": {"max_concurrent": 1, "generation_modes": ["fast", "precision"]}}

    async with async_session() as seed:
        seed.add_all([provider(1, **family), alternate])
        await seed.commit()
    module._PROVIDER_RUNNING[1] = 1
    calls = []
    selected = []
    polled = asyncio.Event()
    params = {"images_data": ["/uploads/reference.png"], "generation_mode": "precision"}

    async def fake_upstream(chosen, prompt, params, **kwargs):
        calls.append((chosen.id, prompt, params))
        return {"task_id": "isolated-upstream", "status": "completed", "image_urls": ["/test/result.png"]}

    async def record_provider(meta):
        selected.append(meta)

    async with async_session() as waiting:
        service = AIImageProviderService(waiting)
        original_list = service.list_providers
        reads = 0

        async def observe_poll(model_name):
            nonlocal reads
            result = await original_list(model_name)
            reads += 1
            if reads >= 3:
                polled.set()
            return result

        monkeypatch.setattr(service, "list_providers", observe_poll)
        monkeypatch.setattr(service, "_call_provider", fake_upstream)
        task = asyncio.create_task(service.generate(
            "unchanged prompt", params, model_name=model, on_provider_selected=record_provider,
        ))
        try:
            await asyncio.wait_for(polled.wait(), 2)
            assert not task.done()
            assert calls == selected == []
            # A separate DB session represents an administrator changing the live entry.
            async with async_session() as admin:
                await AIImageProviderService(admin).update_provider(2, updates)
            result = await asyncio.wait_for(task, 2)
            assert result["status"] == "completed"
            assert result["provider"]["id"] == 2
            assert result["provider_configured"] is True
            assert calls == [(2, "unchanged prompt", params)]
            assert len(selected) == 1
            assert selected[0]["id"] == 2
            assert module._PROVIDER_RUNNING == ({1: 1, 2: 1} if change in {"health", "circuit_recovery", "capacity"} else {1: 1})
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async with async_session() as verify:
        saved = await verify.get(AIImageProvider, 2)
        assert saved.success_count == 1
        for key, value in updates.items():
            assert getattr(saved, key) == value


@pytest.mark.asyncio
async def test_twenty_waiters_respect_capacity_and_all_finish(client):
    async with async_session() as seed:
        seed.add(provider(1, config={"max_concurrent": 3}))
        await seed.commit()
    running = 0
    peak = 0
    completed = []

    async def work(index):
        nonlocal running, peak
        async with async_session() as db:
            service = AIImageProviderService(db)
            chosen = await service._acquire_provider_slot(
                model_name="gptimage2", has_reference=True, wait_interval=0.01,
            )
            running += 1
            peak = max(peak, running)
            try:
                assert chosen.id == 1
                assert module._PROVIDER_RUNNING[1] <= 3
                await asyncio.sleep(0.02)
                completed.append(index)
            finally:
                running -= 1
                await service._release_provider_slot(chosen.id)

    tasks = [asyncio.create_task(work(i)) for i in range(20)]
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
        assert peak == 3
        assert sorted(completed) == list(range(20))
        assert module._PROVIDER_RUNNING == {}
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_reduced_capacity_applies_to_cached_entry(client):
    async with async_session() as seed:
        seed.add(provider(1, config={"max_concurrent": 15}))
        await seed.commit()
    async with async_session() as db:
        service = AIImageProviderService(db)
        retained = await service.list_providers("gptimage2")
        assert retained[0].config["max_concurrent"] == 15
        async with async_session() as admin:
            await AIImageProviderService(admin).update_provider(1, {"config": {"max_concurrent": 1}})
        module._PROVIDER_RUNNING[1] = 1
        task = asyncio.create_task(service._acquire_provider_slot(
            model_name="gptimage2", has_reference=True, wait_interval=0.01,
        ))
        try:
            await asyncio.sleep(0.05)
            assert not task.done()
            await service._release_provider_slot(1)
            chosen = await asyncio.wait_for(task, 2)
            assert chosen.id == 1
            assert module._PROVIDER_RUNNING == {1: 1}
            await service._release_provider_slot(1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("model,lane,mode", [
    ("gptimage2", "interactive", "fast"),
    ("gptimage2", "batch", "fast"),
    ("gptimage25", "interactive", "fast"),
    ("gptimage25", "batch", "precision"),
])
async def test_submitted_task_resumes_after_admin_enables_entry(client, monkeypatch, tmp_path, model, lane, mode):
    png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aH1cAAAAASUVORK5CYII="
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    monkeypatch.setattr(settings, "remove_ai_watermarks_enabled", True)
    monkeypatch.setattr(settings, "ai_image_shadow_enabled", False)
    monkeypatch.setattr(storage_module, "_storage_instance", None)
    enqueue = AsyncMock(return_value=True)
    postprocess_enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(ai_image_task_queue, "enqueue_task", enqueue)
    monkeypatch.setattr(ai_image_postprocess_queue, "enqueue_task", postprocess_enqueue)
    family = dict(model_name=model, provider_model="gpt-image-2.5-flare") if model == "gptimage25" else {}
    async with async_session() as seed:
        seed.add(User(id=81, username="routing_admin", email="routing@example.test", hashed_password="x", role="admin"))
        seed.add_all([provider(1, **family), provider(2, is_enabled=False, **family)])
        await seed.commit()
    module._PROVIDER_RUNNING[1] = 1
    headers = make_auth_headers(81)
    body = {
        "model": model, "prompt": "isolated routing test", "client_request_id": "routing-recovery",
        "queue_lane": lane, "generation_mode": mode,
        "image_data": "data:image/png;base64," + png,
        "width": 1024, "height": 1024,
    }
    submitted = await client.post("/api/v1/ai-image/generate", headers=headers, json=body)
    assert submitted.status_code == 202
    task_id = int(submitted.json()["data"]["task_id"])
    duplicate = await client.post("/api/v1/ai-image/generate", headers=headers, json=body)
    assert int(duplicate.json()["data"]["task_id"]) == task_id
    enqueue.assert_awaited_once()
    assert enqueue.await_args.args == (task_id,)
    if lane == "batch":
        assert enqueue.await_args.kwargs == {"lane": "batch"}

    upstream_calls = []
    generation_release = asyncio.Event()
    upstream_started = asyncio.Event()
    polled = asyncio.Event()
    original_list = AIImageProviderService.list_providers
    reads = 0

    async def observe_poll(self, model_name=None):
        nonlocal reads
        items = await original_list(self, model_name)
        reads += 1
        if reads >= 4:
            polled.set()
        return items

    async def upstream(request):
        assert request.url.host == "unused.invalid"
        assert request.url.path == "/v1/images/edits"
        content = await request.aread()
        expected = "gpt-image-2" if model == "gptimage2" else module._GPT_IMAGE_25_MODELS[mode]
        assert expected.encode() in content
        assert base64.b64decode(png) in content
        upstream_calls.append(request.url.path)
        upstream_started.set()
        await generation_release.wait()
        return httpx.Response(200, json={"id": "test-only-upstream", "data": [{"b64_json": png}]})

    real_client = httpx.AsyncClient
    def isolated_http_client(*args, **kwargs):
        return real_client(*args, **kwargs, transport=httpx.MockTransport(upstream))

    async def postprocess(self, urls):
        for url in urls:
            assert (tmp_path / url.removeprefix("/uploads/")).read_bytes() == base64.b64decode(png)
        return urls

    monkeypatch.setattr(AIImageProviderService, "list_providers", observe_poll)
    monkeypatch.setattr(module.httpx, "AsyncClient", isolated_http_client)
    monkeypatch.setattr(AIImageService, "_remove_watermarks", postprocess)

    async def execute():
        async with async_session() as db:
            return await AIImageService(model_name=model, db=db).execute_submitted_task(task_id)

    running = asyncio.create_task(execute())
    try:
        await asyncio.wait_for(polled.wait(), 2)
        assert upstream_calls == []
        before = await client.get(f"/api/v1/admin/resources/ai-tasks/{task_id}", headers=headers)
        assert before.status_code == 200
        assert before.json()["data"]["provider_name"] is None
        waiting = (await client.get(f"/api/v1/ai-image/tasks/{task_id}", headers=headers)).json()["data"]
        assert waiting["progress"]["phase"] == "waiting_provider"
        assert "并发已满" in waiting["progress"]["message"]
        enabled = await client.post("/api/v1/admin/ai-image/providers/2/enable", headers=headers, json={"is_enabled": True})
        assert enabled.status_code == 200
        await asyncio.wait_for(upstream_started.wait(), 2)
        during = await client.get(f"/api/v1/admin/resources/ai-tasks/{task_id}", headers=headers)
        assert during.json()["data"]["provider_name"] == "Isolated provider 2"
        entries = (await client.get(f"/api/v1/admin/ai-image/providers?model_name={model}", headers=headers)).json()["data"]
        assert next(entry for entry in entries if entry["id"] == 2)["current_running"] == 1
        submitted_progress = (await client.get(f"/api/v1/ai-image/tasks/{task_id}", headers=headers)).json()["data"]
        assert submitted_progress["progress"]["phase"] == "submitting"
        generation_release.set()
        assert await asyncio.wait_for(running, 3) == "postprocessing"
        postprocess_enqueue.assert_awaited_once_with(task_id)
        assert module._PROVIDER_RUNNING == {1: 1}
        async with async_session() as db:
            assert await AIImageService(db=db).execute_postprocessing_task(task_id) == "completed"
        response = await client.get(f"/api/v1/ai-image/tasks/{task_id}", headers=headers)
        assert response.json()["data"]["status"] == "completed"
        assert response.json()["data"]["progress"]["phase"] == "completed"
        entries = (await client.get(f"/api/v1/admin/ai-image/providers?model_name={model}", headers=headers)).json()["data"]
        assert next(entry for entry in entries if entry["id"] == 2)["current_running"] == 0
        assert len(response.json()["data"]["image_urls"]) == 1
        assert upstream_calls == ["/v1/images/edits"]
        async with async_session() as db:
            saved = await db.get(AITask, task_id)
            assert saved.params["provider"]["id"] == 2
            assert saved.params["_queue_lane"] == lane
            assert saved.finished_at is not None
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)

@pytest.mark.asyncio
@pytest.mark.parametrize("updates", [
    {"is_enabled": False},
    {"supports_image_input": False},
    {"config": {"max_concurrent": 1, "generation_modes": ["fast"]}},
])
async def test_waiter_does_not_use_entry_made_ineligible(client, updates):
    async with async_session() as seed:
        seed.add(provider(1, model_name="gptimage25", provider_model="gpt-image-2.5-flare"))
        await seed.commit()
    async with async_session() as waiting:
        service = AIImageProviderService(waiting)
        cached = await service.list_providers("gptimage25")
        assert cached[0].is_enabled
        async with async_session() as admin:
            await AIImageProviderService(admin).update_provider(1, updates)
        selected = await service._acquire_provider_slot(
            model_name="gptimage25", has_reference=True, generation_mode="precision",
        )
        assert selected is None
        assert module._PROVIDER_RUNNING == {}


@pytest.mark.asyncio
async def test_cancel_waiting_generation_never_calls_upstream_or_leaks_slot(client, monkeypatch):
    async with async_session() as seed:
        seed.add(provider(1))
        await seed.commit()
    module._PROVIDER_RUNNING[1] = 1
    async with async_session() as db:
        service = AIImageProviderService(db)
        upstream = AsyncMock()
        monkeypatch.setattr(service, "_call_provider", upstream)
        task = asyncio.create_task(service.generate("cancelled", {}))
        await asyncio.sleep(0.05)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        upstream.assert_not_called()
        assert module._PROVIDER_RUNNING == {1: 1}


@pytest.mark.asyncio
async def test_cancel_during_provider_callback_releases_slot(client, monkeypatch):
    async with async_session() as seed:
        seed.add(provider(1))
        await seed.commit()
    entered = asyncio.Event()

    async def slow_callback(meta):
        entered.set()
        await asyncio.Event().wait()

    async with async_session() as db:
        service = AIImageProviderService(db)
        upstream = AsyncMock()
        monkeypatch.setattr(service, "_call_provider", upstream)
        task = asyncio.create_task(service.generate("cancelled", {}, on_provider_selected=slow_callback))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            upstream.assert_not_called()
            assert module._PROVIDER_RUNNING == {}
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
