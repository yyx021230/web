"""Failure recovery contracts for the optional XHS scrape lab client."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import settings
from app.services.xhs_scrape_lab import XHSScrapeLabClient


class _Response:
    def __init__(self, status_code: int = 200, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True}
        self.text = text

    def json(self) -> dict:
        return self._payload


def test_scrape_lab_configuration_port_and_timeout_helpers(monkeypatch, tmp_path):
    client = XHSScrapeLabClient("http://localhost:19001/")
    assert client.base_url == "http://localhost:19001"
    assert client.host == "localhost"
    assert client.port == 19001
    assert client._is_local_target() is True
    assert XHSScrapeLabClient("https://remote.test").port == 443
    assert XHSScrapeLabClient("http://remote.test").port == 80
    assert XHSScrapeLabClient("http://remote.test")._is_local_target() is False

    server = tmp_path / "lab" / "server.py"
    server.parent.mkdir()
    server.write_text("pass", encoding="utf-8")
    monkeypatch.setattr(settings, "xhs_scrape_lab_server_path", str(server))
    monkeypatch.setattr(settings, "xhs_scrape_lab_log_dir", str(tmp_path / "custom-logs"))
    monkeypatch.setattr(settings, "xhs_scrape_lab_python_path", "/python/test")
    assert client._resolve_server_path() == server.resolve()
    assert client._resolve_log_dir() == (tmp_path / "custom-logs").resolve()
    assert client._resolve_python_bin() == "/python/test"

    monkeypatch.setattr("app.services.xhs_scrape_lab.socket.create_connection", lambda *args, **kwargs: SimpleNamespace(__enter__=lambda self: self, __exit__=lambda *args: None))
    # SimpleNamespace special methods are not used for protocol lookup, so use a tiny context type.
    class _SocketContext:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr("app.services.xhs_scrape_lab.socket.create_connection", lambda *args, **kwargs: _SocketContext())
    assert client._is_port_open() is True

    def refused(*args, **kwargs):
        raise OSError("closed")

    monkeypatch.setattr("app.services.xhs_scrape_lab.socket.create_connection", refused)
    assert client._is_port_open() is False
    assert client._build_timeout({"maxItems": 1}).read == 240
    assert client._build_timeout({"maxItems": 999}).read == 1800


@pytest.mark.asyncio
async def test_scrape_lab_health_wait_and_local_server_boot(monkeypatch, tmp_path):
    client = XHSScrapeLabClient("http://127.0.0.1:19002")
    client._is_port_open = lambda: True
    assert await client._wait_until_ready(timeout_seconds=0.01) is True
    client._is_port_open = lambda: False
    assert await client._wait_until_ready(timeout_seconds=0) is False

    class _HttpClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            return _Response(status_code=404)

    monkeypatch.setattr("app.services.xhs_scrape_lab.httpx.AsyncClient", _HttpClient)
    assert await client._healthcheck_ok() is True

    class _BrokenHttpClient(_HttpClient):
        async def get(self, url):
            raise httpx.ConnectError("down")

    monkeypatch.setattr("app.services.xhs_scrape_lab.httpx.AsyncClient", _BrokenHttpClient)
    assert await client._healthcheck_ok() is False

    remote = XHSScrapeLabClient("https://remote.test")
    assert await remote._ensure_local_server() is False

    client._is_port_open = lambda: True
    client._healthcheck_ok = AsyncMock(return_value=True)
    assert await client._ensure_local_server() is True

    missing = tmp_path / "missing.py"
    client._is_port_open = lambda: False
    client._resolve_server_path = lambda: missing
    assert await client._ensure_local_server() is False

    server = tmp_path / "lab" / "server.py"
    server.parent.mkdir()
    server.write_text("pass", encoding="utf-8")
    log_dir = tmp_path / "logs"
    client._resolve_server_path = lambda: server
    client._resolve_log_dir = lambda: log_dir
    client._resolve_python_bin = lambda: "/python/test"
    client._wait_until_ready = AsyncMock(return_value=True)
    def popen(*args, **kwargs):
        return SimpleNamespace(pid=10)

    monkeypatch.setattr("app.services.xhs_scrape_lab.subprocess.Popen", popen)
    assert await client._ensure_local_server() is True
    assert (log_dir / "server.log").exists()


@pytest.mark.asyncio
async def test_scrape_success_timeout_transport_and_http_recovery(monkeypatch, tmp_path):
    client = XHSScrapeLabClient("http://127.0.0.1:19003")
    client._post_scrape = AsyncMock(return_value=_Response(payload={"ok": True, "items": [1]}))
    assert (await client.scrape({"maxItems": 2}))["items"] == [1]

    client._post_scrape = AsyncMock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(RuntimeError, match="执行超时"):
        await client.scrape({"maxItems": 2})

    recovered = _Response(payload={"ok": True, "recovered": True})
    client._post_scrape = AsyncMock(side_effect=[httpx.ConnectError("down"), recovered])
    client._ensure_local_server = AsyncMock(return_value=True)
    assert (await client.scrape({}))["recovered"] is True

    remote = XHSScrapeLabClient("https://remote.test")
    remote._post_scrape = AsyncMock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(RuntimeError, match="抓取服务不可用"):
        await remote.scrape({})

    client._post_scrape = AsyncMock(
        side_effect=[_Response(status_code=503, text="restart"), _Response(payload={"ok": True, "retried": True})]
    )
    client._healthcheck_ok = AsyncMock(return_value=False)
    client._ensure_local_server = AsyncMock(return_value=True)
    assert (await client.scrape({}))["retried"] is True

    client._resolve_log_dir = lambda: Path(tmp_path)
    client._post_scrape = AsyncMock(return_value=_Response(status_code=500, text="lab exploded"))
    client._healthcheck_ok = AsyncMock(return_value=True)
    with pytest.raises(RuntimeError, match="本地抓取服务异常") as local_error:
        await client.scrape({})
    assert "lab exploded" in str(local_error.value)

    remote._post_scrape = AsyncMock(return_value=_Response(status_code=400, text="bad payload"))
    with pytest.raises(RuntimeError, match="bad payload"):
        await remote.scrape({})
    remote._post_scrape = AsyncMock(return_value=_Response(status_code=400, text=""))
    with pytest.raises(RuntimeError, match="HTTP 400"):
        await remote.scrape({})

    remote._post_scrape = AsyncMock(return_value=_Response(payload={"ok": False, "error": "business failed"}))
    with pytest.raises(RuntimeError, match="business failed"):
        await remote.scrape({})
    remote._post_scrape = AsyncMock(return_value=_Response(payload={"ok": False}))
    with pytest.raises(RuntimeError, match="抓取失败"):
        await remote.scrape({})
