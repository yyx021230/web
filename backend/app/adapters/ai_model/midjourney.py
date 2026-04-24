"""
Midjourney 模型适配器 - 预留

当需要对接 Midjourney API 时实现此类
"""

from app.adapters.ai_model.base import AIModelAdapter


class MidjourneyAdapter(AIModelAdapter):
    @property
    def name(self) -> str:
        return "midjourney"

    @property
    def description(self) -> str:
        return "Midjourney 图像生成（预留）"

    async def generate_image(self, prompt: str, **kwargs) -> dict:
        raise NotImplementedError("Midjourney adapter not implemented yet")

    async def cancel_task(self, task_id: str) -> None:
        raise NotImplementedError("Midjourney adapter not implemented yet")

    async def get_task_status(self, task_id: str) -> dict:
        raise NotImplementedError("Midjourney adapter not implemented yet")
