"""
Stable Diffusion 模型适配器 - 预留

可对接本地 SD WebUI API 或云端 SD 服务
"""

from app.adapters.ai_model.base import AIModelAdapter


class StableDiffusionAdapter(AIModelAdapter):
    @property
    def name(self) -> str:
        return "stable-diffusion"

    @property
    def description(self) -> str:
        return "Stable Diffusion 图像生成（预留）"

    async def generate_image(self, prompt: str, **kwargs) -> dict:
        raise NotImplementedError("Stable Diffusion adapter not implemented yet")

    async def cancel_task(self, task_id: str) -> None:
        raise NotImplementedError("Stable Diffusion adapter not implemented yet")

    async def get_task_status(self, task_id: str) -> dict:
        raise NotImplementedError("Stable Diffusion adapter not implemented yet")
