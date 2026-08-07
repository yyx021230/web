from __future__ import annotations
"""
Seedream 模型适配器 - 字节跳动 Seedream 图像生成 (doubao-seedream-5-0)

对接火山引擎 Ark 平台 Seedream API
API 文档: https://www.volcengine.com/docs/82379/1399008

分辨率要求: 总像素 >= 3686400 (约 1920x1920)

支持的分辨率:
  1:1  -> 2048x2048  (4194304 px)
  16:9 -> 2560x1440  (3686400 px)
  9:16 -> 1440x2560  (3686400 px)
  4:3  -> 2240x1680  (3763200 px)
  3:4  -> 1680x2240  (3763200 px)
  3:2  -> 2400x1600  (3840000 px)
  2:3  -> 1600x2400  (3840000 px)
"""

import httpx
import base64
import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from app.adapters.ai_model.base import AIModelAdapter
from app.config import settings

# Seedream 模型 endpoint ID
MODEL_ID = "ep-m-20260325143757-bkkj6"

# Seedream 支持的分辨率映射 (精确匹配)
_SUPPORTED_SIZES: dict[tuple[int, int], str] = {
    (2048, 2048): "2048x2048",   # 1:1
    (2560, 1440): "2560x1440",   # 16:9
    (1440, 2560): "1440x2560",   # 9:16
    (2240, 1680): "2240x1680",   # 4:3
    (1680, 2240): "1680x2240",   # 3:4
    (2400, 1600): "2400x1600",   # 3:2
    (1600, 2400): "1600x2400",   # 2:3
}

# 候选列表（用于按比例匹配）
_CANDIDATES = list(_SUPPORTED_SIZES.keys())


def _format_api_error(status: int, body: str) -> str:
    """Expose upstream API error details without leaking an oversized response body."""
    body = (body or "").strip()
    if body:
        try:
            parsed = json.loads(body)
            error = parsed.get("error") if isinstance(parsed, dict) else None
            if isinstance(error, dict):
                code = str(error.get("code") or "").strip()
                message = str(error.get("message") or "").strip()
                detail = "：".join(part for part in (code, message) if part)
                if detail:
                    return f"API 错误 ({status})，{detail}"
        except json.JSONDecodeError:
            pass
        return f"API 错误 ({status})，{body[:500]}"
    return f"API 错误 ({status})，请稍后重试"


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


def _uploads_url_to_data_uri(src: str) -> str:
    rel = src[len("/uploads/"):] if src.startswith("/uploads/") else src.lstrip("/")
    rel = unquote(rel.split("?", 1)[0].split("#", 1)[0])
    storage_root = Path(settings.storage_path).resolve()
    local_path = (storage_root / rel).resolve()
    root_text = str(storage_root)
    local_text = str(local_path)
    if local_text != root_text and not local_text.startswith(root_text + "/"):
        raise ValueError("非法参考图路径")
    image_bytes = local_path.read_bytes()
    mime = _infer_mime(image_bytes)
    return f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"


def _normalize_reference_source(src: str) -> str:
    if src.startswith("/uploads/"):
        return _uploads_url_to_data_uri(src)
    return src


def _resolve_size(width: int, height: int) -> str:
    """将前端传入的宽高映射到 Seedream 支持的 size 字符串"""
    key = (width, height)
    if key in _SUPPORTED_SIZES:
        return _SUPPORTED_SIZES[key]

    # 按宽高比找最接近的
    target_ratio = width / height
    best = min(
        _CANDIDATES,
        key=lambda wh: abs(wh[0] / wh[1] - target_ratio),
    )
    return f"{best[0]}x{best[1]}"


