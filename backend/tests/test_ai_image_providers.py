from __future__ import annotations

import pytest

from app.config import settings
from app.db.session import async_session
from app.models.ai_image_provider import AIImageProvider
from app.models.user import User
from app.services.ai_image_provider_service import (
    AIImageProviderService,
    _batch_task_image_url,
    _is_retryable_mentalout_error,
    _normalize_legacy_batch_api_base,
    _request_with_retries,
    _response_body_preview,
)
from app.adapters.ai_model.gptimage2 import _resolve_image_size
from tests.conftest import make_auth_headers


async def _seed_admin() -> None:
    async with async_session() as db:
        db.add(User(id=1, username="admin", email="admin@test.com", hashed_password="x", role="admin"))
        await db.commit()


@pytest.mark.asyncio
async def test_admin_list_ai_image_providers(client, monkeypatch):
    monkeypatch.setattr(settings, "gpt_image2_api_key", "test-api-key")
    monkeypatch.setattr(settings, "gpt_image2_api_url", "https://image.mentalout.top")
    await _seed_admin()
    resp = await client.get("/api/v1/admin/ai-image/providers", headers=make_auth_headers(1))
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert len(items) >= 1
    assert any(item["name"] == "MentalOut GPT Image 2（旧入口）" for item in items)


@pytest.mark.asyncio
async def test_admin_create_toggle_delete_ai_image_provider(client):
    await _seed_admin()
    headers = make_auth_headers(1)

    create_resp = await client.post(
        "/api/v1/admin/ai-image/providers",
        headers=headers,
        json={
            "name": "DuckCoding GPT Image 2",
            "model_name": "gptimage2",
            "provider_kind": "openai_images",
            "provider_model": "gpt-image-2",
            "endpoint_url": "https://api.duckcoding.ai/v1",
            "api_key": "sk-test",
            "is_enabled": True,
            "priority": 10,
            "weight": 3,
            "supports_text_input": True,
            "supports_image_input": False,
            "is_default": True,
            "config": {"send_size": False, "send_n": False},
        },
    )
    assert create_resp.status_code == 200
    provider_id = create_resp.json()["data"]["id"]

    list_resp = await client.get("/api/v1/admin/ai-image/providers", headers=headers)
    assert list_resp.status_code == 200
    items = list_resp.json()["data"]
    assert any(item["id"] == provider_id and item["name"] == "DuckCoding GPT Image 2" for item in items)
    created_item = next(item for item in items if item["id"] == provider_id)
    assert created_item["is_default"] is True

    toggle_resp = await client.post(
        f"/api/v1/admin/ai-image/providers/{provider_id}/enable",
        headers=headers,
        json={"is_enabled": False},
    )
    assert toggle_resp.status_code == 200
    assert toggle_resp.json()["data"]["is_enabled"] is False

    default_resp = await client.post(
        f"/api/v1/admin/ai-image/providers/{provider_id}/default",
        headers=headers,
    )
    assert default_resp.status_code == 200
    assert default_resp.json()["data"]["is_default"] is True

    delete_resp = await client.delete(f"/api/v1/admin/ai-image/providers/{provider_id}", headers=headers)
    assert delete_resp.status_code == 200


@pytest.mark.asyncio
async def test_admin_health_check_uses_generation_probe(client, monkeypatch):
    await _seed_admin()
    headers = make_auth_headers(1)

    create_resp = await client.post(
        "/api/v1/admin/ai-image/providers",
        headers=headers,
        json={
            "name": "DuckCoding GPT Image 2",
            "model_name": "gptimage2",
            "provider_kind": "openai_images",
            "provider_model": "gpt-image-2",
            "endpoint_url": "https://api.duckcoding.ai/v1",
            "api_key": "sk-test",
            "is_enabled": True,
            "priority": 10,
            "weight": 3,
            "supports_text_input": True,
            "supports_image_input": True,
            "is_default": True,
            "config": {"send_size": True, "send_n": False},
        },
    )
    provider_id = create_resp.json()["data"]["id"]

    async def fake_probe(self, provider):
        assert provider.id == provider_id
        return "healthy", None

    monkeypatch.setattr(AIImageProviderService, "_probe_openai_generation", fake_probe)

    health_resp = await client.post(f"/api/v1/admin/ai-image/providers/{provider_id}/health-check", headers=headers)
    assert health_resp.status_code == 200
    body = health_resp.json()["data"]
    assert body["healthy"] is True
    assert body["status"] == "healthy"


