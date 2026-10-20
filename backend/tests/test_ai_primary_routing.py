from __future__ import annotations

import asyncio
import base64
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.config import settings
from app.db.session import async_session
from app.models.ai_image_provider import AIImageProvider
from app.models.ai_task import AITask
from app.models.user import User
from app.adapters import storage as storage_module
from app.services import ai_provider_routing as routing
from app.services.ai_image_provider_service import AIImageProviderService, UpstreamProviderError
from app.services.ai_image_service import AIImageService
from app.services.ai_image_progress import definitely_not_dispatched, image_task_progress
from app.services.ai_task_queue import ai_image_task_queue, ai_image_postprocess_queue
from tests.conftest import make_auth_headers


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 4])
@pytest.mark.parametrize(
    "failure,expected_calls,unknown",
    [(429, [1, 1, 2], False), (401, [1, 1, 2], False),
     ("connect", [1, 1, 2], False), (400, [1], False),
     ("read", [1], True), (502, [1], True),
     ("terminal", [1, 1, 2], False), ("success", [1], False)],
)
async def test_combined_async_protocol_and_primary_routing(
    shared_router, monkeypatch, count, failure, expected_calls, unknown,
):
    items = [
        provider(i, endpoint_url=f"https://provider-{i}.test/v1",
                 config={"max_concurrent": 1, "api_mode": "sub2api_async",
                         "async_poll_interval": 0.001, "async_max_polls": 2})
        for i in (1, 2)
    ]
    service = service_for(items)
    service._call_provider = AIImageProviderService._call_provider.__get__(service)
    service._extract_image_urls = AsyncMock(side_effect=lambda item, data, seed: [f"/uploads/{seed}.png"])
    calls, gets, receipts = [], [], []

    def respond(request):
        number = 1 if request.url.host == "provider-1.test" else 2
        if request.method == "POST":
            calls.append(number)
            assert request.url.path == "/v1/images/generations/async"
            if number == 1:
                if failure == "connect":
                    raise httpx.ConnectError("not sent", request=request)
                if failure == "read":
                    raise httpx.ReadTimeout("unknown receipt", request=request)
                if isinstance(failure, int):
                    return httpx.Response(failure, json={"error": "test failure"})
            return httpx.Response(202, json={"task_id": f"img_{number}_{len(calls)}"})
        gets.append(str(request.url))
        task_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={
            "task_id": task_id,
            "status": "failed" if number == 1 and failure == "terminal" else "completed",
            "error": "known final failure",
            "result": {"data": [{"url": "/uploads/async.png"}]},
        })

    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(respond),
    ))

    async def accepted(details):
        receipts.append(details)

    completed = expected_calls[-1] == 2 or failure == "success"
    result = await service.generate("test", {"count": count}, on_upstream_accepted=accepted)
    assert calls == expected_calls + ([expected_calls[-1]] * (count - 1) if completed else [])
    assert bool(result.get("result_unknown")) is unknown
    assert result["status"] == ("completed" if completed else "failed")
    if completed:
        assert len(result["image_urls"]) == count
        assert gets and any(item.get("upstream_task_id") for item in receipts)
    if failure == 400:
        service._mark_failure.assert_not_awaited()