class SeedreamAdapter(AIModelAdapter):
    """Seedream 图像生成模型适配器"""

    @property
    def name(self) -> str:
        return "seedream"

    @property
    def description(self) -> str:
        return "字节跳动 Seedream 5.0 图像生成模型"

    async def generate_image(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        width: int = 2048,
        height: int = 2048,
        style: str | None = None,
        image_data: str | None = None,
        image_url: str | None = None,
        images_data: list[str] | None = None,
        **kwargs,
    ) -> dict:
        """调用 Seedream API 生成图片

        Args:
            prompt: 文字提示
            image_data: 可选，参考图片 base64（格式 data:image/...;base64,...）
            image_url: 可选，参考图片 URL 地址（与 image_data 二选一）
            images_data: 可选，多张参考图片（base64 或 URL 数组，最多 10 张）
        """
        if not settings.seedream_api_key:
            raise ValueError("SEEDREAM_API_KEY 未配置，请在 .env 中设置")

        # 解析 Seedream 支持的分辨率
        size = _resolve_size(width, height)

        payload: dict[str, Any] = {
            "model": MODEL_ID,
            "prompt": prompt,
            "size": size,
            "response_format": "url",
            "watermark": False,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        # 多图优先，其次单图 base64，最后单图 URL
        if images_data and len(images_data) > 0:
            payload["image"] = [_normalize_reference_source(src) for src in images_data[:10]]
        elif image_data:
            payload["image"] = _normalize_reference_source(image_data)
        elif image_url:
            payload["image"] = _normalize_reference_source(image_url)

        headers = {
            "Authorization": f"Bearer {settings.seedream_api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=180.0) as client:
            try:
                response = await client.post(
                    settings.seedream_api_url,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                # Handle HTTP errors (403, 429, etc.) with friendly messages
                status = e.response.status_code
                body = e.response.text
                if status == 403:
                    return {
                        "task_id": "",
                        "status": "failed",
                        "image_urls": [],
                        "error": "API 配额已用尽或权限不足，请检查 API Key 是否有效",
                    }
                elif status == 429:
                    return {
                        "task_id": "",
                        "status": "failed",
                        "image_urls": [],
                        "error": "请求过于频繁，请稍后再试",
                    }
                elif status >= 500:
                    return {
                        "task_id": "",
                        "status": "failed",
                        "image_urls": [],
                        "error": "AI 服务暂时不可用，请稍后重试",
                    }
                return {
                    "task_id": "",
                    "status": "failed",
                    "image_urls": [],
                    "error": _format_api_error(status, body),
                }
            result = response.json()

        # 成功: { "data": [{ "url": "..." }], "model": "...", "created": ... }
        if "data" in result and result["data"]:
            image_urls = [
                item.get("url", "")
                for item in result["data"]
                if item.get("url")
            ]
            if not image_urls:
                return {
                    "task_id": "",
                    "status": "failed",
                    "image_urls": [],
                    "error": "返回数据中没有图片 URL",
                }
            return {
                "task_id": result.get("id", ""),
                "status": "completed",
                "image_urls": image_urls,
            }

        # 错误处理
        if "error" in result:
            err = result["error"]
            if isinstance(err, dict):
                code = err.get("code", "")
                msg = err.get("message", str(err))
                if code == 500341:
                    msg = f"速率限制（{code}）：请求过于频繁，请稍后重试。如果持续失败，请检查 API 配额是否已用完"
                elif code in (500001, 500002, 500003):
                    msg = f"配额/计费异常（{code}）：{msg}"
            else:
                msg = str(err)
            return {
                "task_id": "",
                "status": "failed",
                "image_urls": [],
                "error": msg,
            }

        return {
            "task_id": "",
            "status": "failed",
            "image_urls": [],
            "error": f"未知响应格式: {str(result)[:200]}",
        }

    async def cancel_task(self, task_id: str) -> None:
        """Seedream 是同步 API，不支持取消"""
        pass

    async def get_task_status(self, task_id: str) -> dict:
        """Seedream 是同步 API，不需要查询状态"""
        return {
            "task_id": task_id,
            "status": "completed",
            "image_urls": [],
        }