@pytest.mark.asyncio
async def test_ensure_default_providers_normalizes_mentalout_batch_api_base(client, monkeypatch):
    monkeypatch.setattr("app.services.ai_image_provider_service.settings.gpt_image2_api_key", "sk-test")
    monkeypatch.setattr(
        "app.services.ai_image_provider_service.settings.gpt_image2_api_url",
        "https://chunfeng.mentalout.top/v1/images/generations",
    )
    monkeypatch.setattr("app.services.ai_image_provider_service.settings.duckcoding_gpt_image2_api_key", "")

    async with async_session() as db:
        provider = AIImageProvider(
            name="MentalOut GPT Image 2（旧入口）",
            model_name="gptimage2",
            provider_kind="mentalout_batch",
            provider_model="gpt-image-2",
            endpoint_url="https://image.mentalout.top",
            api_key="sk-test",
            is_enabled=True,
            is_default=True,
            supports_text_input=True,
            supports_image_input=True,
            config={"api_base_url": "https://chunfeng.mentalout.top/v1"},
        )
        db.add(provider)
        await db.commit()

        service = AIImageProviderService(db)
        created = await service.ensure_default_providers()
        assert created == 0

        await db.refresh(provider)
        assert provider.config["api_base_url"] == "https://chunfeng.mentalout.top"


@pytest.mark.asyncio
async def test_ensure_default_providers_preserves_admin_capability_flags(client, monkeypatch):
    monkeypatch.setattr("app.services.ai_image_provider_service.settings.duckcoding_gpt_image2_api_key", "sk-test")
    monkeypatch.setattr(
        "app.services.ai_image_provider_service.settings.duckcoding_gpt_image2_api_url",
        "https://provider.test/v1",
    )
    monkeypatch.setattr("app.services.ai_image_provider_service.settings.gpt_image2_api_key", "")
    monkeypatch.setattr("app.services.ai_image_provider_service.settings.gpt_image2_api_url", "")

    async with async_session() as db:
        provider = AIImageProvider(
            name="Existing provider",
            model_name="gptimage2",
            provider_kind="openai_images",
            provider_model="gpt-image-2",
            endpoint_url="https://provider.test/v1",
            api_key="sk-test",
            is_enabled=True,
            is_default=True,
            supports_text_input=True,
            supports_image_input=False,
            config={"send_size": True, "send_n": False},
        )
        db.add(provider)
        await db.commit()

        await AIImageProviderService(db).ensure_default_providers()

        await db.refresh(provider)
        assert provider.supports_image_input is False


def test_batch_task_image_url_accepts_multiple_field_shapes():
    api_base = "https://image.mentalout.top"
    assert _batch_task_image_url({"image_url": "/generated/foo.png"}, api_base) == f"{api_base}/generated/foo.png"
    assert _batch_task_image_url({"result": {"url": "https://cdn.example.com/bar.png"}}, api_base) == "https://cdn.example.com/bar.png"


def test_normalize_legacy_batch_api_base_force_https_for_mentalout():
    assert _normalize_legacy_batch_api_base("http://chunfeng.mentalout.top/v1") == "https://chunfeng.mentalout.top"