@pytest_asyncio.fixture
async def shared_router(monkeypatch):
    executable = shutil.which("redis-server")
    if not executable:
        pytest.skip("isolated redis-server is required for Lua/cross-client routing verification")
    with tempfile.TemporaryDirectory(prefix="ai-route-", dir="/tmp") as directory:
        socket = str(Path(directory) / "redis.sock")
        process = subprocess.Popen(
            [executable, "--port", "0", "--unixsocket", socket, "--unixsocketperm", "700",
             "--save", "", "--appendonly", "no", "--dir", directory],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        redis = Redis(unix_socket_path=socket, decode_responses=True)
        try:
            for _ in range(150):
                try:
                    if await redis.ping():
                        break
                except RedisConnectionError:
                    pass
                await asyncio.sleep(0.02)
            else:
                pytest.fail("isolated Redis did not start")
            real_router = routing.SharedProviderRouter
            monkeypatch.setattr(routing, "SharedProviderRouter", lambda model: real_router(model, redis=redis))
            monkeypatch.setattr(settings, "ai_provider_primary_routing_enabled", True)
            monkeypatch.setattr(settings, "ai_provider_recovery_probe_seconds", 1)
            monkeypatch.setattr(settings, "ai_provider_wait_timeout_seconds", 4)
            yield real_router("gptimage2", redis=redis)
        finally:
            await redis.aclose()
            process.terminate()
            process.wait(timeout=5)


def provider(number=1, **changes):
    values = dict(
        id=number, name=f"provider-{number}", model_name="gptimage2",
        provider_kind="openai_images", provider_model="gpt-image-2",
        endpoint_url="https://example.test/v1", api_key="fake-test-key",
        is_default=number == 1, is_enabled=True, priority=number * 10, weight=1,
        supports_text_input=True, supports_image_input=True, config={"max_concurrent": 1},
    )
    return AIImageProvider(**{**values, **changes})


def service_for(providers, response=None):
    service = AIImageProviderService(SimpleNamespace(rollback=AsyncMock()))
    service.list_providers = AsyncMock(side_effect=lambda _: providers)
    service._mark_success = AsyncMock()
    service._mark_failure = AsyncMock()
    service._call_provider = AsyncMock(return_value=response or {
        "status": "completed", "image_urls": ["/uploads/test.png"],
    })
    return service


async def open_circuit(router, item):
    for _ in range(2):
        lease = await router.acquire([item], lease_seconds=60)
        await router.finish(lease, "failure")


@pytest.mark.asyncio
async def test_primary_busy_never_spills_and_first_failure_is_retried(shared_router):
    items = [provider(), provider(2)]
    primary = await shared_router.acquire(items, lease_seconds=60)
    assert primary["id"] == 1
    assert (await shared_router.acquire(items, lease_seconds=60))["reason"] == "capacity"
    await shared_router.finish(primary, "failure")
    second = await shared_router.acquire(items, lease_seconds=60)
    assert second["id"] == 1
    await shared_router.finish(second, "failure")
    standby = await shared_router.acquire(items, lease_seconds=60)
    assert standby["id"] == 2


@pytest.mark.asyncio
async def test_success_between_failures_resets_and_repeated_finish_is_idempotent(shared_router):
    item = provider()
    for outcome in ["failure", "success", "failure"]:
        lease = await shared_router.acquire([item], lease_seconds=60)
        await shared_router.finish(lease, outcome)
        await shared_router.finish(lease, outcome)
    assert await shared_router.redis.hget(f"{shared_router.key}:state:1", "failures") == "1"
    assert (await shared_router.acquire([item], lease_seconds=60))["id"] == 1


@pytest.mark.asyncio
async def test_two_independent_clients_share_capacity_and_single_recovery_probe(shared_router):
    other_redis = Redis(connection_pool=shared_router.redis.connection_pool)
    other = type(shared_router)("gptimage2", redis=other_redis)
    items = [provider(config={"max_concurrent": 3}), provider(2, config={"max_concurrent": 100})]
    leases = await asyncio.gather(*[
        (shared_router if index % 2 else other).acquire(items, lease_seconds=60)
        for index in range(20)
    ])
    held = [lease for lease in leases if lease.get("id") == 1]
    assert len(held) == 3
    assert not any(lease.get("id") == 2 for lease in leases)
    for lease in held:
        await shared_router.finish(lease, "neutral")
    await open_circuit(shared_router, items[0])
    await shared_router.redis.hset(f"{shared_router.key}:state:1", "retry_at", 0)
    leases = await asyncio.gather(*[
        (shared_router if index % 2 else other).acquire(items, lease_seconds=60)
        for index in range(20)
    ])
    assert len([lease for lease in leases if lease.get("id") == 1]) == 1
    probe = next(lease for lease in leases if lease.get("id") == 1)
    assert probe["probe"] is True
    await other.finish(probe, "success")
    assert (await other.acquire(items, lease_seconds=60))["id"] == 1
    await other_redis.aclose()


@pytest.mark.asyncio
async def test_late_pre_failure_success_does_not_close_circuit(shared_router):
    item = provider(config={"max_concurrent": 2})
    older = await shared_router.acquire([item], lease_seconds=60)
    failed = await shared_router.acquire([item], lease_seconds=60)
    await shared_router.finish(failed, "failure")
    await shared_router.finish(older, "success")
    retry = await shared_router.acquire([item], lease_seconds=60)
    await shared_router.finish(retry, "failure")
    assert (await shared_router.acquire([item], lease_seconds=60))["reason"] == "cooldown"


@pytest.mark.asyncio
async def test_concurrent_failures_open_without_waiting_for_other_inflight_calls(shared_router):
    items = [provider(config={"max_concurrent": 3}), provider(2)]
    held = [await shared_router.acquire(items, lease_seconds=60) for _ in range(3)]
    await shared_router.finish(held[0], "failure")
    retry = await shared_router.acquire(items, lease_seconds=60)
    assert retry["id"] == 1
    await shared_router.finish(held[1], "failure")
    assert (await shared_router.acquire(items, lease_seconds=60))["id"] == 2
    await shared_router.finish(held[2], "success")
    await shared_router.finish(retry, "success")
    assert await shared_router.redis.hget(f"{shared_router.key}:state:1", "failures") == "2"


@pytest.mark.asyncio
async def test_expired_lease_cannot_reset_new_owner(shared_router):
    item = provider()
    old = await shared_router.acquire([item], lease_seconds=60)
    await shared_router.redis.zadd(f"{shared_router.key}:slots:1", {old["token"]: 0})
    new = await shared_router.acquire([item], lease_seconds=60)
    await shared_router.finish(old, "failure")
    assert (await shared_router.acquire([item], lease_seconds=60))["reason"] == "capacity"
    await shared_router.finish(new, "success")


@pytest.mark.asyncio
async def test_pipeline_tries_primary_twice_then_standby(shared_router):
    service = service_for([provider(), provider(2)])
    service._call_provider.side_effect = [
        httpx.ConnectError("unsent-1"), httpx.ConnectTimeout("unsent-2"),
        {"status": "completed", "image_urls": ["/uploads/standby.png"]},
    ]
    evidence = AsyncMock()
    result = await service.generate("test", {}, on_attempt_finished=evidence)
    assert result["status"] == "completed"
    assert [call.args[0].id for call in service._call_provider.await_args_list] == [1, 1, 2]
    assert [call.args[0]["safe_to_retry"] for call in evidence.await_args_list] == [True, True, False]
    assert service._mark_failure.await_count == 2


@pytest.mark.asyncio
async def test_generation_duration_does_not_start_recovery_wait_budget(shared_router, monkeypatch):
    monkeypatch.setattr(settings, "ai_provider_wait_timeout_seconds", 1)
    clock = [time.time()]
    monkeypatch.setattr(routing, "time", SimpleNamespace(time=lambda: clock[0], monotonic=time.monotonic))
    service = service_for([provider(), provider(2)])
    calls = []

    async def slow_failure(item, *_args, **_kwargs):
        calls.append(item.id)
        clock[0] += 20
        if item.id == 1:
            raise httpx.ConnectTimeout("definitely unsent")
        return {"status": "completed", "image_urls": ["/uploads/standby.png"]}

    service._call_provider.side_effect = slow_failure
    result = await service.generate("allow both primary attempts", {})
    assert result["status"] == "completed"
    assert calls == [1, 1, 2]


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    httpx.ReadTimeout("unknown"),
    UpstreamProviderError("gateway", {"status_code": 502}),
    UpstreamProviderError("disconnected", {"status_code": 499}),
    UpstreamProviderError("bad success payload", {"status_code": 200}),
    UpstreamProviderError("unknown", result_unknown=True),
])
async def test_unknown_never_resubmits(shared_router, error):
    service = service_for([provider(), provider(2)])
    service._call_provider.side_effect = error
    result = await service.generate("test", {})
    assert result["result_unknown"] is True
    service._call_provider.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 422])
