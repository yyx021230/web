from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.db.session import async_session
from app.models.xhs_report import XHSAdStatsDailyAccount, XHSAdStatsDailyNote, XHSReportDaily
from app.models.xhs_report_refresh_run import XHSReportRefreshRun
from app.models.xhs_schedule_run_log import XHSScheduleRunLog
from app.models.user import User
from app.models.user_xhs_env import UserXHSEnvironment
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_environment import XHSEnvironment
from app.models.xhs_schedule_setting import XHSScheduleSetting
from app.services.xhs_service import XHSService
from app.services.xhs_report_refresh_shadow import (
    create_report_refresh_run_safely,
    finish_report_refresh_run_safely,
    mark_report_refresh_running_safely,
    record_report_refresh_result_safely,
)
from app.utils.timezone import cst_now_naive, utc_now_naive, utc_naive_to_aware_iso, utc_naive_to_cst_naive

logger = logging.getLogger(__name__)

ACCOUNT_DATA_SYNC_TASK = "account_data_sync"
AD_DATA_REFRESH_TASK = "ad_data_refresh"
AD_REPORT_PUBLISH_TASK = "ad_report_publish"
ALL_SCHEDULE_TASK_KEYS = (ACCOUNT_DATA_SYNC_TASK, AD_DATA_REFRESH_TASK, AD_REPORT_PUBLISH_TASK)
AD_REPORT_TYPES = ("simple", "standard", "creative", "simple_note", "standard_note")
AD_SUMMARY_REPORT_TYPES = ("simple", "standard")
_RUNNING_TASK_KEYS: set[str] = set()
STALE_SCHEDULE_RUN_HOURS = 12
RESTART_RECONCILE_GRACE_SECONDS = 120
_PROCESS_STARTED_AT_UTC = utc_now_naive()


def _normalize_run_time(value: object) -> str:
    text = str(value or "").strip()
    try:
        parsed = datetime.strptime(text, "%H:%M")
    except ValueError as exc:
        raise ValueError("执行时间格式必须是 HH:MM") from exc
    return parsed.strftime("%H:%M")


def _scheduled_time_today(run_time: str, now: datetime | None = None) -> datetime:
    current = now or cst_now_naive()
    hour, minute = [int(part) for part in run_time.split(":", 1)]
    return current.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _default_task_definition(task_key: str) -> dict[str, Any]:
    if task_key == ACCOUNT_DATA_SYNC_TASK:
        return {
            "task_key": task_key,
            "label": "账户数据同步",
            "description": "支持主页帖子、创作者中心互动、未同步详情补齐和内容打标的组合定时任务。",
            "enabled": bool(settings.xhs_enable_account_notes_sync_loop),
            "run_time": "19:00",
            "config": {
                "target_scope": "all",
                "target_user_ids": [],
                "target_environment_ids": [],
                "yundeng_sync_concurrency": 5,
                "post_sync_enabled": True,
                "post_sync_runner_ids": [],
                "post_sync_limit_per_env": 60,
                "engagement_sync_enabled": False,
                "detail_sync_enabled": False,
                "detail_sync_mode": "unpublished_only",
                "detail_runner_ids": [],
                "detail_total_limit": 20,
                "detail_limit_per_runner": 10,
                "detail_pause_min_seconds": 45,
                "detail_pause_max_seconds": 90,
                "detail_max_post_age_days": 30,
                "content_tag_enabled": False,
                "content_tag_ai_origin_type": "all",
                "content_tag_status": "all",
                "content_tag_concurrency": 20,
            },
        }
    if task_key == AD_DATA_REFRESH_TASK:
        return {
            "task_key": task_key,
            "label": "投流数据刷新",
            "description": "每天自动回刷投流报表缓存，供投流数据看板使用。",
            "enabled": False,
            "run_time": "06:30",
            "config": {
                "date_range_mode": "relative",
                "days": 30,
                "start_date": "",
                "end_date": "",
                "report_types": list(AD_REPORT_TYPES),
            },
        }
    if task_key == AD_REPORT_PUBLISH_TASK:
        return {
            "task_key": task_key,
            "label": "汇报发布",
            "description": "每天先刷新当天简单投/标准投数据，再汇总指定广告账户并推送到飞书群。",
            "enabled": False,
            "run_time": "18:30",
            "config": {
                "message_title": "今日小红书零跑汇总数据",
                "webhook_url": "",
                "account_ids": [],
                "report_types": list(AD_SUMMARY_REPORT_TYPES),
                "refresh_before_send": True,
                "require_all_accounts_ready": True,
            },
        }
    raise ValueError(f"未知任务类型: {task_key}")


