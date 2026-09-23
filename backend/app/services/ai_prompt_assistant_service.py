"""Prompt assistance for the image studio.

The three operations intentionally use separate contracts. Reverse prompting
describes visible evidence, modification performs a surgical edit, and polish
expands a draft without changing its hard facts.
"""

from __future__ import annotations

import base64
import io
import math
from typing import Any

import httpx
from PIL import Image

from app.config import settings


class PromptAssistantError(RuntimeError):
    """A safe error that can be shown to the caller."""


class PromptAssistantConfigurationError(PromptAssistantError):
    """The prompt assistant provider is not configured."""


REVERSE_SYSTEM_PROMPT = """你是图像复刻提示词工程师。目标不是概括图片，而是产出一段可让生图模型尽可能重建原图的中文执行指令。必须先在内部测量构图，再输出最终提示词。

必须逐项读取并保留：
1. 画布比例和内容类型（摄影、海报、信息图、插画等）。
2. 每个主体的身份或类型、外观、数量和朝向，以及主体边界在画布中的归一化坐标（左、上、右、下百分比）、头顶位置、画面下沿裁切到的具体部位和主体占画布高度。
3. 人物的站姿或坐姿、肩膀方向、头部角度、视线，以及双臂和双手的具体位置；产品的朝向、边界和完整露出程度。
4. 前景、中景、背景的空间关系，摄影机高度、拍摄方向、焦段、透视和景深。
5. 背景结构、主辅配色、材质、光线方向、阴影、高光和整体视觉风格。
6. 平面设计版式、留白、对齐方式、视觉层级和装饰元素。
7. 所有肉眼可辨文字的逐字内容、分行方式、字号层级、位置、颜色和字体气质；Logo 或图形标识的位置及外形。

硬性规则：
- 若是海报、封面、信息图或任何带字图片，文字与排版优先级高于氛围描述。禁止把可见文字概括成“标题文案”，必须逐字抄录。
- 若是人物图片，禁止只写“近景、中景、半身”等模糊景别；必须明确从头顶到画面底边露出哪些身体部位、双手是否入镜及所在位置，不得用常见人像姿势替换原图动作。
- 先在内部逐区域检查左上、右上、中心、左下、右下，避免漏掉角落文字和小元素，但不要输出分析过程。
- 只保留图片中可以确认的内容；不识别真实人物身份，不猜测不可辨认的品牌，不增加原图不存在的对象。
- 全部使用中文，图片内确实可见的外文、数字和符号必须原样保留。
- 最终提示词必须严格使用以下七段结构，每个标题单独占一行，每段之间空一行：
  【画布与类型】
  【构图与裁切】
  【主体与姿势】
  【背景与空间】
  【光影与材质】
  【文字与版式】
  【硬性约束】
- 每段使用完整、明确的执行句，不使用项目符号；没有文字的图片也必须在“文字与版式”中明确写“画面无文字、Logo或水印”。
- 不要输出七段以外的前言、分析、总结、置信度、Markdown 标题或代码块。完整内容控制在 1800 字以内，并保证七段内容合并后可以直接提交给生图模型。"""

MODIFY_SYSTEM_PROMPT = """You are a precision prompt editor. Apply the user's instruction as a surgical patch to the current image-generation prompt.

Rules:
1. Return the complete revised prompt, not a change list.
2. Change only content required by the instruction. Preserve all unrelated wording, paragraph structure, constraints, negative requirements, numbers, variables, reference tokens, product names, and factual claims.
3. Apply the requested change consistently wherever the affected concept appears, resolving contradictions created by the edit.
4. Never silently add prices, specifications, policies, brands, text to render, or other facts.
5. Keep the original language and formatting unless the instruction explicitly asks otherwise.
6. Output only the revised prompt, with no preamble, explanation, quotation marks, or code fence.
7. Keep the complete response under 8,000 characters."""

POLISH_SYSTEM_PROMPT = """You are a professional image-generation prompt writer. Expand a rough Chinese prompt into a clear production prompt while preserving every hard fact in the source.

Rules:
1. Do not change or invent product models, prices, specifications, policies, dates, quantities, slogans, text content, reference tokens, or other factual claims.
2. Add only visually useful detail: subject and scene, composition and lens, light and atmosphere, material and detail, and constraints.
3. If the source does not provide a factual detail, describe its visual treatment without inventing the fact itself.
4. Use exactly these five Chinese section headings, in this order: 主体与场景, 构图与镜头, 光影与氛围, 材质与细节, 约束条件.
5. Write concise paragraphs under each heading. Do not use a preamble, summary, code fence, or decorative Markdown.
6. Keep the complete response under 8,000 characters."""


