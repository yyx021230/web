from __future__ import annotations

import asyncio
import base64

import httpx
import pytest

from app.adapters.ai_model.seedream import (
    SeedreamAdapter,
    _format_api_error,
    _infer_mime,
    _normalize_reference_source,
    _resolve_size,
    _uploads_url_to_data_uri,
)
from app.adapters.storage.local import LocalStorageAdapter
from app.adapters.storage.s3 import S3StorageAdapter
from app.config import settings


def test_seedream_helpers_format_errors_mime_and_sizes():
    assert _format_api_error(400, '{"error":{"code":"bad_size","message":"invalid"}}') == (
        "API 错误 (400)，bad_size：invalid"
    )
    assert _format_api_error(400, "plain failure") == "API 错误 (400)，plain failure"
    assert _format_api_error(400, "") == "API 错误 (400)，请稍后重试"
    assert _infer_mime(b"\x89PNG\r\n\x1a\n") == "image/png"
    assert _infer_mime(b"\xff\xd8jpeg") == "image/jpeg"
    assert _infer_mime(b"RIFFxxxx") == "image/webp"
    assert _infer_mime(b"GIF89xxx") == "image/gif"
    assert _infer_mime(b"unknown") == "image/png"
    assert _resolve_size(1680, 2240) == "1680x2240"
    assert _resolve_size(768, 1024) == "1680x2240"
    assert _resolve_size(1024, 768) == "2240x1680"


def test_seedream_local_reference_is_converted_and_cannot_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    image = tmp_path / "refs" / "car.png"
    image.parent.mkdir()
    image.write_bytes(b"\x89PNGpayload")
    data_uri = _uploads_url_to_data_uri("/uploads/refs/car.png?version=1")
    assert data_uri.startswith("data:image/png;base64,")
    assert base64.b64decode(data_uri.split(",", 1)[1]) == b"\x89PNGpayload"
    assert _normalize_reference_source("https://cdn/ref.png") == "https://cdn/ref.png"
    with pytest.raises(ValueError, match="非法参考图路径"):
        _uploads_url_to_data_uri("/uploads/../secret.png")


class SeedreamResponse:
    def __init__(self, payload, status_code=200, text=""):
        self.payload = payload
        self.status_code = status_code
        self.text = text
        self.request = httpx.Request("POST", "https://ark.example/images")

    def raise_for_status(self):
        if self.status_code >= 400:
            response = httpx.Response(
                self.status_code,
                request=self.request,
                text=self.text,
            )
            raise httpx.HTTPStatusError("failed", request=self.request, response=response)

    def json(self):
        return self.payload


class SeedreamClient:
    responses: list[SeedreamResponse] = []
    requests: list[dict] = []

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, **kwargs):
        self.requests.append({"url": url, **kwargs})
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_seedream_generate_success_payload_and_reference_priority(monkeypatch):
    adapter = SeedreamAdapter()
    monkeypatch.setattr(settings, "seedream_api_key", "sk-test")
    monkeypatch.setattr(settings, "seedream_api_url", "https://ark.example/images")
    monkeypatch.setattr("app.adapters.ai_model.seedream.httpx.AsyncClient", SeedreamClient)
    SeedreamClient.requests = []
    SeedreamClient.responses = [
        SeedreamResponse({"id": "task-1", "data": [{"url": "https://cdn/1.png"}, {}, {"url": "https://cdn/2.png"}]})
    ]

    result = await adapter.generate_image(
        "汽车海报",
        negative_prompt="模糊",
        width=768,
        height=1024,
        images_data=["one", "two"] * 6,
        image_data="ignored",
        image_url="ignored",
    )
    assert result == {
        "task_id": "task-1",
        "status": "completed",
        "image_urls": ["https://cdn/1.png", "https://cdn/2.png"],
    }
    request = SeedreamClient.requests[0]
    assert request["headers"]["Authorization"] == "Bearer sk-test"
    assert request["json"]["size"] == "1680x2240"
    assert request["json"]["negative_prompt"] == "模糊"
    assert request["json"]["watermark"] is False
    assert len(request["json"]["image"]) == 10


@pytest.mark.asyncio
async def test_seedream_generate_requires_key_and_maps_http_errors(monkeypatch):
    adapter = SeedreamAdapter()
    monkeypatch.setattr(settings, "seedream_api_key", "")
    with pytest.raises(ValueError, match="API_KEY"):
        await adapter.generate_image("test")

    monkeypatch.setattr(settings, "seedream_api_key", "sk-test")
    monkeypatch.setattr("app.adapters.ai_model.seedream.httpx.AsyncClient", SeedreamClient)
    for status, expected in (
        (403, "配额已用尽"),
        (429, "请求过于频繁"),
        (524, "暂时不可用"),
        (400, "bad_request：bad image"),
    ):
        SeedreamClient.responses = [SeedreamResponse(
            {},
            status_code=status,
            text='{"error":{"code":"bad_request","message":"bad image"}}',
        )]
        result = await adapter.generate_image("test")
        assert expected in result["error"]


