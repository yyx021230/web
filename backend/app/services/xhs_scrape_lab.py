from __future__ import annotations

import asyncio
import os
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.config import settings


class XHSScrapeLabClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.xhs_scrape_lab_base_url).rstrip("/")
        parsed = urlparse(self.base_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = int(parsed.port or (443 if parsed.scheme == "https" else 80))

    def _is_local_target(self) -> bool:
        return self.host in {"127.0.0.1", "localhost", "::1"}

    def _resolve_server_path(self) -> Path:
        if settings.xhs_scrape_lab_server_path:
            return Path(settings.xhs_scrape_lab_server_path).expanduser().resolve()
        return Path(__file__).resolve().parents[4] / "xhs-copy-filter-lab" / "server.py"

    def _resolve_log_dir(self) -> Path:
        if settings.xhs_scrape_lab_log_dir:
            return Path(settings.xhs_scrape_lab_log_dir).expanduser().resolve()
        return self._resolve_server_path().parent / "logs"

    def _resolve_python_bin(self) -> str:
        return settings.xhs_scrape_lab_python_path or "python3"

    def _is_port_open(self) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=1.0):
                return True
        except OSError:
            return False

    async def _wait_until_ready(self, timeout_seconds: float = 10.0) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            if self._is_port_open():
                return True
            await asyncio.sleep(0.4)
        return False

    async def _healthcheck_ok(self) -> bool:
        try:
            timeout = httpx.Timeout(5.0, connect=2.0)
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.get(f"{self.base_url}/api/history/list")
            return resp.status_code < 500
        except Exception:
            return False

    def _build_timeout(self, payload: dict) -> httpx.Timeout:
        max_items = max(1, int(payload.get("maxItems") or 30))
        total_seconds = max(240.0, min(1800.0, 60.0 + max_items * 12.0))
        return httpx.Timeout(total_seconds, connect=10.0)

    async def _ensure_local_server(self) -> bool:
        if not self._is_local_target():
            return False
        if self._is_port_open() and await self._healthcheck_ok():
            return True

        server_path = self._resolve_server_path()
        if not server_path.exists():
            return False

        log_dir = self._resolve_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "server.log"
        with open(log_path, "ab") as log_file:
            subprocess.Popen(
                [self._resolve_python_bin(), str(server_path), "--host", self.host, "--port", str(self.port)],
                cwd=str(server_path.parent),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        return await self._wait_until_ready()

    async def _post_scrape(self, payload: dict) -> httpx.Response:
        timeout = self._build_timeout(payload)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            return await client.post(f"{self.base_url}/api/xhs/scrape", json=payload)

    async def scrape(self, payload: dict) -> dict:
        try:
            resp = await self._post_scrape(payload)
        except httpx.ReadTimeout as exc:
            timeout_seconds = int(self._build_timeout(payload).read or 0)
            raise RuntimeError(
                f"抓取任务执行超时（>{timeout_seconds}秒）。通常是抓取条数较多、详情补全较慢导致；"
                f" 可稍后重试，或降低单次抓取条数。"
            ) from exc
        except httpx.HTTPError as exc:
            if self._is_local_target() and await self._ensure_local_server():
                resp = await self._post_scrape(payload)
            else:
                raise RuntimeError(f"抓取服务不可用：{self.base_url}。请检查本地抓取器是否启动。") from exc

        if resp.status_code >= 400:
            if (
                self._is_local_target()
                and resp.status_code >= 500
                and not await self._healthcheck_ok()
                and await self._ensure_local_server()
            ):
                resp = await self._post_scrape(payload)
            else:
                body = (resp.text or "").strip()
                if self._is_local_target() and resp.status_code >= 500:
                    raise RuntimeError(
                        f"本地抓取服务异常: HTTP {resp.status_code}。"
                        f" 如服务刚刚中断，可重试一次；日志见 {self._resolve_log_dir() / 'server.log'}。"
                        f"{(' 响应: ' + body[:300]) if body else ''}"
                    )
                raise RuntimeError(body[:500] or f"抓取服务异常: HTTP {resp.status_code}")
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(str(data.get("error") or "抓取失败"))
        return data
