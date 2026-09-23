from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.adapters.ai_model.gptimage2 import GPTImage2Adapter
from app.adapters.ai_model.image_results import batch_result, validate_image_count
from app.adapters.ai_model.seedream import SeedreamAdapter
from app.config import settings
from app.core.security import create_access_token
from app.db.session import async_session
from app.models.ai_image_provider import AIImageProvider
from app.models.ai_task import AITask
from app.models.user import User
from app.services.ai_image_provider_service import AIImageProviderService
from app.services.ai_image_service import AIImageService
from app.services.ai_task_queue import ai_image_postprocess_queue, ai_image_task_queue


def provider(**kwargs):
    fields = dict(id=92, name="count-test", model_name="gptimage2", provider_kind="mentalout_batch",
                  endpoint_url="https://upstream.test", provider_model="test-image", api_key="test-key",
                  supports_image_input=True, config={"poll_interval": 0, "max_polls": 4, "upstream_retry_attempts": 2})
    return AIImageProvider(**{**fields, **kwargs})


def batch(done, *, count=4, status="running"):
    return {"status": status, "count": count, "tasks": [
        {"id": f"child-{i}", "status": "completed" if i < done else "running",
         **({"imageUrl": f"/image-{i}.png"} if i < done else {})}
        for i in range(count)
    ]}


def http_responses(monkeypatch, responses):
    requests = []
    responses = iter(responses)
    client_class = httpx.AsyncClient

    def handler(request):
        requests.append(request)
        item = next(responses)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, httpx.Response):
            return item
        return httpx.Response(200, json=item)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_class(
        **kwargs, transport=httpx.MockTransport(handler),
    ))
    return requests


@pytest.mark.parametrize("done", [1, 2, 3, 4])
def test_batch_does_not_complete_while_batch_is_running(done):
    result = batch_result(batch(done), "b", "https://upstream.test", 4)
    assert result["status"] == "generating"
    assert len(result["image_urls"]) == done


def test_batch_checks_children_even_when_parent_claims_success():
    assert batch_result(batch(1, status="succeeded"), "b", "https://host", 4)["status"] == "generating"
    short = batch_result(batch(1, count=1, status="succeeded"), "b", "https://host", 4)
    assert short["status"] == "failed"
    assert "请求 4 张，实际返回 1 张" in short["error"]
    assert len(short["image_urls"]) == 1


def test_duplicate_urls_do_not_count_as_four_images():
    result = validate_image_count({"status": "completed", "image_urls": ["/same.png"] * 4}, 4)
    assert result["status"] == "failed"
    assert result["image_urls"] == ["/same.png"]


@pytest.mark.asyncio
async def test_batch_waits_for_all_four_and_posts_only_once(monkeypatch):
    requests = http_responses(monkeypatch, [{"id": "b"}, batch(1), batch(2), batch(4, status="succeeded")])
    result = await AIImageProviderService(None)._call_mentalout_batch(provider(), "p", {"count": 4})
    assert result["status"] == "completed"
    assert len(result["image_urls"]) == 4
    assert [r.method for r in requests] == ["POST", "GET", "GET", "GET"]
    assert json.loads(requests[0].content)["count"] == 4


@pytest.mark.asyncio
async def test_partial_failed_batch_keeps_images_and_does_not_rebill(monkeypatch):
    failed = batch(1, status="failed")
    for item in failed["tasks"][1:]:
        item.update(status="failed", error="Tool choice 'image_generation' not found in 'tools' parameter.")
    requests = http_responses(monkeypatch, [{"id": "b"}, failed])
    result = await AIImageProviderService(None)._call_mentalout_batch(provider(), "p", {"count": 4})
    assert result["status"] == "failed"
    assert len(result["image_urls"]) == 1
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_batch_timeout_keeps_id_and_partial_images_without_resubmit(monkeypatch):
    requests = http_responses(monkeypatch, [{"id": "b"}, batch(1)])
    p = provider(config={"max_polls": 1, "poll_interval": 0})
    result = await AIImageProviderService(None)._call_mentalout_batch(p, "p", {"count": 4})
    assert result["result_unknown"] is True
    assert result["task_id"] == "b"
    assert len(result["image_urls"]) == 1
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_query_only_waits_for_complete_batch(monkeypatch):
    requests = http_responses(monkeypatch, [batch(1), batch(4, status="succeeded")])
    service = AIImageProviderService(None)
    monkeypatch.setattr(service, "get_provider", AsyncMock(return_value=provider()))
    assert (await service.get_upstream_task_status(92, "b", 4))["status"] == "generating"
    assert len((await service.get_upstream_task_status(92, "b", 4))["image_urls"]) == 4
    assert all(r.method == "GET" for r in requests)