def _normalize_task_config(task_key: str, config: dict[str, Any] | None) -> dict[str, Any]:
    config = dict(config or {})
    defaults = _default_task_definition(task_key)["config"]
    merged = {**defaults, **config}
    if task_key == ACCOUNT_DATA_SYNC_TASK:
        target_scope = str(merged.get("target_scope") or "all").strip()
        if target_scope not in {"all", "owner_users", "environment_ids"}:
            target_scope = "all"
        detail_sync_mode = str(merged.get("detail_sync_mode") or "unpublished_only").strip()
        ai_origin_type = str(merged.get("content_tag_ai_origin_type") or "all").strip()
        status = str(merged.get("content_tag_status") or "all").strip()
        return {
            "target_scope": target_scope,
            "target_user_ids": sorted({int(item) for item in (merged.get("target_user_ids") or []) if int(item) > 0}),
            "target_environment_ids": sorted({int(item) for item in (merged.get("target_environment_ids") or []) if int(item) > 0}),
            "yundeng_sync_concurrency": max(1, min(int(merged.get("yundeng_sync_concurrency") or 5), 5)),
            "post_sync_enabled": bool(merged.get("post_sync_enabled")),
            "post_sync_runner_ids": sorted({int(item) for item in (merged.get("post_sync_runner_ids") or []) if int(item) > 0}),
            "post_sync_limit_per_env": max(1, min(int(merged.get("post_sync_limit_per_env") or 60), 60)),
            "engagement_sync_enabled": bool(merged.get("engagement_sync_enabled")),
            "detail_sync_enabled": bool(merged.get("detail_sync_enabled")),
            "detail_sync_mode": detail_sync_mode if detail_sync_mode in {"all", "unpublished_only"} else "unpublished_only",
            "detail_runner_ids": sorted({int(item) for item in (merged.get("detail_runner_ids") or []) if int(item) > 0}),
            "detail_total_limit": max(1, min(int(merged.get("detail_total_limit") or 20), 1000)),
            "detail_limit_per_runner": max(1, min(int(merged.get("detail_limit_per_runner") or 10), 60)),
            "detail_pause_min_seconds": max(0.0, min(float(merged.get("detail_pause_min_seconds") or 45), 900.0)),
            "detail_pause_max_seconds": max(
                max(0.0, min(float(merged.get("detail_pause_min_seconds") or 45), 900.0)),
                min(float(merged.get("detail_pause_max_seconds") or 90), 900.0),
            ),
            "detail_max_post_age_days": max(0, min(int(merged.get("detail_max_post_age_days") or 30), 3650)),
            "content_tag_enabled": bool(merged.get("content_tag_enabled")),
            "content_tag_ai_origin_type": ai_origin_type if ai_origin_type in {"all", "__unset__", "manual", "text_ai", "image_ai", "all_ai"} else "all",
            "content_tag_status": status or "all",
            "content_tag_concurrency": max(1, min(int(merged.get("content_tag_concurrency") or 20), 50)),
        }
    if task_key == AD_DATA_REFRESH_TASK:
        date_range_mode = str(merged.get("date_range_mode") or "relative").strip()
        if date_range_mode not in {"relative", "fixed"}:
            date_range_mode = "relative"
        days = max(1, min(int(merged.get("days") or 30), 365))
        start_date = str(merged.get("start_date") or "").strip()
        end_date = str(merged.get("end_date") or "").strip()
        if date_range_mode == "fixed":
            try:
                start_d = date.fromisoformat(start_date)
                end_d = date.fromisoformat(end_date)
            except ValueError as exc:
                raise ValueError("固定日期范围必须填写合法的开始日期和结束日期") from exc
            if start_d > end_d:
                raise ValueError("开始日期不能晚于结束日期")
            if (end_d - start_d).days > 365:
                raise ValueError("投流数据刷新范围不能超过 366 天")
        merged["date_range_mode"] = date_range_mode
        merged["days"] = days
        merged["start_date"] = start_date if date_range_mode == "fixed" else ""
        merged["end_date"] = end_date if date_range_mode == "fixed" else ""
        raw_report_types = merged.get("report_types") or list(AD_REPORT_TYPES)
        normalized_report_types = [str(item).strip() for item in raw_report_types if str(item).strip() in AD_REPORT_TYPES]
        merged["report_types"] = normalized_report_types or list(AD_REPORT_TYPES)
        return merged
    if task_key == AD_REPORT_PUBLISH_TASK:
        raw_account_ids = merged.get("account_ids") or []
        if isinstance(raw_account_ids, str):
            separators = [",", "\n", "\r", "\t", " "]
            parsed_account_ids = [str(raw_account_ids)]
            for separator in separators:
                next_items: list[str] = []
                for item in parsed_account_ids:
                    next_items.extend(item.split(separator))
                parsed_account_ids = next_items
            raw_account_ids = parsed_account_ids
        raw_report_types = merged.get("report_types") or list(AD_SUMMARY_REPORT_TYPES)
        normalized_report_types = [str(item).strip() for item in raw_report_types if str(item).strip() in AD_SUMMARY_REPORT_TYPES]
        return {
            "message_title": str(merged.get("message_title") or "今日小红书零跑汇总数据").strip() or "今日小红书零跑汇总数据",
            "webhook_url": str(merged.get("webhook_url") or "").strip(),
            "account_ids": sorted({str(item).strip() for item in raw_account_ids if str(item).strip()}),
            "report_types": normalized_report_types or list(AD_SUMMARY_REPORT_TYPES),
            "refresh_before_send": bool(merged.get("refresh_before_send", True)),
            "require_all_accounts_ready": bool(merged.get("require_all_accounts_ready", True)),
        }
    raise ValueError(f"未知任务类型: {task_key}")


def _resolve_ad_refresh_date_range(config: dict[str, Any]) -> tuple[date, date, int]:
    normalized = _normalize_task_config(AD_DATA_REFRESH_TASK, config)
    if normalized.get("date_range_mode") == "fixed":
        start_d = date.fromisoformat(str(normalized.get("start_date") or ""))
        end_d = date.fromisoformat(str(normalized.get("end_date") or ""))
    else:
        days = max(1, min(int(normalized.get("days") or 30), 365))
        # 巨量/小红书投流日报当天数据不稳定且常被接口拒绝，最近 N 天固定截至昨天。
        end_d = cst_now_naive().date() - timedelta(days=1)
        start_d = end_d - timedelta(days=days - 1)
    days = (end_d - start_d).days + 1
    return start_d, end_d, days


def _next_run_cst(run_time: str, last_run_at: datetime | None) -> datetime:
    now = cst_now_naive()
    scheduled_today = _scheduled_time_today(run_time, now)
    if now < scheduled_today:
        return scheduled_today
    if last_run_at is not None:
        last_run_cst = utc_naive_to_cst_naive(last_run_at)
        if last_run_cst >= scheduled_today:
            return scheduled_today + timedelta(days=1)
    return scheduled_today


def _is_due(enabled: bool, run_time: str, last_run_at: datetime | None) -> bool:
    if not enabled:
        return False
    now = cst_now_naive()
    scheduled_today = _scheduled_time_today(run_time, now)
    if now < scheduled_today:
        return False
    if last_run_at is None:
        return True
    return utc_naive_to_cst_naive(last_run_at) < scheduled_today


def _scope_label(scope: str, target_env_ids: list[int], config: dict[str, Any]) -> str:
    if scope == "owner_users":
        return f"指定负责人({len(config.get('target_user_ids') or [])}人)"
    if scope == "environment_ids":
        return f"指定账号({len(target_env_ids)}个)"
    return "全量"


def _build_even_runner_assignments(runner_ids: list[int], target_env_ids: list[int]) -> dict[int, list[int]]:
    assignments = {runner_id: [] for runner_id in runner_ids}
    if not runner_ids:
        return assignments
    for index, env_id in enumerate(target_env_ids):
        runner_id = runner_ids[index % len(runner_ids)]
        assignments[runner_id].append(env_id)
    return {runner_id: env_ids for runner_id, env_ids in assignments.items() if env_ids}


def _distribute_limit(total_limit: int, env_ids: list[int]) -> list[tuple[int, int]]:
    if not env_ids:
        return []
    base = total_limit // len(env_ids)
    remainder = total_limit % len(env_ids)
    result: list[tuple[int, int]] = []
    for index, env_id in enumerate(env_ids):
        result.append((env_id, base + (1 if index < remainder else 0)))
    return result


