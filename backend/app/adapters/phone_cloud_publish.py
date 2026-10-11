"""Existing Phone Cloud user API. Never replay an uncertain publish POST."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import ipaddress
import json
import os
import re
import socket
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

import aiofiles
import httpx
from PIL import Image

from app.config import settings

MAX_SOURCE_IMAGE_BYTES = 25_000_000
MAX_PUBLISH_IMAGE_BYTES = 3_000_000
MAX_LOSSLESS_IMAGE_PIXELS = 8_000_000


def publish_evidence(task: dict) -> dict:
    """Keep proof fields only, never raw pages or remote credentials."""
    result = task.get("result")
    if not isinstance(result, dict):
        return {}
    raw = result.get("publishEvidence")
    if raw is None and isinstance(result.get("runner"), dict):
        raw = result["runner"].get("publishEvidence")
    if not isinstance(raw, dict) or type(raw.get("version")) is not int or raw["version"] != 1:
        return {}
    proof = {"version": 1}
    for key in ("accountIdentityVerified", "titleExact", "contentExact", "clickedFinalPublish", "imageSelectionVerified"):
        proof[key] = raw.get(key) is True
    confirmation = raw.get("confirmation")
    proof["confirmation"] = confirmation if isinstance(confirmation, str) and confirmation in {
        "success_text", "editor_closed_and_xhs_foreground"} else "none"
    for key in ("accountSha256", "titleSha256", "contentSha256"):
        value = raw.get(key)
        if isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value):
            proof[key] = value
    return proof


class PublishError(Exception):
    def __init__(self, code: str, *, uncertain: bool = False, retryable: bool = False):
        super().__init__(code)
        self.code, self.uncertain, self.retryable = code, uncertain, retryable


class PhoneCloudPublisher:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client
        self.token = ""
        self.expires_at = datetime.min.replace(tzinfo=timezone.utc)
        self.auth_lock = asyncio.Lock()

    async def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        base = settings.phone_cloud_publish_base_url.rstrip("/")
        parsed = urlsplit(base)
        http_origins = {value.strip().rstrip("/") for value in settings.phone_cloud_publish_http_origins.split(",") if value.strip()}
        allowed_scheme = parsed.scheme == "https" or (parsed.scheme == "http" and base in http_origins and not parsed.path)
        if not allowed_scheme or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise PublishError("publish_configuration_invalid")
        if self.client is not None:
            return await self.client.request(method, base + path, **kwargs)
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            return await client.request(method, base + path, **kwargs)

    async def _authenticate(self) -> None:
        async with self.auth_lock:
            if self.token and self.expires_at > datetime.now(timezone.utc) + timedelta(seconds=60):
                return
            if not settings.phone_cloud_publish_username or not settings.phone_cloud_publish_password:
                raise PublishError("publish_configuration_invalid")
            response = await self._send("POST", "/api/v1/auth/login", json={
                "username": settings.phone_cloud_publish_username,
                "password": settings.phone_cloud_publish_password,
            })
            if response.status_code != 200:
                raise PublishError("publish_auth_failed", retryable=response.status_code == 429)
            try:
                session = response.json()["session"]
                token = session["token"]
                expires = datetime.fromisoformat(session["expiresAt"].replace("Z", "+00:00"))
                if not isinstance(token, str) or not token or expires.tzinfo is None:
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                raise PublishError("publish_auth_invalid") from None
            self.token, self.expires_at = token, expires

    async def request(self, method: str, path: str, *, json_body=None, creation=False) -> dict:
        try:
            await self._authenticate()
        except httpx.HTTPError:
            raise PublishError("publish_auth_unavailable", retryable=True) from None
        for attempt in range(2):
            try:
                response = await self._send(method, path, headers={"Authorization": f"Bearer {self.token}"}, json=json_body)
            except httpx.HTTPError:
                raise PublishError("publish_response_unknown" if creation else "publish_api_unavailable",
                                   uncertain=creation, retryable=not creation) from None
            # A definite 401 is rejected before task creation; only this POST is safe to replay.
            if response.status_code == 401 and attempt == 0:
                self.token = ""
                try:
                    await self._authenticate()
                except httpx.HTTPError:
                    raise PublishError("publish_auth_unavailable", retryable=True) from None
                continue
            if response.status_code not in {200, 201}:
                if creation and response.status_code == 409:
                    try:
                        code = response.json().get("error")
                    except (ValueError, AttributeError):
                        code = None
                    if code in {"device_busy", "account_slot_busy", "xhs_device_not_available"}:
                        raise PublishError("publish_device_busy", retryable=True)
                    if code == "publish_account_identity_mismatch":
                        raise PublishError("publish_account_identity_mismatch")
                    raise PublishError("publish_conflict_rejected")
                if creation and response.status_code in {400, 413, 415, 422}:
                    raise PublishError("publish_payload_rejected")
                raise PublishError("publish_response_unknown" if creation else "publish_api_unavailable",
                                   uncertain=creation, retryable=not creation)
            try:
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError()
                return data
            except ValueError:
                raise PublishError("publish_response_invalid", uncertain=creation, retryable=not creation) from None
        raise PublishError("publish_auth_failed")

    async def devices(self) -> list[dict]:
        rows = (await self.request("GET", "/api/v1/user/devices")).get("devices")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise PublishError("publish_devices_invalid", retryable=True)
        return rows

    @staticmethod
    def target(devices: list[dict], xhs_id: str) -> dict:
        matches = []
        for device in devices:
            for account in device.get("xhsAccounts", []):
                if str(account.get("xhsId") or "").strip() == xhs_id and account.get("enabled") is not False:
                    matches.append((device, account))
        if len(matches) != 1:
            raise PublishError("publish_account_ambiguous" if matches else "publish_account_unmapped")
        device, account = matches[0]
        if not device.get("deviceId") or account.get("appSlot") not in {"app1", "app2"}:
            raise PublishError("publish_account_unmapped")
        if (device.get("listingStatus") != "listed" or not device.get("adbOnline")
                or not (device.get("automationStatus") or {}).get("deviceAutomationReady")):
            raise PublishError("publish_device_offline", retryable=True)
        if device.get("busy") or account.get("busy") or not device.get("available"):
            raise PublishError("publish_device_busy", retryable=True)
        return {"device_id": device["deviceId"], "app_slot": account["appSlot"], "expected_xhs_id": xhs_id}

    async def create(self, target: dict, snapshot: dict, images: list[str]) -> str:
        expected_id = target.get("expected_xhs_id")
        if not isinstance(expected_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", expected_id):
            raise PublishError("publish_account_unmapped")
        if snapshot.get("xhs_id", expected_id) != expected_id:
            raise PublishError("publish_account_identity_mismatch")
        body = {"deviceId": target["device_id"], "xhsAppSlot": target["app_slot"],
                "expectedXhsId": expected_id,
                "title": snapshot["title"], "content": snapshot["content"], "imageDataUrls": images}
        if len(json.dumps(body).encode()) > 20_000_000:
            raise PublishError("publish_payload_too_large")
        data = await self.request("POST", "/api/v1/user/automation/xhs-publish-tasks", json_body=body, creation=True)
        job_id = (data.get("task") or {}).get("jobId")
        if not isinstance(job_id, str) or not job_id or len(job_id) > 200:
            raise PublishError("publish_response_invalid", uncertain=True)
        return job_id

    async def tasks(self) -> list[dict]:
        rows = (await self.request("GET", "/api/v1/user/automation/xhs-publish-tasks")).get("tasks")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise PublishError("publish_tasks_invalid", retryable=True)
        return rows

    async def cancel(self, job_id: str) -> None:
        from urllib.parse import quote
        await self.request("POST", f"/api/v1/user/automation/xhs-publish-tasks/{quote(job_id, safe='')}/cancel")


class PublishAssets:
    """Copy reviewed images to a private content-addressed snapshot directory."""

    @staticmethod
    def root() -> Path:
        root = Path(settings.phone_cloud_publish_snapshot_path).resolve()
        uploads = Path(settings.storage_path).resolve()
        if root == uploads or uploads in root.parents:
            raise PublishError("publish_snapshot_path_public")
        return root

    async def fetch(self, url: str) -> bytes:
        parsed = urlsplit(url)
        from app.services.hermes_workflow_service import browser_image_url
        normalized = browser_image_url(url)
        public = urlsplit(settings.uploads_public_base_url.rstrip('/'))
        prefix = public.path.rstrip('/') + '/uploads/'
        # Our own absolute upload URLs are local files, not remote fetch targets.
        # Match the configured origin and mount prefix; never trust any loopback host.
        if (settings.storage_type == 'local' and public.scheme in {'http', 'https'}
                and public.hostname and not public.username and not public.password
                and not public.query and not public.fragment
                and parsed.scheme == public.scheme and parsed.netloc == public.netloc
                and parsed.username is None and parsed.password is None
                and parsed.path.startswith(prefix)):
            normalized = '/uploads/' + parsed.path[len(prefix):]
        if normalized and normalized.startswith("/uploads/"):
            relative = unquote(urlsplit(normalized).path[len("/uploads/"):])
            root = Path(settings.storage_path).resolve()
            path = (root / relative).resolve()
            if root not in path.parents or not path.is_file():
                raise PublishError("publish_image_missing")
            async with aiofiles.open(path, "rb") as handle:
                return await handle.read(MAX_SOURCE_IMAGE_BYTES + 1)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        allowed = {value.strip().rstrip("/") for value in settings.phone_cloud_publish_image_origins.split(",") if value.strip()}
        if parsed.scheme != "https" or parsed.username or parsed.password or origin not in allowed or not parsed.hostname:
            raise PublishError("publish_image_origin_denied")
        # Origins are operator-controlled; never follow provider redirects to internal endpoints.
        addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port or 443)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise PublishError("publish_image_origin_denied")
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise PublishError("publish_image_missing")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_SOURCE_IMAGE_BYTES:
                        raise PublishError("publish_image_too_large")
                return bytes(data)

    @staticmethod
    def mime(data: bytes) -> str:
        if not data or len(data) > MAX_PUBLISH_IMAGE_BYTES:
            raise PublishError("publish_image_too_large")
        try:
            with Image.open(io.BytesIO(data)) as image:
                mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(image.format)
                image.verify()
            if mime is None:
                raise ValueError()
            return mime
        except (ValueError, OSError, Image.DecompressionBombError):
            raise PublishError("publish_image_invalid") from None

    @staticmethod
    def prepare(data: bytes) -> tuple[bytes, dict]:
        if len(data) <= MAX_PUBLISH_IMAGE_BYTES:
            return data, {}
        if len(data) > MAX_SOURCE_IMAGE_BYTES:
            raise PublishError("publish_image_too_large")
        # Large generated PNGs can exceed the phone limit without requiring
        # any visual edit. Keep dimensions, alpha, color metadata and pixels.
        try:
            with Image.open(io.BytesIO(data)) as source:
                if (source.format != "PNG" or source.mode not in {"RGB", "RGBA"}
                        or getattr(source, "n_frames", 1) != 1
                        or source.width * source.height > MAX_LOSSLESS_IMAGE_PIXELS):
                    raise PublishError("publish_image_too_large")
                source.load()
                output = io.BytesIO()
                metadata = {key: source.info[key] for key in ("icc_profile", "exif") if source.info.get(key)}
                source.save(output, format="WEBP", lossless=True, exact=True, method=6, **metadata)
                prepared = output.getvalue()
                if len(prepared) > MAX_PUBLISH_IMAGE_BYTES:
                    raise PublishError("publish_image_too_large")
                with Image.open(io.BytesIO(prepared)) as decoded:
                    if decoded.size != source.size or decoded.convert(source.mode).tobytes() != source.tobytes():
                        raise PublishError("publish_image_invalid")
            return prepared, {"source_sha256": hashlib.sha256(data).hexdigest(),
                              "source_bytes": len(data), "preparation": "lossless_png_to_webp"}
        except (ValueError, OSError, Image.DecompressionBombError):
            raise PublishError("publish_image_invalid") from None

    async def freeze(self, urls: list[str]) -> list[dict]:
        if not 1 <= len(urls) <= min(9, max(1, settings.phone_cloud_publish_max_images)):
            raise PublishError("publish_image_count_invalid")
        root = self.root()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        images = []
        for url in urls:
            try:
                data = await self.fetch(url)
            except (httpx.HTTPError, OSError):
                raise PublishError("publish_image_missing") from None
            data, preparation = await asyncio.to_thread(self.prepare, data)
            mime = await asyncio.to_thread(self.mime, data)
            digest = hashlib.sha256(data).hexdigest()
            path = root / digest
            # Atomic rename prevents concurrent saves from exposing partial image bytes.
            temporary = root / f".{digest}.{uuid.uuid4().hex}.tmp"
            try:
                async with aiofiles.open(temporary, "xb") as handle:
                    await handle.write(data)
                await asyncio.to_thread(os.chmod, temporary, 0o600)
                await asyncio.to_thread(os.replace, temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            images.append({"sha256": digest, "mime": mime, "bytes": len(data), **preparation})
        return images

    async def data_urls(self, images: list[dict]) -> list[str]:
        values = []
        for image in images:
            digest = image["sha256"]
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise PublishError("publish_image_invalid")
            try:
                async with aiofiles.open(self.root() / digest, "rb") as handle:
                    data = await handle.read(3_000_001)
            except OSError:
                raise PublishError("publish_image_missing") from None
            if hashlib.sha256(data).hexdigest() != digest or await asyncio.to_thread(self.mime, data) != image["mime"]:
                raise PublishError("publish_image_changed")
            values.append(f"data:{image['mime']};base64,{base64.b64encode(data).decode()}")
        return values
