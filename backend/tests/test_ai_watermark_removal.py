from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.config import settings
from app.services import ai_image_service as service_module
from app.services.ai_image_service import (
    AIImageService,
    WatermarkRemovalError,
    _watermark_endpoint,
)


class _FakeStorage:
    def __init__(self) -> None:
        self.saved: list[tuple[bytes, str, str, str]] = []

    async def save(self, content: bytes, filename: str, content_type: str, subdir: str) -> str:
        self.saved.append((content, filename, content_type, subdir))
        return f"/uploads/{subdir}/{filename}"


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"", content_type: str = "image/png") -> None:
        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": content_type}
        self.text = content.decode("utf-8", errors="replace")


def _service() -> AIImageService:
    return object.__new__(AIImageService)


def _source_image(tmp_path: Path, name: str = "source.png") -> tuple[str, bytes]:
    content = b"\x89PNG\r\n\x1a\nsource-image"
    local_path = tmp_path / "ai-images" / name
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(content)
    return f"/uploads/ai-images/{name}", content


def _install_http_client(monkeypatch, responses: list[_FakeResponse], calls: list[dict]) -> None:
    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.timeout = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, files: dict):
            calls.append({"url": url, "files": files, "timeout": self.timeout})
            return responses.pop(0)

    monkeypatch.setattr(service_module.httpx, "AsyncClient", FakeClient)


def test_watermark_endpoint_accepts_base_or_full_url():
    assert _watermark_endpoint("http://service:8899") == "http://service:8899/remove-watermark"
    assert (
        _watermark_endpoint("http://47.98.127.132/pureimage/watermark-api/remove-watermark/")
        == "http://47.98.127.132/pureimage/watermark-api/remove-watermark"
    )


@pytest.mark.asyncio
async def test_remove_watermark_uses_full_endpoint_and_persists_clean_image(tmp_path, monkeypatch):
    source_url, source_bytes = _source_image(tmp_path)
    cleaned_bytes = b"\x89PNG\r\n\x1a\ncleaned-image"
    calls: list[dict] = []
    storage = _FakeStorage()
    _install_http_client(monkeypatch, [_FakeResponse(200, cleaned_bytes)], calls)
    monkeypatch.setattr(service_module, "get_storage", lambda: storage)
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    monkeypatch.setattr(settings, "remove_ai_watermarks_enabled", True)
    monkeypatch.setattr(
        settings,
        "remove_ai_watermarks_api_url",
        "http://47.98.127.132/pureimage/watermark-api/remove-watermark",
    )
    monkeypatch.setattr(settings, "remove_ai_watermarks_strict", True)

    result = await _service()._remove_watermarks([source_url])

    assert len(result) == 1
    assert result[0].startswith("/uploads/ai-images/ai_clean_")
    assert result[0] != source_url
    assert calls[0]["url"] == "http://47.98.127.132/pureimage/watermark-api/remove-watermark"
    assert calls[0]["files"]["image"][1] == source_bytes
    assert calls[0]["files"]["image"][2] == "image/png"
    assert storage.saved[0][0] == cleaned_bytes
    assert storage.saved[0][2:] == ("image/png", "ai-images")


@pytest.mark.asyncio
async def test_remove_watermark_retries_busy_service_then_succeeds(tmp_path, monkeypatch):
    source_url, _ = _source_image(tmp_path)
    calls: list[dict] = []
    storage = _FakeStorage()
    _install_http_client(
        monkeypatch,
        [_FakeResponse(503, b"busy", "text/plain"), _FakeResponse(200, b"\x89PNG\r\n\x1a\nclean")],
        calls,
    )

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(service_module.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(service_module, "get_storage", lambda: storage)
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    monkeypatch.setattr(settings, "remove_ai_watermarks_enabled", True)
    monkeypatch.setattr(settings, "remove_ai_watermarks_api_url", "http://service:8899")
    monkeypatch.setattr(settings, "remove_ai_watermarks_retries", 2)
    monkeypatch.setattr(settings, "remove_ai_watermarks_retry_delay_seconds", 0.01)
    monkeypatch.setattr(settings, "remove_ai_watermarks_strict", True)

    result = await _service()._remove_watermarks([source_url])

    assert len(calls) == 2
    assert calls[0]["url"] == "http://service:8899/remove-watermark"
    assert result[0].startswith("/uploads/ai-images/ai_clean_")


@pytest.mark.asyncio
async def test_strict_watermark_failure_never_returns_original(monkeypatch):
    async def fail(*_args, **_kwargs):
        raise WatermarkRemovalError("service unavailable")

    monkeypatch.setattr(settings, "remove_ai_watermarks_enabled", True)
    monkeypatch.setattr(settings, "remove_ai_watermarks_api_url", "http://service:8899")
    monkeypatch.setattr(settings, "remove_ai_watermarks_strict", True)
    service = _service()
    monkeypatch.setattr(service, "_remove_watermark_single", fail)

    with pytest.raises(WatermarkRemovalError, match="图片已生成，但去水印处理失败"):
        await service._remove_watermarks(["/uploads/ai-images/source.png"])


@pytest.mark.asyncio
async def test_non_strict_watermark_failure_can_fall_back_to_original(monkeypatch):
    async def fail(*_args, **_kwargs):
        raise WatermarkRemovalError("service unavailable")

    service = _service()
    monkeypatch.setattr(settings, "remove_ai_watermarks_enabled", True)
    monkeypatch.setattr(settings, "remove_ai_watermarks_api_url", "http://service:8899")
    monkeypatch.setattr(settings, "remove_ai_watermarks_strict", False)
    monkeypatch.setattr(service, "_remove_watermark_single", fail)

    source_url = "/uploads/ai-images/source.png"
    assert await service._remove_watermarks([source_url]) == [source_url]


@pytest.mark.asyncio
async def test_watermark_requests_respect_configured_concurrency(tmp_path, monkeypatch):
    storage = _FakeStorage()
    active = 0
    peak = 0

    class SlowClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, _url: str, files: dict):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return _FakeResponse(200, b"\x89PNG\r\n\x1a\nclean")

    monkeypatch.setattr(service_module.httpx, "AsyncClient", SlowClient)
    monkeypatch.setattr(service_module, "get_storage", lambda: storage)
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    monkeypatch.setattr(settings, "remove_ai_watermarks_api_url", "http://service:8899")
    monkeypatch.setattr(settings, "remove_ai_watermarks_max_concurrent", 2)

    urls = [_source_image(tmp_path, f"source-{index}.png")[0] for index in range(6)]
    await asyncio.gather(
        *[
            _service()._remove_watermark_single(
                url,
                _watermark_endpoint(settings.remove_ai_watermarks_api_url),
                30,
                tmp_path,
            )
            for url in urls
        ]
    )

    assert peak == 2


