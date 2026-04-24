from __future__ import annotations
"""AI 生图服务 - 通过适配器模式支持多模型，并持久化任务"""

import time
import asyncio
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.ai_task import AITask
from app.adapters.ai_model.base import AIModelAdapter
from app.adapters.ai_model.registry import model_registry
from app.services.request_queue import image_generation_queue


class AIImageService:
    """AI 生图服务"""

    def __init__(self, model_name: str = "seedream", db: AsyncSession | None = None):
        self.adapter: AIModelAdapter = model_registry.get(model_name)
        if not self.adapter:
            raise ValueError(f"Model '{model_name}' not registered")
        self.db = db

    async def generate(self, prompt: str, params: dict, user_id: int | None = None) -> dict:
        """生成图片并保存任务记录（带排队机制）"""
        # 先创建任务记录
        ai_task = None
        if self.db:
            ai_task = AITask(
                user_id=user_id or 0,
                model_name=self.adapter.name,
                prompt=prompt,
                negative_prompt=params.get("negative_prompt"),
                params={k: v for k, v in params.items() if k != "negative_prompt"},
                status="queued",
            )
            self.db.add(ai_task)
            await self.db.commit()
            await self.db.refresh(ai_task)

        async def _do_generate():
            """实际执行生成的内部协程"""
            # 更新状态为 processing
            if ai_task and self.db:
                ai_task.status = "processing"
                await self.db.commit()

            start_time = time.time()
            try:
                result = await self.adapter.generate_image(prompt=prompt, **params)
                elapsed = time.time() - start_time

                # 更新任务状态
                if ai_task and self.db:
                    ai_task.status = "completed" if result.get("status") == "completed" else "failed"
                    ai_task.result_urls = result.get("image_urls", [])
                    ai_task.elapsed_seconds = elapsed
                    if result.get("error"):
                        ai_task.error = result["error"]
                    ai_task.finished_at = datetime.now(timezone.utc)
                    await self.db.commit()

                return result

            except Exception as e:
                elapsed = time.time() - start_time
                if ai_task and self.db:
                    ai_task.status = "failed"
                    ai_task.error = str(e)
                    ai_task.elapsed_seconds = elapsed
                    ai_task.finished_at = datetime.now(timezone.utc)
                    await self.db.commit()
                raise

        # 将生成任务加入队列
        result = await image_generation_queue.enqueue(_do_generate())
        return result

    async def cancel(self, task_id: str) -> None:
        """取消任务"""
        await self.adapter.cancel_task(task_id)

    async def get_status(self, task_id: str) -> dict:
        """查询任务状态"""
        return await self.adapter.get_task_status(task_id)

    @staticmethod
    def list_available_models() -> list[dict]:
        """列出可用模型"""
        return [
            {"id": m.name, "name": m.name, "description": m.description}
            for m in model_registry.list()
        ]

    async def get_history(self, user_id: int, page: int = 1, limit: int = 20) -> tuple[list[AITask], int]:
        """获取用户生图历史"""
        query = select(AITask).where(AITask.user_id == user_id)
        count_stmt = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar() or 0

        items_stmt = query.order_by(AITask.created_at.desc()).offset((page - 1) * limit).limit(limit)
        items_result = await self.db.execute(items_stmt)
        items = list(items_result.scalars().all())
        return items, total