@pytest.mark.asyncio
async def test_openai_images_empty_response_error_includes_body_preview(monkeypatch):
    for proxy_env in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(proxy_env, raising=False)

    provider = AIImageProvider(
        id=8,
        name="Empty GPT Image 2",
        model_name="gptimage2",
        provider_kind="openai_images",
        provider_model="gpt-image-2",
        endpoint_url="https://empty.example.com/v1",
        api_key="sk-test",
        is_enabled=True,
        supports_text_input=True,
        supports_image_input=True,
        config={"send_size": True},
    )
    service = AIImageProviderService(None)  # type: ignore[arg-type]
    long_body = '{"id":"empty-task","data":[{"revised_prompt":"no image"}],"debug":"' + ("x" * 1300) + '"}'

    class FakeResponse:
        status_code = 200
        text = long_body
        headers = {"content-type": "application/json"}

        def json(self):
            return {"id": "empty-task", "data": [{"revised_prompt": "no image"}], "debug": "x" * 1300}

    async def fake_request_with_retries(client, method, url, **kwargs):
        return FakeResponse()

    monkeypatch.setattr("app.services.ai_image_provider_service._request_with_retries", fake_request_with_retries)

    with pytest.raises(ValueError) as exc:
        await service._call_openai_images(provider, "empty prompt", {"width": 768, "height": 1024})

    message = str(exc.value)
    assert "响应中没有图片数据；上游响应预览:" in message
    assert "empty-task" in message
    assert len(_response_body_preview(FakeResponse())) == 1024


def test_gptimage2_size_constraints_accept_official_4k_portrait():
    assert _resolve_image_size(2160, 3840) == "2160x3840"
    assert _resolve_image_size(3840, 2160) == "3840x2160"
    assert _resolve_image_size(1536, 2048) == "1536x2048"

    with pytest.raises(ValueError, match="16px"):
        _resolve_image_size(1080, 1920)

    with pytest.raises(ValueError, match="总像素"):
        _resolve_image_size(3840, 3840)


@pytest.mark.asyncio
async def test_request_with_retries_retries_gateway_status(monkeypatch):
    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def request(self, method, url, **kwargs):
            self.calls += 1

            class FakeResponse:
                def __init__(self, status_code):
                    self.status_code = status_code

            return FakeResponse(502 if self.calls == 1 else 200)

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr("app.services.ai_image_provider_service.asyncio.sleep", fake_sleep)

    client = FakeClient()
    resp = await _request_with_retries(
        client,  # type: ignore[arg-type]
        "POST",
        "https://api.duckcoding.ai/v1/images/generations",
        retries=3,
        retry_delay=0,
        retry_on_statuses={502, 503, 504},
    )

    assert resp.status_code == 200
    assert client.calls == 2


@pytest.mark.asyncio
async def test_mentalout_batch_retries_retryable_upstream_error(monkeypatch):
    provider = AIImageProvider(
        id=2,
        name="MentalOut GPT Image 2（旧入口）",
        model_name="gptimage2",
        provider_kind="mentalout_batch",
        provider_model="gpt-image-2",
        endpoint_url="https://image.mentalout.top",
        api_key="sk-test",
        is_enabled=True,
        is_default=True,
        supports_text_input=True,
        supports_image_input=True,
        config={
            "api_base_url": "https://chunfeng.mentalout.top",
            "poll_interval": 0,
            "max_polls": 1,
            "upstream_retry_attempts": 2,
        },
    )
    service = AIImageProviderService(None)  # type: ignore[arg-type]

    class FakeResponse:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text

        def json(self):
            return self._payload

    retryable_error = "upstream http 400: Tool choice 'image_generation' not found in 'tools' parameter.; type=invalid_request_error"
    responses = iter([
        FakeResponse(200, {"id": "batch-1"}),
        FakeResponse(200, {
            "status": "failed",
            "tasks": [{"status": "failed", "errorMessage": retryable_error}],
        }),
        FakeResponse(200, {"id": "batch-2"}),
        FakeResponse(200, {
            "status": "succeeded",
            "tasks": [{"status": "succeeded", "imageUrl": "/results/final.png"}],
        }),
    ])
    submit_urls: list[str] = []

    async def fake_request_with_retries(client, method, url, **kwargs):
        if method == "POST":
            submit_urls.append(url)
        return next(responses)

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr("app.services.ai_image_provider_service._request_with_retries", fake_request_with_retries)
    monkeypatch.setattr("app.services.ai_image_provider_service.asyncio.sleep", fake_sleep)

    result = await service._call_mentalout_batch(provider, "retry prompt", {"width": 1536, "height": 2048})

    assert result["status"] == "completed"
    assert result["task_id"] == "batch-2"
    assert result["image_urls"] == ["https://image.mentalout.top/results/final.png"]
    assert len(submit_urls) == 2
    assert _is_retryable_mentalout_error(retryable_error) is True


