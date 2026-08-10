"""AI 生图服务 - 通过适配器模式支持多模型，并持久化任务"""

from __future__ import annotations

import time
import asyncio
import logging
import hashlib
import math
from datetime import datetime, timezone, timedelta
from pathlib import PurePosixPath, Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from app.models.ai_task import AITask
from app.adapters.ai_model.base import AIModelAdapter
from app.adapters.ai_model.registry import model_registry
from app.adapters.storage import get_storage
from app.config import settings
from app.services.request_queue import image_generation_queue
from app.services.ai_image_provider_service import AIImageProviderService
from app.services.ai_image_shadow import mirror_ai_image_shadow_safely
from app.services.ai_task_queue import ai_image_task_queue

logger = logging.getLogger("app")

MAX_USER_ACTIVE_IMAGE_TASKS = 6
_DIMENSION_PROMPT_MARKER = "画幅约束："


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
        async with httpx.AsyncClient(timeout=600.0, follow_redirects=True) as client:
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


def _build_dimension_prompt_instruction(params: dict) -> str | None:
    """Build a prompt-side aspect/size constraint for providers that may ignore size."""
    try:
        width = int(params.get("width") or 0)
        height = int(params.get("height") or 0)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None

    divisor = math.gcd(width, height)
    ratio = f"{width // divisor}:{height // divisor}"
    return (
        f"{_DIMENSION_PROMPT_MARKER}请严格按照 {ratio} 画幅构图，"
        f"目标输出分辨率为 {width}x{height} 像素；"
        "不要改成其他横竖比例，不要用留白或扩边来凑比例。"
    )


def _append_dimension_prompt_instruction(prompt: str, params: dict) -> str:
    if _DIMENSION_PROMPT_MARKER in prompt:
        return prompt
    instruction = _build_dimension_prompt_instruction(params)
    if not instruction:
        return prompt
    return f"{prompt.rstrip()}\n\n{instruction}"


