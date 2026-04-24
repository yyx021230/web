from __future__ import annotations
from abc import ABC, abstractmethod


class AIModelAdapter(ABC):
    """AI 生图模型适配器基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """模型名称标识"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """模型描述"""
        pass

    @abstractmethod
    async def generate_image(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        width: int = 1024,
        height: int = 1024,
        style: str | None = None,
        **kwargs,
    ) -> dict:
        """
        生成图片
        返回: {"task_id": str, "status": str, "image_urls": list, "error": str}
        """
        pass

    @abstractmethod
    async def cancel_task(self, task_id: str) -> None:
        """取消生成任务"""
        pass

    @abstractmethod
    async def get_task_status(self, task_id: str) -> dict:
        """
        查询任务状态
        返回: {"task_id": str, "status": str, "image_urls": list, "error": str}
        """
        pass
