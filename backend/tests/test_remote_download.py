from __future__ import annotations

import socket
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.config import settings
from app.core.remote_download import (
    MAX_REMOTE_IMAGE_BYTES,
    _infer_image_mime,
    _is_forbidden_ip,
    _validate_remote_image_url,
    download_allowed_remote_image,
)


def test_remote_host_validation_rejects_schemes_hosts_and_private_dns(monkeypatch):
    monkeypatch.setattr(settings, "remote_image_allowed_hosts", ["cdn.example.com"])
    with pytest.raises(HTTPException, match="不被允许"):
        _validate_remote_image_url("file:///etc/passwd")
    with pytest.raises(HTTPException, match="不被允许"):
        _validate_remote_image_url("https://evil.example.com/a.png")

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))],
    )
    with pytest.raises(HTTPException, match="不被允许"):
        _validate_remote_image_url("https://cdn.example.com/a.png")


def test_remote_dns_failures_and_invalid_addresses_are_rejected(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        Mock(side_effect=socket.gaierror("missing")),
    )
    with pytest.raises(HTTPException, match="不可解析"):
        _is_forbidden_ip("missing.example")

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("not-an-ip", 0))],
    )
    with pytest.raises(HTTPException, match="来源无效"):
        _is_forbidden_ip("bad.example")

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )
    assert _is_forbidden_ip("public.example") is False


def test_remote_image_mime_detection():
    assert _infer_image_mime(b"\xff\xd8\xffjpeg") == "image/jpeg"
    assert _infer_image_mime(b"\x89PNG\r\n\x1a\npng") == "image/png"
    assert _infer_image_mime(b"GIF87apayload") == "image/gif"
    assert _infer_image_mime(b"RIFFxxxxWEBPpayload") == "image/webp"
    assert _infer_image_mime(b"<html>") is None


class StreamResponse:
    def __init__(self, *, status=200, url="https://cdn.example.com/a", headers=None, chunks=None):
        self.status_code = status
        self.url = url
        self.headers = headers or {}
        self.chunks = chunks or []

    async def aiter_bytes(self):
        for chunk in self.chunks:
            yield chunk


class StreamContext:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *_args):
        return None


class DownloadClient:
    response: StreamResponse

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def stream(self, method, url):
        assert (method, url) == ("GET", "https://cdn.example.com/source")
        return StreamContext(self.response)


@pytest.mark.asyncio
async def test_remote_download_success_detects_type_and_adds_extension(monkeypatch):
    monkeypatch.setattr(
        "app.core.remote_download._validate_remote_image_url",
        Mock(return_value="cdn.example.com"),
    )
    monkeypatch.setattr("app.core.remote_download.httpx.AsyncClient", DownloadClient)
    DownloadClient.response = StreamResponse(
        url="https://cdn.example.com/generated/image",
        headers={"content-type": "application/octet-stream", "content-length": "12"},
        chunks=[b"\x89PNG\r\n\x1a\n", b"data"],
    )
    content, filename, content_type = await download_allowed_remote_image(
        "https://cdn.example.com/source"
    )
    assert content == b"\x89PNG\r\n\x1a\ndata"
    assert filename == "image.png"
    assert content_type == "image/png"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "message"),
    [
        (StreamResponse(status=404), "HTTP 404"),
        (
            StreamResponse(headers={"content-length": str(MAX_REMOTE_IMAGE_BYTES + 1)}),
            "大小超过限制",
        ),
        (StreamResponse(headers={"content-length": "invalid"}), "响应无效"),
        (
            StreamResponse(chunks=[b"x" * (MAX_REMOTE_IMAGE_BYTES + 1)]),
            "大小超过限制",
        ),
        (
            StreamResponse(headers={"content-type": "text/html"}, chunks=[b"<html>"]),
            "不支持",
        ),
    ],
)
async def test_remote_download_rejects_invalid_responses(monkeypatch, response, message):
    monkeypatch.setattr(
        "app.core.remote_download._validate_remote_image_url",
        Mock(return_value="cdn.example.com"),
    )
    monkeypatch.setattr("app.core.remote_download.httpx.AsyncClient", DownloadClient)
    DownloadClient.response = response
    with pytest.raises(HTTPException, match=message):
        await download_allowed_remote_image("https://cdn.example.com/source")


@pytest.mark.asyncio
async def test_remote_download_revalidates_redirect_host(monkeypatch):
    validate = Mock(side_effect=["cdn.example.com", "other.example.com"])
    monkeypatch.setattr("app.core.remote_download._validate_remote_image_url", validate)
    monkeypatch.setattr("app.core.remote_download.httpx.AsyncClient", DownloadClient)
    DownloadClient.response = StreamResponse(
        url="https://other.example.com/a.jpg",
        chunks=[b"\xff\xd8\xffimage"],
    )
    _, filename, content_type = await download_allowed_remote_image(
        "https://cdn.example.com/source"
    )
    assert filename == "a.jpg"
    assert content_type == "image/jpeg"
    assert validate.call_count == 2