@pytest.mark.asyncio
async def test_openai_images_retries_gateway_error(monkeypatch):
    provider = AIImageProvider(
        id=1,
        name="DuckCoding GPT Image 2",
        model_name="gptimage2",
        provider_kind="openai_images",
        provider_model="gpt-image-2",
        endpoint_url="https://api.duckcoding.ai/v1",
        api_key="sk-test",
        is_enabled=True,
        is_default=True,
        supports_text_input=True,
        supports_image_input=True,
        config={
            "send_size": True,
            "send_n": False,
            "timeout": 180,
            "upstream_retry_attempts": 2,
            "upstream_retry_delay": 0,
        },
    )
    service = AIImageProviderService(None)  # type: ignore[arg-type]

    class FakeResponse:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text
            self.headers = {"content-type": "application/json"}

        def json(self):
            return self._payload

    responses = iter([
        FakeResponse(502, text="bad gateway"),
        FakeResponse(200, {"data": [{"b64_json": "aGVsbG8="}], "created": 123}),
    ])
    requests: list[dict] = []

    class DummyClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def request(self, method, url, **kwargs):
            self.calls += 1
            requests.append({"method": method, "url": url, **kwargs})
            return next(responses)

    async def fake_sleep(_seconds):
        return None

    async def fake_extract_image_urls(self, provider, data, seed):
        return ["/uploads/ai-images/final.png"]

    monkeypatch.setattr("app.services.ai_image_provider_service.httpx.AsyncClient", DummyClient)
    monkeypatch.setattr("app.services.ai_image_provider_service.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(AIImageProviderService, "_extract_image_urls", fake_extract_image_urls)

    result = await service._call_openai_images(
        provider,
        "retry prompt",
        {"width": 2160, "height": 3840, "quality": "high"},
    )

    assert result["status"] == "completed"
    assert result["task_id"] == "123"
    assert result["image_urls"] == ["/uploads/ai-images/final.png"]
    assert requests[0]["json"]["size"] == "2160x3840"
    assert requests[0]["json"]["quality"] == "high"


@pytest.mark.asyncio
async def test_provider_diagnostic_can_force_image_edit_when_routing_is_disabled(monkeypatch):
    provider = AIImageProvider(
        id=8,
        name="Temporarily disabled image provider",
        model_name="gptimage2",
        provider_kind="openai_images",
        provider_model="gpt-image-2",
        endpoint_url="https://provider.test/v1",
        api_key="sk-test",
        is_enabled=True,
        is_default=False,
        supports_text_input=True,
        supports_image_input=False,
        config={"send_size": True, "send_n": False, "timeout": 180},
    )
    service = AIImageProviderService(None)  # type: ignore[arg-type]
    requests: list[dict] = []

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"created": 123}'

        @staticmethod
        def json():
            return {"created": 123}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def fake_request_with_retries(client, method, url, **kwargs):
        requests.append({"method": method, "url": url, **kwargs})
        return FakeResponse()

    async def fake_extract_image_urls(self, provider, data, seed):
        return ["/uploads/ai-images/provider-test.png"]

    monkeypatch.setattr("app.services.ai_image_provider_service.httpx.AsyncClient", DummyClient)
    monkeypatch.setattr("app.services.ai_image_provider_service._request_with_retries", fake_request_with_retries)
    monkeypatch.setattr(AIImageProviderService, "_extract_image_urls", fake_extract_image_urls)

    result = await service._call_openai_images(
        provider,
        "diagnose edit endpoint",
        {
            "width": 768,
            "height": 1024,
            "image_data": "data:image/png;base64,aGVsbG8=",
            "_provider_test_force_image_edit": True,
        },
    )

    assert result["status"] == "completed"
    assert requests[0]["url"] == "https://provider.test/v1/images/edits"
    assert requests[0]["data"]["size"] == "768x1024"
    assert requests[0]["files"][0][0] == "image"


