"""GPT Image 2 模型适配器

默认走 OpenAI 兼容的图片生成接口；如果环境里仍配置了旧的 batch 网关，
则保留兼容路径。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import unquote

import httpx
from app.adapters.ai_model.base import AIModelAdapter
from app.config import settings

# 轮询配置
_BATCH_POLL_INTERVAL = 3  # 秒
_BATCH_MAX_POLLS = 200    # 最多轮询 10 分钟
_DEFAULT_MODEL = "gpt-image-2"
_IMAGE_QUALITIES = {"low", "medium", "high"}


def _short_text(v: Any, max_len: int = 600) -> str:
    text = str(v)
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _normalize_image_quality(value: Any, default: str = "low") -> str:
    quality = str(value or "").strip().lower()
    return quality if quality in _IMAGE_QUALITIES else default


def _infer_mime(bytes_header: bytes) -> str:
    """根据文件头推断 MIME type"""
    if bytes_header[:3] == b"\x89PNG":
        return "image/png"
    if bytes_header[:2] == b"\xff\xd8":
        return "image/jpeg"
    if bytes_header[:4] in (b"RIFF", b"Riff"):
        return "image/webp"
    if bytes_header[:4] == b"GIF8":
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
    return image_bytes, _infer_mime(image_bytes[:8])


async def _download_image_bytes(url: str) -> bytes | None:
    """下载图片 URL 或解析 base64 data URI 返回原始字节"""
    if url.startswith("data:"):
        header, b64 = url.split(",", 1)
        return base64.b64decode(b64)
    if url.startswith("/uploads/"):
        image_bytes, _ = _read_uploads_url(url)
        return image_bytes
    try:
        async with httpx.AsyncClient(timeout=240.0) as client:
            resp = await _request_with_retries(client, "GET", url)
            resp.raise_for_status()
            return resp.content
    except Exception:
        return None


async def _save_b64_to_local(b64_json: str) -> str:
    """将 base64 图片保存到本地存储，返回本地 URL"""
    from app.adapters.storage import get_storage

    if b64_json.startswith("data:"):
        _, b64_json = b64_json.split(",", 1)
    image_bytes = base64.b64decode(b64_json)
    name_hash = hashlib.md5(image_bytes[:1024]).hexdigest()[:12]
    filename = f"ai_gpt2_{name_hash}.png"

    storage = get_storage()
    return await storage.save(image_bytes, filename, "image/png", subdir="ai-images")


def _read_backend_env_overrides() -> tuple[str | None, str | None]:
    """优先读取 backend/.env"""
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return None, None

    key = None
    url = None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k == "GPT_IMAGE2_API_KEY":
            key = v
        elif k == "GPT_IMAGE2_API_URL":
            url = v
    return key, url


def _is_batch_gateway(api_url: str) -> bool:
    value = api_url.lower()
    return "image.mentalout.top" in value or "/api/batches" in value


def _normalize_batch_base_url(api_url: str) -> str:
    url = api_url.rstrip("/")
    if url.endswith("/api/batches"):
        return url[: -len("/api/batches")]
    return url


def _normalize_api_url(api_url: str) -> tuple[str, str]:
    url = api_url.rstrip("/")
    if url.endswith("/images/edits"):
        return url[: -len("/images/edits")], "/images/edits"
    if url.endswith("/images/generations"):
        return url[: -len("/images/generations")], "/images/generations"
    return url, "/images/generations"


def _normalize_legacy_batch_api_base(api_url: str) -> str:
    base, _ = _normalize_api_url(api_url)
    if base.endswith("/v1"):
        return base[: -len("/v1")]
    return base


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
    **kwargs,
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return await client.request(method, url, **kwargs)
        except httpx.RequestError as exc:
            last_error = exc
            if attempt >= retries - 1:
                break
            await asyncio.sleep(retry_delay * (attempt + 1))
    assert last_error is not None
    raise last_error


def _collect_reference_sources(
    images_data: list[str] | None,
    image_data: str | None,
    image_url: str | None,
) -> list[str]:
    refs: list[str] = []
    if images_data:
        refs.extend([src for src in images_data if isinstance(src, str) and src])
    if not refs and image_data:
        refs.append(image_data)
    if not refs and image_url:
        refs.append(image_url)
    return refs


async def _download_reference_file(src: str) -> tuple[str, bytes, str] | None:
    if src.startswith("data:"):
        header, b64 = src.split(",", 1)
        mime = "image/png"
        if ":" in header and ";" in header:
            mime = header.split(":", 1)[1].split(";", 1)[0]
        image_bytes = base64.b64decode(b64)
    elif src.startswith("/uploads/"):
        image_bytes, mime = _read_uploads_url(src)
    else:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await _request_with_retries(client, "GET", src)
            resp.raise_for_status()
        image_bytes = resp.content
        mime = resp.headers.get("content-type") or _infer_mime(image_bytes[:8])
    ext = mime.split("/", 1)[-1] if mime != "image/jpeg" else "jpg"
    return f"ref.{ext}", image_bytes, mime


def _resolve_image_size(width: int, height: int) -> str:
    """Validate GPT Image 2 size constraints before sending to upstream."""
    if width <= 0 or height <= 0:
        raise ValueError("GPT Image 2 尺寸必须为正数")
    if width > 3840 or height > 3840:
        raise ValueError("GPT Image 2 单边最大不能超过 3840px")
    if width % 16 != 0 or height % 16 != 0:
        raise ValueError("GPT Image 2 宽高必须都是 16px 的倍数")
    short_edge = min(width, height)
    long_edge = max(width, height)
    if long_edge / short_edge > 3:
        raise ValueError("GPT Image 2 长短边比例不能超过 3:1")
    total_pixels = width * height
    if total_pixels < 655_360 or total_pixels > 8_294_400:
        raise ValueError("GPT Image 2 总像素必须在 655,360 到 8,294,400 之间")
    return f"{width}x{height}"


class GPTImage2Adapter(AIModelAdapter):
    """GPT Image 2 图像生成模型适配器"""

    @property
    def name(self) -> str:
        return "gptimage2"

    @property
    def description(self) -> str:
        return "OpenAI GPT Image 2 图像生成模型"

    async def generate_image(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        width: int = 1024,
        height: int = 1024,
        style: str | None = None,
        image_data: str | None = None,
        image_url: str | None = None,
        images_data: list[str] | None = None,
        quality: str | None = None,
        count: int = 1,
        **kwargs,
    ) -> dict:
        """根据配置调用 OpenAI 兼容接口，必要时兼容旧 batch 网关"""
        on_upstream_accepted = kwargs.pop("_on_upstream_accepted", None)
        env_key, env_url = _read_backend_env_overrides()
        api_key = env_key or settings.gpt_image2_api_key
        if not api_key:
            raise ValueError("GPT_IMAGE2_API_KEY 未配置，请在 .env 中设置")

        api_url = (env_url or settings.gpt_image2_api_url).strip() or "https://api.openai.com/v1/images/generations"
        if _is_batch_gateway(api_url):
            return await self._generate_with_batch_gateway(
                prompt=prompt,
                width=width,
                height=height,
                quality=quality,
                count=count,
                image_data=image_data,
                image_url=image_url,
                images_data=images_data,
                api_url=api_url,
                api_key=api_key,
                on_upstream_accepted=on_upstream_accepted,
            )

        return await self._generate_with_openai_compatible(
            prompt=prompt,
            width=width,
            height=height,
            quality=quality,
            count=count,
            image_data=image_data,
            image_url=image_url,
            images_data=images_data,
            api_url=api_url,
            api_key=api_key,
        )

    async def _generate_with_openai_compatible(
        self,
        *,
        prompt: str,
        width: int,
        height: int,
        quality: str | None,
        count: int,
        image_data: str | None,
        image_url: str | None,
        images_data: list[str] | None,
        api_url: str,
        api_key: str,
    ) -> dict:
        ref_sources = _collect_reference_sources(images_data, image_data, image_url)
        base_url, default_path = _normalize_api_url(api_url)
        path = "/images/edits" if ref_sources else default_path
        requested_size = _resolve_image_size(width, height)
        requested_quality = _normalize_image_quality(quality, default="")
        attempts = max(1, min(int(count or 1), 4))
        image_urls: list[str] = []
        task_id = ""

        async with httpx.AsyncClient(timeout=300.0) as client:
            for idx in range(attempts):
                if ref_sources:
                    ref = await _download_reference_file(ref_sources[min(idx, len(ref_sources) - 1)])
                    if not ref:
                        return {
                            "task_id": "",
                            "status": "failed",
                            "image_urls": [],
                            "error": "参考图下载失败",
                        }

                    data: dict[str, str] = {
                        "model": _DEFAULT_MODEL,
                        "prompt": prompt,
                        "size": requested_size,
                    }
                    if requested_quality:
                        data["quality"] = requested_quality
                    files = [("image", ref)]
                    resp = await _request_with_retries(
                        client,
                        "POST",
                        f"{base_url}{path}",
                        headers={"Authorization": f"Bearer {api_key}"},
                        data=data,
                        files=files,
                    )
                else:
                    payload: dict[str, Any] = {
                        "model": _DEFAULT_MODEL,
                        "prompt": prompt,
                        "size": requested_size,
                    }
                    if requested_quality:
                        payload["quality"] = requested_quality
                    resp = await _request_with_retries(
                        client,
                        "POST",
                        f"{base_url}{path}",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )

                if resp.status_code >= 400:
                    raise ValueError(_short_text(self._extract_error_message(resp)))

                data = resp.json()
                if not task_id:
                    task_id = str(data.get("id") or data.get("created") or int(time.time()))
                image_urls.extend(await self._extract_image_urls(data, f"{prompt}-{idx}"))

        if not image_urls:
            return {
                "task_id": task_id or "",
                "status": "failed",
                "image_urls": [],
                "error": "响应中没有图片数据",
            }

        return {
            "task_id": task_id or str(int(time.time())),
            "status": "completed",
            "image_urls": image_urls,
        }

    async def _generate_with_batch_gateway(
        self,
        *,
        prompt: str,
        width: int,
        height: int,
        quality: str | None,
        count: int,
        image_data: str | None,
        image_url: str | None,
        images_data: list[str] | None,
        api_url: str,
        api_key: str,
        on_upstream_accepted: Callable[[dict], Awaitable[None]] | None = None,
    ) -> dict:
        batch_count = max(1, min(int(count or 1), 4))
        ref_sources = _collect_reference_sources(images_data, image_data, image_url)
        batch_payload = {
            "apiBaseUrl": _normalize_legacy_batch_api_base(api_url),
            "apiKey": api_key,
            "prompt": prompt,
            "style": "",
            "size": f"{width}x{height}",
            "count": batch_count,
            "tuning": {
                "quality": _normalize_image_quality(quality),
                "outputFormat": "",
                "outputCompression": None,
            },
        }

        batch_base_url = _normalize_batch_base_url(api_url)

        async with httpx.AsyncClient(timeout=60.0) as client:
            files_to_send: list[tuple[str, tuple[str | None, str | bytes, str]]] = []

            for idx, src in enumerate(ref_sources):
                img_bytes = await _download_image_bytes(src)
                if img_bytes:
                    mime = _infer_mime(img_bytes[:8])
                    ext = mime.split("/")[1] if mime != "image/jpeg" else "jpg"
                    files_to_send.append(("image", (f"ref_{idx}.{ext}", img_bytes, mime)))

            if files_to_send:
                files_to_send.insert(0, ("payload", (None, json.dumps(batch_payload), "application/json")))
                response = await _request_with_retries(
                    client,
                    "POST",
                    f"{batch_base_url}/api/batches",
                    files=files_to_send,
                )
            else:
                response = await _request_with_retries(
                    client,
                    "POST",
                    f"{batch_base_url}/api/batches",
                    headers={"Content-Type": "application/json"},
                    json=batch_payload,
                )

            try:
                submit_result = response.json()
            except Exception:
                return {
                    "task_id": "",
                    "status": "failed",
                    "image_urls": [],
                    "error": f"提交失败 HTTP {response.status_code}: {response.text[:200]}",
                }

        if response.status_code >= 400:
            err_msg = submit_result.get("message", submit_result.get("error", str(submit_result)))
            return {
                "task_id": "",
                "status": "failed",
                "image_urls": [],
                "error": f"HTTP {response.status_code}: {_short_text(err_msg)}",
            }

        batch_id = submit_result.get("id", "")
        if not batch_id:
            return {
                "task_id": "",
                "status": "failed",
                "image_urls": [],
                "error": f"响应中没有 batch_id: {str(submit_result)[:200]}",
            }

        if on_upstream_accepted:
            try:
                await on_upstream_accepted(
                    {
                        "upstream_task_id": str(batch_id),
                        "provider_id": None,
                        "provider_kind": "legacy_batch_adapter",
                        "provider_model": _DEFAULT_MODEL,
                        "query_capability": "legacy_batch_gateway",
                    }
                )
            except Exception:
                # Observability must never fail the legacy generation request.
                pass

        result = await self._poll_batch(batch_id, api_url=batch_base_url)
        if result.get("status") == "completed" and result.get("image_urls"):
            stored_urls = []
            for url in result["image_urls"]:
                if url.startswith("data:"):
                    local_url = await _save_b64_to_local(url)
                    stored_urls.append(local_url)
                else:
                    stored_urls.append(url)
            result["image_urls"] = stored_urls

        return result

    def _extract_error_message(self, resp: httpx.Response) -> str:
        if resp.headers.get("content-type", "").startswith("application/json"):
            try:
                body = resp.json()
                if isinstance(body, dict):
                    if isinstance(body.get("error"), dict):
                        error = body["error"]
                        return str(error.get("message") or error.get("code") or error)
                    if body.get("message"):
                        return str(body["message"])
                    if body.get("error"):
                        return str(body["error"])
            except Exception:
                pass
        return resp.text[:300] or f"HTTP {resp.status_code}"

    async def _extract_image_urls(self, data: dict, seed: str) -> list[str]:
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
                local_url = await _save_b64_to_local(str(item["b64_json"]))
                image_urls.append(local_url)
                continue
            if item.get("b64"):
                local_url = await _save_b64_to_local(str(item["b64"]))
                image_urls.append(local_url)
        return image_urls

    async def _poll_batch(self, batch_id: str, api_url: str | None = None) -> dict:
        """轮询 batch 状态直到完成"""
        base = _normalize_batch_base_url(api_url or "https://image.mentalout.top")
        async with httpx.AsyncClient(timeout=60.0) as client:
            for _ in range(_BATCH_MAX_POLLS):
                await asyncio.sleep(_BATCH_POLL_INTERVAL)

                try:
                    resp = await _request_with_retries(client, "GET", f"{base}/api/batches/{batch_id}")
                    data = resp.json()
                except Exception:
                    continue

                status = data.get("status", "")
                tasks = data.get("tasks", [])
                image_urls = []
                for t in tasks:
                    if not isinstance(t, dict):
                        continue
                    img_url = _batch_task_image_url(t, base)
                    task_status = t.get("status")
                    if img_url and (_batch_success_status(task_status) or _batch_success_status(status) or not task_status):
                        image_urls.append(img_url)
                if image_urls:
                    return {
                        "task_id": batch_id,
                        "status": "completed",
                        "image_urls": image_urls,
                    }

                if _batch_success_status(status) and tasks:
                    return {
                        "task_id": batch_id,
                        "status": "failed",
                        "image_urls": [],
                        "error": "任务成功但无图片 URL",
                    }

                if _batch_failure_status(status):
                    err = ""
                    for t in tasks:
                        if isinstance(t, dict):
                            err = _batch_task_error(t)
                            if err:
                                break
                    return {
                        "task_id": batch_id,
                        "status": "failed",
                        "image_urls": [],
                        "error": err or f"任务{status or 'failed'}",
                    }

                if status == "retrying" and tasks:
                    # 检查是否超过最大重试次数
                    t = tasks[0]
                    if isinstance(t, dict) and t.get("attempts", 0) >= t.get("maxAttempts", 6):
                        err = _batch_task_error(t)
                        return {
                            "task_id": batch_id,
                            "status": "failed",
                            "image_urls": [],
                            "error": f"超过最大重试次数: {_short_text(err)}",
                        }
                    # 继续轮询

        # 超时
        return {
            "task_id": batch_id,
            "status": "failed",
            "image_urls": [],
            "error": "生成超时（10分钟）",
        }

    async def cancel_task(self, task_id: str) -> None:
        """GPT Image 2 兼容接口不支持取消"""
        pass

    async def get_task_status(self, task_id: str) -> dict:
        """查询旧 batch 任务状态；直连接口是同步生成，不需要轮询"""
        _, env_url = _read_backend_env_overrides()
        api_url = (env_url or settings.gpt_image2_api_url).strip() or "https://api.openai.com/v1/images/generations"
        if not _is_batch_gateway(api_url):
            return {
                "task_id": task_id,
                "status": "completed",
                "image_urls": [],
            }

        batch_base_url = _normalize_batch_base_url(api_url)
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await _request_with_retries(client, "GET", f"{batch_base_url}/api/batches/{task_id}")
                data = resp.json()
            except Exception:
                return {
                    "task_id": task_id,
                    "status": "failed",
                    "image_urls": [],
                    "error": "查询失败",
                }

        status = data.get("status", "")
        tasks = data.get("tasks", [])

        image_urls = []
        for t in tasks:
            if not isinstance(t, dict):
                continue
            img_url = _batch_task_image_url(t, batch_base_url)
            task_status = t.get("status")
            if img_url and (_batch_success_status(task_status) or _batch_success_status(status) or not task_status):
                image_urls.append(img_url)
        if image_urls:
            return {
                "task_id": task_id,
                "status": "completed",
                "image_urls": image_urls,
            }

        if _batch_failure_status(status):
            err = ""
            for t in tasks:
                if isinstance(t, dict):
                    err = _batch_task_error(t)
                    if err:
                        break
            return {
                "task_id": task_id,
                "status": "failed",
                "image_urls": [],
                "error": err or f"任务{status or 'failed'}",
            }

        # running, retrying, queued 等
        return {
            "task_id": task_id,
            "status": "generating",
            "image_urls": [],
        }