@pytest.mark.asyncio
async def test_legacy_batch_adapter_has_same_completion_rule(monkeypatch):
    requests = http_responses(monkeypatch, [batch(1), batch(4, status="succeeded")])
    monkeypatch.setattr("app.adapters.ai_model.gptimage2._BATCH_POLL_INTERVAL", 0)
    result = await GPTImage2Adapter()._poll_batch("b", "https://upstream.test", expected_count=4)
    assert result["status"] == "completed"
    assert len(result["image_urls"]) == 4
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 2, 4])
@pytest.mark.parametrize("with_reference", [False, True])
async def test_seedream_sends_exact_number_of_single_requests(monkeypatch, count, with_reference):
    monkeypatch.setattr(settings, "seedream_api_key", "test-key")
    requests = http_responses(monkeypatch, [{"data": [{"url": f"https://cdn/{i}.png"}]} for i in range(count)])
    kwargs = {"images_data": ["https://ref/one.png", "https://ref/two.png"]} if with_reference else {}
    result = await SeedreamAdapter().generate_image("p", count=count, **kwargs)
    assert result["status"] == "completed"
    assert len(result["image_urls"]) == len(requests) == count
    for request in requests:
        payload = json.loads(request.content)
        assert payload["sequential_image_generation"] == "disabled"
        assert payload["prompt"] == "p"
        if with_reference:
            assert payload["image"] == kwargs["images_data"]