@pytest.mark.asyncio
async def test_seedream_generate_maps_empty_and_business_error_responses(monkeypatch):
    adapter = SeedreamAdapter()
    monkeypatch.setattr(settings, "seedream_api_key", "sk-test")
    monkeypatch.setattr("app.adapters.ai_model.seedream.httpx.AsyncClient", SeedreamClient)
    responses = [
        SeedreamResponse({"data": [{}]}),
        SeedreamResponse({"error": {"code": 500341, "message": "limited"}}),
        SeedreamResponse({"error": {"code": 500001, "message": "billing"}}),
        SeedreamResponse({"error": "plain error"}),
        SeedreamResponse({"unexpected": True}),
    ]
    SeedreamClient.responses = responses
    results = [await adapter.generate_image("test") for _ in range(len(responses))]
    assert results[0]["error"] == "返回数据中没有图片 URL"
    assert "速率限制" in results[1]["error"]
    assert "配额/计费异常" in results[2]["error"]
    assert results[3]["error"] == "plain error"
    assert results[4]["error"].startswith("未知响应格式")
    assert await adapter.cancel_task("task") is None
    assert (await adapter.get_task_status("task"))["status"] == "completed"


@pytest.mark.asyncio
async def test_local_storage_save_delete_and_path_safety(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_path", str(tmp_path / "uploads"))
    storage = LocalStorageAdapter()
    url = await storage.save(b"image", "cover.png", "image/png", subdir="ai-images")
    assert url.startswith("/uploads/ai-images/")
    file_path = storage.storage_path / url.removeprefix("/uploads/")
    assert file_path.read_bytes() == b"image"
    assert await storage.get_url("cover.png") == "/uploads/cover.png"
    await storage.delete(url + "?v=1")
    assert not file_path.exists()

    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    with pytest.raises(ValueError, match="非法存储路径"):
        await storage.save(b"bad", "bad.png", subdir="../")
    with pytest.raises(ValueError, match="非法存储路径"):
        await storage.delete("/uploads/../outside.txt")
    assert outside.read_text() == "keep"


@pytest.mark.asyncio
async def test_s3_storage_bucket_upload_delete_and_signed_url(monkeypatch):
    class MinioClient:
        def __init__(self, *args, **kwargs):
            self.init = (args, kwargs)
            self.created = []
            self.put = []
            self.deleted = []

        def bucket_exists(self, _bucket):
            return False

        def make_bucket(self, bucket):
            self.created.append(bucket)

        def put_object(self, *args, **kwargs):
            self.put.append((args, kwargs))

        def remove_object(self, *args):
            self.deleted.append(args)

        def presigned_get_object(self, bucket, filename, expires):
            return f"signed://{bucket}/{filename}?expires={expires}"

    client = MinioClient()
    monkeypatch.setattr("app.adapters.storage.s3.Minio", lambda *args, **kwargs: client)
    monkeypatch.setattr(settings, "s3_endpoint", "https://s3.example")
    monkeypatch.setattr(settings, "s3_access_key", "ak")
    monkeypatch.setattr(settings, "s3_secret_key", "sk")
    monkeypatch.setattr(settings, "s3_bucket", "bucket")

    async def run_in_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", run_in_thread)
    storage = S3StorageAdapter()
    assert client.created == ["bucket"]
    url = await storage.save(b"content", "asset.webp", "image/webp", subdir="gallery")
    assert url.startswith("https://s3.example/bucket/gallery/")
    assert client.put[0][0][0] == "bucket"
    assert client.put[0][1]["content_type"] == "image/webp"
    await storage.delete(url)
    assert client.deleted[0][0] == "bucket"
    assert client.deleted[0][1].startswith("gallery/")
    assert await storage.get_url("gallery/a.webp", expires=60) == (
        "signed://bucket/gallery/a.webp?expires=60"
    )


def test_storage_factory_is_lazy_singleton_and_falls_back_to_local(tmp_path, monkeypatch):
    import app.adapters.storage as storage_module

    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    monkeypatch.setattr(settings, "storage_type", "unknown")
    monkeypatch.setattr(storage_module, "_storage_instance", None)
    first = storage_module.get_storage()
    second = storage_module.get_storage()
    assert isinstance(first, LocalStorageAdapter)
    assert first is second
    assert storage_module.storage is first
    with pytest.raises(AttributeError):
        storage_module.__getattr__("missing")