class AIImageService:
    """AI 生图服务"""

    def __init__(self, model_name: str = "seedream", db: AsyncSession | None = None):
        self.adapter: AIModelAdapter = model_registry.get(model_name)
        if not self.adapter:
            raise ValueError(f"Model '{model_name}' not registered")
        self.db = db

    @staticmethod
    def _now_naive_utc() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    @classmethod
    def _mark_processing_started(cls, task: AITask) -> None:
        task.params = {
            **(task.params or {}),
            "_processing_started_at": cls._now_naive_utc().isoformat(),
        }

    @staticmethod
    def _parse_naive_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value).replace(tzinfo=None)
        except ValueError:
            return None

    @staticmethod
    def _should_fallback_to_adapter(result: dict | None) -> bool:
        if not isinstance(result, dict):
            return True
        if result.get("provider_configured"):
            return False
        if result.get("status") == "completed":
            return False
        if result.get("task_id") or result.get("image_urls"):
            return False
        return True

    @staticmethod
    def _normalize_failed_result(result: dict | None) -> dict | None:
        if not isinstance(result, dict):
            return result
        if result.get("status") == "failed" and not result.get("error"):
            return {
                **result,
                "error": "上游返回失败，但没有提供错误详情",
            }
        return result

    @staticmethod
    def _task_timeout_seconds() -> int:
        try:
            value = int(getattr(settings, "ai_task_timeout_seconds", 1800) or 1800)
        except (TypeError, ValueError):
            value = 1800
        return max(60, value)

    @classmethod
    def _task_timeout_error(cls) -> str:
        seconds = cls._task_timeout_seconds()
        minutes = max(1, seconds // 60)
        return f"任务执行超时（超过 {minutes} 分钟未收尾）"

    @staticmethod
    def _normalize_client_request_id(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized[:64] or None

    @staticmethod
    def _task_response(task: AITask) -> dict:
        return {
            "task_id": str(task.id),
            "status": task.status,
            "image_urls": task.result_urls or [],
            "error": task.error,
            "client_request_id": task.client_request_id,
            "created_at": str(task.created_at) if task.created_at else None,
            "finished_at": str(task.finished_at) if task.finished_at else None,
            "elapsed_seconds": task.elapsed_seconds,
        }

    async def _lock_user_active_tasks(self, user_id: int) -> None:
        """Serialize per-user active-task checks on PostgreSQL."""
        if not self.db:
            return
        bind = self.db.get_bind()
        dialect_name = getattr(getattr(bind, "dialect", None), "name", "")
        if dialect_name != "postgresql":
            return
        # Keep the key in a project-local namespace and lock for this transaction.
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": 7_300_000_000 + int(user_id)},
        )

    async def _finish_task_if_active(
        self,
        session: AsyncSession,
        task_id: int,
        *,
        status: str,
        error: str | None = None,
        result_urls: list[str] | None = None,
        elapsed_seconds: float | None = None,
        provider: dict | None = None,
        upstream_debug: dict | None = None,
        shadow_phase: str | None = None,
        result_unknown: bool = False,
    ) -> bool:
        result = await session.execute(select(AITask).where(AITask.id == task_id))
        task = result.scalar_one_or_none()
        if not task or task.status not in ("queued", "processing"):
            return False

        task.status = status
        if provider:
            task.params = {**(task.params or {}), "provider": provider}
        if upstream_debug:
            task.params = {**(task.params or {}), "upstream_debug": upstream_debug}
        if result_urls is not None:
            task.result_urls = result_urls
        task.error = error
        task.elapsed_seconds = elapsed_seconds
        task.finished_at = self._now_naive_utc()
        await session.commit()
        await mirror_ai_image_shadow_safely(
            task_id,
            phase=shadow_phase or ("completed" if status == "completed" else "failed"),
            details={
                "legacy_status": status,
                "image_count": len(result_urls or []),
            },
            result_unknown=result_unknown,
        )
        return True

    async def _mark_task_provider(
        self,
        session: AsyncSession,
        task_id: int,
        provider: dict | None,
    ) -> bool:
        if not provider:
            return False
        result = await session.execute(select(AITask).where(AITask.id == int(task_id)))
        task = result.scalar_one_or_none()
        if not task or task.status not in ("queued", "processing"):
            return False
        task.params = {**(task.params or {}), "provider": provider}
        await session.commit()
        await mirror_ai_image_shadow_safely(
            task_id,
            phase="provider_selected",
            details={"provider": provider},
        )
        return True

    async def cleanup_stale_tasks(self, stale_after_minutes: int = 30) -> int:
        """将长期未收尾的队列任务自动降级，防止前端永久转圈。"""
        if not self.db:
            raise ValueError("cleanup_stale_tasks 需要数据库会话")

        cutoff = self._now_naive_utc() - timedelta(minutes=stale_after_minutes)
        result = await self.db.execute(select(AITask).where(AITask.status == "processing"))
        tasks = list(result.scalars().all())
        if not tasks:
            return 0

        now = self._now_naive_utc()
        recovered = 0
        recovered_task_ids: list[int] = []
        for task in tasks:
            processing_started_at = self._parse_naive_datetime(
                (task.params or {}).get("_processing_started_at")
                if isinstance(task.params, dict)
                else None
            ) or task.created_at
            if processing_started_at is not None and processing_started_at >= cutoff:
                continue
            task.status = "failed"
            task.error = f"任务超时未完成，已自动失败（超过 {stale_after_minutes} 分钟未收尾）"
            task.elapsed_seconds = (
                (now - processing_started_at).total_seconds()
                if processing_started_at is not None
                else None
            )
            task.finished_at = now
            recovered += 1
            recovered_task_ids.append(int(task.id))
        await self.db.commit()
        for task_id in recovered_task_ids:
            await mirror_ai_image_shadow_safely(
                task_id,
                phase="result_unknown",
                details={"reason": "stale_processing_cleanup"},
                result_unknown=True,
            )
        return recovered

    async def recover_incomplete_tasks(self) -> dict[str, int]:
        """Worker 启动时恢复上次中断的任务并对齐 Redis 队列。"""
        if not self.db:
            raise ValueError("recover_incomplete_tasks 需要数据库会话")

        drained_processing_ids = await ai_image_task_queue.drain_processing_tasks()
        requeue_processing_ids: list[int] = []
        reset_processing_ids: list[int] = []
        discarded_processing_ids: list[int] = []
        reset_processing = 0

        if drained_processing_ids:
            result = await self.db.execute(
                select(AITask).where(AITask.id.in_(drained_processing_ids))
            )
            task_map = {int(task.id): task for task in result.scalars().all()}

            for task_id in drained_processing_ids:
                task = task_map.get(task_id)
                if task is None:
                    discarded_processing_ids.append(task_id)
                    continue
                if task.status == "processing":
                    task.status = "queued"
                    task.error = None
                    task.elapsed_seconds = None
                    task.finished_at = None
                    requeue_processing_ids.append(task_id)
                    reset_processing_ids.append(task_id)
                    reset_processing += 1
                elif task.status == "queued":
                    requeue_processing_ids.append(task_id)
                else:
                    discarded_processing_ids.append(task_id)

            if reset_processing:
                await self.db.commit()
                for task_id in reset_processing_ids:
                    await mirror_ai_image_shadow_safely(
                        task_id,
                        phase="worker_recovered",
                        details={"reason": "worker_restart"},
                        result_unknown=True,
                    )

        if requeue_processing_ids:
            await ai_image_task_queue.requeue_drained_tasks(requeue_processing_ids)
        if discarded_processing_ids:
            await ai_image_task_queue.discard_tasks(discarded_processing_ids)

        queued_result = await self.db.execute(
            select(AITask.id).where(AITask.status == "queued")
        )
        queued_ids = [int(task_id) for task_id in queued_result.scalars().all()]
        enqueued_missing = await ai_image_task_queue.enqueue_missing_tasks(queued_ids)

        return {
            "reset_processing": reset_processing,
            "requeued_processing": len(requeue_processing_ids),
            "enqueued_missing": enqueued_missing,
            "discarded_processing": len(discarded_processing_ids),
        }

    async def _remove_watermarks(self, stored_urls: list[str]) -> list[str]:
        """调用远端 HTTP API 去除 AI 水印 (visible + invisible + metadata)"""
        if not getattr(settings, "remove_ai_watermarks_enabled", True):
            return stored_urls

        api_url = getattr(settings, "remove_ai_watermarks_api_url", "") or ""
        if not api_url:
            logger.warning("remove_ai_watermarks_api_url 未配置，跳过水印移除")
            return stored_urls

        api_url = api_url.rstrip("/")
        timeout = int(getattr(settings, "remove_ai_watermarks_timeout", 120) or 120)

        storage_root = Path(settings.storage_path).resolve()

        cleaned_urls: list[str] = []
        for url in stored_urls:
            try:
                cleaned_url = await self._remove_watermark_single(
                    url, api_url, timeout, storage_root
                )
                cleaned_urls.append(cleaned_url)
            except Exception:
                logger.exception("水印移除失败，使用原图: %s", url)
                cleaned_urls.append(url)
        return cleaned_urls

    async def _remove_watermark_single(
        self, url: str, api_url: str, timeout: int, storage_root: Path
    ) -> str:
        """通过 HTTP API 对单张图片去水印，返回清理后的本地 URL"""
        # 非本地 URL 跳过
        if not url.startswith("/uploads/"):
            return url

        # 读取本地图片文件
        rel = url[len("/uploads/"):]
        local_path = (storage_root / rel).resolve()
        if str(local_path) != str(storage_root) and not str(local_path).startswith(str(storage_root) + "/"):
            logger.warning("非法路径，跳过: %s", url)
            return url
        if not local_path.exists():
            logger.warning("文件不存在，跳过: %s", local_path)
            return url

        image_bytes = local_path.read_bytes()
        logger.info("发送去水印请求: %s (%dKB)", url, len(image_bytes) // 1024)
        start = time.time()

        retries = 3
        last_error = None
        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=float(timeout)) as client:
                    resp = await client.post(
                        f"{api_url}/remove-watermark",
                        files={"image": ("image.png", image_bytes, "image/png")},
                    )
                if resp.status_code == 200:
                    cleaned_bytes = resp.content
                    elapsed = time.time() - start

                    storage = get_storage()
                    name_hash = hashlib.md5(cleaned_bytes[:1024]).hexdigest()[:12]
                    ext = local_path.suffix or ".png"
                    filename = f"ai_clean_{name_hash}{ext}"
                    content_type = f"image/{ext.lstrip('.')}" if ext != ".jpg" else "image/jpeg"
                    new_url = await storage.save(cleaned_bytes, filename, content_type, subdir="ai-images")

                    logger.info("去水印完成 (%.1fs): %s -> %s", elapsed, url, new_url)
                    return new_url

                if resp.status_code == 503:
                    # 所有 GPU 忙，等一会重试
                    logger.warning("去水印 API 繁忙 (503)，%d/%d 次重试", attempt + 1, retries)
                    last_error = "API busy (503)"
                    await asyncio.sleep(5 * (attempt + 1))
                    continue

                err_text = resp.text[:300]
                logger.warning("去水印 API 失败 (HTTP %s): %s", resp.status_code, err_text)
                last_error = f"HTTP {resp.status_code}: {err_text}"
                return url  # 非 503 的错误不重试，直接返回原图

            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
                logger.warning("去水印 API 连接失败 (%d/%d): %s", attempt + 1, retries, e)
                last_error = str(e)
                if attempt < retries - 1:
                    await asyncio.sleep(3 * (attempt + 1))
                continue

        logger.error("去水印重试耗尽: %s", last_error)
        return url

    async def _run_generation_pipeline(
        self,
        prompt: str,
        params: dict,
        user_id: int | None = None,
        task_id: int | None = None,
    ) -> tuple[dict, list[str], list[str]]:
        upstream_prompt = prompt
        if self.adapter.name == "gptimage2":
            upstream_prompt = _append_dimension_prompt_instruction(prompt, params)
        await mirror_ai_image_shadow_safely(
            task_id,
            phase="upstream_started",
            details={"model_name": self.adapter.name},
        )
        result = self._normalize_failed_result(
            await self._generate_with_configured_provider(upstream_prompt, params, user_id, task_id)
        )
        await mirror_ai_image_shadow_safely(
            task_id,
            phase="upstream_finished",
            details={
                "status": result.get("status"),
                "upstream_task_id": result.get("task_id"),
                "image_count": len(result.get("image_urls") or []),
            },
        )
        raw_urls = result.get("image_urls", [])
        stored_urls = await _store_images(raw_urls)
        await mirror_ai_image_shadow_safely(
            task_id,
            phase="result_stored",
            details={
                "source_count": len(raw_urls),
                "stored_count": len(stored_urls),
            },
        )
        # AI 水印移除 (visible + invisible + metadata)
        if stored_urls and result.get("status") == "completed":
            stored_urls = await self._remove_watermarks(stored_urls)
            await mirror_ai_image_shadow_safely(
                task_id,
                phase="watermark_finished",
                details={"image_count": len(stored_urls)},
            )
        return result, raw_urls, stored_urls

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
            await mirror_ai_image_shadow_safely(ai_task.id, phase="queued")

        async def _do_generate():
            """实际执行生成的内部协程"""
            # 更新状态为 processing
            if ai_task and self.db:
                await self.db.refresh(ai_task)
                if ai_task.status not in ("queued", "processing"):
                    return
                ai_task.status = "processing"
                self._mark_processing_started(ai_task)
                await self.db.commit()
                await mirror_ai_image_shadow_safely(
                    ai_task.id,
                    phase="worker_started",
                )

            start_time = time.time()
            raw_urls: list[str] = []
            stored_urls: list[str] = []
            try:
                result, raw_urls, stored_urls = await asyncio.wait_for(
                    self._run_generation_pipeline(
                        prompt,
                        params,
                        user_id,
                        task_id=ai_task.id if ai_task else None,
                    ),
                    timeout=self._task_timeout_seconds(),
                )
                elapsed = time.time() - start_time

                # 更新任务状态
                if ai_task and self.db:
                    await self.db.refresh(ai_task)
                    if ai_task.status in ("queued", "processing"):
                        await self._finish_task_if_active(
                            self.db,
                            ai_task.id,
                            status="completed" if result.get("status") == "completed" else "failed",
                            error=result.get("error"),
                            result_urls=stored_urls,
                            elapsed_seconds=elapsed,
                            provider=result.get("provider"),
                            upstream_debug=result.get("upstream_debug"),
                        )

                # 返回持久化后的 URL
                result["image_urls"] = stored_urls if "image_urls" in result else raw_urls
                return result

            except asyncio.TimeoutError:
                elapsed = time.time() - start_time
                error = self._task_timeout_error()
                if ai_task and self.db:
                    await self.db.refresh(ai_task)
                    if ai_task.status in ("queued", "processing"):
                        await self._finish_task_if_active(
                            self.db,
                            ai_task.id,
                            status="failed",
                            error=error,
                            elapsed_seconds=elapsed,
                            shadow_phase="result_unknown",
                            result_unknown=True,
                        )
                return {
                    "task_id": "",
                    "status": "failed",
                    "image_urls": [],
                    "error": error,
                }
            except Exception as e:
                elapsed = time.time() - start_time
                if ai_task and self.db:
                    await self.db.refresh(ai_task)
                    if ai_task.status in ("queued", "processing"):
                        await self._finish_task_if_active(
                            self.db,
                            ai_task.id,
                            status="failed",
                            error=str(e),
                            elapsed_seconds=elapsed,
                        )
                # 不重新抛出异常，返回失败结果让前端正常显示错误
                return {
                    "task_id": "",
                    "status": "failed",
                    "image_urls": [],
                    "error": str(e),
                }

        # 将生成任务加入队列
        try:
            result = await image_generation_queue.enqueue(_do_generate())
        except Exception as e:
            if ai_task and self.db:
                await self.db.refresh(ai_task)
                if ai_task.status in ("queued", "processing"):
                    await self._finish_task_if_active(
                        self.db,
                        ai_task.id,
                        status="failed",
                        error=str(e),
                    )
            raise
        return result

    async def _generate_with_configured_provider(
        self,
        prompt: str,
        params: dict,
        user_id: int | None = None,
        task_id: int | None = None,
    ) -> dict:
        """优先使用管理后台配置的生图入口；没有配置时回落到静态 adapter。"""
        if self.db and self.adapter.name == "gptimage2":
            provider_service = AIImageProviderService(self.db)
            providers = await provider_service.list_providers("gptimage2")
            if providers:
                async def mark_selected_provider(provider: dict) -> None:
                    if not task_id:
                        return
                    try:
                        await self._mark_task_provider(self.db, int(task_id), provider)
                    except Exception as exc:
                        await self.db.rollback()
                        logger.warning(
                            "Failed to mark selected image provider: task_id=%s error=%s",
                            task_id,
                            exc,
                        )

                provider_result = await provider_service.generate(
                    prompt=prompt,
                    params=params,
                    user_id=user_id,
                    model_name="gptimage2",
                    on_provider_selected=mark_selected_provider if task_id else None,
                )
                if not self._should_fallback_to_adapter(provider_result):
                    return provider_result
        return await self.adapter.generate_image(prompt=prompt, **params)

    async def submit(
        self,
        prompt: str,
        params: dict,
        user_id: int | None = None,
        client_request_id: str | None = None,
    ) -> dict:
        """提交生图任务：立即返回 task_id，后台异步执行"""
        if not self.db:
            raise ValueError("submit 模式需要数据库会话")

        normalized_user_id = user_id or 0
        normalized_client_request_id = self._normalize_client_request_id(client_request_id)
        await self._lock_user_active_tasks(normalized_user_id)
        if normalized_client_request_id:
            existing_result = await self.db.execute(
                select(AITask).where(
                    AITask.user_id == normalized_user_id,
                    AITask.client_request_id == normalized_client_request_id,
                )
            )
            existing_task = existing_result.scalar_one_or_none()
            if existing_task is not None:
                return self._task_response(existing_task)

        active_count_result = await self.db.execute(
            select(func.count())
            .select_from(AITask)
            .where(
                AITask.user_id == normalized_user_id,
                AITask.status.in_(("queued", "processing")),
            )
        )
        active_count = int(active_count_result.scalar() or 0)
        if active_count >= MAX_USER_ACTIVE_IMAGE_TASKS:
            raise ValueError(f"最多同时提交 {MAX_USER_ACTIVE_IMAGE_TASKS} 个生图任务，请等待当前任务完成后再试")

        ai_task = AITask(
            user_id=normalized_user_id,
            client_request_id=normalized_client_request_id,
            model_name=self.adapter.name,
            prompt=prompt,
            negative_prompt=params.get("negative_prompt"),
            params={k: v for k, v in params.items() if k != "negative_prompt"},
            status="queued",
        )
        self.db.add(ai_task)
        await self.db.commit()
        await self.db.refresh(ai_task)
        await mirror_ai_image_shadow_safely(ai_task.id, phase="queued")
        try:
            await ai_image_task_queue.enqueue_task(ai_task.id)
        except Exception as exc:
            ai_task.status = "failed"
            ai_task.error = f"任务入队失败: {exc}"
            ai_task.finished_at = self._now_naive_utc()
            await self.db.commit()
            await mirror_ai_image_shadow_safely(
                ai_task.id,
                phase="enqueue_failed",
                details={"reason": "queue_unavailable"},
            )
            raise RuntimeError("AI 生图队列暂时不可用，请稍后重试") from exc
        return {
            "task_id": str(ai_task.id),
            "status": "queued",
            "image_urls": [],
            "error": None,
            "client_request_id": ai_task.client_request_id,
            "created_at": str(ai_task.created_at) if ai_task.created_at else None,
            "finished_at": None,
            "elapsed_seconds": None,
        }

    async def get_active_tasks(self, user_id: int) -> dict:
        """Return the current user's active queued/processing image tasks."""
        if not self.db:
            raise ValueError("get_active_tasks 需要数据库会话")
        result = await self.db.execute(
            select(AITask)
            .where(
                AITask.user_id == int(user_id),
                AITask.status.in_(("queued", "processing")),
            )
            .order_by(AITask.created_at.asc(), AITask.id.asc())
        )
        tasks = list(result.scalars().all())
        return {
            "active_count": len(tasks),
            "max_active": MAX_USER_ACTIVE_IMAGE_TASKS,
            "can_submit": len(tasks) < MAX_USER_ACTIVE_IMAGE_TASKS,
            "items": [
                {
                    "id": task.id,
                    "task_id": str(task.id),
                    "model_name": task.model_name,
                    "status": task.status,
                    "prompt": task.prompt,
                    "created_at": str(task.created_at),
                    "finished_at": str(task.finished_at) if task.finished_at else None,
                }
                for task in tasks
            ],
        }

    async def execute_submitted_task(self, task_id: int) -> str:
        """由独立 worker 消费并执行已提交的任务。"""
        if not self.db:
            raise ValueError("execute_submitted_task 需要数据库会话")

        result = await self.db.execute(select(AITask).where(AITask.id == int(task_id)))
        task = result.scalar_one_or_none()
        if not task:
            return "missing"
        if task.status != "queued":
            return task.status or "skipped"

        task.status = "processing"
        task.error = None
        task.finished_at = None
        task.elapsed_seconds = None
        self._mark_processing_started(task)
        await self.db.commit()
        await mirror_ai_image_shadow_safely(task.id, phase="worker_started")

        start_time = time.time()
        try:
            model = model_registry.get(task.model_name)
            if not model:
                raise ValueError(f"Model '{task.model_name}' not registered")
            task_params = task.params or {}
            service = AIImageService(model_name=task.model_name, db=self.db)
            gen_result, raw_urls, stored_urls = await asyncio.wait_for(
                service._run_generation_pipeline(
                    prompt=task.prompt,
                    params=task_params,
                    user_id=task.user_id,
                    task_id=task.id,
                ),
                timeout=service._task_timeout_seconds(),
            )
            elapsed = time.time() - start_time
            final_status = (
                "completed" if gen_result.get("status") == "completed" else "failed"
            )
            await self._finish_task_if_active(
                self.db,
                task.id,
                status=final_status,
                error=gen_result.get("error"),
                result_urls=stored_urls,
                elapsed_seconds=elapsed,
                provider=gen_result.get("provider"),
                upstream_debug=gen_result.get("upstream_debug"),
            )
            return final_status
        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            await self._finish_task_if_active(
                self.db,
                task.id,
                status="failed",
                error=self._task_timeout_error(),
                elapsed_seconds=elapsed,
                shadow_phase="result_unknown",
                result_unknown=True,
            )
            return "failed"
        except Exception as e:
            elapsed = time.time() - start_time
            await self._finish_task_if_active(
                self.db,
                task.id,
                status="failed",
                error=str(e),
                elapsed_seconds=elapsed,
            )
            return "failed"

    async def get_local_task_status(
        self,
        task_id: int,
        *,
        user_id: int | None = None,
        allow_any_user: bool = False,
    ) -> dict | None:
        if not self.db:
            raise ValueError("get_local_task_status 需要数据库会话")
        stmt = select(AITask).where(AITask.id == task_id)
        if user_id is not None and not allow_any_user:
            stmt = stmt.where(AITask.user_id == int(user_id))
        result = await self.db.execute(stmt)
        task = result.scalar_one_or_none()
        if not task:
            return None
        return {
            **self._task_response(task),
        }

    async def get_task_by_client_request_id(self, user_id: int, client_request_id: str) -> dict | None:
        if not self.db:
            raise ValueError("get_task_by_client_request_id 需要数据库会话")
        normalized_client_request_id = self._normalize_client_request_id(client_request_id)
        if not normalized_client_request_id:
            return None
        result = await self.db.execute(
            select(AITask).where(
                AITask.user_id == int(user_id),
                AITask.client_request_id == normalized_client_request_id,
            )
        )
        task = result.scalar_one_or_none()
        return self._task_response(task) if task else None

    async def cancel(self, task_id: str, user_id: int | None = None) -> None:
        """取消任务"""
        if task_id.isdigit() and self.db:
            result = await self.db.execute(select(AITask).where(AITask.id == int(task_id)))
            task = result.scalar_one_or_none()
            if task:
                if user_id is not None and task.user_id != user_id:
                    raise ValueError("无权取消该任务")
                if task.status not in ("completed", "failed", "cancelled"):
                    task.status = "cancelled"
                    task.error = "已取消"
                    task.elapsed_seconds = (
                        (self._now_naive_utc() - task.created_at).total_seconds()
                        if task.created_at is not None
                        else None
                    )
                    task.finished_at = self._now_naive_utc()
                    await self.db.commit()
                    await mirror_ai_image_shadow_safely(
                        task.id,
                        phase="cancelled",
                    )
                    try:
                        await ai_image_task_queue.remove_pending_task(int(task_id))
                    except Exception as exc:
                        logger.warning("移除已取消的待处理生图任务失败: task_id=%s error=%s", task_id, exc)
            return

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