def _report_metric_value(row: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            raw = str(value).strip().replace(",", "")
            if raw.endswith("%"):
                raw = raw[:-1]
            try:
                parsed = float(raw)
                if parsed == parsed:
                    return parsed
            except Exception:
                continue
    return 0.0


def _report_conversion_value(row: dict[str, Any]) -> float:
    return _report_metric_value(row, "msg_leads_num", "valid_leads", "leads", "conversion", "conversions")


def _format_publish_message(title: str, summary: dict[str, Any]) -> str:
    return "\n".join([
        title,
        f"● 展示数：{int(summary['impression'])}",
        f"● 点击数：{int(summary['click'])}",
        f"● 总投流线索：{int(summary['conversion'])}",
        f"● 总投流：{float(summary['fee']):.2f}",
        f"● 单个线索成本：{float(summary['conversion_cost']):.2f}",
    ])


async def _send_feishu_robot_message(webhook_url: str, text: str) -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), trust_env=False) as client:
        response = await client.post(
            webhook_url,
            json={
                "msg_type": "text",
                "content": {
                    "text": text,
                },
            },
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except Exception:
            payload = {}
        status_code = payload.get("StatusCode")
        if status_code not in (None, 0):
            raise ValueError(payload.get("StatusMessage") or payload.get("msg") or "飞书机器人返回失败")


async def _load_system_admin_user(db: AsyncSession) -> User:
    user = (await db.execute(select(User).where(User.role == "admin").order_by(User.id.asc()))).scalars().first()
    if not user:
        raise ValueError("系统中还没有管理员账号，暂时无法执行创作者中心帖子主同步")
    return user


async def _resolve_target_environment_ids(db: AsyncSession, config: dict[str, Any]) -> list[int]:
    stmt = (
        select(XHSEnvironment.id)
        .where(
            and_(
                XHSEnvironment.status == "active",
                or_(XHSEnvironment.is_sync_runner.is_(False), XHSEnvironment.is_sync_runner.is_(None)),
            )
        )
        .order_by(XHSEnvironment.account_name.asc())
    )
    all_env_ids = [int(item) for item in (await db.execute(stmt)).scalars().all()]
    scope = str(config.get("target_scope") or "all")
    if scope == "environment_ids":
        selected = {int(item) for item in (config.get("target_environment_ids") or []) if int(item) > 0}
        return [env_id for env_id in all_env_ids if env_id in selected]
    if scope == "owner_users":
        selected_users = {int(item) for item in (config.get("target_user_ids") or []) if int(item) > 0}
        if not selected_users:
            return []
        assigned_env_ids = [
            int(item)
            for item in (
                await db.execute(
                    select(UserXHSEnvironment.environment_id)
                    .where(UserXHSEnvironment.user_id.in_(list(selected_users)))
                )
            ).scalars().all()
        ]
        allowed = set(assigned_env_ids)
        return [env_id for env_id in all_env_ids if env_id in allowed]
    return all_env_ids


def _normalize_creator_login_phone(value: object) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    if len(digits) == 13 and digits.startswith("86"):
        digits = digits[2:]
    return digits


def _creator_sync_configuration_issues(env: XHSEnvironment) -> list[str]:
    issues: list[str] = []
    if not str(env.account_name or "").strip():
        issues.append("账号名称")
    if not str(env.xhs_account_id or "").strip():
        issues.append("小红书ID")
    if len(_normalize_creator_login_phone(env.login_phone_number)) != 11:
        issues.append("登录手机号")
    if str(env.xhs_account_type or "").strip() not in {
        "enterprise_professional",
        "enterprise_employee",
        "personal",
    }:
        issues.append("账号类型")
    return issues


async def _partition_creator_sync_targets(
    db: AsyncSession,
    target_environment_ids: list[int],
) -> tuple[list[int], list[dict[str, Any]], dict[int, str]]:
    if not target_environment_ids:
        return [], [], {}
    rows = list(
        (
            await db.execute(
                select(XHSEnvironment)
                .where(XHSEnvironment.id.in_(target_environment_ids))
                .order_by(XHSEnvironment.account_name.asc(), XHSEnvironment.id.asc())
            )
        ).scalars().all()
    )
    rows_by_id = {int(row.id): row for row in rows}
    eligible_ids: list[int] = []
    skipped: list[dict[str, Any]] = []
    account_names: dict[int, str] = {}
    for environment_id in target_environment_ids:
        env = rows_by_id.get(int(environment_id))
        if env is None:
            continue
        account_names[int(env.id)] = str(env.account_name or "").strip() or f"环境{env.id}"
        issues = _creator_sync_configuration_issues(env)
        if issues:
            skipped.append(
                {
                    "environment_id": int(env.id),
                    "account_name": account_names[int(env.id)],
                    "reason": f"未配置完整：{'、'.join(issues)}",
                }
            )
            continue
        eligible_ids.append(int(env.id))
    return eligible_ids, skipped, account_names


def _failed_creator_environment_ids(result: dict[str, Any]) -> list[int]:
    failed_ids: list[int] = []
    seen: set[int] = set()
    for item in result.get("failed_accounts") or []:
        try:
            environment_id = int(item.get("environment_id") or 0)
        except (AttributeError, TypeError, ValueError):
            continue
        if environment_id > 0 and environment_id not in seen:
            seen.add(environment_id)
            failed_ids.append(environment_id)
    return failed_ids


async def _run_creator_sync_pass(
    service: XHSService,
    *,
    admin_user: User,
    target_environment_ids: list[int],
    concurrency: int,
    account_names: dict[int, str],
) -> dict[str, Any]:
    if not target_environment_ids:
        return {
            "synced_accounts": 0,
            "created_notes": 0,
            "updated_notes": 0,
            "failed_accounts": [],
        }
    try:
        return await service.sync_account_note_engagements(
            user=admin_user,
            environment_id=None,
            target_environment_ids=target_environment_ids,
            sync_account_limit=len(target_environment_ids),
            concurrency=concurrency,
        )
    except Exception as exc:
        logger.exception(
            "创作者中心批次执行异常，批次内账号统一记为失败: target_environment_ids=%s",
            target_environment_ids,
        )
        return {
            "synced_accounts": 0,
            "created_notes": 0,
            "updated_notes": 0,
            "failed_accounts": [
                {
                    "environment_id": environment_id,
                    "account_name": account_names.get(environment_id, f"环境{environment_id}"),
                    "error": str(exc),
                }
                for environment_id in target_environment_ids
            ],
        }


async def _run_content_tag_batch(
    db: AsyncSession,
    *,
    target_env_ids: list[int],
    ai_origin_type: str,
    status: str,
    concurrency: int,
) -> dict[str, Any]:
    from app.api.v1.xhs import _tag_xhs_account_note_with_model

    conditions = [
        XHSAccountNote.title != "",
        XHSAccountNote.detail_synced_at.is_not(None),
        XHSAccountNote.content_status == "from_detail",
        XHSAccountNote.content.is_not(None),
        XHSAccountNote.content != "",
        or_(
            XHSAccountNote.primary_content_tag.is_(None),
            XHSAccountNote.primary_content_tag == "",
            XHSAccountNote.secondary_content_tag.is_(None),
            XHSAccountNote.secondary_content_tag == "",
        ),
    ]
    if target_env_ids:
        conditions.append(XHSAccountNote.environment_id.in_(target_env_ids))
    ai_origin_value = (ai_origin_type or "").strip()
    if ai_origin_value and ai_origin_value != "all":
        if ai_origin_value == "__unset__":
            conditions.append(or_(XHSAccountNote.ai_origin_type == "", XHSAccountNote.ai_origin_type.is_(None)))
        else:
            conditions.append(XHSAccountNote.ai_origin_type == ai_origin_value)
    status_value = (status or "").strip()
    if status_value and status_value != "all":
        conditions.append(XHSAccountNote.status == status_value)

    stmt = (
        select(XHSAccountNote)
        .where(and_(*conditions))
        .order_by(XHSAccountNote.environment_id.asc(), XHSAccountNote.sort_index.asc(), XHSAccountNote.id.desc())
    )
    notes = list((await db.execute(stmt)).scalars().all())
    if not notes:
        return {
            "matched_count": 0,
            "tagged_count": 0,
            "failed_count": 0,
            "concurrency": concurrency,
        }

    semaphore = asyncio.Semaphore(concurrency)
    failed_items: list[dict[str, Any]] = []
    tagged_results: list[tuple[XHSAccountNote, str, str]] = []

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0), trust_env=False) as client:
        async def run_one(note: XHSAccountNote) -> None:
            async with semaphore:
                try:
                    primary, secondary = await _tag_xhs_account_note_with_model(client, note)
                    tagged_results.append((note, primary, secondary))
                except Exception as exc:
                    failed_items.append({
                        "id": int(note.id),
                        "title": note.title or note.feed_id,
                        "error": str(exc)[:240],
                    })

        await asyncio.gather(*(run_one(note) for note in notes))

    for note, primary, secondary in tagged_results:
        note.primary_content_tag = primary
        note.secondary_content_tag = secondary
    if tagged_results:
        await db.commit()

    return {
        "matched_count": len(notes),
        "tagged_count": len(tagged_results),
        "failed_count": len(failed_items),
        "concurrency": concurrency,
        "failed_items": failed_items[:20],
    }


