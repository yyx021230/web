from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.services.ai_image_service import AIImageService
from app.services.xhs_schedule_service import (
    due_xhs_schedule_task_keys,
    has_running_xhs_scheduled_task,
    run_xhs_scheduled_task,
)
from app.services.xhs_service import XHSService
from app.services.hermes_workflow_service import enqueue_due_hermes_runs
from app.utils.timezone import cst_now_naive

logger = logging.getLogger(__name__)


async def hermes_workflow_schedule_loop(
    session_factory: async_sessionmaker,
    poll_seconds: int = 30,
):
    """Enqueue the administrator's daily Hermes 8×5 production batch."""
    while True:
        try:
            async with session_factory() as session:
                run_ids = await enqueue_due_hermes_runs(session)
            for run_id in run_ids:
                logger.info("已创建 Hermes 每日内容批次: run_id=%s", run_id)
        except Exception:
            logger.exception("Hermes 定时内容生产轮询失败")
        await asyncio.sleep(max(15, int(poll_seconds or 30)))


async def sync_task_loop(session_factory: async_sessionmaker, interval_hours: int = 12):
    """
    定时同步帖子数据的后台任务。
    每天早晚各执行一次（默认间隔 12 小时）。
    首次执行时间可配置：默认启动后等待至下一个 08:00 或 20:00。
    """
    while True:
        now = cst_now_naive()
        # 计算下一个执行时间：最近的 08:00 或 20:00
        if now.hour < 8:
            next_run = now.replace(hour=8, minute=0, second=0, microsecond=0)
        elif now.hour < 20:
            next_run = now.replace(hour=20, minute=0, second=0, microsecond=0)
        else:
            next_run = now.replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)

        wait_seconds = (next_run - now).total_seconds()
        logger.info(f"下次数据同步时间: {next_run.isoformat()} (等待 {wait_seconds:.0f} 秒)")

        await asyncio.sleep(wait_seconds)

        try:
            logger.info("开始执行帖子数据同步...")
            async with session_factory() as session:
                service = XHSService(session)
                count = await service.sync_all_posts()
            logger.info(f"数据同步完成: 成功更新 {count} 条帖子")
        except Exception as e:
            logger.error(f"数据同步失败: {e}", exc_info=True)


async def scheduled_publish_loop(session_factory: async_sessionmaker, interval_seconds: int = 60):
    """定时发布轮询：按间隔扫描到期帖子并触发发布。"""
    while True:
        try:
            async with session_factory() as session:
                service = XHSService(session)
                count = await service.execute_due_scheduled_posts()
                if count > 0:
                    logger.info(f"定时发布执行完成: {count} 条")
        except Exception as e:
            err_text = str(e).lower()
            if "no such column: xhs_posts.scheduled_at" in err_text:
                logger.error(
                    "定时发布字段缺失：请先执行数据库迁移 `./.venv/bin/alembic upgrade head`，"
                    "然后重启后端服务。"
                )
            else:
                logger.error(f"定时发布执行失败: {e}", exc_info=True)
        await asyncio.sleep(interval_seconds)


async def account_notes_sync_loop(session_factory: async_sessionmaker):
    """每天 19:00 后执行主页字段补齐，不负责新增帖子主记录。"""
    while True:
        now = cst_now_naive()
        if now.hour < 19:
            next_run = now.replace(hour=19, minute=0, second=0, microsecond=0)
        else:
            next_run = now.replace(hour=19, minute=0, second=0, microsecond=0) + timedelta(days=1)

        wait_seconds = (next_run - now).total_seconds()
        logger.info(f"下次账号帖子同步时间: {next_run.isoformat()} (等待 {wait_seconds:.0f} 秒)")
        await asyncio.sleep(wait_seconds)

        try:
            logger.info("开始执行账号帖子同步...")
            async with session_factory() as session:
                service = XHSService(session)
                result = await service.sync_account_notes(user=None, limit_per_env=30)
            logger.info(
                "主页帖子补充完成: 账号=%s, 补齐=%s, 待创作者中心建档=%s, 拉取总数=%s",
                result.get("synced_accounts", 0),
                result.get("updated_notes", 0),
                result.get("deferred_homepage_notes", 0),
                result.get("total_notes", 0),
            )
        except Exception as e:
            err_text = str(e).lower()
            if "no such column: xhs_account_notes.content" in err_text:
                logger.error(
                    "账号帖子表缺少内容字段：请先执行数据库迁移 `./.venv/bin/alembic upgrade head`，"
                    "然后重启后端服务。"
                )
            else:
                logger.error(f"账号帖子列表同步失败: {e}", exc_info=True)
            continue

        try:
            async with session_factory() as session:
                service = XHSService(session)
                metric_result = await service.sync_existing_account_note_stats()
            logger.info(
                "账号帖子互动数据同步完成: 总数=%s, 成功=%s, 失败=%s",
                metric_result.get("total_notes", 0),
                metric_result.get("synced_notes", 0),
                metric_result.get("failed_notes", 0),
            )
        except Exception as e:
            err_text = str(e).lower()
            if "no such column: xhs_account_notes.content" in err_text:
                logger.error(
                    "账号帖子详情同步失败：本地数据库尚未升级到内容字段版本，请执行 "
                    "`./.venv/bin/alembic upgrade head` 后重启。"
                )
            elif "无法获取采集环境" in str(e):
                logger.warning(
                    "账号帖子详情同步跳过：同步环境浏览器未能启动。请检查云登本地服务、"
                    "同步环境配置，以及该环境是否能在云登客户端中正常打开。错误=%s",
                    e,
                )
            else:
                logger.error(f"账号帖子详情同步失败: {e}", exc_info=True)


async def xhs_configured_task_loop(
    session_factory: async_sessionmaker,
    poll_seconds: int = 30,
):
    """按后台配置轮询执行账户数据/投流数据定时任务。"""
    while True:
        try:
            if has_running_xhs_scheduled_task():
                due_task_keys = []
            else:
                async with session_factory() as session:
                    due_task_keys = await due_xhs_schedule_task_keys(session)
            if due_task_keys:
                task_key = due_task_keys[0]
                logger.info("开始执行后台定时任务: %s", task_key)
                launched = await run_xhs_scheduled_task(
                    task_key,
                    source="schedule",
                    session_factory=session_factory,
                )
                if launched:
                    logger.info("后台定时任务已结束: %s", task_key)
        except Exception as e:
            logger.error(f"后台定时任务轮询失败: {e}", exc_info=True)
        await asyncio.sleep(max(15, int(poll_seconds or 30)))


async def ai_task_cleanup_loop(
    session_factory: async_sessionmaker,
    interval_seconds: int | None = None,
    stale_after_minutes: int | None = None,
):
    """定时清理长期未收尾的 AI 生图任务。"""
    cleanup_interval = max(
        30,
        int(
            interval_seconds
            or getattr(settings, "ai_task_cleanup_interval_seconds", 60)
            or 60
        ),
    )
    stale_minutes = max(
        5,
        int(
            stale_after_minutes
            or getattr(settings, "ai_task_stale_after_minutes", 30)
            or 30
        ),
    )

    while True:
        try:
            async with session_factory() as session:
                recovered = await AIImageService(db=session).cleanup_stale_tasks(
                    stale_after_minutes=stale_minutes
                )
                if recovered:
                    logger.warning(
                        "Recovered %d stale AI image tasks during runtime cleanup",
                        recovered,
                    )
        except Exception as e:
            logger.error(f"AI 生图超时清理失败: {e}", exc_info=True)

        await asyncio.sleep(cleanup_interval)
