from __future__ import annotations
"""
GPT Image 2 模型适配器 - OpenAI GPT Image 2 图像生成

对接 OpenAI Images API
API 文档: https://platform.openai.com/docs/api-reference/images/create

支持的尺寸: 1024x1024, 1024x1536, 1536x1024
质量等级: low, medium, high
"""

import httpx
from typing import Any
from app.adapters.ai_model.base import AIModelAdapter
from app.config import settings

# OpenAI GPT Image 2 支持的尺寸
_SUPPORTED_SIZES = {
    (1024, 1024): "1024x1024",
    (1024, 1536): "1024x1536",
    (1536, 1024): "1536x1024",
}

# 候选列表（用于按比例匹配）
_CANDIDATES = list(_SUPPORTED_SIZES.keys())


def _resolve_size(width: int, height: int) -> str:
    """将前端传入的宽高映射到 GPT Image 2 支持的 size 字符串"""
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


def _resolve_quality(quality: str | None) -> str:
    """解析质量等级，默认为 low"""
    if quality in ("low", "medium", "high"):
        return quality
    return "low"


class GPTImage2Adapter(AIModelAdapter):
    """OpenAI GPT Image 2 图像生成模型适配器"""

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
        quality: str | None = None,
        **kwargs,
    ) -> dict:
        """调用 OpenAI Images API 生成图片

        Args:
            prompt: 文字提示
            quality: 质量等级 (low/medium/high)，默认 low
            image_data: 可选，参考图片 URL 或 base64（图生图模式）
        """
        if not settings.gpt_image2_api_key:
            raise ValueError("GPT_IMAGE2_API_KEY 未配置，请在 .env 中设置")

        size = _resolve_size(width, height)
        resolved_quality = _resolve_quality(quality)

        payload: dict[str, Any] = {
            "model": "gpt-image-2",
            "prompt": prompt,
            "size": size,
            "quality": resolved_quality,
        }

        # GPT Image 2 支持图生图
        if image_data:
            if image_data.startswith("data:"):
                payload["image"] = image_data
            else:
                payload["image_url"] = image_data

        headers = {
            "Authorization": f"Bearer {settings.gpt_image2_api_key}",
            "Content-Type": "application/json",
        }

        api_url = settings.gpt_image2_api_url

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                api_url,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

        # 成功: { "data": [{ "url": "..." | "b64_json": "..." }], ... }
        if "data" in result and result["data"]:
            image_urls = []
            for item in result["data"]:
                if item.get("url"):
                    image_urls.append(item["url"])
                elif item.get("b64_json"):
                    image_urls.append(f"data:image/png;base64,{item['b64_json']}")

            if not image_urls:
                return {
                    "task_id": "",
                    "status": "failed",
                    "image_urls": [],
                    "error": "返回数据中没有图片",
                }
            return {
                "task_id": str(result.get("created", "")),
                "status": "completed",
                "image_urls": image_urls,
            }

        # 错误处理
        if "error" in result:
            err = result["error"]
            if isinstance(err, dict):
                msg = err.get("message", str(err))
                code = err.get("code", "")
                err_type = err.get("type", "")

                if "billing" in err_type.lower() or "billing" in str(code).lower():
                    msg = f"计费异常（{code}）：{msg}"
                elif code == "rate_limit_exceeded":
                    msg = f"速率限制（{code}）：请求过于频繁，请稍后重试"
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
        """GPT Image 2 是同步 API，不支持取消"""
        pass

    async def get_task_status(self, task_id: str) -> dict:
        """GPT Image 2 是同步 API，不需要查询状态"""
        return {
            "task_id": task_id,
            "status": "completed",
            "image_urls": [],
        }