class AIPromptAssistantService:
    def __init__(self) -> None:
        self.api_base = settings.ai_prompt_assistant_api_base_url.strip().rstrip("/")
        self.api_key = settings.ai_prompt_assistant_api_key.strip()
        self.model = settings.ai_prompt_assistant_model.strip()
        self.reverse_model = self.model

    async def reverse_image(self, image_data: str) -> str:
        dimensions = self._image_dimensions(image_data)
        dimension_hint = ""
        if dimensions:
            width, height = dimensions
            divisor = math.gcd(width, height)
            dimension_hint = (
                f"原图像素为 {width}x{height}，宽高比为 "
                f"{width // divisor}:{height // divisor}；画布比例必须严格按此信息描述。"
            )
        return await self._complete(
            REVERSE_SYSTEM_PROMPT,
            [
                {
                    "type": "text",
                    "text": (
                        "仔细查看整张图片，生成高保真重建提示词。"
                        f"{dimension_hint}任何可辨文字都必须逐字写入，任何主体都要说明坐标、占比和裁切边界。"
                        "人物构图、身体裁切位置、双手动作与主体占比是最高优先级，不得用模糊景别替代。"
                        "请严格按系统要求的七段结构输出并保留自然换行。"
                    ),
                },
                {"type": "image_url", "image_url": {"url": image_data, "detail": "high"}},
            ],
            temperature=0,
            max_tokens=1800,
            model=self.reverse_model,
        )

    @staticmethod
    def _image_dimensions(image_data: str) -> tuple[int, int] | None:
        """Read dimensions locally so the vision model cannot guess the ratio."""
        try:
            encoded = image_data.split(",", 1)[1]
            with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
                return image.size
        except (IndexError, ValueError, OSError):
            return None

    async def modify_prompt(self, current: str, instruction: str) -> str:
        return await self._complete(
            MODIFY_SYSTEM_PROMPT,
            f"CURRENT PROMPT:\n{current}\n\nEDIT INSTRUCTION:\n{instruction}",
            temperature=0.1,
            max_tokens=2200,
        )

    async def polish_prompt(self, current: str) -> str:
        return await self._complete(
            POLISH_SYSTEM_PROMPT,
            f"请润色以下生图提示词：\n\n{current}",
            temperature=0.25,
            max_tokens=2200,
        )

    async def _complete(
        self,
        system_prompt: str,
        user_content: str | list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        model: str | None = None,
    ) -> str:
        if not self.api_base or not self.api_key or not self.model:
            raise PromptAssistantConfigurationError("提示词助手尚未配置内部模型地址、密钥或模型 ID")

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(settings.ai_prompt_assistant_timeout_seconds),
            ) as client:
                response = await client.post(
                    f"{self.api_base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model or self.model,
                        "temperature": temperature,
                        "max_completion_tokens": max_tokens,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content},
                        ],
                    },
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise PromptAssistantError("提示词处理超时，请稍后重试") from exc
        except httpx.HTTPStatusError as exc:
            raise PromptAssistantError(f"提示词模型请求失败（{exc.response.status_code}）") from exc
        except httpx.HTTPError as exc:
            raise PromptAssistantError("暂时无法连接提示词模型，请稍后重试") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise PromptAssistantError("提示词模型返回了无法解析的结果") from exc
        if not isinstance(payload, dict):
            raise PromptAssistantError("提示词模型返回了无法解析的结果")
        if payload.get("error"):
            message = payload["error"].get("message") if isinstance(payload["error"], dict) else None
            raise PromptAssistantError(message or "提示词模型返回错误")
        choices = payload.get("choices") or []
        content = choices[0].get("message", {}).get("content") if choices else None
        result = self._extract_text(content)
        if not result:
            raise PromptAssistantError("提示词模型未返回有效内容")
        if len(result) > 8000:
            raise PromptAssistantError("模型返回内容过长，请缩短原始提示词后重试")
        return result

    @staticmethod
    def _extract_text(content: Any) -> str:
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            text = "\n".join(
                item.get("text", "").strip()
                for item in content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ).strip()
        else:
            return ""
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()
        return text