async def test_input_failure_does_not_trip_provider(shared_router, status):
    service = service_for([provider(), provider(2)])
    service._call_provider.side_effect = UpstreamProviderError("input rejected", {"status_code": status})
    result = await service.generate("test", {})
    assert result["status"] == "failed"
    service._call_provider.assert_awaited_once()
    service._mark_failure.assert_not_awaited()
    assert not await shared_router.redis.hget(f"{shared_router.key}:state:1", "failures")


@pytest.mark.asyncio
async def test_partial_images_are_preserved_without_any_retry(shared_router):
    service = service_for([provider(), provider(2)], {"status": "completed", "image_urls": ["/uploads/paid.png"]})
    result = await service.generate("four images", {"count": 4})
    assert result["status"] == "failed"
    assert result["image_urls"] == ["/uploads/paid.png"]
    service._call_provider.assert_awaited_once()


@pytest.mark.asyncio
async def test_all_failed_wait_then_primary_probe_recovers_same_task(shared_router):
    items = [provider(), provider(2)]
    service = service_for(items)
    seen = []

    async def generate(item, *_args, **_kwargs):
        seen.append(item.id)
        if len(seen) <= 4:
            raise httpx.ConnectError("unsent")
        return {"status": "completed", "image_urls": ["/uploads/recovered.png"]}

    service._call_provider.side_effect = generate
    wait = AsyncMock(return_value=True)
    result = await service.generate("recover", {}, on_routing_wait=wait)
    assert result["status"] == "completed"
    assert seen == [1, 1, 2, 2, 1]
    assert any(call.args[0]["reason"] == "cooldown" for call in wait.await_args_list)
    assert result["routing_attempts"][-1]["probe"] is True


