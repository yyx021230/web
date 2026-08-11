from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
from httpx import RequestError

from app.db.session import async_session
from app.models.ai_image_provider import AIImageProvider
from app.models.ai_task import AITask
from app.services import ai_image_provider_service as module
from app.services.ai_image_provider_service import AIImageProviderService, UpstreamProviderError


def _provider(**overrides) -> AIImageProvider:
    values = {
        "name": "Provider",
        "model_name": "gptimage2",
        "provider_kind": "openai_images",
        "provider_model": "gpt-image-2",
        "endpoint_url": "https://api.example.com/v1",
        "api_key": "key",
        "is_enabled": True,
        "is_default": False,
        "priority": 10,
        "weight": 1,
        "supports_text_input": True,
        "supports_image_input": True,
        "config": {},
    }
    values.update(overrides)
    return AIImageProvider(**values)


def test_provider_helpers_cover_formats_limits_and_debug(monkeypatch, tmp_path):
    assert module._strip_slashes("https://a///") == "https://a"
    assert module._normalize_base_url("https://a/v1/images/generations") == ("https://a/v1", "/images/generations")
    assert module._normalize_base_url("https://a/v1/images/edits") == ("https://a/v1", "/images/edits")
    assert module._normalize_base_url("https://a/v1") == ("https://a/v1", "/images/generations")
    assert module._normalize_generation_base("https://a/v1") == "https://a/v1"

    provider = _provider(config={"max_concurrent": "bad"})
    provider.id = 1
    assert module._provider_max_concurrent(provider) == 1
    provider.config = {"max_concurrent": 999}
    assert module._provider_max_concurrent(provider) == 100
    module._PROVIDER_RUNNING.clear()
    module._PROVIDER_RUNNING[1] = -3
    assert module._provider_running_count(1) == 0
    provider.weight = 2
    monkeypatch.setattr(module.random, "choice", lambda population: population[-1])
    assert module._choose_weighted_provider([provider]) is provider

    assert module._generate_image_filename("seed", "image/jpeg").endswith(".jpg")
    encoded = base64.b64encode(b"GIF89a-data").decode()
    assert module._decode_data_uri(f"data:image/gif;base64,{encoded}") == (b"GIF89a-data", "image/gif")
    assert module._infer_mime(b"\x89PNG\r\n\x1a\n") == "image/png"
    assert module._infer_mime(b"\xff\xd8abc") == "image/jpeg"
    assert module._infer_mime(b"RIFFabc") == "image/webp"
    assert module._infer_mime(b"GIF8abc") == "image/gif"
    assert module._infer_mime(b"unknown") == "image/png"
    assert module._collect_reference_sources({"images_data": ["a", "", 1], "image_data": "b"}) == ["a"]
    assert module._collect_reference_sources({"image_data": "b"}) == ["b"]
    assert module._collect_reference_sources({"image_url": "c"}) == ["c"]
    assert module._collect_reference_sources({}) == []
    assert module._edits_size(512, 512) == "512x512"
    assert module._edits_size(768, 1024) is None
    assert module._edits_size(None, 1024) is None

    storage = tmp_path / "uploads"
    storage.mkdir()
    (storage / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(module.settings, "storage_path", str(storage))
    assert module._read_uploads_url("/uploads/a.png?x=1")[1] == "image/png"
    with pytest.raises(ValueError, match="非法"):
        module._read_uploads_url("/uploads/../secret")

    for status, expected in ((200, "healthy"), (401, "unhealthy"), (429, "degraded"), (503, "unhealthy"), (400, "unhealthy")):
        assert module._infer_health_status(status, "bad")[0] == expected
    assert module._batch_success_status("DONE") is True
    assert module._batch_failure_status("cancelled") is True
    assert module._batch_task_error({"debugMessage": "failed"}) == "failed"
    assert module._batch_task_error({}) == ""
    assert module._normalize_image_quality("HIGH") == "high"
    assert module._normalize_image_quality("invalid") == "low"
    assert module._find_status_code({"nested": [{"statusCode": "202"}]}) == 202
    assert module._find_status_code({"status_code": "bad"}) is None
    assert module._contains_openai_pending_error({"code": "openai_error"}) is True
    assert module._looks_like_html_response("<!DOCTYPE html><title>524</title>") is True
    assert module._extract_html_title("<html><title> Gateway  Timeout </title></html>") == "Gateway Timeout"

    class _Response:
        status_code = 524
        reason_phrase = "Timeout"
        text = "<html><title>Gateway Timeout</title></html>"
        headers = {"content-type": "text/html", "authorization": "secret", "x-trace": "ok"}
        request = SimpleNamespace(method="POST", url="https://api/images")

        def json(self):
            raise ValueError("not json")

    response = _Response()
    assert module._safe_response_headers(response)["authorization"] == "[redacted]"
    assert "Gateway Timeout" in module._upstream_html_error(response)
    debug = module._upstream_response_debug(
        response,
        provider=provider,
        endpoint="https://api",
        path="/images",
        request_kind="generation",
    )
    assert debug["response"]["status_code"] == 524
    assert debug["request"]["method"] == "POST"
    assert UpstreamProviderError("bad", debug).debug == debug


@pytest.mark.asyncio
async def test_inline_and_reference_file_helpers(monkeypatch):
    saved = []

    class _Storage:
        async def save(self, content, filename, content_type, subdir):
            saved.append((content, filename, content_type, subdir))
            return f"/uploads/{subdir}/{filename}"

    monkeypatch.setattr(module, "get_storage", lambda: _Storage())
    encoded = base64.b64encode(b"image").decode()
    assert (await module._save_inline_image(encoded, "seed")).startswith("/uploads/ai-images/")
    assert await module._download_reference_file(f"data:image/png;base64,{encoded}", 2) == (
        "ref_2.png",
        b"image",
        "image/png",
    )

    class _BrokenStorage:
        async def save(self, *args, **kwargs):
            raise RuntimeError("disk")

    monkeypatch.setattr(module, "get_storage", lambda: _BrokenStorage())
    assert await module._save_inline_image(encoded, "seed") is None


@pytest.mark.asyncio
async def test_request_retries_request_error_and_exhaustion(monkeypatch):
    monkeypatch.setattr(module.asyncio, "sleep", lambda _seconds: _async_none())

    class _Client:
        def __init__(self, fail_count):
            self.calls = 0
            self.fail_count = fail_count

        async def request(self, method, url, **kwargs):
            self.calls += 1
            if self.calls <= self.fail_count:
                raise RequestError("offline")
            return SimpleNamespace(status_code=200)

    client = _Client(1)
    assert (await module._request_with_retries(client, "GET", "https://a", retries=2)).status_code == 200
    with pytest.raises(RequestError):
        await module._request_with_retries(_Client(3), "GET", "https://a", retries=2)


async def _async_none():
    return None


@pytest.mark.asyncio
async def test_provider_crud_selection_slots_and_runtime(client, monkeypatch):
    async with async_session() as db:
        service = AIImageProviderService(db)
        first = await service.create_provider({
            "name": "Default",
            "model_name": "gptimage2",
            "provider_kind": "openai_images",
            "provider_model": "gpt-image-2",
            "endpoint_url": "https://a/v1",
            "api_key": "a",
            "is_enabled": True,
            "is_default": True,
            "priority": 2,
            "weight": 1,
            "supports_text_input": True,
            "supports_image_input": False,
            "config": {"max_concurrent": 2},
        })
        second = await service.create_provider({
            "name": "Image",
            "model_name": "gptimage2",
            "provider_kind": "mentalout_batch",
            "provider_model": "gpt-image-2",
            "endpoint_url": "https://b",
            "api_key": "b",
            "is_enabled": True,
            "is_default": False,
            "priority": 1,
            "weight": 1,
            "supports_text_input": False,
            "supports_image_input": True,
            "config": {"max_concurrent": 1},
        })
        assert [p.id for p in await service.list_providers()] == [second.id, first.id]
        assert await service.get_provider(99999) is None
        assert await service.set_default_provider(99999) is None
        assert (await service.set_default_provider(second.id)).is_default is True
        assert (await service.update_provider(first.id, {"name": "Updated", "is_default": True})).name == "Updated"
        assert await service.update_provider(99999, {}) is None
        assert (await service.toggle_provider(first.id, False)).is_enabled is False
        assert await service.delete_provider(99999) is False

        eligible_text = service._eligible_providers([first, second], has_reference=False)
        assert eligible_text == []
        first.is_enabled = True
        assert service._eligible_providers([first, second], has_reference=False) == [first]
        assert service._eligible_providers([first, second], has_reference=True) == [second]

        module._PROVIDER_RUNNING.clear()
        monkeypatch.setattr(module, "_choose_weighted_provider", lambda providers: providers[0])
        selected = await service._acquire_provider_slot(model_name="gptimage2", has_reference=True, wait_interval=0)
        assert selected.id == second.id
        assert service.provider_runtime(second) == {"current_running": 1, "max_concurrent": 1}
        await service._release_provider_slot(second.id)
        await service._release_provider_slot(second.id)
        await service._acquire_specific_provider_slot(second, wait_interval=0)
        await service._release_provider_slot(second.id)
        assert await service.delete_provider(second.id) is True


@pytest.mark.asyncio
async def test_generate_success_failure_callbacks_and_no_provider(client, monkeypatch):
    async with async_session() as db:
        provider = _provider(id=101, is_default=True)
        db.add(provider)
        await db.commit()
        service = AIImageProviderService(db)

        selected = []

        async def callback(meta):
            selected.append(meta)

        async def success_call(*args, **kwargs):
            return {"task_id": "up-1", "status": "completed", "image_urls": ["image.png"]}

        monkeypatch.setattr(service, "_call_provider", success_call)
        result = await service.generate("prompt", {}, on_provider_selected=callback)
        assert result["status"] == "completed"
        assert result["provider"]["id"] == provider.id
        assert selected[0]["name"] == "Provider"

        async def bad_callback(_meta):
            raise RuntimeError("callback failed")

        async def failure_call(*args, **kwargs):
            raise UpstreamProviderError("upstream failed", {"response": {"status_code": 524}})

        monkeypatch.setattr(service, "_call_provider", failure_call)
        failed = await service.generate("prompt", {}, on_provider_selected=bad_callback)
        assert failed["status"] == "failed"
        assert failed["upstream_debug"]["response"]["status_code"] == 524
        provider.is_enabled = False
        await db.commit()
        unavailable = await service.generate("prompt", {})
        assert unavailable["provider_configured"] is True


@pytest.mark.asyncio
async def test_upstream_status_and_provider_test_task_lifecycle(client, monkeypatch):
    async with async_session() as db:
        service = AIImageProviderService(db)
        assert (await service.get_upstream_task_status(99999, "x"))["status"] == "unknown"
        provider = _provider(id=201)
        batch = _provider(id=202, provider_kind="mentalout_batch", endpoint_url="https://batch")
        db.add_all([provider, batch])
        await db.commit()
        assert (await service.get_upstream_task_status(batch.id, ""))["error"] == "缺少上游任务 ID"
        assert (await service.get_upstream_task_status(provider.id, "x"))["status"] == "unsupported"

        class _Response:
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self.payload = payload

            def json(self):
                return self.payload

        responses = iter([
            _Response(500, {}),
            _Response(200, {"status": "failed", "tasks": [{"errorMessage": "bad"}]}),
            _Response(200, {"status": "completed", "tasks": []}),
            _Response(200, {"status": "processing", "tasks": []}),
        ])

        async def fake_request(*args, **kwargs):
            return next(responses)

        monkeypatch.setattr(module, "_request_with_retries", fake_request)

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        monkeypatch.setattr(module.httpx, "AsyncClient", _Client)
        assert (await service.get_upstream_task_status(batch.id, "a"))["status"] == "unknown"
        assert (await service.get_upstream_task_status(batch.id, "b"))["status"] == "failed"
        assert (await service.get_upstream_task_status(batch.id, "c"))["error"].startswith("上游任务已完成")
        assert (await service.get_upstream_task_status(batch.id, "d"))["status"] == "generating"

        assert await service.submit_provider_test(99999, "p", {}) is None
        submitted = await service.submit_provider_test(provider.id, "test prompt", {"width": 1024}, user_id=7)
        task_id = int(submitted["task_id"])
        assert (await service.get_provider_test_status(task_id))["status"] == "queued"
        assert await service.get_provider_test_status(99999) is None

        async def fake_test(provider_id, prompt, params):
            return {
                "status": "completed",
                "image_urls": ["test.png"],
                "error": None,
                "elapsed_seconds": 1.2,
                "provider": {"id": provider_id},
            }

        monkeypatch.setattr(service, "test_provider", fake_test)
        executed = await service.execute_provider_test_task(task_id)
        assert executed["status"] == "completed"
        assert executed["image_urls"] == ["test.png"]
        assert (await service.execute_provider_test_task(task_id))["status"] == "completed"
        db.add(AITask(id=999, user_id=1, model_name="other", prompt="x", status="queued"))
        await db.commit()
        assert (await service.execute_provider_test_task(999))["status"] == "queued"
        assert await service.execute_provider_test_task(998) is None


@pytest.mark.asyncio
async def test_test_provider_health_and_call_dispatch(client, monkeypatch):
    async with async_session() as db:
        service = AIImageProviderService(db)
        assert (await service.test_provider(99999, "p", {}))["status"] == "missing"
        provider = _provider(id=301)
        batch = _provider(id=302, provider_kind="mentalout_batch")
        unknown = _provider(id=303, provider_kind="unknown")
        db.add_all([provider, batch, unknown])
        await db.commit()

        async def success(*args, **kwargs):
            return {"status": "completed", "image_urls": ["x.png"]}

        monkeypatch.setattr(service, "_call_provider", success)
        assert (await service.test_provider(provider.id, "p", {}))["status"] == "completed"

        async def failure(*args, **kwargs):
            raise RuntimeError("failed")

        monkeypatch.setattr(service, "_call_provider", failure)
        assert (await service.test_provider(provider.id, "p", {}))["status"] == "failed"

        async def healthy(_provider):
            return "healthy", None

        async def degraded(_provider):
            return "degraded", "slow"

        monkeypatch.setattr(service, "_probe_openai_generation", healthy)
        monkeypatch.setattr(service, "_probe_batch_generation", degraded)
        assert (await service.health_check(provider.id))["healthy"] is True
        assert (await service.health_check(batch.id))["status"] == "degraded"
        assert (await service.health_check(unknown.id))["status"] == "unhealthy"
        assert (await service.health_check(99999))["status"] == "missing"

        monkeypatch.setattr(service, "_call_openai_images", success)
        monkeypatch.setattr(service, "_call_mentalout_batch", success)
        assert (await AIImageProviderService._call_provider(service, provider, "p", {}))["status"] == "completed"
        assert (await AIImageProviderService._call_provider(service, batch, "p", {}))["status"] == "completed"
        with pytest.raises(ValueError, match="不支持"):
            await AIImageProviderService._call_provider(service, unknown, "p", {})
