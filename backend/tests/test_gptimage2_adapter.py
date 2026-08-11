from __future__ import annotations

import base64
from unittest.mock import AsyncMock

import httpx
import pytest

from app.adapters.ai_model.gptimage2 import (
    GPTImage2Adapter,
    _batch_failure_status,
    _batch_success_status,
    _batch_task_error,
    _batch_task_image_url,
    _collect_reference_sources,
    _download_image_bytes,
    _download_reference_file,
    _infer_mime,
    _is_batch_gateway,
    _normalize_api_url,
    _normalize_batch_base_url,
    _normalize_image_quality,
    _normalize_legacy_batch_api_base,
    _read_uploads_url,
    _request_with_retries,
    _resolve_image_size,
    _save_b64_to_local,
    _short_text,
)
from app.config import settings


class FakeResponse:
    def __init__(
        self,
        payload=None,
        *,
        status_code: int = 200,
        text: str = "",
        headers: dict | None = None,
        content: bytes = b"",
        json_error: Exception | None = None,
    ):
        self.payload = payload
        self.status_code = status_code
        self.text = text
        self.headers = headers or {"content-type": "application/json"}
        self.content = content
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://upstream.example")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("failed", request=request, response=response)


def test_gptimage2_helpers_cover_normalization_and_statuses():
    assert _short_text("abcdef", 3) == "abc..."
    assert _short_text("abc", 3) == "abc"
    assert _normalize_image_quality(" HIGH ") == "high"
    assert _normalize_image_quality("ultra") == "low"
    assert _infer_mime(b"\x89PNGxxxx") == "image/png"
    assert _infer_mime(b"\xff\xd8xxxx") == "image/jpeg"
    assert _infer_mime(b"RIFFxxxx") == "image/webp"
    assert _infer_mime(b"GIF89xxx") == "image/gif"
    assert _infer_mime(b"unknown") == "image/png"

    assert _is_batch_gateway("https://image.mentalout.top") is True
    assert _is_batch_gateway("https://host/api/batches") is True
    assert _is_batch_gateway("https://api.openai.com/v1") is False
    assert _normalize_batch_base_url("https://host/api/batches") == "https://host"
    assert _normalize_api_url("https://host/v1/images/edits") == (
        "https://host/v1",
        "/images/edits",
    )
    assert _normalize_api_url("https://host/v1") == (
        "https://host/v1",
        "/images/generations",
    )
    assert _normalize_legacy_batch_api_base("https://host/v1/images/generations") == "https://host"

    assert _batch_success_status(" FINISHED ") is True
    assert _batch_failure_status("cancelled") is True
    assert _batch_task_error({"debugMessage": "upstream 524"}) == "upstream 524"
    assert _batch_task_image_url(
        {"result": {"output_url": "/generated/a.png"}},
        "https://host",
    ) == "https://host/generated/a.png"
    assert _batch_task_image_url({}, "https://host") is None

    assert _collect_reference_sources(["a", "", 1], "b", "c") == ["a"]
    assert _collect_reference_sources([], "b", "c") == ["b"]
    assert _collect_reference_sources(None, None, "c") == ["c"]
    assert _collect_reference_sources(None, None, None) == []


@pytest.mark.parametrize(
    ("width", "height", "message"),
    [
        (0, 1024, "正数"),
        (4096, 1024, "最大"),
        (1000, 1024, "16px"),
        (512, 2048, "3:1"),
        (512, 512, "总像素"),
        (3840, 3840, "总像素"),
    ],
)
def test_resolve_image_size_rejects_invalid_dimensions(width, height, message):
    with pytest.raises(ValueError, match=message):
        _resolve_image_size(width, height)


def test_upload_reference_read_and_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    image = tmp_path / "ai-images" / "ref image.png"
    image.parent.mkdir()
    image.write_bytes(b"\x89PNGpayload")

    image_bytes, mime = _read_uploads_url("/uploads/ai-images/ref%20image.png?x=1")
    assert image_bytes == b"\x89PNGpayload"
    assert mime == "image/png"
    with pytest.raises(ValueError, match="非法参考图路径"):
        _read_uploads_url("/uploads/../secret.txt")