@pytest.mark.asyncio
async def test_all_failed_wait_is_bounded_and_cancellable(shared_router, monkeypatch):
    monkeypatch.setattr(settings, "ai_provider_wait_timeout_seconds", 1)
    items = [provider(), provider(2)]
    for item in items:
        await open_circuit(shared_router, item)
        await shared_router.redis.hset(f"{shared_router.key}:state:{item.id}", "retry_at", time.time() + 100)
    service = service_for(items)
    waits = AsyncMock(return_value=True)
    result = await service.generate("wait", {}, on_routing_wait=waits)
    assert "超过 1 秒" in result["error"]
    assert not result["result_unknown"]
    service._call_provider.assert_not_awaited()
    assert len({call.args[0]["deadline"] for call in waits.await_args_list}) == 1
    result = await service.generate("cancel", {}, on_routing_wait=AsyncMock(return_value=False))
    assert result["status"] == "cancelled"


@pytest.mark.asyncio
async def test_restart_deadline_does_not_refresh_budget(shared_router):
    service = service_for([provider()])
    result = await service.generate("expired", {"_provider_routing_deadline": time.time() - 1})
    assert result["status"] == "failed"
    service._call_provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_redis_unavailable_waits_and_never_falls_back_to_local(shared_router, monkeypatch):
    monkeypatch.setattr(type(shared_router), "acquire", AsyncMock(side_effect=RedisConnectionError("unavailable")))
    service = service_for([provider(), provider(2)])
    waiting = AsyncMock(return_value=False)
    result = await service.generate("safe", {}, on_routing_wait=waiting)
    assert result["status"] == "cancelled"
    assert waiting.await_args.args[0]["reason"] == "routing_unavailable"
    service._call_provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancelled_probe_releases_slot_but_does_not_claim_healthy(shared_router):
    item = provider()
    await open_circuit(shared_router, item)
    await shared_router.redis.hset(f"{shared_router.key}:state:1", "retry_at", 0)
    service = service_for([item])
    result = await service.generate("cancelled", {}, on_provider_selected=AsyncMock(return_value=False))
    assert result["status"] == "cancelled"
    service._call_provider.assert_not_awaited()
    assert await shared_router.redis.zcard(f"{shared_router.key}:slots:1") == 0
    assert await shared_router.redis.hget(f"{shared_router.key}:state:1", "failures") == "2"


