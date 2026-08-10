from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import unquote
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.storage import get_storage
from app.config import settings
from app.models.ai_task import AITask
from app.models.ai_image_provider import AIImageProvider


_CONTENT_TYPE_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_DEFAULT_PROVIDER_MAX_CONCURRENT = 1
_PROVIDER_RUNNING: dict[int, int] = {}
_PROVIDER_SLOT_LOCK = asyncio.Lock()
_MENTALOUT_RETRYABLE_ERROR_MARKER = "Tool choice 'image_generation' not found in 'tools' parameter."
_OPENAI_PENDING_ERROR_MARKER = "openai_error"
_IMAGE_QUALITIES = {"low", "medium", "high"}
_UPSTREAM_RESPONSE_PREVIEW_LIMIT = 1024
_UPSTREAM_DEBUG_BODY_LIMIT = 60000
_PROVIDER_TEST_TASK_MODEL = "gptimage2_provider_test"
_PROVIDER_TEST_PROVIDER_ID_PARAM = "_provider_test_provider_id"
logger = logging.getLogger("app")


class UpstreamProviderError(ValueError):
    """Provider error that carries a sanitized upstream response snapshot."""

    def __init__(self, message: str, debug: dict[str, Any] | None = None):
        super().__init__(message)
        self.debug = debug or {}


def _strip_slashes(value: str) -> str:
    return value.rstrip("/")


def _provider_max_concurrent(provider: AIImageProvider) -> int:
    try:
        value = int((provider.config or {}).get("max_concurrent") or _DEFAULT_PROVIDER_MAX_CONCURRENT)
    except (TypeError, ValueError):
        value = _DEFAULT_PROVIDER_MAX_CONCURRENT
    return max(1, min(value, 100))


def _provider_running_count(provider_id: int) -> int:
    return max(0, int(_PROVIDER_RUNNING.get(provider_id, 0)))


def _choose_weighted_provider(providers: list[AIImageProvider]) -> AIImageProvider:
    population: list[AIImageProvider] = []
    for provider in providers:
        population.extend([provider] * max(1, int(provider.weight or 1)))
    return random.choice(population)


def _normalize_base_url(endpoint_url: str) -> tuple[str, str]:
    url = endpoint_url.strip()
    if url.endswith("/v1/images/generations"):
        base = url[: -len("/images/generations")]
        return _strip_slashes(base), "/images/generations"
    if url.endswith("/v1/images/edits"):
        base = url[: -len("/images/edits")]
        return _strip_slashes(base), "/images/edits"
    if url.endswith("/v1"):
        return _strip_slashes(url), "/images/generations"
    return _strip_slashes(url), "/images/generations"


def _normalize_generation_base(endpoint_url: str) -> str:
    base, _ = _normalize_base_url(endpoint_url)
    return base


def _normalize_legacy_batch_api_base(endpoint_url: str) -> str:
    base = _normalize_generation_base(endpoint_url)
    # MentalOut upstream only accepts HTTPS; an HTTP value can trigger
    # "The plain HTTP request was sent to HTTPS port" in OpenResty.
    parsed = urlparse(base)
    if parsed.scheme == "http" and parsed.hostname and parsed.hostname.endswith("mentalout.top"):
        base = base.replace("http://", "https://", 1)
    if base.endswith("/v1"):
        return base[: -len("/v1")]
    return base


def _generate_image_filename(seed: str, content_type: str = "") -> str:
    ext = ".png"
    if content_type and content_type in _CONTENT_TYPE_EXT:
        ext = _CONTENT_TYPE_EXT[content_type]
    name_hash = hashlib.md5(seed.encode()).hexdigest()[:12]
    return f"ai_{name_hash}{ext}"


def _decode_data_uri(data_uri: str) -> tuple[bytes, str]:
    header, b64 = data_uri.split(",", 1)
    mime = "image/png"
    if ":" in header and ";" in header:
        # data:image/png;base64,...
        mime = header.split(":", 1)[1].split(";", 1)[0]
    return base64.b64decode(b64), mime


def _infer_mime(image_bytes: bytes) -> str:
    if image_bytes[:8].startswith(b"\x89PNG"):
        return "image/png"
    if image_bytes[:2] == b"\xff\xd8":
        return "image/jpeg"
    if image_bytes[:4] in (b"RIFF", b"Riff"):
        return "image/webp"
    if image_bytes[:4] == b"GIF8":
        return "image/gif"
    return "image/png"


def _read_uploads_url(src: str) -> tuple[bytes, str]:
    rel = src[len("/uploads/"):] if src.startswith("/uploads/") else src.lstrip("/")
    rel = unquote(rel.split("?", 1)[0].split("#", 1)[0])
    storage_root = Path(settings.storage_path).resolve()
    local_path = (storage_root / rel).resolve()
    root_text = str(storage_root)
    local_text = str(local_path)
    if local_text != root_text and not local_text.startswith(root_text + "/"):
        raise ValueError("非法参考图路径")
    image_bytes = local_path.read_bytes()
    return image_bytes, _infer_mime(image_bytes)


def _collect_reference_sources(params: dict) -> list[str]:
    refs: list[str] = []
    images_data = params.get("images_data")
    if isinstance(images_data, list):
        refs.extend([src for src in images_data if isinstance(src, str) and src])
    if not refs:
        image_data = params.get("image_data")
        if isinstance(image_data, str) and image_data:
            refs.append(image_data)
    if not refs:
        image_url = params.get("image_url")
        if isinstance(image_url, str) and image_url:
            refs.append(image_url)
    return refs


async def _download_reference_file(src: str, idx: int) -> tuple[str, bytes, str] | None:
    if src.startswith("data:"):
        image_bytes, mime = _decode_data_uri(src)
    elif src.startswith("/uploads/"):
        image_bytes, mime = _read_uploads_url(src)
    else:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await _request_with_retries(client, "GET", src)
            resp.raise_for_status()
        image_bytes = resp.content
        mime = resp.headers.get("content-type") or _infer_mime(image_bytes)
    ext = mime.split("/", 1)[-1] if mime != "image/jpeg" else "jpg"
    return f"ref_{idx}.{ext}", image_bytes, mime