@pytest.mark.asyncio
async def test_download_helpers_support_data_uri_local_and_network(tmp_path, monkeypatch):
    raw = b"\xff\xd8jpeg"
    data_uri = "data:image/jpeg;base64," + base64.b64encode(raw).decode()
    assert await _download_image_bytes(data_uri) == raw
    filename, content, mime = await _download_reference_file(data_uri)
    assert (filename, content, mime) == ("ref.jpg", raw, "image/jpeg")

    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    local = tmp_path / "refs" / "local.webp"
    local.parent.mkdir()
    local.write_bytes(b"RIFFpayload")
    assert await _download_image_bytes("/uploads/refs/local.webp") == b"RIFFpayload"

    async def fake_request(_client, method, url, **_kwargs):
        assert (method, url) == ("GET", "https://cdn.example/ref.png")
        return FakeResponse(
            content=b"\x89PNGnetwork",
            headers={"content-type": "image/png"},
        )

    monkeypatch.setattr("app.adapters.ai_model.gptimage2._request_with_retries", fake_request)
    assert await _download_image_bytes("https://cdn.example/ref.png") == b"\x89PNGnetwork"
    filename, content, mime = await _download_reference_file("https://cdn.example/ref.png")
    assert (filename, content, mime) == ("ref.png", b"\x89PNGnetwork", "image/png")