@pytest.mark.asyncio
async def test_openai_images_retries_pending_openai_error(monkeypatch):
    provider = AIImageProvider(
        id=3,
        name="DuckCoding GPT Image 2",
        model_name="gptimage2",
        provider_kind="openai_images",
        provider_model="gpt-image-2",
        endpoint_url="https://api.duckcoding.ai/v1",
        api_key="sk-test",
        is_enabled=True,
        is_default=True,
        supports_text_input=True,
        supports_image_input=True,
        config={
            "send_size": True,
            "send_n": False,
            "timeout": 180,
            "pending_retry_attempts": 2,
            "pending_retry_delay": 0,
        },
    )
    service = AIImageProviderService(None)  # type: ignore[arg-type]

    class FakeResponse:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text
            self.headers = {"content-type": "application/json"}

        def json(self):
            return self._payload

    responses = iter([
        FakeResponse(
            200,
            {
                "error": {
                    "code": "openai_error",
                    "message": "image generation still processing",
                    "status_code": 202,
                },
            },
            text='{"error":{"code":"openai_error","status_code":202}}',
        ),
        FakeResponse(200, {"data": [{"b64_json": "aGVsbG8="}], "created": 789}),
    ])
    requests: list[dict] = []

    class DummyClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def request(self, method, url, **kwargs):
            self.calls += 1
            requests.append({"method": method, "url": url, **kwargs})
            return next(responses)

    async def fake_sleep(_seconds):
        return None

    async def fake_extract_image_urls(self, provider, data, seed):
        return ["/uploads/ai-images/pending-final.png"]

    monkeypatch.setattr("app.services.ai_image_provider_service.httpx.AsyncClient", DummyClient)
    monkeypatch.setattr("app.services.ai_image_provider_service.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(AIImageProviderService, "_extract_image_urls", fake_extract_image_urls)

    result = await service._call_openai_images(provider, "pending prompt", {"width": 1536, "height": 2048})

    assert result["status"] == "completed"
    assert result["task_id"] == "789"
    assert result["image_urls"] == ["/uploads/ai-images/pending-final.png"]
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_openai_images_retries_tool_choice_error(monkeypatch):
    provider = AIImageProvider(
        id=2,
        name="MentalOut GPT Image 2（直连 chunfeng）",
        model_name="gptimage2",
        provider_kind="openai_images",
        provider_model="gpt-image-2",
        endpoint_url="https://chunfeng.mentalout.top/v1",
        api_key="sk-test",
        is_enabled=True,
        is_default=True,
        supports_text_input=True,
        supports_image_input=True,
        config={
            "send_size": True,
            "send_n": False,
            "timeout": 180,
            "tool_choice_retry_attempts": 2,
            "tool_choice_retry_delay": 0,
        },
    )
    service = AIImageProviderService(None)  # type: ignore[arg-type]

    retryable_error = "Tool choice 'image_generation' not found in 'tools' parameter."

    class FakeResponse:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text
            self.headers = {"content-type": "application/json"}

        def json(self):
            return self._payload

    responses = iter([
        FakeResponse(400, {"error": {"message": retryable_error}}, text=retryable_error),
        FakeResponse(200, {"data": [{"b64_json": "aGVsbG8="}], "created": 456}),
    ])

    class DummyClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def request(self, method, url, **kwargs):
            self.calls += 1
            return next(responses)

    async def fake_sleep(_seconds):
        return None

    async def fake_extract_image_urls(self, provider, data, seed):
        return ["/uploads/ai-images/tool-choice.png"]

    monkeypatch.setattr("app.services.ai_image_provider_service.httpx.AsyncClient", DummyClient)
    monkeypatch.setattr("app.services.ai_image_provider_service.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(AIImageProviderService, "_extract_image_urls", fake_extract_image_urls)

    result = await service._call_openai_images(provider, "retry prompt", {"width": 1536, "height": 2048})

    assert result["status"] == "completed"
    assert result["task_id"] == "456"
    assert result["image_urls"] == ["/uploads/ai-images/tool-choice.png"]


@pytest.mark.asyncio
async def test_mentalout_batch_reports_id_before_polling(monkeypatch):
    provider = AIImageProvider(
        id=77,
        name="MentalOut Batch",
        model_name="gptimage2",
        provider_kind="mentalout_batch",
        provider_model="gpt-image-2",
        endpoint_url="https://image.example.com",
        api_key="test-key",
        is_enabled=True,
        config={"poll_interval": 0, "max_polls": 2, "upstream_retry_attempts": 1},
    )
    callbacks: list[dict] = []
    responses = iter(
        [
            {
                "id": "batch-accepted",
            },
            {
                "status": "completed",
                "tasks": [
                    {
                        "status": "completed",
                        "imageUrl": "https://images.example.com/result.png",
                    }
                ],
            },
        ]
    )

    class FakeResponse:
        status_code = 200
        text = ""
        headers = {"content-type": "application/json"}

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def request(self, method, url, **kwargs):
            return FakeResponse(next(responses))

    async def fake_sleep(_seconds):
        return None

    async def accepted(details: dict) -> None:
        callbacks.append(details)

    monkeypatch.setattr(
        "app.services.ai_image_provider_service.httpx.AsyncClient", DummyClient
    )
    monkeypatch.setattr(
        "app.services.ai_image_provider_service.asyncio.sleep", fake_sleep
    )
    result = await AIImageProviderService(None)._call_mentalout_batch(  # type: ignore[arg-type]
        provider,
        "batch prompt",
        {"width": 768, "height": 1024, "count": 1},
        on_upstream_accepted=accepted,
    )

    assert callbacks == [
        {
            "upstream_task_id": "batch-accepted",
            "provider_id": 77,
            "provider_kind": "mentalout_batch",
            "provider_model": "gpt-image-2",
            "query_capability": "mentalout_batch",
        }
    ]
    assert result == {
        "task_id": "batch-accepted",
        "status": "completed",
        "image_urls": ["https://images.example.com/result.png"],
    }


@pytest.mark.asyncio
async def test_provider_upstream_status_query_never_submits_work(client, monkeypatch):
    requests: list[tuple[str, str]] = []

    class FakeResponse:
        status_code = 200
        text = ""
        headers = {"content-type": "application/json"}

        def json(self):
            return {
                "status": "completed",
                "tasks": [
                    {
                        "status": "completed",
                        "output": {"imageUrl": "/api/files/result.png"},
                    }
                ],
            }

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def request(self, method, url, **kwargs):
            requests.append((method, url))
            return FakeResponse()

    monkeypatch.setattr(
        "app.services.ai_image_provider_service.httpx.AsyncClient", DummyClient
    )
    async with async_session() as db:
        db.add(
            AIImageProvider(
                id=88,
                name="Queryable Batch",
                model_name="gptimage2",
                provider_kind="mentalout_batch",
                provider_model="gpt-image-2",
                endpoint_url="https://image.example.com",
                api_key="test-key",
                is_enabled=True,
                config={},
            )
        )
        await db.commit()
        result = await AIImageProviderService(db).get_upstream_task_status(
            88,
            "batch-query",
        )

    assert requests == [
        ("GET", "https://image.example.com/api/batches/batch-query")
    ]
    assert result == {
        "task_id": "batch-query",
        "status": "completed",
        "raw_status": "completed",
        "image_urls": ["https://image.example.com/api/files/result.png"],
        "error": None,
    }
