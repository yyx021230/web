from __future__ import annotations
"""
GPT Image 2 模型适配器 - 通过 image.mentalout.top batch API 调用

请求格式: multipart/form-data
  - payload (JSON): {apiBaseUrl, apiKey, prompt, style, size, count, tuning}
  - image (binary): 参考图片（可选）

API:
  POST https://image.mentalout.top/api/batches  → 返回 batch_id
  GET  https://image.mentalout.top/api/batches/{id}  → 轮询状态
"""

import asyncio
import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
from app.adapters.ai_model.base import AIModelAdapter
from app.config import settings

# 轮询配置
_BATCH_POLL_INTERVAL = 3  # 秒
_BATCH_MAX_POLLS = 100    # 最多轮询 5 分钟


def _short_text(v: Any, max_len: int = 600) -> str:
    text = str(v)
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


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


async def _download_image_bytes(url: str) -> bytes | None:
    """下载图片 URL 或解析 base64 data URI 返回原始字节"""
    if url.startswith("data:"):
        header, b64 = url.split(",", 1)
        return base64.b64decode(b64)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    except Exception:
        return None


async def _save_b64_to_local(b64_json: str) -> str:
    """将 base64 图片保存到本地存储，返回本地 URL"""
    from app.adapters.storage import get_storage

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


class GPTImage2Adapter(AIModelAdapter):
    """GPT Image 2 图像生成模型适配器（通过 batch API）"""

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
        **kwargs,
    ) -> dict:
        """提交 batch 任务并轮询直到完成"""

        # 收集参考图
        ref_sources: list[str] = []
        if images_data and len(images_data) > 0:
            ref_sources = list(images_data[:10])
        elif image_data:
            ref_sources = [image_data]
        elif image_url:
            ref_sources = [image_url]

        has_ref = len(ref_sources) > 0

        # 构建 batch payload
        batch_payload = {
            "apiBaseUrl": "https://chunfeng.mentalout.top",
            "apiKey": "",  # 用 settings 里的 key
            "prompt": prompt,
            "style": "",
            "size": f"{width}x{height}",
            "count": 1,
            "tuning": {
                "quality": quality or "low",
                "outputFormat": "",
                "outputCompression": None,
            },
        }

        # 读取 API key
        env_key, _ = _read_backend_env_overrides()
        batch_payload["apiKey"] = env_key or settings.gpt_image2_api_key
        if not batch_payload["apiKey"]:
            raise ValueError("GPT_IMAGE2_API_KEY 未配置，请在 .env 中设置")

        # 提交 batch 任务
        async with httpx.AsyncClient(timeout=60.0) as client:
            payload_json = json.dumps(batch_payload)

            # 始终用 multipart/form-data（服务器只认这个格式）
            # payload 也放 files 列表里，用 None 文件名让它作为 form 字段发送
            files_to_send: list[tuple[str, tuple[str | None, str | bytes, str]]] = [
                ("payload", (None, payload_json, "application/json")),
            ]

            if has_ref:
                for idx, src in enumerate(ref_sources):
                    img_bytes = await _download_image_bytes(src)
                    if img_bytes:
                        mime = _infer_mime(img_bytes[:8])
                        ext = mime.split("/")[1] if mime != "image/jpeg" else "jpg"
                        files_to_send.append((
                            "image",
                            (f"ref_{idx}.{ext}", img_bytes, mime),
                        ))

            response = await client.post(
                "https://image.mentalout.top/api/batches",
                files=files_to_send,
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

        # 轮询 batch 状态
        result = await self._poll_batch(batch_id)

        # 如果返回的是 base64 图片，保存到本地
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

    async def _poll_batch(self, batch_id: str) -> dict:
        """轮询 batch 状态直到完成"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            for _ in range(_BATCH_MAX_POLLS):
                await asyncio.sleep(_BATCH_POLL_INTERVAL)

                try:
                    resp = await client.get(
                        f"https://image.mentalout.top/api/batches/{batch_id}"
                    )
                    data = resp.json()
                except Exception:
                    continue

                status = data.get("status", "")
                tasks = data.get("tasks", [])

                if status == "succeeded" and tasks:
                    # 收集所有成功任务的图片 URL
                    image_urls = []
                    for t in tasks:
                        if t.get("status") == "succeeded" and t.get("imageUrl"):
                            img_url = t["imageUrl"]
                            # 拼接完整 URL
                            if img_url.startswith("/"):
                                img_url = f"https://image.mentalout.top{img_url}"
                            image_urls.append(img_url)
                    if image_urls:
                        return {
                            "task_id": batch_id,
                            "status": "completed",
                            "image_urls": image_urls,
                        }
                    return {
                        "task_id": batch_id,
                        "status": "failed",
                        "image_urls": [],
                        "error": "任务成功但无图片 URL",
                    }

                if status == "failed" or status == "cancelled":
                    err = ""
                    for t in tasks:
                        if t.get("errorMessage"):
                            err = t["errorMessage"]
                            break
                    return {
                        "task_id": batch_id,
                        "status": "failed",
                        "image_urls": [],
                        "error": err or f"任务{status}",
                    }

                if status == "retrying" and tasks:
                    # 检查是否超过最大重试次数
                    t = tasks[0]
                    if t.get("attempts", 0) >= t.get("maxAttempts", 6):
                        err = t.get("errorMessage", "")
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
            "error": "生成超时（5分钟）",
        }

    async def cancel_task(self, task_id: str) -> None:
        """GPT Image 2 batch 任务不支持取消"""
        pass

    async def get_task_status(self, task_id: str) -> dict:
        """查询 batch 任务状态"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.get(
                    f"https://image.mentalout.top/api/batches/{task_id}"
                )
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

        if status == "succeeded" and tasks:
            image_urls = []
            for t in tasks:
                if t.get("status") == "succeeded" and t.get("imageUrl"):
                    img_url = t["imageUrl"]
                    if img_url.startswith("/"):
                        img_url = f"https://image.mentalout.top{img_url}"
                    image_urls.append(img_url)
            return {
                "task_id": task_id,
                "status": "completed",
                "image_urls": image_urls,
            }

        if status in ("failed", "cancelled"):
            err = ""
            for t in tasks:
                if t.get("errorMessage"):
                    err = t["errorMessage"]
                    break
            return {
                "task_id": task_id,
                "status": "failed",
                "image_urls": [],
                "error": err or f"任务{status}",
            }

        # running, retrying, queued 等
        return {
            "task_id": task_id,
            "status": "generating",
            "image_urls": [],
        }