class XHSScheduleService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _ensure_rows(self) -> dict[str, XHSScheduleSetting]:
        result = await self.db.execute(
            select(XHSScheduleSetting).where(XHSScheduleSetting.task_key.in_(ALL_SCHEDULE_TASK_KEYS))
        )
        rows = {row.task_key: row for row in result.scalars().all()}
        changed = False
        for task_key in ALL_SCHEDULE_TASK_KEYS:
            if task_key in rows:
                continue
            definition = _default_task_definition(task_key)
            row = XHSScheduleSetting(
                task_key=task_key,
                enabled=bool(definition["enabled"]),
                run_time=str(definition["run_time"]),
                config=_normalize_task_config(task_key, definition.get("config")),
            )
            self.db.add(row)
            rows[task_key] = row
            changed = True
        if changed:
            await self.db.commit()
            for row in rows.values():
                await self.db.refresh(row)
        return rows

    def serialize_row(self, row: XHSScheduleSetting) -> dict[str, Any]:
        definition = _default_task_definition(row.task_key)
        config = _normalize_task_config(row.task_key, row.config if isinstance(row.config, dict) else {})
        return {
            "task_key": row.task_key,
            "label": definition["label"],
            "description": definition["description"],
            "enabled": bool(row.enabled),
            "run_time": _normalize_run_time(row.run_time),
            "config": config,
            "is_running": row.task_key in _RUNNING_TASK_KEYS,
            "next_run_at": _next_run_cst(_normalize_run_time(row.run_time), row.last_run_at).isoformat(),
            "last_run_at": utc_naive_to_aware_iso(row.last_run_at),
            "last_status": row.last_status,
            "last_message": row.last_message,
            "updated_at": utc_naive_to_aware_iso(row.updated_at),
        }

    @staticmethod
    def serialize_run_log(row: XHSScheduleRunLog) -> dict[str, Any]:
        return {
            "id": int(row.id),
            "task_key": row.task_key,
            "source": row.source,
            "status": row.status,
            "message": row.message,
            "started_at": utc_naive_to_aware_iso(row.started_at),
            "finished_at": utc_naive_to_aware_iso(row.finished_at),
            "updated_at": utc_naive_to_aware_iso(row.updated_at),
        }

    async def list_settings(self) -> list[dict[str, Any]]:
        rows = await self._ensure_rows()
        return [self.serialize_row(rows[task_key]) for task_key in ALL_SCHEDULE_TASK_KEYS]

    async def list_run_logs(self, *, task_key: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        stmt = select(XHSScheduleRunLog)
        if task_key:
            stmt = stmt.where(XHSScheduleRunLog.task_key == task_key)
        stmt = stmt.order_by(XHSScheduleRunLog.started_at.desc(), XHSScheduleRunLog.id.desc()).limit(
            max(1, min(int(limit), 200))
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [self.serialize_run_log(row) for row in rows]

    async def get_row(self, task_key: str) -> XHSScheduleSetting:
        if task_key not in ALL_SCHEDULE_TASK_KEYS:
            raise ValueError("不支持的定时任务")
        rows = await self._ensure_rows()
        return rows[task_key]

    async def update_setting(
        self,
        task_key: str,
        *,
        enabled: bool,
        run_time: str,
        config: dict[str, Any] | None,
    ) -> dict[str, Any]:
        row = await self.get_row(task_key)
        was_enabled = bool(row.enabled)
        previous_run_time = _normalize_run_time(row.run_time)
        normalized_run_time = _normalize_run_time(run_time)
        row.enabled = bool(enabled)
        row.run_time = normalized_run_time
        row.config = _normalize_task_config(task_key, config)
        schedule_changed = not was_enabled or previous_run_time != normalized_run_time
        if row.enabled and schedule_changed:
            scheduled_today = _scheduled_time_today(normalized_run_time)
            if cst_now_naive() >= scheduled_today:
                # Enabling a time that already passed should schedule tomorrow,
                # not unexpectedly catch up immediately.
                row.last_run_at = utc_now_naive()
        await self.db.commit()
        await self.db.refresh(row)
        return self.serialize_row(row)


async def _execute_account_data_sync(session: AsyncSession, config: dict[str, Any]) -> str:
    service = XHSService(session)
    normalized = _normalize_task_config(ACCOUNT_DATA_SYNC_TASK, config)
    target_env_ids = await _resolve_target_environment_ids(session, normalized)
    scoped_selection = str(normalized["target_scope"]) != "all"
    scope_label = _scope_label(normalized["target_scope"], target_env_ids, normalized)

    summary_parts: list[str] = []
    if normalized["engagement_sync_enabled"]:
        if target_env_ids:
            admin_user = await _load_system_admin_user(session)
            eligible_env_ids, skipped_configs, account_names = await _partition_creator_sync_targets(
                session,
                target_env_ids,
            )
            if skipped_configs:
                logger.info(
                    "创作者中心定时同步预检跳过配置不全账号: %s",
                    json.dumps(skipped_configs, ensure_ascii=False),
                )
            first_result = await _run_creator_sync_pass(
                service,
                admin_user=admin_user,
                target_environment_ids=eligible_env_ids,
                concurrency=int(normalized["yundeng_sync_concurrency"]),
                account_names=account_names,
            )
            first_failed_ids = _failed_creator_environment_ids(first_result)
            retry_result = await _run_creator_sync_pass(
                service,
                admin_user=admin_user,
                target_environment_ids=first_failed_ids,
                concurrency=int(normalized["yundeng_sync_concurrency"]),
                account_names=account_names,
            )
            remaining_failed_ids = _failed_creator_environment_ids(retry_result)
            first_synced = int(first_result.get("synced_accounts") or 0)
            retry_synced = int(retry_result.get("synced_accounts") or 0)
            created_notes = int(first_result.get("created_notes") or 0) + int(retry_result.get("created_notes") or 0)
            updated_notes = int(first_result.get("updated_notes") or 0) + int(retry_result.get("updated_notes") or 0)
            final_failure_summary = (
                f"最终异常 {len(remaining_failed_ids)} 个"
                if remaining_failed_ids
                else "最终失败 0 个"
            )
            summary_parts.append(
                f"创作者中心首轮成功 {first_synced}/{len(eligible_env_ids)} 个账号，"
                f"失败 {len(first_failed_ids)} 个；"
                f"失败重试成功 {retry_synced}/{len(first_failed_ids)} 个，"
                f"{final_failure_summary}；"
                f"配置不全跳过 {len(skipped_configs)} 个；"
                f"新增 {created_notes} 条，更新 {updated_notes} 条"
            )
        else:
            summary_parts.append("创作者中心首轮成功 0/0 个账号，失败重试 0 个")

    # Creator-center export owns the post inventory and metrics. Homepage sync
    # follows it only to resolve feed IDs and enrich content-related fields.
    if normalized["post_sync_enabled"]:
        if not normalized["post_sync_runner_ids"]:
            raise ValueError("主页帖子同步已启用，但还没有选择同步环境")
        if not target_env_ids:
            summary_parts.append("主页帖子同步 0 个账号")
        else:
            runner_assignments = _build_even_runner_assignments(normalized["post_sync_runner_ids"], target_env_ids)
            result = await service.sync_account_notes(
                user=None,
                scrape_environment_id=normalized["post_sync_runner_ids"][0] if len(normalized["post_sync_runner_ids"]) == 1 else None,
                scrape_environment_ids=normalized["post_sync_runner_ids"],
                sync_account_limit=len(target_env_ids),
                runner_account_assignments=runner_assignments,
                concurrency=int(normalized["yundeng_sync_concurrency"]),
                limit_per_env=int(normalized["post_sync_limit_per_env"]),
            )
            summary_parts.append(
                f"主页帖子 {scope_label} {result.get('synced_accounts', 0)} 个账号，"
                f"补齐 {result.get('updated_notes', 0)} 条，"
                f"待创作者中心建档 {result.get('deferred_homepage_notes', 0)} 条"
            )

    if normalized["detail_sync_enabled"]:
        if not normalized["detail_runner_ids"]:
            raise ValueError("未同步策略已启用，但还没有选择同步环境")
        detail_runner_ids = normalized["detail_runner_ids"]
        detail_mode = str(normalized["detail_sync_mode"])
        detail_limit = int(normalized["detail_total_limit"])
        detail_results = []
        detail_env_groups = target_env_ids if scoped_selection else (target_env_ids or [])
        if scoped_selection and not detail_env_groups:
            summary_parts.append(f"未同步策略 {detail_mode} 0 条")
            detail_env_groups = None
        if detail_env_groups is None:
            pass
        elif not detail_env_groups:
            detail_results.append(
                await service.sync_existing_account_note_stats(
                    environment_id=None,
                    scrape_environment_id=detail_runner_ids[0] if len(detail_runner_ids) == 1 else None,
                    scrape_environment_ids=detail_runner_ids,
                    sync_mode=detail_mode,
                    sync_limit=detail_limit,
                    sync_limit_per_runner=int(normalized["detail_limit_per_runner"]),
                    pause_seconds_min=float(normalized["detail_pause_min_seconds"]),
                    pause_seconds_max=float(normalized["detail_pause_max_seconds"]),
                    max_post_age_days=int(normalized["detail_max_post_age_days"]),
                    concurrency=int(normalized["yundeng_sync_concurrency"]),
                )
            )
        else:
            env_limits = _distribute_limit(detail_limit, detail_env_groups)
            for env_id, env_limit in env_limits:
                if env_limit <= 0:
                    continue
                detail_results.append(
                    await service.sync_existing_account_note_stats(
                        environment_id=env_id,
                        scrape_environment_id=detail_runner_ids[0] if len(detail_runner_ids) == 1 else None,
                        scrape_environment_ids=detail_runner_ids,
                        sync_mode=detail_mode,
                        sync_limit=env_limit,
                        sync_limit_per_runner=int(normalized["detail_limit_per_runner"]),
                        pause_seconds_min=float(normalized["detail_pause_min_seconds"]),
                        pause_seconds_max=float(normalized["detail_pause_max_seconds"]),
                        max_post_age_days=int(normalized["detail_max_post_age_days"]),
                        concurrency=int(normalized["yundeng_sync_concurrency"]),
                    )
                )
        if detail_results:
            detail_synced = sum(int(item.get("synced_notes") or 0) for item in detail_results)
            detail_failed = sum(int(item.get("failed_notes") or 0) for item in detail_results)
            summary_parts.append(f"未同步策略 {detail_mode} 成功 {detail_synced} 条，失败 {detail_failed} 条")

    if normalized["content_tag_enabled"]:
        if scoped_selection and not target_env_ids:
            summary_parts.append("内容打标 0/0 条")
        else:
            tag_result = await _run_content_tag_batch(
                session,
                target_env_ids=target_env_ids,
                ai_origin_type=str(normalized["content_tag_ai_origin_type"]),
                status=str(normalized["content_tag_status"]),
                concurrency=int(normalized["content_tag_concurrency"]),
            )
            summary_parts.append(f"内容打标 {tag_result.get('tagged_count', 0)}/{tag_result.get('matched_count', 0)} 条")

    if not summary_parts:
        return "未启用任何账户同步步骤"
    return "；".join(summary_parts)


async def _execute_ad_data_refresh(
    session: AsyncSession,
    config: dict[str, Any],
    *,
    history_run_id: int | None = None,
) -> str:
    service = XHSService(session)
    start_d, end_d, days = _resolve_ad_refresh_date_range(config)
    report_types = [str(item).strip() for item in (config.get("report_types") or AD_REPORT_TYPES) if str(item).strip() in AD_REPORT_TYPES]
    report_types = report_types or list(AD_REPORT_TYPES)

    total_accounts = 0
    total_attempted_accounts = 0
    total_rows = 0
    total_changed_rows = 0
    errors: list[str] = []
    skipped_token_accounts: dict[str, str] = {}
    refreshed_report_types: list[str] = []
    await mark_report_refresh_running_safely(history_run_id)
    try:
        token_refresh = await service.refresh_report_token_statuses()
    except Exception as exc:
        await finish_report_refresh_run_safely(
            history_run_id,
            status="failed",
            message="广告账户 Token 统一复核失败",
            error=str(exc),
        )
        raise
    for item in token_refresh.get("failed_accounts") or []:
        errors.append(
            f"{item.get('account_id')} {item.get('account_name')}: Token 不可用: {item.get('error')}"
        )
    for item in token_refresh.get("transient_errors") or []:
        errors.append(
            f"{item.get('account_id')} {item.get('account_name')}: Token 复核暂时失败，继续使用缓存: {item.get('error')}"
        )
    for report_type in report_types:
        try:
            result = await service.refresh_jg_report_cache(
                report_type=report_type,
                start_date=start_d.isoformat(),
                end_date=end_d.isoformat(),
                days=days,
                resilient=True,
                preserve_existing_on_empty=True,
                successful_tokens_only=True,
                use_cached_tokens=True,
                defer_post_processing=True,
            )
        except Exception as exc:
            await record_report_refresh_result_safely(
                history_run_id,
                report_type=report_type,
                status="failed",
                error=str(exc),
            )
            await finish_report_refresh_run_safely(
                history_run_id,
                status="failed",
                message=f"{report_type} 报表刷新失败",
                error=str(exc),
            )
            raise
        await record_report_refresh_result_safely(
            history_run_id,
            report_type=report_type,
            status="failed" if result.get("errors") else "succeeded",
            result=result,
        )
        total_accounts += int(result.get("updated_accounts") or 0)
        total_attempted_accounts += int(result.get("attempted_accounts") or 0)
        total_rows += int(result.get("updated_rows") or 0)
        total_changed_rows += int(result.get("changed_rows") or 0)
        refreshed_report_types.append(report_type)
        for skipped in result.get("skipped_token_accounts") or []:
            skipped_account_id = str(skipped.get("account_id") or "").strip()
            if skipped_account_id:
                skipped_token_accounts[skipped_account_id] = str(skipped.get("account_name") or "")
        errors.extend(str(item) for item in (result.get("errors") or []))

    if refreshed_report_types:
        finalized = await service.finalize_jg_report_refresh(
            report_types=refreshed_report_types,
            start_date=start_d,
            end_date=end_d,
            account_id=None,
        )
        errors.extend(str(item) for item in (finalized.get("errors") or []))

    consistency = await _validate_ad_refresh_consistency(
        session,
        start_d=start_d,
        end_d=end_d,
        report_types=report_types,
    )
    errors.extend(consistency["errors"])

    token_progress = (
        f"Token 有效 {len(token_refresh.get('valid_accounts') or [])}/"
        f"{int(token_refresh.get('configured_accounts') or 0)} 个"
    )
    progress = f"{token_progress}，成功 {total_accounts}/{total_attempted_accounts} 个账户报表组合"
    skipped = f"，跳过 Token 不可用账户 {len(skipped_token_accounts)} 个" if skipped_token_accounts else ""
    if errors:
        message = f"刷新完成，日期 {start_d.isoformat()} 至 {end_d.isoformat()}，{progress}{skipped}，读取 {total_rows} 行，实际变更 {total_changed_rows} 行，异常 {len(errors)} 条"
    else:
        message = f"刷新完成，日期 {start_d.isoformat()} 至 {end_d.isoformat()}，{progress}{skipped}，读取 {total_rows} 行，实际变更 {total_changed_rows} 行，数据一致性验收通过"
    await finish_report_refresh_run_safely(
        history_run_id,
        status="failed" if errors else "succeeded",
        message=message,
        error=" | ".join(errors[:20]) if errors else None,
    )
    return message


async def _validate_ad_refresh_consistency(
    session: AsyncSession,
    *,
    start_d: date,
    end_d: date,
    report_types: list[str] | tuple[str, ...] = AD_REPORT_TYPES,
) -> dict[str, Any]:
    normalized_types = tuple(
        report_type
        for report_type in dict.fromkeys(str(item).strip() for item in report_types)
        if report_type in AD_REPORT_TYPES
    )
    if not normalized_types:
        return {"errors": []}
    raw_rows = list(
        (
            await session.execute(
                select(
                    XHSReportDaily.report_type,
                    XHSReportDaily.account_id,
                    XHSReportDaily.report_date,
                )
                .where(
                    XHSReportDaily.report_type.in_(normalized_types),
                    XHSReportDaily.report_date >= start_d,
                    XHSReportDaily.report_date <= end_d,
                )
                .distinct()
            )
        ).all()
    )
    raw_dates: dict[str, set[tuple[str, date]]] = {report_type: set() for report_type in normalized_types}
    for report_type, account_id, report_date in raw_rows:
        raw_dates.setdefault(str(report_type), set()).add((str(account_id), report_date))

    account_aggregate_rows = list(
        (
            await session.execute(
                select(
                    XHSAdStatsDailyAccount.report_type,
                    XHSAdStatsDailyAccount.account_id,
                    XHSAdStatsDailyAccount.stat_date,
                )
                .where(
                    XHSAdStatsDailyAccount.report_type.in_(normalized_types),
                    XHSAdStatsDailyAccount.stat_date >= start_d,
                    XHSAdStatsDailyAccount.stat_date <= end_d,
                )
                .distinct()
            )
        ).all()
    )
    note_aggregate_rows = list(
        (
            await session.execute(
                select(
                    XHSAdStatsDailyNote.report_type,
                    XHSAdStatsDailyNote.account_id,
                    XHSAdStatsDailyNote.stat_date,
                )
                .where(
                    XHSAdStatsDailyNote.report_type.in_(normalized_types),
                    XHSAdStatsDailyNote.stat_date >= start_d,
                    XHSAdStatsDailyNote.stat_date <= end_d,
                )
                .distinct()
            )
        ).all()
    )
    aggregate_dates: dict[str, set[tuple[str, date]]] = {report_type: set() for report_type in normalized_types}
    for report_type, account_id, stat_date in account_aggregate_rows + note_aggregate_rows:
        aggregate_dates.setdefault(str(report_type), set()).add((str(account_id), stat_date))

    errors: list[str] = []
    pair_checks = (
        ("简单投", "simple", "simple_note"),
        ("标准投", "standard", "standard_note"),
    )
    for label, account_report, note_report in pair_checks:
        if account_report not in normalized_types or note_report not in normalized_types:
            continue
        account_only = raw_dates.get(account_report, set()) - raw_dates.get(note_report, set())
        note_only = raw_dates.get(note_report, set()) - raw_dates.get(account_report, set())
        if account_only or note_only:
            errors.append(
                f"{label}账户/笔记报表日期不一致: 账户侧缺口 {len(note_only)}，笔记侧缺口 {len(account_only)}"
            )

    for report_type in normalized_types:
        raw_only = raw_dates.get(report_type, set()) - aggregate_dates.get(report_type, set())
        aggregate_only = aggregate_dates.get(report_type, set()) - raw_dates.get(report_type, set())
        if raw_only or aggregate_only:
            errors.append(
                f"{report_type}原始/聚合日期不一致: 未聚合 {len(raw_only)}，残留聚合 {len(aggregate_only)}"
            )
    return {"errors": errors}


async def _execute_ad_report_publish(session: AsyncSession, config: dict[str, Any]) -> str:
    normalized = _normalize_task_config(AD_REPORT_PUBLISH_TASK, config)
    webhook_url = str(normalized.get("webhook_url") or "").strip()
    account_ids = [str(item).strip() for item in (normalized.get("account_ids") or []) if str(item).strip()]
    report_types = [str(item).strip() for item in (normalized.get("report_types") or []) if str(item).strip() in AD_SUMMARY_REPORT_TYPES]
    report_types = report_types or list(AD_SUMMARY_REPORT_TYPES)
    if not webhook_url:
        raise ValueError("请先配置飞书 webhook")
    if not account_ids:
        raise ValueError("请先选择要汇报的广告账户")

    refresh_message = ""
    if normalized.get("refresh_before_send", True):
        refresh_message = await _execute_ad_data_refresh(
            session,
            {
                "days": 1,
                "report_types": report_types,
            },
        )

    today = cst_now_naive().date()
    async def fetch_today_rows() -> list[tuple[str, Any]]:
        return list(
            (
                await session.execute(
                    select(
                        XHSReportDaily.account_id,
                        XHSReportDaily.payload,
                    ).where(
                        and_(
                            XHSReportDaily.report_date == today,
                            XHSReportDaily.report_type.in_(report_types),
                            XHSReportDaily.account_id.in_(account_ids),
                        )
                    )
                )
            )
            .all()
        )

    rows = await fetch_today_rows()

    if not rows and not normalized.get("refresh_before_send", True):
        fallback_refresh_message = await _execute_ad_data_refresh(
            session,
            {
                "days": 1,
                "report_types": report_types,
            },
        )
        refresh_message = f"当天无匹配数据，已自动补刷；{fallback_refresh_message}"
        rows = await fetch_today_rows()

    present_account_ids = sorted({str(account_id).strip() for account_id, _payload in rows if str(account_id).strip()})
    missing_account_ids = [account_id for account_id in account_ids if account_id not in present_account_ids]

    summary = {
        "fee": 0.0,
        "impression": 0,
        "click": 0,
        "conversion": 0,
        "conversion_cost": 0.0,
    }
    for _account_id, payload in rows:
        row_payload = payload if isinstance(payload, dict) else {}
        if isinstance(payload, str):
            try:
                row_payload = json.loads(payload)
            except Exception:
                row_payload = {}
        fee = _report_metric_value(row_payload, "fee", "cost", "spend")
        impression = _report_metric_value(row_payload, "impression", "show", "exposure")
        click = _report_metric_value(row_payload, "click")
        conversion = _report_conversion_value(row_payload)
        summary["fee"] += fee
        summary["impression"] += int(round(impression))
        summary["click"] += int(round(click))
        summary["conversion"] += int(round(conversion))

    summary["fee"] = round(float(summary["fee"]), 2)
    summary["conversion_cost"] = round(
        float(summary["fee"]) / float(summary["conversion"]) if summary["conversion"] else 0.0,
        2,
    )

    text = _format_publish_message(str(normalized.get("message_title") or "今日小红书零跑汇总数据"), summary)
    await _send_feishu_robot_message(webhook_url, text)

    parts = [f"飞书推送成功，日期 {today.isoformat()}，账户 {len(present_account_ids)}/{len(account_ids)} 个"]
    if missing_account_ids:
        parts.append(f"{len(missing_account_ids)} 个账户当天无日报数据，已按 0 计入汇总")
    if refresh_message:
        parts.append(refresh_message)
    return "；".join(parts)


async def _run_task(task_key: str, source: str, session_factory: async_sessionmaker) -> None:
    _RUNNING_TASK_KEYS.add(task_key)
    run_log_id: int | None = None
    try:
        async with session_factory() as session:
            schedule_service = XHSScheduleService(session)
            row = await schedule_service.get_row(task_key)
            started_at = utc_now_naive()
            run_log = XHSScheduleRunLog(
                task_key=task_key,
                source=source,
                status="running",
                message="任务执行中",
                started_at=started_at,
            )
            session.add(run_log)
            row.last_status = "running"
            row.last_message = "任务执行中"
            if source == "schedule":
                # Claim today's schedule durably before doing any long-running work.
                # A container restart then cannot start the same task a second time.
                row.last_run_at = started_at
            await session.commit()
            await session.refresh(run_log)
            run_log_id = int(run_log.id)

        async with session_factory() as session:
            schedule_service = XHSScheduleService(session)
            row = await schedule_service.get_row(task_key)
            config = _normalize_task_config(task_key, row.config if isinstance(row.config, dict) else {})
            if task_key == ACCOUNT_DATA_SYNC_TASK:
                message = await _execute_account_data_sync(session, config)
            elif task_key == AD_DATA_REFRESH_TASK:
                start_d, end_d, days = _resolve_ad_refresh_date_range(config)
                history_run_id = await create_report_refresh_run_safely(
                    job_id=f"schedule:{run_log_id}:ad-data-refresh",
                    source=source,
                    schedule_run_id=run_log_id,
                    request_config={
                        "report_types": config.get("report_types") or AD_REPORT_TYPES,
                        "start_date": start_d.isoformat(),
                        "end_date": end_d.isoformat(),
                        "days": days,
                    },
                )
                message = await _execute_ad_data_refresh(
                    session,
                    config,
                    history_run_id=history_run_id,
                )
            elif task_key == AD_REPORT_PUBLISH_TASK:
                message = await _execute_ad_report_publish(session, config)
            else:
                raise ValueError(f"未知任务类型: {task_key}")
            finished_at = utc_now_naive()
            final_status = "partial" if "异常 " in message else "succeeded"
            row.last_run_at = finished_at
            row.last_status = final_status
            outcome_label = "部分成功" if final_status == "partial" else "成功"
            row.last_message = f"{source}执行{outcome_label}：{message}"
            if run_log_id:
                run_log = await session.get(XHSScheduleRunLog, run_log_id)
                if run_log:
                    run_log.status = final_status
                    run_log.message = row.last_message
                    run_log.finished_at = finished_at
            await session.commit()
            logger.info("XHS scheduled task finished: task_key=%s source=%s message=%s", task_key, source, message)
    except asyncio.CancelledError:
        try:
            await asyncio.shield(
                _mark_interrupted_task(
                    task_key,
                    source,
                    run_log_id,
                    session_factory,
                )
            )
        except Exception:
            logger.exception(
                "XHS scheduled task cancellation cleanup failed: task_key=%s source=%s",
                task_key,
                source,
            )
        raise
    except Exception as exc:
        logger.exception("XHS scheduled task failed: task_key=%s source=%s", task_key, source)
        async with session_factory() as session:
            schedule_service = XHSScheduleService(session)
            row = await schedule_service.get_row(task_key)
            finished_at = utc_now_naive()
            row.last_run_at = finished_at
            row.last_status = "failed"
            row.last_message = f"{source}执行失败：{str(exc)[:1000]}"
            if run_log_id:
                run_log = await session.get(XHSScheduleRunLog, run_log_id)
                if run_log:
                    run_log.status = "failed"
                    run_log.message = row.last_message
                    run_log.finished_at = finished_at
            await session.commit()
    finally:
        _RUNNING_TASK_KEYS.discard(task_key)


async def _mark_interrupted_task(
    task_key: str,
    source: str,
    run_log_id: int | None,
    session_factory: async_sessionmaker,
) -> None:
    finished_at = utc_now_naive()
    refresh_run_ids: list[int] = []
    async with session_factory() as session:
        row = await XHSScheduleService(session).get_row(task_key)
        if row.last_status == "running":
            row.last_status = "failed"
            row.last_message = f"{source}执行中断：服务停止或调度权切换"
            row.last_run_at = None if source == "schedule" else finished_at
        if run_log_id:
            run_log = await session.get(XHSScheduleRunLog, run_log_id)
            if run_log and run_log.status == "running":
                run_log.status = "failed"
                run_log.message = f"{source}执行中断：服务停止或调度权切换"
                run_log.finished_at = finished_at
            refresh_rows = list(
                (
                    await session.execute(
                        select(XHSReportRefreshRun).where(
                            XHSReportRefreshRun.schedule_run_id == run_log_id,
                            XHSReportRefreshRun.status.in_(("queued", "running")),
                        )
                    )
                ).scalars().all()
            )
            for refresh_row in refresh_rows:
                refresh_row.status = "failed"
                refresh_row.message = "服务停止或调度权切换导致报表刷新中断"
                refresh_row.error = "报表刷新被中断"
                refresh_row.finished_at = finished_at
                refresh_run_ids.append(int(refresh_row.id))
        await session.commit()

    for refresh_run_id in refresh_run_ids:
        await finish_report_refresh_run_safely(
            refresh_run_id,
            status="failed",
            message="服务停止或调度权切换导致报表刷新中断",
            error="报表刷新被中断",
        )


async def trigger_xhs_scheduled_task(
    task_key: str,
    *,
    source: str = "manual",
    session_factory: async_sessionmaker | None = None,
) -> bool:
    if task_key not in ALL_SCHEDULE_TASK_KEYS:
        raise ValueError("不支持的定时任务")
    if task_key in _RUNNING_TASK_KEYS:
        return False
    factory = session_factory or async_session
    asyncio.create_task(_run_task(task_key, source, factory))
    return True


def has_running_xhs_scheduled_task() -> bool:
    return bool(_RUNNING_TASK_KEYS)


async def run_xhs_scheduled_task(
    task_key: str,
    *,
    source: str = "schedule",
    session_factory: async_sessionmaker | None = None,
) -> bool:
    """Run one configured task inline so scheduler cancellation reaches the work."""
    if task_key not in ALL_SCHEDULE_TASK_KEYS:
        raise ValueError("不支持的定时任务")
    if task_key in _RUNNING_TASK_KEYS:
        return False
    await _run_task(task_key, source, session_factory or async_session)
    return True


async def due_xhs_schedule_task_keys(db: AsyncSession) -> list[str]:
    now = utc_now_naive()
    stale_cutoff = now - timedelta(hours=STALE_SCHEDULE_RUN_HOURS)
    restart_reconcile_ready = now >= _PROCESS_STARTED_AT_UTC + timedelta(
        seconds=RESTART_RECONCILE_GRACE_SECONDS
    )
    running_rows = list(
        (
            await db.execute(
                select(XHSScheduleRunLog).where(
                    XHSScheduleRunLog.status == "running"
                )
            )
        ).scalars().all()
    )
    stale_rows: list[XHSScheduleRunLog] = []
    restart_interrupted_ids: set[int] = set()
    for running_row in running_rows:
        exceeded_stale_limit = running_row.started_at < stale_cutoff
        belongs_to_previous_process = (
            restart_reconcile_ready
            and running_row.source == "schedule"
            and running_row.started_at < _PROCESS_STARTED_AT_UTC
            and running_row.task_key not in _RUNNING_TASK_KEYS
        )
        if exceeded_stale_limit or belongs_to_previous_process:
            stale_rows.append(running_row)
        if belongs_to_previous_process:
            restart_interrupted_ids.add(int(running_row.id))

    interrupted_refresh_run_ids: list[int] = []
    if stale_rows:
        finished_at = now
        task_keys = {row.task_key for row in stale_rows}
        for stale_row in stale_rows:
            stale_row.status = "failed"
            stale_row.finished_at = finished_at
            if int(stale_row.id) in restart_interrupted_ids:
                stale_row.message = "服务重启导致任务中断，已自动重新排队"
            else:
                stale_row.message = (
                    f"任务运行记录超过 {STALE_SCHEDULE_RUN_HOURS} 小时未收尾，已自动标记失败"
                )
        settings_rows = list(
            (
                await db.execute(
                    select(XHSScheduleSetting).where(
                        XHSScheduleSetting.task_key.in_(task_keys),
                        XHSScheduleSetting.last_status == "running",
                    )
                )
            ).scalars().all()
        )
        for settings_row in settings_rows:
            settings_row.last_status = "failed"
            if any(
                row.task_key == settings_row.task_key
                and int(row.id) in restart_interrupted_ids
                for row in stale_rows
            ):
                # Clear the durable daily claim so this interrupted run remains due.
                settings_row.last_run_at = None
                settings_row.last_message = "服务重启导致任务中断，等待自动补跑"
            else:
                settings_row.last_run_at = finished_at
                settings_row.last_message = "上一次任务未正常收尾，已自动标记失败"

        if restart_interrupted_ids:
            refresh_rows = list(
                (
                    await db.execute(
                        select(XHSReportRefreshRun).where(
                            XHSReportRefreshRun.schedule_run_id.in_(restart_interrupted_ids),
                            XHSReportRefreshRun.status.in_(("queued", "running")),
                        )
                    )
                ).scalars().all()
            )
            for refresh_row in refresh_rows:
                refresh_row.status = "failed"
                refresh_row.message = "服务重启导致报表刷新中断，已自动重新排队"
                refresh_row.error = "服务重启导致报表刷新中断"
                refresh_row.finished_at = finished_at
                interrupted_refresh_run_ids.append(int(refresh_row.id))
        await db.commit()

        for refresh_run_id in interrupted_refresh_run_ids:
            await finish_report_refresh_run_safely(
                refresh_run_id,
                status="failed",
                message="服务重启导致报表刷新中断，已自动重新排队",
                error="服务重启导致报表刷新中断",
            )

    service = XHSScheduleService(db)
    rows = await service._ensure_rows()
    due_keys = [
        task_key
        for task_key, row in rows.items()
        if _is_due(bool(row.enabled), _normalize_run_time(row.run_time), row.last_run_at)
    ]
    return sorted(
        due_keys,
        key=lambda task_key: _scheduled_time_today(
            _normalize_run_time(rows[task_key].run_time)
        ),
        reverse=True,
    )