@pytest.mark.asyncio
async def test_cancellation_in_flight_does_not_leave_slot(shared_router):
    started = asyncio.Event()
    service = service_for([provider()])

    async def block(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    service._call_provider.side_effect = block
    task = asyncio.create_task(service.generate("cancel", {}))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await shared_router.redis.zcard(f"{shared_router.key}:slots:1") == 0


@pytest.mark.asyncio
async def test_configuration_reloaded_while_waiting_and_capability_filtering(shared_router):
    items = [provider(supports_image_input=False), provider(2)]
    service = service_for(items)
    image = await service.generate("image", {"image_url": "/uploads/ref.png"})
    assert image["provider"]["id"] == 2
    held = await shared_router.acquire(items, lease_seconds=60)

    async def change(_details):
        items[0].is_enabled = False
        return True

    result = await service.generate("dynamic", {}, on_routing_wait=change)
    assert result["provider"]["id"] == 2
    await shared_router.finish(held, "neutral")


@pytest.mark.asyncio
async def test_25_mode_uses_only_compatible_provider(shared_router):
    items = [
        provider(model_name="gptimage25", provider_model="gpt-image-2.5-flare",
                 config={"generation_modes": ["fast"]}),
        provider(2, model_name="gptimage25", provider_model="gpt-image-2.5-sunburst",
                 config={"generation_modes": ["precision"]}),
    ]
    result = await service_for(items).generate("precision", {"generation_mode": "precision"}, model_name="gptimage25")
    assert result["provider"]["id"] == 2
    assert result["provider"]["provider_model"] == "gpt-image-2.5-sunburst"


@pytest.mark.asyncio
async def test_failed_attempt_evidence_stops_retry_but_keeps_success(shared_router):
    service = service_for([provider(), provider(2)])
    result = await service.generate("keep", {}, on_attempt_finished=AsyncMock(side_effect=RuntimeError("db")))
    assert result["image_urls"] == ["/uploads/test.png"]
    service._call_provider.side_effect = httpx.ConnectError("unsent")
    service._call_provider.reset_mock()
    result = await service.generate("stop", {}, on_attempt_finished=AsyncMock(side_effect=RuntimeError("db")))
    assert result["status"] == "failed"
    service._call_provider.assert_awaited_once()


@pytest.mark.asyncio
async def test_safe_attempt_is_persisted_and_restartable_only_until_next_dispatch(client, shared_router):
    async with async_session() as db:
        db.add(AITask(id=8801, user_id=1, model_name="gptimage2", prompt="test", status="processing",
                      params={"provider": {"id": 1}, "_upstream_dispatch_started_at": "test",
                              "_upstream_attempts": [{"upstream_task_id": "already-failed"}]}))
        await db.commit()
        service = AIImageService(db=db)
        deadline = time.time() + 100
        await service._mark_provider_attempt_finished(8801, {
            "provider_id": 1, "safe_to_retry": True, "result_unknown": False, "deadline": deadline,
        })
        await db.refresh(await db.get(AITask, 8801))
        task = await db.get(AITask, 8801)
        assert definitely_not_dispatched(task.params)
        assert task.params["_provider_routing_deadline"] == deadline
        assert task.params["_upstream_attempts"][0]["upstream_task_id"] == "already-failed"
        assert await service._mark_task_provider(db, 8801, {"id": 2})
        assert not definitely_not_dispatched(task.params)
        assert task.params["_routing_last_attempt_safe"] is False


def test_waiting_messages_explain_recovery():
    for reason in ["cooldown", "routing_unavailable"]:
        assert "恢复" in image_task_progress("processing", {"_routing": {
            "phase": "waiting_provider", "reason": reason,
        }})["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("model,lane,count", [
    ("gptimage2", "interactive", 1), ("gptimage25", "batch", 4),
])
async def test_submit_worker_failover_postprocess_and_poll_same_task(
    client, shared_router, monkeypatch, tmp_path, model, lane, count,
):
    png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aH1cAAAAASUVORK5CYII="
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    monkeypatch.setattr(settings, "remove_ai_watermarks_enabled", True)
    monkeypatch.setattr(settings, "ai_image_shadow_enabled", False)
    monkeypatch.setattr(storage_module, "_storage_instance", None)
    enqueue = AsyncMock(return_value=True)
    postprocess = AsyncMock(return_value=True)
    monkeypatch.setattr(ai_image_task_queue, "enqueue_task", enqueue)
    monkeypatch.setattr(ai_image_postprocess_queue, "enqueue_task", postprocess)
    family = {"model_name": model, "provider_model": "gpt-image-2.5-flare"} if model == "gptimage25" else {}
    async with async_session() as db:
        db.add(User(id=81, username="primary_test", email="primary@example.test", hashed_password="x", role="admin"))
        db.add_all([
            provider(1, endpoint_url="https://primary.test/v1", config={"send_n": True}, **family),
            provider(2, endpoint_url="https://standby.test/v1", config={"send_n": True}, **family),
        ])
        await db.commit()
    body = {
        "model": model, "prompt": "isolated reference generation", "client_request_id": "primary-end-to-end",
        "queue_lane": lane, "image_data": "data:image/png;base64," + png,
        "generation_mode": "fast", "width": 1024, "height": 1024,
        "count": count,
    }
    headers = make_auth_headers(81)
    response = await client.post("/api/v1/ai-image/generate", headers=headers, json=body)
    assert response.status_code == 202
    task_id = int(response.json()["data"]["task_id"])
    duplicate = await client.post("/api/v1/ai-image/generate", headers=headers, json=body)
    assert int(duplicate.json()["data"]["task_id"]) == task_id
    enqueue.assert_awaited_once()
    calls = []

    async def upstream(request):
        assert request.url.host in {"primary.test", "standby.test"}
        assert request.url.path == "/v1/images/edits"
        assert base64.b64decode(png) in await request.aread()
        calls.append(request.url.host)
        if request.url.host == "primary.test":
            return httpx.Response(429, json={"error": "overloaded"})
        return httpx.Response(200, json={"data": [{"b64_json": png} for _ in range(count)]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: real_client(
        *a, **kw, transport=httpx.MockTransport(upstream),
    ))

    async def cleanup(self, urls):
        for url in urls:
            assert (tmp_path / url.removeprefix("/uploads/")).read_bytes() == base64.b64decode(png)
        return urls

    monkeypatch.setattr(AIImageService, "_remove_watermarks", cleanup)
    async with async_session() as db:
        assert await AIImageService(model_name=model, db=db).execute_submitted_task(task_id) == "postprocessing"
    postprocess.assert_awaited_once_with(task_id)
    async with async_session() as db:
        assert await AIImageService(db=db).execute_postprocessing_task(task_id) == "completed"
        saved = await db.get(AITask, task_id)
        assert saved.params["_queue_lane"] == lane
        attempts = saved.params["_provider_routing_attempts"]
        assert [entry["provider_id"] for entry in attempts] == [1, 1, 2]
        assert saved.params["provider"]["id"] == 2
    response = await client.get(f"/api/v1/ai-image/tasks/{task_id}", headers=headers)
    assert response.json()["data"]["status"] == "completed"
    assert len(response.json()["data"]["image_urls"]) == count
    assert calls == ["primary.test", "primary.test", "standby.test"]


@pytest.mark.asyncio
async def test_accepted_terminal_failure_can_retry_but_pending_cannot(shared_router):
    service = service_for([provider(), provider(2)])
    seen = []

    async def generate(item, *_args, on_upstream_accepted=None, **_kwargs):
        seen.append(item.id)
        await on_upstream_accepted({"upstream_task_id": f"fake-{len(seen)}", "provider_id": item.id})
        if len(seen) <= 2:
            return {"status": "failed", "raw_status": "failed", "task_id": f"fake-{len(seen)}",
                    "image_urls": [], "result_unknown": False, "error": "confirmed failure"}
        return {"status": "completed", "image_urls": ["/uploads/result.png"]}

    service._call_provider.side_effect = generate
    result = await service.generate("known terminal", {}, on_upstream_accepted=AsyncMock())
    assert result["status"] == "completed"
    assert seen == [1, 1, 2]


@pytest.mark.asyncio
async def test_local_pool_exhaustion_does_not_switch_to_paid_standby(shared_router):
    service = service_for([provider(), provider(2)])
    service._call_provider.side_effect = [
        httpx.PoolTimeout("local pool full"), httpx.PoolTimeout("still full"),
        {"status": "completed", "image_urls": ["/uploads/local.png"]},
    ]
    result = await service.generate("stay on primary", {})
    assert result["status"] == "completed"
    assert [call.args[0].id for call in service._call_provider.await_args_list] == [1, 1, 1]
    service._mark_failure.assert_not_awaited()


@pytest.mark.asyncio
async def test_shared_state_write_failure_preserves_result_and_disallows_retry(shared_router, monkeypatch):
    monkeypatch.setattr(type(shared_router), "finish", AsyncMock(side_effect=RedisConnectionError("lost")))
    service = service_for([provider(config={"max_concurrent": 2}), provider(2)])
    result = await service.generate("retain image", {})
    assert result["status"] == "completed"
    assert result["image_urls"] == ["/uploads/test.png"]
    service._call_provider.reset_mock()
    service._call_provider.side_effect = httpx.ConnectError("not submitted")
    result = await service.generate("stop retry", {})
    assert result["status"] == "failed"
    service._call_provider.assert_awaited_once()


@pytest.mark.asyncio
async def test_all_failed_wait_then_timeout_is_observable_via_user_api(client, shared_router, monkeypatch):
    monkeypatch.setattr(settings, "ai_provider_wait_timeout_seconds", 1)
    for item in [provider(), provider(2)]:
        await open_circuit(shared_router, item)
        await shared_router.redis.hset(f"{shared_router.key}:state:{item.id}", "retry_at", time.time() + 100)
    monkeypatch.setattr(ai_image_task_queue, "enqueue_task", AsyncMock(return_value=True))
    upstream = AsyncMock()
    monkeypatch.setattr(AIImageProviderService, "_call_provider", upstream)
    async with async_session() as db:
        db.add(User(id=81, username="wait_primary", email="waitprimary@example.test", hashed_password="x"))
        db.add_all([provider(), provider(2)])
        await db.commit()
    headers = make_auth_headers(81)
    response = await client.post("/api/v1/ai-image/generate", headers=headers, json={
        "model": "gptimage2", "prompt": "wait without duplication", "client_request_id": "wait-recovery",
    })
    assert response.status_code == 202
    task_id = int(response.json()["data"]["task_id"])
    entered = asyncio.Event()
    original_wait = AIImageService._mark_task_waiting

    async def observe(self, *args, **kwargs):
        result = await original_wait(self, *args, **kwargs)
        entered.set()
        return result

    monkeypatch.setattr(AIImageService, "_mark_task_waiting", observe)

    async def run():
        async with async_session() as db:
            return await AIImageService(db=db).execute_submitted_task(task_id)

    running = asyncio.create_task(run())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        data = (await client.get(f"/api/v1/ai-image/tasks/{task_id}", headers=headers)).json()["data"]
        assert data["status"] == "processing"
        assert data["progress"]["phase"] == "waiting_provider"
        assert "等待恢复" in data["progress"]["message"]
        assert await asyncio.wait_for(running, 3) == "failed"
        data = (await client.get(f"/api/v1/ai-image/tasks/{task_id}", headers=headers)).json()["data"]
        assert data["status"] == "failed"
        assert "超过 1 秒" in data["error"]
        assert data["progress"]["phase"] != "review_required"
        upstream.assert_not_awaited()
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
async def test_repeated_cooldown_after_a_failed_probe_refreshes_progress(client, shared_router, monkeypatch):
    async with async_session() as db:
        db.add(provider())
        db.add(AITask(id=8802, user_id=1, model_name="gptimage2", prompt="repeat wait",
                      status="processing", params={}))
        await db.commit()

        async def repeated_cycle(_self, **kwargs):
            deadline = time.time() + 10
            await kwargs["on_routing_wait"]({"reason": "cooldown", "deadline": deadline})
            await kwargs["on_provider_selected"]({"id": 1})
            await kwargs["on_attempt_finished"]({
                "provider_id": 1, "safe_to_retry": True, "result_unknown": False, "deadline": deadline,
            })
            await kwargs["on_routing_wait"]({"reason": "cooldown", "deadline": deadline})
            return {"status": "failed", "image_urls": [], "provider_configured": True}

        monkeypatch.setattr(AIImageProviderService, "generate", repeated_cycle)
        await AIImageService(model_name="gptimage2", db=db)._generate_with_configured_provider(
            "repeat wait", {}, task_id=8802,
        )
        db.expire_all()
        saved = await db.get(AITask, 8802)
        assert saved.params["_routing"]["reason"] == "cooldown"
        assert "等待恢复" in image_task_progress("processing", saved.params)["message"]