@pytest.mark.asyncio
async def test_generation_pipeline_returns_only_cleaned_urls(monkeypatch):
    service = AIImageService(model_name="gptimage2")
    events: list[str] = []

    async def fake_generate(*_args, **_kwargs):
        events.append("generated")
        return {"status": "completed", "image_urls": ["https://upstream/image.png"]}

    async def fake_store(urls: list[str]):
        events.append("stored")
        assert urls == ["https://upstream/image.png"]
        return ["/uploads/ai-images/original.png"]

    async def fake_remove(urls: list[str]):
        events.append("cleaned")
        assert urls == ["/uploads/ai-images/original.png"]
        return ["/uploads/ai-images/cleaned.png"]

    async def fake_mirror(*_args, **_kwargs):
        return None

    monkeypatch.setattr(service, "_generate_with_configured_provider", fake_generate)
    monkeypatch.setattr(service, "_remove_watermarks", fake_remove)
    monkeypatch.setattr(service_module, "_store_images", fake_store)
    monkeypatch.setattr(service_module, "mirror_ai_image_shadow_safely", fake_mirror)

    _result, raw_urls, final_urls = await service._run_generation_pipeline(
        "prompt",
        {"width": 768, "height": 1024},
    )

    assert events == ["generated", "stored", "cleaned"]
    assert raw_urls == ["https://upstream/image.png"]
    assert final_urls == ["/uploads/ai-images/cleaned.png"]


@pytest.mark.asyncio
async def test_ten_generation_tasks_share_four_watermark_slots(tmp_path, monkeypatch):
    storage = _FakeStorage()
    active = 0
    peak = 0
    request_count = 0

    class SlowClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, _url: str, files: dict):
            nonlocal active, peak, request_count
            active += 1
            peak = max(peak, active)
            request_count += 1
            try:
                await asyncio.sleep(0.02)
                source_bytes = files["image"][1]
                return _FakeResponse(200, b"\x89PNG\r\n\x1a\ncleaned-" + source_bytes)
            finally:
                active -= 1

    async def fake_store(urls: list[str]) -> list[str]:
        stored: list[str] = []
        for upstream_url in urls:
            filename = upstream_url.rsplit("/", 1)[-1]
            local_path = tmp_path / "ai-images" / filename
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(b"\x89PNG\r\n\x1a\nsource-" + filename.encode())
            stored.append(f"/uploads/ai-images/{filename}")
        return stored

    async def fake_mirror(*_args, **_kwargs):
        return None

    monkeypatch.setattr(service_module.httpx, "AsyncClient", SlowClient)
    monkeypatch.setattr(service_module, "get_storage", lambda: storage)
    monkeypatch.setattr(service_module, "_store_images", fake_store)
    monkeypatch.setattr(service_module, "mirror_ai_image_shadow_safely", fake_mirror)
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    monkeypatch.setattr(settings, "remove_ai_watermarks_enabled", True)
    monkeypatch.setattr(settings, "remove_ai_watermarks_api_url", "http://service:8899")
    monkeypatch.setattr(settings, "remove_ai_watermarks_strict", True)
    monkeypatch.setattr(settings, "remove_ai_watermarks_max_concurrent", 4)

    services: list[AIImageService] = []
    for index in range(10):
        service = AIImageService(model_name="gptimage2")

        async def fake_generate(*_args, task_index=index, **_kwargs):
            return {
                "status": "completed",
                "image_urls": [f"https://upstream/task-{task_index}.png"],
            }

        monkeypatch.setattr(service, "_generate_with_configured_provider", fake_generate)
        services.append(service)

    results = await asyncio.gather(
        *[
            service._run_generation_pipeline(
                f"prompt-{index}",
                {"width": 768, "height": 1024},
                task_id=index + 1,
            )
            for index, service in enumerate(services)
        ]
    )

    final_urls = [item[2][0] for item in results]
    assert request_count == 10
    assert peak == 4
    assert len(storage.saved) == 10
    assert len(final_urls) == 10
    assert all(url.startswith("/uploads/ai-images/ai_clean_") for url in final_urls)
    assert all("task-" not in url for url in final_urls)
