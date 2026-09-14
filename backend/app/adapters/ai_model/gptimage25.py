from __future__ import annotations

from app.adapters.ai_model.gptimage2 import GPTImage2Adapter


class GPTImage25Adapter(GPTImage2Adapter):
    """GPT Image 2.5 registry entry.

    Production requests are routed through the dedicated ``gptimage25``
    provider pool. Inheriting the Image 2 adapter keeps the common image task
    contract available without mixing the two provider pools.
    """

    @property
    def name(self) -> str:
        return "gptimage25"

    @property
    def description(self) -> str:
        return "OpenAI GPT Image 2.5 图像生成与精细编辑模型"