@pytest.mark.asyncio
async def test_request_with_retries_retries_request_errors(monkeypatch):
    request = httpx.Request("GET", "https://upstream.example")

    class FakeClient:
        calls = 0

        async def request(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls < 3:
                raise httpx.ConnectError("offline", request=request)
            return FakeResponse({"ok": True})

    monkeypatch.setattr("app.adapters.ai_model.gptimage2.asyncio.sleep", AsyncMock())
    client = FakeClient()
    result = await _request_with_retries(client, "GET", str(request.url), retry_delay=0)  # type: ignore[arg-type]
    assert result.json() == {"ok": True}
    assert client.calls == 3

    failing = FakeClient()
    failing.calls = 0

    async def always_fail(*_args, **_kwargs):
        raise httpx.ConnectError("offline", request=request)

    failing.request = always_fail  # type: ignore[method-assign]
    with pytest.raises(httpx.ConnectError):
        await _request_with_retries(failing, "GET", str(request.url), retries=1)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_generate_image_dispatches_and_requires_key(monkeypatch):
    adapter = GPTImage2Adapter()
    monkeypatch.setattr("app.adapters.ai_model.gptimage2._read_backend_env_overrides", lambda: (None, None))
    monkeypatch.setattr(settings, "gpt_image2_api_key", "")
    with pytest.raises(ValueError, match="API_KEY"):
        await adapter.generate_image("test")

    monkeypatch.setattr(
        "app.adapters.ai_model.gptimage2._read_backend_env_overrides",
        lambda: ("sk-env", "https://image.mentalout.top/api/batches"),
    )
    batch = AsyncMock(return_value={"status": "completed"})
    monkeypatch.setattr(adapter, "_generate_with_batch_gateway", batch)
    result = await adapter.generate_image("batch", count=9)
    assert result["status"] == "completed"
    assert batch.await_args.kwargs["api_key"] == "sk-env"

    monkeypatch.setattr(
        "app.adapters.ai_model.gptimage2._read_backend_env_overrides",
        lambda: ("sk-env", "https://api.example/v1/images/generations"),
    )
    direct = AsyncMock(return_value={"status": "completed"})
    monkeypatch.setattr(adapter, "_generate_with_openai_compatible", direct)
    await adapter.generate_image("direct", width=768, height=1024)
    assert direct.await_args.kwargs["api_url"].endswith("/images/generations")


@pytest.mark.asyncio
async def test_openai_compatible_text_and_reference_requests(monkeypatch):
    adapter = GPTImage2Adapter()
    calls: list[dict] = []

    async def fake_request(_client, method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return FakeResponse({"id": "task-1", "data": [{"url": f"https://cdn/{len(calls)}.png"}]})

    monkeypatch.setattr("app.adapters.ai_model.gptimage2._request_with_retries", fake_request)
    text_result = await adapter._generate_with_openai_compatible(
        prompt="portrait",
        width=768,
        height=1024,
        quality="HIGH",
        count=5,
        image_data=None,
        image_url=None,
        images_data=None,
        api_url="https://api.example/v1/images/generations",
        api_key="sk-test",
    )
    assert text_result == {
        "task_id": "task-1",
        "status": "completed",
        "image_urls": [f"https://cdn/{index}.png" for index in range(1, 5)],
    }
    assert len(calls) == 4
    assert calls[0]["json"]["size"] == "768x1024"
    assert calls[0]["json"]["quality"] == "high"

    calls.clear()
    ref = ("ref.png", b"image", "image/png")
    monkeypatch.setattr("app.adapters.ai_model.gptimage2._download_reference_file", AsyncMock(return_value=ref))
    reference_result = await adapter._generate_with_openai_compatible(
        prompt="edit",
        width=768,
        height=1024,
        quality="unknown",
        count=1,
        image_data="data:image/png;base64,aW1hZ2U=",
        image_url=None,
        images_data=None,
        api_url="https://api.example/v1/images/generations",
        api_key="sk-test",
    )
    assert reference_result["status"] == "completed"
    assert calls[0]["url"].endswith("/images/edits")
    assert calls[0]["files"] == [("image", ref)]
    assert "quality" not in calls[0]["data"]


@pytest.mark.asyncio
async def test_openai_response_errors_empty_and_base64(monkeypatch):
    adapter = GPTImage2Adapter()
    saved = AsyncMock(side_effect=["/uploads/one.png", "/uploads/two.png"])
    monkeypatch.setattr("app.adapters.ai_model.gptimage2._save_b64_to_local", saved)
    urls = await adapter._extract_image_urls(
        {"data": [None, {"url": "https://cdn/a.png"}, {"b64_json": "one"}, {"b64": "two"}]},
        "seed",
    )
    assert urls == ["https://cdn/a.png", "/uploads/one.png", "/uploads/two.png"]
    assert await adapter._extract_image_urls({"data": {}}, "seed") == []

    assert adapter._extract_error_message(FakeResponse({"error": {"message": "quota"}})) == "quota"
    assert adapter._extract_error_message(FakeResponse({"message": "busy"})) == "busy"
    assert adapter._extract_error_message(FakeResponse(None, text="plain", headers={})) == "plain"

    responses = iter([
        FakeResponse({"id": "empty", "data": []}),
        FakeResponse({"error": {"message": "upstream 524"}}, status_code=524),
    ])

    async def fake_request(*_args, **_kwargs):
        return next(responses)

    monkeypatch.setattr("app.adapters.ai_model.gptimage2._request_with_retries", fake_request)
    empty = await adapter._generate_with_openai_compatible(
        prompt="empty", width=768, height=1024, quality=None, count=1,
        image_data=None, image_url=None, images_data=None,
        api_url="https://api.example/v1", api_key="sk",
    )
    assert empty["error"] == "响应中没有图片数据"
    with pytest.raises(ValueError, match="upstream 524"):
        await adapter._generate_with_openai_compatible(
            prompt="error", width=768, height=1024, quality=None, count=1,
            image_data=None, image_url=None, images_data=None,
            api_url="https://api.example/v1", api_key="sk",
        )


@pytest.mark.asyncio
async def test_save_base64_accepts_plain_and_data_uri(monkeypatch):
    class Storage:
        save = AsyncMock(return_value="/uploads/ai-images/result.png")

    storage = Storage()
    monkeypatch.setattr("app.adapters.storage.get_storage", lambda: storage)
    encoded = base64.b64encode(b"png-bytes").decode()

    assert await _save_b64_to_local(encoded) == "/uploads/ai-images/result.png"
    assert await _save_b64_to_local(f"data:image/png;base64,{encoded}") == "/uploads/ai-images/result.png"
    assert storage.save.await_count == 2


@pytest.mark.asyncio
async def test_batch_submission_callback_and_result_storage(monkeypatch):
    adapter = GPTImage2Adapter()
    submitted: list[dict] = []

    async def fake_request(_client, _method, _url, **kwargs):
        submitted.append(kwargs)
        return FakeResponse({"id": "batch-1"})

    callback = AsyncMock()
    monkeypatch.setattr("app.adapters.ai_model.gptimage2._request_with_retries", fake_request)
    monkeypatch.setattr("app.adapters.ai_model.gptimage2._download_image_bytes", AsyncMock(return_value=b"\x89PNGref"))
    monkeypatch.setattr(adapter, "_poll_batch", AsyncMock(return_value={
        "task_id": "batch-1",
        "status": "completed",
        "image_urls": ["data:image/png;base64,aW1hZ2U=", "https://cdn/a.png"],
    }))
    monkeypatch.setattr("app.adapters.ai_model.gptimage2._save_b64_to_local", AsyncMock(return_value="/uploads/a.png"))

    result = await adapter._generate_with_batch_gateway(
        prompt="batch", width=768, height=1024, quality="medium", count=9,
        image_data=None, image_url=None, images_data=["https://cdn/ref.png"],
        api_url="https://image.mentalout.top/api/batches", api_key="sk",
        on_upstream_accepted=callback,
    )
    assert result["image_urls"] == ["/uploads/a.png", "https://cdn/a.png"]
    assert callback.await_args.args[0]["upstream_task_id"] == "batch-1"
    payload_part = submitted[0]["files"][0]
    assert payload_part[0] == "payload"
    assert '"count": 4' in payload_part[1][1]


@pytest.mark.asyncio
async def test_batch_submission_failure_shapes(monkeypatch):
    adapter = GPTImage2Adapter()
    responses = iter([
        FakeResponse(json_error=ValueError("html"), status_code=502, text="bad gateway"),
        FakeResponse({"message": "denied"}, status_code=403),
        FakeResponse({"status": "queued"}),
    ])

    async def fake_request(*_args, **_kwargs):
        return next(responses)

    monkeypatch.setattr("app.adapters.ai_model.gptimage2._request_with_retries", fake_request)
    kwargs = dict(
        prompt="batch", width=768, height=1024, quality=None, count=1,
        image_data=None, image_url=None, images_data=None,
        api_url="https://image.mentalout.top", api_key="sk",
    )
    malformed = await adapter._generate_with_batch_gateway(**kwargs)
    forbidden = await adapter._generate_with_batch_gateway(**kwargs)
    missing_id = await adapter._generate_with_batch_gateway(**kwargs)
    assert "HTTP 502" in malformed["error"]
    assert forbidden["error"] == "HTTP 403: denied"
    assert "没有 batch_id" in missing_id["error"]


@pytest.mark.asyncio
async def test_poll_batch_success_failure_retry_limit_and_timeout(monkeypatch):
    adapter = GPTImage2Adapter()
    monkeypatch.setattr("app.adapters.ai_model.gptimage2.asyncio.sleep", AsyncMock())
    responses = iter([
        FakeResponse({"status": "running", "tasks": []}),
        FakeResponse({"status": "completed", "tasks": [{"imageUrl": "/a.png", "status": "completed"}]}),
        FakeResponse({"status": "completed", "tasks": [{"status": "completed"}]}),
        FakeResponse({"status": "failed", "tasks": [{"errorMessage": "quota"}]}),
        FakeResponse({"status": "retrying", "tasks": [{"attempts": 6, "maxAttempts": 6, "error": "524"}]}),
        FakeResponse({"status": "running", "tasks": []}),
    ])

    async def fake_request(*_args, **_kwargs):
        return next(responses)

    monkeypatch.setattr("app.adapters.ai_model.gptimage2._request_with_retries", fake_request)
    success = await adapter._poll_batch("one", "https://host")
    no_url = await adapter._poll_batch("two", "https://host")
    failed = await adapter._poll_batch("three", "https://host")
    retry_limit = await adapter._poll_batch("four", "https://host")
    monkeypatch.setattr("app.adapters.ai_model.gptimage2._BATCH_MAX_POLLS", 1)
    timeout = await adapter._poll_batch("five", "https://host")

    assert success["image_urls"] == ["https://host/a.png"]
    assert no_url["error"] == "任务成功但无图片 URL"
    assert failed["error"] == "quota"
    assert "最大重试次数" in retry_limit["error"]
    assert "超时" in timeout["error"]


@pytest.mark.asyncio
async def test_get_task_status_direct_batch_and_query_failure(monkeypatch):
    adapter = GPTImage2Adapter()
    monkeypatch.setattr(
        "app.adapters.ai_model.gptimage2._read_backend_env_overrides",
        lambda: ("sk", "https://api.example/v1/images/generations"),
    )
    assert (await adapter.get_task_status("sync"))["status"] == "completed"

    monkeypatch.setattr(
        "app.adapters.ai_model.gptimage2._read_backend_env_overrides",
        lambda: ("sk", "https://image.mentalout.top"),
    )
    responses = iter([
        FakeResponse({"status": "completed", "tasks": [{"url": "https://cdn/a.png"}]}),
        FakeResponse({"status": "failed", "tasks": [{"detail": "blocked"}]}),
        FakeResponse({"status": "queued", "tasks": []}),
    ])

    async def fake_request(*_args, **_kwargs):
        return next(responses)

    monkeypatch.setattr("app.adapters.ai_model.gptimage2._request_with_retries", fake_request)
    assert (await adapter.get_task_status("done"))["status"] == "completed"
    assert (await adapter.get_task_status("bad"))["error"] == "blocked"
    assert (await adapter.get_task_status("waiting"))["status"] == "generating"

    monkeypatch.setattr(
        "app.adapters.ai_model.gptimage2._request_with_retries",
        AsyncMock(side_effect=httpx.ConnectError("offline")),
    )
    assert (await adapter.get_task_status("offline"))["error"] == "查询失败"
    assert await adapter.cancel_task("ignored") is None