@pytest.mark.asyncio
async def test_seedream_preserves_previous_image_on_second_call_timeout(monkeypatch):
    monkeypatch.setattr(settings, "seedream_api_key", "test-key")
    requests = http_responses(monkeypatch, [{"data": [{"url": "https://cdn/1.png"}]}, httpx.ReadTimeout("timeout")])
    result = await SeedreamAdapter().generate_image("p", count=4)
    assert result["status"] == "failed"
    assert result["image_urls"] == ["https://cdn/1.png"]
    assert result["result_unknown"] is True
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_edit_request_sends_batch_count_and_rejects_short_result(monkeypatch):
    requests = http_responses(monkeypatch, [{"data": [{"url": "https://cdn/1.png"}]}])
    p = provider(provider_kind="openai_images", config={"send_n": True})
    result = await AIImageProviderService(None)._call_openai_images(
        p, "p", {"count": 4, "image_data": "data:image/png;base64,aW1hZ2U="},
    )
    assert requests[0].url.path == "/images/edits"
    assert b'name="n"\r\n\r\n4' in requests[0].content
    assert result["status"] == "failed"
    assert len(result["image_urls"]) == 1
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_sequential_provider_preserves_paid_images_on_later_failure(monkeypatch):
    requests = http_responses(monkeypatch, [
        {"data": [{"url": "https://cdn/1.png"}]},
        httpx.Response(403, json={"error": {"message": "quota"}}),
    ])
    result = await AIImageProviderService(None)._call_openai_images(
        provider(provider_kind="openai_images", config={"send_n": False}), "p", {"count": 4},
    )
    assert result["status"] == "failed"
    assert result["image_urls"] == ["https://cdn/1.png"]
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["seedream", "gptimage2"])
async def test_empty_timeout_message_still_identifies_failure(monkeypatch, model):
    monkeypatch.setattr(settings, "seedream_api_key", "test-key")
    requests = http_responses(monkeypatch, [
        {"data": [{"url": "https://cdn/1.png"}]}, httpx.ReadTimeout(""),
    ])
    if model == "seedream":
        result = await SeedreamAdapter().generate_image("p", count=4)
    else:
        result = await AIImageProviderService(None)._call_openai_images(
            provider(provider_kind="openai_images", config={"send_n": False}), "p", {"count": 4},
        )
    assert "ReadTimeout" in result["error"]
    assert result["result_unknown"] is True
    assert result["image_urls"] == ["https://cdn/1.png"]
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("generated, cleaned, final_status", [(4, 4, "completed"), (1, 1, "failed"), (4, 1, "failed")])
async def test_worker_and_postprocess_enforce_delivery_count(client, monkeypatch, generated, cleaned, final_status):
    upstream = AsyncMock(return_value={"status": "completed", "image_urls": [f"/raw/{i}.png" for i in range(generated)]})
    monkeypatch.setattr(AIImageService, "_generate_with_configured_provider", upstream)
    monkeypatch.setattr("app.services.ai_image_service._store_images", AsyncMock(side_effect=lambda urls: urls))
    monkeypatch.setattr(AIImageService, "_remove_watermarks", AsyncMock(return_value=[f"/clean/{i}.png" for i in range(cleaned)]))
    monkeypatch.setattr(settings, "remove_ai_watermarks_enabled", True)
    monkeypatch.setattr(ai_image_postprocess_queue, "enqueue_task", AsyncMock(return_value=True))
    async with async_session() as db:
        db.add(User(id=1, username="count-user", email="count@example.com", hashed_password="x"))
        task = AITask(user_id=1, model_name="gptimage2", prompt="p", params={"count": 4}, status="queued")
        db.add(task)
        await db.commit()
        service = AIImageService(db=db)
        assert await service.execute_submitted_task(task.id) == "postprocessing"
        await db.refresh(task)
        assert task.result_urls == []
        assert len(task.params["_postprocess_source_urls"]) == generated
        assert await service.execute_postprocessing_task(task.id) == final_status
        await db.refresh(task)
        assert task.status == final_status
        assert len(task.result_urls) == cleaned
        if final_status == "failed":
            assert "请求 4 张" in task.error
        assert upstream.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("model, delivered, send_n", [
    ("seedream", 4, False), ("gptimage2", 4, True), ("gptimage2", 1, True),
    ("gptimage2", 4, False), ("gptimage25", 4, False),
])
async def test_submit_worker_cleanup_poll_and_history_keep_correct_count(client, monkeypatch, model, delivered, send_n):
    # Only the paid upstream HTTP and storage/cleanup transports are replaced.
    # Authentication, API, DB, provider/adapters, worker and status mapping run normally.
    monkeypatch.setattr(settings, "ai_image_shadow_enabled", False)
    monkeypatch.setattr(settings, "seedream_api_key", "test-key")
    monkeypatch.setattr(settings, "remove_ai_watermarks_enabled", True)
    monkeypatch.setattr(ai_image_task_queue, "enqueue_task", AsyncMock(return_value=True))
    monkeypatch.setattr(ai_image_postprocess_queue, "enqueue_task", AsyncMock(return_value=True))
    monkeypatch.setattr("app.services.ai_image_service._store_images", AsyncMock(side_effect=lambda urls: urls))
    monkeypatch.setattr(AIImageService, "_remove_watermarks", AsyncMock(side_effect=lambda urls: [f"/clean/{i}.png" for i in range(len(urls))]))
    async with async_session() as db:
        db.add(User(id=1, username="integration-user", email="integration@example.com", hashed_password="x"))
        if model != "seedream":
            db.add(provider(model_name=model, provider_kind="openai_images", is_enabled=True,
                            config={"send_n": send_n, "max_concurrent": 1}))
        await db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(subject='1')}"}
    response = await client.post("/api/v1/ai-image/generate", headers=headers,
                                 json={"prompt": "four posters", "model": model, "count": 4})
    assert response.status_code == 202
    task_id = int(response.json()["data"]["task_id"])
    assert response.json()["data"]["status"] == "queued"
    ai_image_task_queue.enqueue_task.assert_awaited_once()
    responses = ([{"data": [{"url": f"https://cdn/{i}.png"}]} for i in range(4)] if not send_n
                 else [{"data": [{"url": f"https://cdn/{i}.png"} for i in range(delivered)]}])
    requests = http_responses(monkeypatch, responses)
    async with async_session() as db:
        service = AIImageService(db=db)
        assert await service.execute_submitted_task(task_id) == "postprocessing"
    processing = await client.get(f"/api/v1/ai-image/tasks/{task_id}", headers=headers)
    assert processing.json()["data"]["status"] == "postprocessing"
    assert processing.json()["data"]["image_urls"] == []
    final_status = "completed" if delivered == 4 else "failed"
    async with async_session() as db:
        assert await AIImageService(db=db).execute_postprocessing_task(task_id) == final_status
    final = (await client.get(f"/api/v1/ai-image/tasks/{task_id}", headers=headers)).json()["data"]
    assert final["status"] == final_status
    assert len(final["image_urls"]) == delivered
    history_response = await client.get("/api/v1/ai-image/history", headers=headers)
    assert history_response.status_code == 200
    history = history_response.json()["data"]["items"][0]
    assert history["params"]["count"] == 4
    assert history["status"] == final_status
    assert len(history["result_urls"]) == delivered
    assert len(requests) == (4 if not send_n else 1)
    if delivered < 4:
        assert "请求 4 张，实际返回 1 张" in final["error"]
