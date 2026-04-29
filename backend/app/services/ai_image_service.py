from __future__ import annotations
"""AI 生图服务 - 通过适配器模式支持多模型，并持久化任务"""

import time
import asyncio
import logging
import hashlib
from datetime import datetime, timezone
from pathlib import PurePosixPath

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.ai_task import AITask
from app.adapters.ai_model.base import AIModelAdapter
from app.adapters.ai_model.registry import model_registry
from app.adapters.storage import get_storage
from app.services.request_queue import image_generation_queue
from app.db.session import async_session

logger = logging.getLogger("app")


_CONTENT_TYPE_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _generate_image_filename(url: str, content_type: str = "") -> str:
    """从 URL 和 content type 生成稳定的文件名"""
    ext = ".png"
    if content_type and content_type in _CONTENT_TYPE_EXT:
        ext = _CONTENT_TYPE_EXT[content_type]
    else:
        path = PurePosixPath(url)
        if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            ext = path.suffix.lower()
    name_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    return f"ai_{name_hash}{ext}"


async def _download_and_store_image(url: str) -> str | None:
    """下载外部图片并上传到本地存储，返回持久化后的 URL

    如果 URL 已经是内部存储的（/uploads/），直接返回。
    如果是 base64 data URI，也直接返回。
    """
    if not url:
        return None
    # 已经是内部路径或 data URI，不需要下载
    if url.startswith("/uploads/") or url.startswith("data:"):
        return url

    storage = get_storage()

    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        content = resp.content
        content_type = resp.headers.get("content-type", "image/png")
        filename = _generate_image_filename(url, content_type)
        stored_url = await storage.save(content, filename, content_type, subdir="ai-images")
        logger.info("Downloaded and stored image: %s -> %s", url[:80], stored_url)
        return stored_url
    except Exception:
        logger.exception("Failed to download image from %s, using original URL", url[:80])
        return None


async def _store_images(urls: list[str]) -> list[str]:
    """批量下载并存储图片，返回替换后的 URL 列表"""
    results = await asyncio.gather(*[_download_and_store_image(u) for u in urls])
    # 下载成功的用新 URL，失败的用原始 URL
    return [new or orig for new, orig in zip(results, urls)]


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
                    # 下载外部图片并保存到本地存储，避免临时 URL 过期
                    raw_urls = result.get("image_urls", [])
                    stored_urls = await _store_images(raw_urls)
                    ai_task.result_urls = stored_urls
                    ai_task.elapsed_seconds = elapsed
                    if result.get("error"):
                        ai_task.error = result["error"]
                    ai_task.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    await self.db.commit()

                # 返回持久化后的 URL
                result["image_urls"] = stored_urls if "image_urls" in result else raw_urls
                return result

            except Exception as e:
                elapsed = time.time() - start_time
                if ai_task and self.db:
                    ai_task.status = "failed"
                    ai_task.error = str(e)
                    ai_task.elapsed_seconds = elapsed
                    ai_task.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    await self.db.commit()
                # 不重新抛出异常，返回失败结果让前端正常显示错误
                return {
                    "task_id": "",
                    "status": "failed",
                    "image_urls": [],
                    "error": str(e),
                }

        # 将生成任务加入队列
        result = await image_generation_queue.enqueue(_do_generate())
        return result

    async def submit(self, prompt: str, params: dict, user_id: int | None = None) -> dict:
        """提交生图任务：立即返回 task_id，后台异步执行"""
        if not self.db:
            raise ValueError("submit 模式需要数据库会话")

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

        async def _run_in_background(task_id: int):
            async def _do_generate():
                async with async_session() as s:
                    result = await s.execute(select(AITask).where(AITask.id == task_id))
                    task = result.scalar_one_or_none()
                    if not task:
                        return
                    task.status = "processing"
                    await s.commit()

                    start_time = time.time()
                    try:
                        model = model_registry.get(task.model_name)
                        if not model:
                            raise ValueError(f"Model '{task.model_name}' not registered")
                        gen_result = await model.generate_image(prompt=task.prompt, **(task.params or {}))
                        elapsed = time.time() - start_time
                        task.status = "completed" if gen_result.get("status") == "completed" else "failed"
                        # 下载外部图片并保存到本地存储
                        raw_urls = gen_result.get("image_urls", [])
                        stored_urls = await _store_images(raw_urls)
                        task.result_urls = stored_urls
                        task.error = gen_result.get("error")
                        task.elapsed_seconds = elapsed
                        task.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                        await s.commit()
                    except Exception as e:
                        elapsed = time.time() - start_time
                        task.status = "failed"
                        task.error = str(e)
                        task.elapsed_seconds = elapsed
                        task.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                        await s.commit()

            try:
                await image_generation_queue.enqueue(_do_generate())
            except Exception as e:
                logger.exception("background image generation failed: %s", e)

        asyncio.create_task(_run_in_background(ai_task.id))
        return {
            "task_id": str(ai_task.id),
            "status": "queued",
            "image_urls": [],
            "error": None,
        }

    async def get_local_task_status(self, task_id: int) -> dict | None:
        if not self.db:
            raise ValueError("get_local_task_status 需要数据库会话")
        result = await self.db.execute(select(AITask).where(AITask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return None
        return {
            "task_id": str(task.id),
            "status": task.status,
            "image_urls": task.result_urls or [],
            "error": task.error,
        }

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