def _edits_size(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None
    if width == height and width in (256, 512, 1024):
        return f"{width}x{height}"
    return None


async def _save_inline_image(data_uri_or_b64: str, filename_seed: str) -> str | None:
    storage = get_storage()
    try:
        if data_uri_or_b64.startswith("data:"):
            image_bytes, mime = _decode_data_uri(data_uri_or_b64)
        else:
            image_bytes = base64.b64decode(data_uri_or_b64)
            mime = "image/png"
        filename = _generate_image_filename(filename_seed, mime)
        return await storage.save(image_bytes, filename, mime, subdir="ai-images")
    except Exception:
        return None


def _infer_health_status(status_code: int, body: str = "") -> tuple[str, str | None]:
    if 200 <= status_code < 300:
        return "healthy", None
    if status_code in (401, 403):
        return "unhealthy", "认证失败"
    if status_code == 429:
        return "degraded", "频率限制"
    if status_code >= 500:
        return "unhealthy", "上游服务异常"
    return "unhealthy", body[:200] if body else f"HTTP {status_code}"


def _batch_success_status(status: str | None) -> bool:
    return (status or "").strip().lower() in {"succeeded", "success", "completed", "done", "finished"}


def _batch_failure_status(status: str | None) -> bool:
    return (status or "").strip().lower() in {"failed", "cancelled", "canceled", "error"}


def _batch_task_error(item: dict[str, Any]) -> str:
    for key in ("errorMessage", "error_message", "error", "message", "detail", "debugMessage"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def _is_retryable_mentalout_error(error: str | None) -> bool:
    return _MENTALOUT_RETRYABLE_ERROR_MARKER in str(error or "")


def _tool_choice_retry_attempts(provider: AIImageProvider) -> int:
    config = provider.config or {}
    try:
        value = int(config.get("tool_choice_retry_attempts", 10) or 10)
    except (TypeError, ValueError):
        value = 10
    return max(1, value)


def _tool_choice_retry_delay(provider: AIImageProvider) -> float:
    config = provider.config or {}
    try:
        value = float(config.get("tool_choice_retry_delay", config.get("upstream_retry_delay", 2) or 2))
    except (TypeError, ValueError):
        value = 2.0
    return max(0.0, value)


def _pending_retry_delay(provider: AIImageProvider) -> float:
    config = provider.config or {}
    try:
        value = float(config.get("pending_retry_delay", config.get("upstream_retry_delay", 2) or 2))
    except (TypeError, ValueError):
        value = 2.0
    return max(0.0, value)


def _pending_retry_attempts(provider: AIImageProvider) -> int:
    config = provider.config or {}
    try:
        value = int(config.get("pending_retry_attempts", 300) or 300)
    except (TypeError, ValueError):
        value = 300
    return max(1, value)


def _find_status_code(value: Any) -> int | None:
    if isinstance(value, dict):
        for key in ("status_code", "statusCode", "http_status", "httpStatus"):
            if key not in value:
                continue
            try:
                return int(value[key])
            except (TypeError, ValueError):
                pass
        for nested in value.values():
            found = _find_status_code(nested)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_status_code(item)
            if found is not None:
                return found
    return None


def _contains_openai_pending_error(value: Any) -> bool:
    try:
        text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    except Exception:
        text = str(value)
    return _OPENAI_PENDING_ERROR_MARKER in text.lower()


def _is_retryable_openai_pending_response(resp: httpx.Response) -> bool:
    if getattr(resp, "status_code", None) == 202:
        return True
    try:
        body = resp.json()
    except Exception:
        body = getattr(resp, "text", "")
    return _find_status_code(body) == 202 and _contains_openai_pending_error(body)


def _normalize_image_quality(value: Any, default: str = "low") -> str:
    quality = str(value or "").strip().lower()
    return quality if quality in _IMAGE_QUALITIES else default


def _response_body_preview(resp: httpx.Response, limit: int = _UPSTREAM_RESPONSE_PREVIEW_LIMIT) -> str:
    try:
        body = resp.text
    except Exception:
        return ""
    return " ".join(body.split())[:limit]


def _safe_response_headers(resp: httpx.Response) -> dict[str, str]:
    blocked = {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key", "api-key"}
    headers: dict[str, str] = {}
    try:
        items = resp.headers.items()
    except Exception:
        return headers
    for key, value in items:
        lowered = key.lower()
        headers[key] = "[redacted]" if lowered in blocked else str(value)
    return headers


def _upstream_response_debug(
    resp: httpx.Response,
    *,
    provider: AIImageProvider,
    endpoint: str,
    path: str,
    request_kind: str,
) -> dict[str, Any]:
    body = ""
    body_error = ""
    try:
        body = resp.text
    except Exception as exc:
        body_error = str(exc)
    truncated = len(body) > _UPSTREAM_DEBUG_BODY_LIMIT
    body_snapshot = body[:_UPSTREAM_DEBUG_BODY_LIMIT]
    parsed_json: Any = None
    json_error = ""
    content_type = ""
    try:
        content_type = resp.headers.get("content-type", "")
    except Exception:
        content_type = ""
    if "json" in content_type.lower() and body_snapshot:
        try:
            parsed_json = resp.json()
        except Exception as exc:
            json_error = str(exc)
    return {
        "source": "openai_images_provider",
        "provider": {
            "id": provider.id,
            "name": provider.name,
            "kind": provider.provider_kind,
            "model": provider.provider_model,
        },
        "request": {
            "method": getattr(getattr(resp, "request", None), "method", "POST"),
            "url": str(getattr(getattr(resp, "request", None), "url", f"{endpoint}{path}")),
            "endpoint": endpoint,
            "path": path,
            "kind": request_kind,
        },
        "response": {
            "status_code": getattr(resp, "status_code", None),
            "reason_phrase": getattr(resp, "reason_phrase", ""),
            "headers": _safe_response_headers(resp),
            "content_type": content_type,
            "body": body_snapshot,
            "body_length": len(body),
            "body_truncated": truncated,
            "body_read_error": body_error,
            "json": parsed_json,
            "json_parse_error": json_error,
        },
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def _looks_like_html_response(text: str) -> bool:
    value = text.strip().lower()
    return value.startswith("<!doctype html") or value.startswith("<html") or "<html" in value[:300]


def _extract_html_title(text: str) -> str:
    lower = text.lower()
    start = lower.find("<title>")
    end = lower.find("</title>", start + len("<title>"))
    if start < 0 or end < 0:
        return ""
    return " ".join(text[start + len("<title>"):end].split())[:120]


def _upstream_html_error(resp: httpx.Response) -> str | None:
    preview = _response_body_preview(resp, 300)
    content_type = ""
    try:
        content_type = resp.headers.get("content-type", "")
    except Exception:
        content_type = ""
    if "text/html" not in content_type.lower() and not _looks_like_html_response(preview):
        return None
    title = _extract_html_title(preview)
    status = getattr(resp, "status_code", "")
    message = "上游返回 HTML 页面而不是图片 API 响应，可能接口地址不是 OpenAI Images API，或被 Cloudflare/WAF 拦截"
    if status:
        message = f"{message}；HTTP {status}"
    if title:
        message = f"{message}；页面标题: {title}"
    return message


def _batch_task_image_url(item: dict[str, Any], api_base: str) -> str | None:
    candidates: list[Any] = [
        item.get("imageUrl"),
        item.get("image_url"),
        item.get("url"),
        item.get("outputUrl"),
        item.get("output_url"),
    ]
    for nested_key in ("result", "output", "data"):
        nested = item.get(nested_key)
        if isinstance(nested, dict):
            candidates.extend([
                nested.get("imageUrl"),
                nested.get("image_url"),
                nested.get("url"),
                nested.get("outputUrl"),
                nested.get("output_url"),
            ])

    for value in candidates:
        if not value:
            continue
        url = str(value)
        if url.startswith("/"):
            return f"{api_base}{url}"
        return url
    return None


async def _request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retries: int = 3,
    retry_delay: float = 1.0,
    retry_on_statuses: set[int] | None = None,
    **kwargs,
) -> httpx.Response:
    last_error: Exception | None = None
    retryable_statuses = set(retry_on_statuses or set())
    for attempt in range(retries):
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.RequestError as exc:
            last_error = exc
            if attempt >= retries - 1:
                break
            await asyncio.sleep(retry_delay * (attempt + 1))
            continue
        if response.status_code in retryable_statuses and attempt < retries - 1:
            logger.warning(
                "Retrying %s %s after upstream status %s (%d/%d)",
                method,
                url,
                response.status_code,
                attempt + 2,
                retries,
            )
            await asyncio.sleep(retry_delay * (attempt + 1))
            continue
        return response
    assert last_error is not None
    raise last_error


class AIImageProviderService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def ensure_default_providers(self, created_by: int | None = None) -> int:
        """补齐内置 GPT Image 2 入口；不覆盖用户已经编辑过的入口。"""
        existing = await self.list_providers("gptimage2")
        existing_keys = {
            (
                (p.provider_kind or "").lower(),
                _strip_slashes(p.endpoint_url or ""),
                p.provider_model or "",
            )
            for p in existing
        }
        has_default = any(p.is_default for p in existing)

        defaults: list[dict[str, Any]] = []

        if settings.duckcoding_gpt_image2_api_key:
            duck_endpoint = _strip_slashes(settings.duckcoding_gpt_image2_api_url or "https://api.duckcoding.ai/v1")
            defaults.append({
                "name": "DuckCoding GPT Image 2",
                "model_name": "gptimage2",
                "provider_kind": "openai_images",
                "provider_model": "gpt-image-2",
                "endpoint_url": duck_endpoint,
                "api_key": settings.duckcoding_gpt_image2_api_key,
                "is_enabled": True,
                "is_default": True,
                "priority": 10,
                "weight": 3,
                "supports_text_input": True,
                "supports_image_input": True,
                "config": {
                    "send_size": True,
                    "send_n": False,
                    "timeout": 180,
                    "max_concurrent": 3,
                    "upstream_retry_attempts": 4,
                    "upstream_retry_delay": 2,
                    "pending_retry_attempts": 300,
                    "pending_retry_delay": 2,
                },
                "created_by": created_by,
            })

        if settings.gpt_image2_api_key and settings.gpt_image2_api_url:
            old_base = _normalize_legacy_batch_api_base(settings.gpt_image2_api_url)
            defaults.append({
                "name": "MentalOut GPT Image 2（旧入口）",
                "model_name": "gptimage2",
                "provider_kind": "mentalout_batch",
                "provider_model": "gpt-image-2",
                "endpoint_url": "https://image.mentalout.top",
                "api_key": settings.gpt_image2_api_key,
                "is_enabled": True,
                "is_default": False,
                "priority": 100,
                "weight": 1,
                "supports_text_input": True,
                "supports_image_input": True,
                "config": {
                    "api_base_url": old_base,
                    "send_size": True,
                    "send_n": True,
                    "timeout": 240,
                    "poll_interval": 3,
                    "max_polls": 200,
                    "max_concurrent": 5,
                },
                "created_by": created_by,
            })

        created = 0
        updated = 0
        for item in defaults:
            item = {**item, "is_default": bool(item.get("is_default") and not has_default)}
            key = (
                item["provider_kind"].lower(),
                _strip_slashes(item["endpoint_url"]),
                item["provider_model"],
            )
            if key in existing_keys:
                existing_provider = next(
                    (
                        p for p in existing
                        if (p.provider_kind or "").lower() == item["provider_kind"].lower()
                        and _strip_slashes(p.endpoint_url or "") == _strip_slashes(item["endpoint_url"])
                        and (p.provider_model or "") == item["provider_model"]
                    ),
                    None,
                )
                if existing_provider:
                    needs_update = False
                    for field in ("supports_text_input", "supports_image_input"):
                        if getattr(existing_provider, field) != item[field]:
                            setattr(existing_provider, field, item[field])
                            needs_update = True
                    if existing_provider.provider_kind == "mentalout_batch":
                        normalized_api_base = _normalize_legacy_batch_api_base(settings.gpt_image2_api_url)
                        current_config = existing_provider.config or {}
                        if current_config.get("api_base_url") != normalized_api_base:
                            existing_provider.config = {**current_config, "api_base_url": normalized_api_base}
                            needs_update = True
                        if "max_concurrent" not in (existing_provider.config or {}):
                            existing_provider.config = {**(existing_provider.config or {}), "max_concurrent": 5}
                            needs_update = True
                    if item["is_default"] and not existing_provider.is_default:
                        existing_provider.is_default = True
                        needs_update = True
                    if "duckcoding.ai" in (existing_provider.endpoint_url or "") and existing_provider.config.get("send_size") is not True:
                        existing_provider.config = {**(existing_provider.config or {}), "send_size": True, "send_n": False}
                        needs_update = True
                    if "duckcoding.ai" in (existing_provider.endpoint_url or "") and "max_concurrent" not in (existing_provider.config or {}):
                        existing_provider.config = {**(existing_provider.config or {}), "max_concurrent": 3}
                        needs_update = True
                    if needs_update:
                        self.db.add(existing_provider)
                        updated += 1
                        if existing_provider.is_default:
                            has_default = True
                continue
            self.db.add(AIImageProvider(**item))
            existing_keys.add(key)
            created += 1
            if item["is_default"]:
                has_default = True

        if created or updated:
            await self.db.commit()
        return created

    async def list_providers(self, model_name: str | None = None) -> list[AIImageProvider]:
        stmt = select(AIImageProvider)
        if model_name:
            stmt = stmt.where(AIImageProvider.model_name == model_name)
        stmt = stmt.order_by(AIImageProvider.priority.asc(), AIImageProvider.id.asc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def set_default_provider(self, provider_id: int) -> AIImageProvider | None:
        provider = await self.get_provider(provider_id)
        if not provider:
            return None
        result = await self.db.execute(
            select(AIImageProvider).where(AIImageProvider.model_name == provider.model_name)
        )
        providers = list(result.scalars().all())
        for item in providers:
            item.is_default = item.id == provider.id
            if item.id == provider.id:
                item.is_enabled = True
        await self.db.commit()
        await self.db.refresh(provider)
        return provider

    async def get_provider(self, provider_id: int) -> AIImageProvider | None:
        result = await self.db.execute(select(AIImageProvider).where(AIImageProvider.id == provider_id))
        return result.scalar_one_or_none()

    async def create_provider(self, data: dict, created_by: int | None = None) -> AIImageProvider:
        provider = AIImageProvider(**data, created_by=created_by)
        self.db.add(provider)
        await self.db.commit()
        await self.db.refresh(provider)
        if provider.is_default:
            await self.set_default_provider(provider.id)
        return provider

    async def update_provider(self, provider_id: int, data: dict) -> AIImageProvider | None:
        provider = await self.get_provider(provider_id)
        if not provider:
            return None
        for key, value in data.items():
            setattr(provider, key, value)
        await self.db.commit()
        await self.db.refresh(provider)
        if data.get("is_default"):
            await self.set_default_provider(provider.id)
        return provider

    async def delete_provider(self, provider_id: int) -> bool:
        provider = await self.get_provider(provider_id)
        if not provider:
            return False
        await self.db.delete(provider)
        await self.db.commit()
        return True

    async def toggle_provider(self, provider_id: int, is_enabled: bool) -> AIImageProvider | None:
        return await self.update_provider(provider_id, {"is_enabled": is_enabled})

    def _eligible_providers(
        self,
        providers: list[AIImageProvider],
        has_reference: bool,
    ) -> list[AIImageProvider]:
        eligible = []
        for provider in providers:
            if not provider.is_enabled:
                continue
            if not has_reference and not provider.supports_text_input:
                continue
            if has_reference and not provider.supports_image_input:
                continue
            eligible.append(provider)
        return eligible

    async def _acquire_provider_slot(
        self,
        *,
        model_name: str,
        has_reference: bool,
        wait_interval: float = 0.5,
    ) -> AIImageProvider | None:
        """按启用状态、任务类型、并发容量和权重选择一个 provider，并占用一个运行槽。"""
        while True:
            providers = await self.list_providers(model_name)
            eligible = self._eligible_providers(providers, has_reference)
            if not eligible:
                return None

            async with _PROVIDER_SLOT_LOCK:
                available = [
                    provider
                    for provider in eligible
                    if _provider_running_count(provider.id) < _provider_max_concurrent(provider)
                ]
                if available:
                    defaults = [provider for provider in available if provider.is_default]
                    provider = _choose_weighted_provider(defaults or available)
                    _PROVIDER_RUNNING[provider.id] = _provider_running_count(provider.id) + 1
                    return provider

            await asyncio.sleep(wait_interval)

    async def _release_provider_slot(self, provider_id: int) -> None:
        async with _PROVIDER_SLOT_LOCK:
            current = _provider_running_count(provider_id)
            if current <= 1:
                _PROVIDER_RUNNING.pop(provider_id, None)
            else:
                _PROVIDER_RUNNING[provider_id] = current - 1

    async def _acquire_specific_provider_slot(
        self,
        provider: AIImageProvider,
        *,
        wait_interval: float = 0.5,
    ) -> None:
        """占用指定 provider 的运行槽，用于后台真实测试指定入口。"""
        while True:
            async with _PROVIDER_SLOT_LOCK:
                if _provider_running_count(provider.id) < _provider_max_concurrent(provider):
                    _PROVIDER_RUNNING[provider.id] = _provider_running_count(provider.id) + 1
                    return
            await asyncio.sleep(wait_interval)

    @staticmethod
    def provider_runtime(provider: AIImageProvider) -> dict[str, int]:
        return {
            "current_running": _provider_running_count(provider.id),
            "max_concurrent": _provider_max_concurrent(provider),
        }

    async def generate(
        self,
        prompt: str,
        params: dict,
        user_id: int | None = None,
        model_name: str = "gptimage2",
        on_provider_selected: Callable[[dict], Awaitable[None]] | None = None,
        on_upstream_accepted: Callable[[dict], Awaitable[None]] | None = None,
    ) -> dict:
        providers = await self.list_providers(model_name)
        has_reference = bool(params.get("image_data") or params.get("image_url") or params.get("images_data"))
        eligible = self._eligible_providers(providers, has_reference)

        if not eligible:
            # 没配置 provider 时，直接返回失败，让上层走老适配器兜底。
            return {
                "task_id": "",
                "status": "failed",
                "image_urls": [],
                "error": "未找到可用的生图入口配置",
                "provider_configured": bool(providers),
                "provider": None,
            }

        provider = await self._acquire_provider_slot(model_name=model_name, has_reference=has_reference)
        if not provider:
            return {
                "task_id": "",
                "status": "failed",
                "image_urls": [],
                "error": "未找到可用的生图入口配置",
                "provider_configured": bool(providers),
                "provider": None,
            }

        start = time.time()
        provider_meta = {
            "id": provider.id,
            "name": provider.name,
            "provider_kind": provider.provider_kind,
            "provider_model": provider.provider_model,
        }
        if on_provider_selected:
            try:
                await on_provider_selected(provider_meta)
            except Exception as exc:
                logger.warning(
                    "Failed to persist selected image provider: provider_id=%s error=%s",
                    provider.id,
                    exc,
                )
        try:
            result = await self._call_provider(
                provider,
                prompt,
                params,
                on_upstream_accepted=on_upstream_accepted,
            )
            elapsed_ms = (time.time() - start) * 1000.0
            await self._mark_success(provider, elapsed_ms)
            result["provider"] = provider_meta
            result["provider_configured"] = True
            return result
        except Exception as e:
            elapsed_ms = (time.time() - start) * 1000.0
            error = str(e)
            await self._mark_failure(provider, error, elapsed_ms)
            upstream_debug = getattr(e, "debug", None)
            return {
                "task_id": "",
                "status": "failed",
                "image_urls": [],
                "error": error,
                "upstream_debug": upstream_debug,
                "provider_configured": True,
                "provider": provider_meta,
            }
        finally:
            await self._release_provider_slot(provider.id)

    async def get_upstream_task_status(
        self,
        provider_id: int,
        upstream_task_id: str,
    ) -> dict[str, Any]:
        """Query a previously accepted batch without submitting new work."""

        provider = await self.get_provider(int(provider_id))
        task_id = str(upstream_task_id or "").strip()
        if provider is None:
            return {
                "task_id": task_id,
                "status": "unknown",
                "image_urls": [],
                "error": "生图入口已不存在",
            }
        if not task_id:
            return {
                "task_id": "",
                "status": "unknown",
                "image_urls": [],
                "error": "缺少上游任务 ID",
            }
        if (provider.provider_kind or "").strip().lower() != "mentalout_batch":
            return {
                "task_id": task_id,
                "status": "unsupported",
                "image_urls": [],
                "error": "当前生图入口不支持按任务 ID 查询",
            }

        api_base = provider.endpoint_url.rstrip("/")
        timeout = min(60.0, max(5.0, float((provider.config or {}).get("status_timeout", 30) or 30)))
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await _request_with_retries(
                    client,
                    "GET",
                    f"{api_base}/api/batches/{task_id}",
                    retries=2,
                    retry_delay=1,
                    retry_on_statuses={502, 503, 504},
                )
            if response.status_code >= 400:
                return {
                    "task_id": task_id,
                    "status": "unknown",
                    "image_urls": [],
                    "error": f"查询上游任务失败：HTTP {response.status_code}",
                }
            data = response.json()
        except Exception as exc:
            return {
                "task_id": task_id,
                "status": "unknown",
                "image_urls": [],
                "error": f"查询上游任务失败：{str(exc)[:300]}",
            }

        raw_status = str(data.get("status") or "").strip()
        tasks = data.get("tasks") if isinstance(data.get("tasks"), list) else []
        image_urls: list[str] = []
        for item in tasks:
            if not isinstance(item, dict):
                continue
            image_url = _batch_task_image_url(item, api_base)
            item_status = item.get("status")
            if image_url and (
                _batch_success_status(item_status)
                or _batch_success_status(raw_status)
                or not item_status
            ):
                image_urls.append(image_url)
        if image_urls:
            return {
                "task_id": task_id,
                "status": "completed",
                "raw_status": raw_status,
                "image_urls": image_urls,
                "error": None,
            }
        if _batch_failure_status(raw_status):
            error = next(
                (
                    _batch_task_error(item)
                    for item in tasks
                    if isinstance(item, dict) and _batch_task_error(item)
                ),
                "",
            )
            return {
                "task_id": task_id,
                "status": "failed",
                "raw_status": raw_status,
                "image_urls": [],
                "error": error or f"任务{raw_status or 'failed'}",
            }
        if _batch_success_status(raw_status):
            return {
                "task_id": task_id,
                "status": "unknown",
                "raw_status": raw_status,
                "image_urls": [],
                "error": "上游任务已完成但没有返回图片",
            }
        return {
            "task_id": task_id,
            "status": "generating",
            "raw_status": raw_status,
            "image_urls": [],
            "error": None,
        }

    async def test_provider(self, provider_id: int, prompt: str, params: dict) -> dict:
        """后台真实调用指定入口生成测试图片。"""
        provider = await self.get_provider(provider_id)
        if not provider:
            return {
                "id": provider_id,
                "status": "missing",
                "image_urls": [],
                "error": "provider not found",
                "elapsed_seconds": 0.0,
                "provider": {},
            }

        provider_meta = {
            "id": provider.id,
            "name": provider.name,
            "provider_kind": provider.provider_kind,
            "provider_model": provider.provider_model,
        }
        await self._acquire_specific_provider_slot(provider)
        start = time.time()
        try:
            result = await self._call_provider(provider, prompt, params)
            elapsed = time.time() - start
            await self._mark_success(provider, elapsed * 1000.0)
            return {
                "id": provider.id,
                "status": result.get("status") or "completed",
                "image_urls": result.get("image_urls") or [],
                "error": result.get("error"),
                "elapsed_seconds": round(elapsed, 2),
                "provider": provider_meta,
            }
        except Exception as exc:
            elapsed = time.time() - start
            error = str(exc)
            await self._mark_failure(provider, error, elapsed * 1000.0)
            upstream_debug = getattr(exc, "debug", None)
            return {
                "id": provider.id,
                "status": "failed",
                "image_urls": [],
                "error": error,
                "upstream_debug": upstream_debug,
                "elapsed_seconds": round(elapsed, 2),
                "provider": provider_meta,
            }
        finally:
            await self._release_provider_slot(provider.id)

    async def submit_provider_test(
        self,
        provider_id: int,
        prompt: str,
        params: dict,
        user_id: int | None = None,
    ) -> dict | None:
        provider = await self.get_provider(provider_id)
        if not provider:
            return None
        provider_meta = {
            "id": provider.id,
            "name": provider.name,
            "provider_kind": provider.provider_kind,
            "provider_model": provider.provider_model,
        }
        task = AITask(
            user_id=user_id or 0,
            model_name=_PROVIDER_TEST_TASK_MODEL,
            prompt=prompt,
            params={
                **params,
                _PROVIDER_TEST_PROVIDER_ID_PARAM: int(provider.id),
                "provider": provider_meta,
            },
            status="queued",
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return {
            "id": provider.id,
            "task_id": str(task.id),
            "status": task.status,
            "image_urls": [],
            "error": None,
            "elapsed_seconds": None,
            "provider": provider_meta,
        }

    async def get_provider_test_status(self, task_id: int) -> dict | None:
        result = await self.db.execute(select(AITask).where(AITask.id == int(task_id)))
        task = result.scalar_one_or_none()
        if not task:
            return None
        params = task.params or {}
        provider_meta = params.get("provider") if isinstance(params.get("provider"), dict) else {}
        upstream_debug = params.get("upstream_debug") if isinstance(params.get("upstream_debug"), dict) else None
        provider_id = int(params.get(_PROVIDER_TEST_PROVIDER_ID_PARAM) or provider_meta.get("id") or 0)
        return {
            "id": provider_id,
            "task_id": str(task.id),
            "status": task.status or "queued",
            "image_urls": task.result_urls or [],
            "error": task.error,
            "upstream_debug": upstream_debug,
            "elapsed_seconds": task.elapsed_seconds,
            "provider": provider_meta,
        }

    async def execute_provider_test_task(self, task_id: int) -> dict | None:
        result = await self.db.execute(select(AITask).where(AITask.id == int(task_id)))
        task = result.scalar_one_or_none()
        if not task:
            return None
        if task.model_name != _PROVIDER_TEST_TASK_MODEL:
            return await self.get_provider_test_status(task_id)
        if task.status not in ("queued", "processing"):
            return await self.get_provider_test_status(task_id)

        params = task.params or {}
        provider_id = int(params.get(_PROVIDER_TEST_PROVIDER_ID_PARAM) or 0)
        run_params = {
            key: value
            for key, value in params.items()
            if key not in {_PROVIDER_TEST_PROVIDER_ID_PARAM, "provider"}
        }
        task.status = "processing"
        task.error = None
        task.result_urls = []
        task.finished_at = None
        task.elapsed_seconds = None
        await self.db.commit()

        result = await self.test_provider(provider_id, task.prompt, run_params)
        task.status = "completed" if result.get("status") == "completed" and result.get("image_urls") else "failed"
        task.result_urls = result.get("image_urls") or []
        task.error = result.get("error")
        if result.get("upstream_debug"):
            task.params = {**(task.params or {}), "upstream_debug": result.get("upstream_debug")}
        task.elapsed_seconds = result.get("elapsed_seconds")
        task.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.db.commit()
        return await self.get_provider_test_status(task_id)

    async def _mark_success(self, provider: AIImageProvider, elapsed_ms: float) -> None:
        provider.last_health_status = "healthy"
        provider.last_health_error = None
        provider.last_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        provider.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
        provider.success_count = (provider.success_count or 0) + 1
        if provider.avg_latency_ms:
            provider.avg_latency_ms = round((provider.avg_latency_ms * 0.8) + (elapsed_ms * 0.2), 2)
        else:
            provider.avg_latency_ms = round(elapsed_ms, 2)
        await self.db.commit()

    async def _mark_failure(self, provider: AIImageProvider, error: str, elapsed_ms: float | None = None) -> None:
        provider.last_health_status = "unhealthy"
        provider.last_health_error = error[:1000]
        provider.last_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        provider.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
        provider.failure_count = (provider.failure_count or 0) + 1
        if elapsed_ms is not None:
            if provider.avg_latency_ms:
                provider.avg_latency_ms = round((provider.avg_latency_ms * 0.8) + (elapsed_ms * 0.2), 2)
            else:
                provider.avg_latency_ms = round(elapsed_ms, 2)
        await self.db.commit()

    async def _call_provider(
        self,
        provider: AIImageProvider,
        prompt: str,
        params: dict,
        *,
        on_upstream_accepted: Callable[[dict], Awaitable[None]] | None = None,
    ) -> dict:
        kind = (provider.provider_kind or "openai_images").lower()
        if kind == "openai_images":
            return await self._call_openai_images(provider, prompt, params)
        if kind == "mentalout_batch":
            return await self._call_mentalout_batch(
                provider,
                prompt,
                params,
                on_upstream_accepted=on_upstream_accepted,
            )
        raise ValueError(f"不支持的 provider_kind: {provider.provider_kind}")

    async def _call_openai_images(self, provider: AIImageProvider, prompt: str, params: dict) -> dict:
        base_url, path = _normalize_base_url(provider.endpoint_url)
        ref_sources = _collect_reference_sources(params)
        has_reference = bool(ref_sources)
        if has_reference and provider.supports_image_input:
            path = "/images/edits"
        retry_attempts = max(1, int(provider.config.get("upstream_retry_attempts", 4) or 4))
        retry_delay = float(provider.config.get("upstream_retry_delay", 2) or 2)
        retryable_statuses = {502, 503, 504}
        tool_choice_attempts = _tool_choice_retry_attempts(provider)
        tool_choice_delay = _tool_choice_retry_delay(provider)
        pending_attempts = _pending_retry_attempts(provider)
        pending_delay = _pending_retry_delay(provider)
        payload: dict[str, Any] = {
            "model": provider.provider_model,
            "prompt": prompt,
        }

        count = max(1, min(int(params.get("count") or 1), 4))
        send_n = bool(provider.config.get("send_n", False))
        if send_n:
            payload["n"] = count
        quality = _normalize_image_quality(params.get("quality"), default="")
        if quality:
            payload["quality"] = quality

        timeout = provider.config.get("timeout", 180)
        image_urls: list[str] = []
        task_id = ""
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            attempts = 1 if send_n else count
            for idx in range(attempts):
                for tool_choice_attempt in range(1, tool_choice_attempts + 1):
                    for pending_attempt in range(1, pending_attempts + 1):
                        request_kind = "image_edit" if path == "/images/edits" else "image_generation"
                        if path == "/images/edits":
                            data: dict[str, str] = {
                                "model": provider.provider_model,
                                "prompt": prompt,
                            }
                            if provider.config.get("send_size", False) and params.get("width") and params.get("height"):
                                data["size"] = f"{int(params['width'])}x{int(params['height'])}"
                            if quality:
                                data["quality"] = quality
                            if provider.config.get("response_format"):
                                data["response_format"] = str(provider.config["response_format"])

                            files = []
                            if ref_sources:
                                ref = await _download_reference_file(ref_sources[min(idx, len(ref_sources) - 1)], idx)
                                if ref:
                                    files.append(("image", ref))
                            if not files:
                                raise ValueError("参考图输入无效，无法调用图片编辑接口")
                            resp = await _request_with_retries(
                                client,
                                "POST",
                                f"{base_url}{path}",
                                retries=retry_attempts,
                                retry_delay=retry_delay,
                                retry_on_statuses=retryable_statuses,
                                headers={"Authorization": f"Bearer {provider.api_key}"},
                                data=data,
                                files=files,
                            )
                        else:
                            if provider.config.get("send_size", False) and params.get("width") and params.get("height"):
                                payload["size"] = f"{int(params['width'])}x{int(params['height'])}"
                            if provider.config.get("response_format"):
                                payload["response_format"] = provider.config["response_format"]
                            if has_reference:
                                payload["prompt"] = f"{prompt}"
                            resp = await _request_with_retries(
                                client,
                                "POST",
                                f"{base_url}{path}",
                                retries=retry_attempts,
                                retry_delay=retry_delay,
                                retry_on_statuses=retryable_statuses,
                                headers={
                                    "Authorization": f"Bearer {provider.api_key}",
                                    "Content-Type": "application/json",
                                },
                                json=payload,
                            )
                        if not _is_retryable_openai_pending_response(resp):
                            break
                        if pending_attempt >= pending_attempts:
                            preview = _response_body_preview(resp)
                            error = f"上游返回 202 处理中，重试 {pending_attempts} 次后仍未返回图片"
                            if preview:
                                error = f"{error}；上游响应预览: {preview}"
                            debug = _upstream_response_debug(
                                resp,
                                provider=provider,
                                endpoint=base_url,
                                path=path,
                                request_kind=request_kind,
                            )
                            raise UpstreamProviderError(error, debug)
                        logger.warning(
                            "OpenAI-compatible provider %s returned pending openai_error status; retrying request %d/%d",
                            provider.name or provider.id,
                            pending_attempt + 1,
                            pending_attempts,
                        )
                        if pending_delay > 0:
                            await asyncio.sleep(pending_delay)
                    if resp.status_code < 400:
                        break
                    error = self._extract_error(resp)
                    if tool_choice_attempt < tool_choice_attempts and _is_retryable_mentalout_error(error):
                        logger.warning(
                            "OpenAI-compatible provider %s hit retryable tool_choice error; retrying request %d/%d",
                            provider.name or provider.id,
                            tool_choice_attempt + 1,
                            tool_choice_attempts,
                        )
                        if tool_choice_delay > 0:
                            await asyncio.sleep(tool_choice_delay)
                        continue
                    debug = _upstream_response_debug(
                        resp,
                        provider=provider,
                        endpoint=base_url,
                        path=path,
                        request_kind=request_kind,
                    )
                    raise UpstreamProviderError(error, debug)
                try:
                    data = resp.json()
                except Exception as exc:
                    debug = _upstream_response_debug(
                        resp,
                        provider=provider,
                        endpoint=base_url,
                        path=path,
                        request_kind=request_kind,
                    )
                    error = f"上游响应不是合法 JSON，无法解析图片结果；HTTP {getattr(resp, 'status_code', '')}；解析错误: {exc}"
                    raise UpstreamProviderError(error, debug) from exc
                if not task_id:
                    task_id = str(data.get("id") or data.get("created") or int(time.time()))
                image_urls.extend(await self._extract_image_urls(provider, data, f"{prompt}-{idx}"))

        if not image_urls:
            html_error = _upstream_html_error(resp)
            if html_error:
                logger.warning(
                    "OpenAI-compatible provider returned HTML instead of image data: provider_id=%s provider=%s endpoint=%s path=%s status=%s error=%s",
                    provider.id,
                    provider.name,
                    base_url,
                    path,
                    getattr(resp, "status_code", ""),
                    html_error,
                )
                debug = _upstream_response_debug(
                    resp,
                    provider=provider,
                    endpoint=base_url,
                    path=path,
                    request_kind="image_generation",
                )
                raise UpstreamProviderError(html_error, debug)
            preview = _response_body_preview(resp)
            logger.warning(
                "OpenAI-compatible provider returned no image data: provider_id=%s provider=%s endpoint=%s path=%s status=%s task_id=%s body_preview=%s",
                provider.id,
                provider.name,
                base_url,
                path,
                getattr(resp, "status_code", ""),
                task_id,
                preview,
            )
            error = "响应中没有图片数据"
            if preview:
                error = f"{error}；上游响应预览: {preview}"
            debug = _upstream_response_debug(
                resp,
                provider=provider,
                endpoint=base_url,
                path=path,
                request_kind="image_generation",
            )
            raise UpstreamProviderError(error, debug)

        return {
            "task_id": task_id or str(int(time.time())),
            "status": "completed",
            "image_urls": image_urls,
        }

    def _extract_error(self, resp: httpx.Response) -> str:
        html_error = _upstream_html_error(resp)
        if html_error:
            return html_error
        if resp.headers.get("content-type", "").startswith("application/json"):
            try:
                body = resp.json()
                error = body.get("error") if isinstance(body, dict) else None
                if isinstance(error, dict):
                    return str(error.get("message") or error.get("code") or error)
                if error:
                    return str(error)
                if isinstance(body, dict) and body.get("message"):
                    return str(body["message"])
            except Exception:
                pass
        return resp.text[:300] or f"HTTP {resp.status_code}"

    async def _call_mentalout_batch(
        self,
        provider: AIImageProvider,
        prompt: str,
        params: dict,
        *,
        on_upstream_accepted: Callable[[dict], Awaitable[None]] | None = None,
    ) -> dict:
        api_base = provider.endpoint_url.rstrip("/")
        upstream_base = _normalize_legacy_batch_api_base(
            str(provider.config.get("api_base_url") or "https://api.duckcoding.ai/v1")
        )
        payload = {
            "apiBaseUrl": upstream_base,
            "apiKey": provider.api_key,
            "prompt": prompt,
            "style": params.get("style") or "",
            "size": f"{int(params.get('width') or 1024)}x{int(params.get('height') or 1024)}",
            "count": max(1, min(int(params.get("count") or 1), 4)),
            "tuning": {
                "quality": _normalize_image_quality(params.get("quality")),
                "outputFormat": "",
                "outputCompression": None,
            },
        }

        files: list[tuple[str, tuple[str | None, str | bytes, str]]] = []
        refs = _collect_reference_sources(params)
        for idx, src in enumerate(refs[:10]):
            if not isinstance(src, str):
                continue
            ref = await _download_reference_file(src, idx)
            if not ref:
                continue
            _, image_bytes, mime = ref
            ext = mime.split("/", 1)[-1] if mime != "image/jpeg" else "jpg"
            files.append(("image", (f"ref_{idx}.{ext}", image_bytes, mime)))

        timeout = provider.config.get("timeout", 240)
        max_submit_attempts = max(1, int(provider.config.get("upstream_retry_attempts", 10) or 10))
        retry_delay = float(provider.config.get("upstream_retry_delay", 0) or 0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for submit_attempt in range(1, max_submit_attempts + 1):
                if files:
                    request_files = [("payload", (None, json.dumps(payload), "application/json")), *files]
                    resp = await _request_with_retries(client, "POST", f"{api_base}/api/batches", files=request_files)
                else:
                    resp = await _request_with_retries(
                        client,
                        "POST",
                        f"{api_base}/api/batches",
                        headers={"Content-Type": "application/json"},
                        json=payload,
                    )
                if resp.status_code >= 400:
                    raise ValueError(resp.text[:300])
                submit = resp.json()
                batch_id = submit.get("id") or submit.get("batch_id")
                if not batch_id:
                    raise ValueError(f"响应中没有 batch id: {str(submit)[:200]}")
                if on_upstream_accepted:
                    try:
                        await on_upstream_accepted(
                            {
                                "upstream_task_id": str(batch_id),
                                "provider_id": int(provider.id),
                                "provider_kind": str(provider.provider_kind),
                                "provider_model": str(provider.provider_model),
                                "query_capability": "mentalout_batch",
                            }
                        )
                    except Exception:
                        logger.exception(
                            "Failed to persist accepted upstream batch: provider_id=%s batch_id=%s",
                            provider.id,
                            batch_id,
                        )

                for _ in range(int(provider.config.get("max_polls", 200))):
                    await asyncio.sleep(float(provider.config.get("poll_interval", 3)))
                    poll = await _request_with_retries(client, "GET", f"{api_base}/api/batches/{batch_id}")
                    if poll.status_code >= 400:
                        continue
                    data = poll.json()
                    status = data.get("status", "")
                    tasks = data.get("tasks", [])
                    image_urls = []
                    for item in tasks:
                        if not isinstance(item, dict):
                            continue
                        img_url = _batch_task_image_url(item, api_base)
                        task_status = item.get("status")
                        if img_url and (_batch_success_status(task_status) or _batch_success_status(status) or not task_status):
                            image_urls.append(img_url)
                    if image_urls:
                        return {
                            "task_id": str(batch_id),
                            "status": "completed",
                            "image_urls": image_urls,
                        }
                    if _batch_success_status(status) and tasks:
                        raise ValueError("任务成功但无图片 URL")
                    if _batch_failure_status(status):
                        err = ""
                        for item in tasks:
                            if isinstance(item, dict):
                                err = _batch_task_error(item)
                                if err:
                                    break
                        if submit_attempt < max_submit_attempts and _is_retryable_mentalout_error(err):
                            logger.warning(
                                "MentalOut batch %s failed with retryable upstream error; retrying submit %d/%d",
                                batch_id,
                                submit_attempt + 1,
                                max_submit_attempts,
                            )
                            if retry_delay > 0:
                                await asyncio.sleep(retry_delay)
                            break
                        raise ValueError(err or f"任务{status or 'failed'}")
                    if status == "retrying" and tasks:
                        first = next((item for item in tasks if isinstance(item, dict)), None)
                        if first and int(first.get("attempts") or 0) >= int(first.get("maxAttempts") or 6):
                            err = _batch_task_error(first) or "超过最大重试次数"
                            if submit_attempt < max_submit_attempts and _is_retryable_mentalout_error(err):
                                logger.warning(
                                    "MentalOut batch %s exhausted upstream attempts with retryable error; retrying submit %d/%d",
                                    batch_id,
                                    submit_attempt + 1,
                                    max_submit_attempts,
                                )
                                if retry_delay > 0:
                                    await asyncio.sleep(retry_delay)
                                break
                            raise ValueError(err)
                else:
                    raise ValueError("生成超时")

            logger.error(
                "MentalOut upstream retry exhausted after %d submit attempts for prompt=%r size=%sx%s",
                max_submit_attempts,
                prompt[:120],
                int(params.get("width") or 1024),
                int(params.get("height") or 1024),
            )
            raise ValueError(f"上游重试 {max_submit_attempts} 次后仍失败")

    async def _extract_image_urls(self, provider: AIImageProvider, data: dict, seed: str) -> list[str]:
        image_urls: list[str] = []
        items = data.get("data") or []
        if not isinstance(items, list):
            return image_urls

        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            if item.get("url"):
                image_urls.append(str(item["url"]))
                continue
            if item.get("b64_json"):
                local_url = await _save_inline_image(str(item["b64_json"]), f"{seed}-{provider.id}-{idx}")
                if local_url:
                    image_urls.append(local_url)
                continue
            if item.get("b64"):
                local_url = await _save_inline_image(str(item["b64"]), f"{seed}-{provider.id}-{idx}")
                if local_url:
                    image_urls.append(local_url)
        return image_urls

    async def health_check(self, provider_id: int) -> dict:
        provider = await self.get_provider(provider_id)
        if not provider:
            return {"id": provider_id, "status": "missing", "healthy": False, "error": "provider not found"}

        start = time.time()
        try:
            if provider.provider_kind.lower() == "openai_images":
                status, err = await self._probe_openai_generation(provider)
            elif provider.provider_kind.lower() == "mentalout_batch":
                status, err = await self._probe_batch_generation(provider)
            else:
                status, err = "unhealthy", f"不支持的 provider_kind: {provider.provider_kind}"
        except Exception as e:
            status, err = "unhealthy", str(e)

        provider.last_health_status = status
        provider.last_health_error = err
        provider.last_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        elapsed_ms = (time.time() - start) * 1000.0
        provider.avg_latency_ms = round(elapsed_ms, 2) if not provider.avg_latency_ms else round(provider.avg_latency_ms * 0.9 + elapsed_ms * 0.1, 2)
        await self.db.commit()

        return {
            "id": provider.id,
            "status": status,
            "healthy": status == "healthy",
            "error": err,
            "checked_at": provider.last_checked_at.isoformat() if provider.last_checked_at else datetime.now(timezone.utc).isoformat(),
        }

    async def _probe_openai_generation(self, provider: AIImageProvider) -> tuple[str, str | None]:
        base_url, _ = _normalize_base_url(provider.endpoint_url)
        payload: dict[str, Any] = {
            "model": provider.provider_model,
            "prompt": "health check",
            "size": "1024x1024",
        }
        if provider.config.get("response_format"):
            payload["response_format"] = provider.config["response_format"]

        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }
        retry_attempts = max(1, int(provider.config.get("health_retry_attempts", provider.config.get("upstream_retry_attempts", 3)) or 3))
        retry_delay = float(provider.config.get("health_retry_delay", provider.config.get("upstream_retry_delay", 1) or 1))
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await _request_with_retries(
                client,
                "POST",
                f"{base_url}/images/generations",
                retries=retry_attempts,
                retry_delay=retry_delay,
                retry_on_statuses={502, 503, 504},
                headers=headers,
                json=payload,
            )
        if resp.status_code >= 400:
            return _infer_health_status(resp.status_code, resp.text)
        try:
            data = resp.json()
        except Exception:
            return "degraded", "生图响应无法解析"
        items = data.get("data") or []
        if not isinstance(items, list) or not items:
            return "degraded", "生图响应中没有图片数据"
        for item in items:
            if isinstance(item, dict) and (item.get("url") or item.get("b64_json") or item.get("b64")):
                return "healthy", None
        return "degraded", "生图响应中没有可用图片数据"

    async def _probe_batch_generation(self, provider: AIImageProvider) -> tuple[str, str | None]:
        base_url = provider.endpoint_url.rstrip("/")
        upstream_base = _normalize_legacy_batch_api_base(
            str(provider.config.get("api_base_url") or "https://api.duckcoding.ai/v1")
        )
        payload = {
            "apiBaseUrl": upstream_base,
            "apiKey": provider.api_key,
            "prompt": "health check",
            "style": "",
            "size": "1024x1024",
            "count": 1,
            "tuning": {
                "quality": "low",
                "outputFormat": "",
                "outputCompression": None,
            },
        }
        timeout = float(provider.config.get("timeout", 240))
        poll_interval = float(provider.config.get("health_poll_interval", provider.config.get("poll_interval", 3)))
        max_polls = int(provider.config.get("health_max_polls", 20))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await _request_with_retries(
                client,
                "POST",
                f"{base_url}/api/batches",
                files=[("payload", (None, json.dumps(payload), "application/json"))],
            )
            if resp.status_code >= 400:
                return _infer_health_status(resp.status_code, resp.text)
            try:
                submit = resp.json()
            except Exception:
                return "degraded", "批量提交响应无法解析"

            batch_id = submit.get("id") or submit.get("batch_id")
            if not batch_id:
                return "degraded", "批量提交响应中没有 batch id"

            for _ in range(max_polls):
                await asyncio.sleep(poll_interval)
                poll = await _request_with_retries(client, "GET", f"{base_url}/api/batches/{batch_id}")
                if poll.status_code >= 400:
                    continue
                try:
                    data = poll.json()
                except Exception:
                    continue
                status = data.get("status", "")
                tasks = data.get("tasks", [])
                for item in tasks:
                    if isinstance(item, dict) and _batch_task_image_url(item, base_url):
                        return "healthy", None
                if _batch_success_status(status) and tasks:
                    return "degraded", "批量任务成功但未返回图片"
                if _batch_failure_status(status):
                    err = ""
                    for item in tasks:
                        if isinstance(item, dict):
                            err = _batch_task_error(item)
                            if err:
                                break
                    return "unhealthy", err or f"任务{status or 'failed'}"
            return "degraded", "批量生成超时"
