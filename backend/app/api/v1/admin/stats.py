"""Admin dashboard stats API"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, literal, union_all, and_, or_
from datetime import datetime, timedelta

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.core.deps import require_admin
from app.models.user import User
from app.models.project import Project
from app.models.material import Material
from app.models.ai_task import AITask
from app.models.dify_workflow import DifyWorkflowConfig
from app.models.dify_run_log import DifyRunLog
from app.models.dify_task import DifyTask
from app.models.user_xhs_env import UserXHSEnvironment
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_post import XHSPost
from app.models.xhs_environment import XHSEnvironment
from app.utils.timezone import (
    cst_naive_to_utc_naive,
    cst_now_naive,
    utc_naive_to_aware_iso,
    utc_naive_to_cst_naive,
)

router = APIRouter()

XHS_PUBLISH_SOURCE_AUTO = "auto_tool"
XHS_PUBLISH_SOURCE_SELF = "self_published"
XHS_PUBLISH_SOURCE_AUTO_LABEL = "自动工具发布"
XHS_PUBLISH_SOURCE_SELF_LABEL = "自主发布"


def _now_cst_naive() -> datetime:
    return cst_now_naive()


def _today_cst_bounds(now_cst: datetime | None = None) -> tuple[datetime, datetime]:
    now = now_cst or _now_cst_naive()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _utc_naive_to_cst_naive(value: datetime) -> datetime:
    return utc_naive_to_cst_naive(value)


def _cst_naive_to_utc_naive(value: datetime) -> datetime:
    return cst_naive_to_utc_naive(value)


async def _resolve_user_id(db: AsyncSession, username: str | None) -> int | None:
    if not username:
        return None
    normalized = username.strip()
    if not normalized:
        return None
    ures = await db.execute(select(User.id).where(User.username == normalized))
    return ures.scalar_one_or_none()


async def _resolve_user_environment_ids(db: AsyncSession, user_id: int | None) -> set[int]:
    if user_id is None:
        return set()
    rows = await db.execute(
        select(UserXHSEnvironment.environment_id).where(UserXHSEnvironment.user_id == user_id)
    )
    return {int(environment_id) for (environment_id,) in rows.all() if environment_id is not None}


async def _load_environment_usernames(db: AsyncSession, environment_ids: set[int]) -> dict[int, str]:
    if not environment_ids:
        return {}
    rows = await db.execute(
        select(UserXHSEnvironment.environment_id, User.username)
        .join(User, User.id == UserXHSEnvironment.user_id)
        .where(UserXHSEnvironment.environment_id.in_(environment_ids))
        .order_by(UserXHSEnvironment.environment_id.asc(), User.username.asc())
    )
    grouped: dict[int, list[str]] = {}
    for environment_id, username in rows.all():
        if environment_id is None or not username:
            continue
        grouped.setdefault(int(environment_id), []).append(username)
    return {env_id: "、".join(names) for env_id, names in grouped.items()}


def _successful_xhs_feed_ids_stmt():
    return select(XHSPost.feed_id).where(
        XHSPost.status == "success",
        XHSPost.feed_id.is_not(None),
    )


def _self_managed_account_note_condition():
    return and_(
        XHSAccountNote.source_post_id.is_(None),
        or_(
            XHSAccountNote.feed_id.is_(None),
            func.trim(XHSAccountNote.feed_id) == "",
            ~XHSAccountNote.feed_id.in_(_successful_xhs_feed_ids_stmt()),
        ),
    )


@router.get("/overview")
async def get_overview_stats(
    username: str | None = Query(default=None, description="按用户名筛选"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Dashboard overview statistics"""
    _ = current_user
    filter_user_id = await _resolve_user_id(db, username)
    if username and filter_user_id is None:
        return ApiResponse(data={
            "user_count": 0,
            "project_count": 0,
            "material_count": 0,
            "ai_task_count": 0,
            "workflow_count": 0,
            "run_log_count": 0,
            "storage_bytes": 0,
            "storage_mb": 0,
            "ai_tasks_24h": 0,
            "ai_success_rate_24h": 0,
            "ai_tasks_today": 0,
            "ai_success_rate_today": 0,
        })

    if filter_user_id is not None:
        user_count = 1
    else:
        user_count_res = await db.execute(select(func.count()).select_from(User))
        user_count = user_count_res.scalar() or 0

    project_stmt = select(func.count()).select_from(Project).where(Project.deleted_at.is_(None))
    if filter_user_id is not None:
        project_stmt = project_stmt.where(Project.user_id == filter_user_id)
    project_count = (await db.execute(project_stmt)).scalar() or 0

    material_stmt = select(func.count()).select_from(Material).where(Material.deleted_at.is_(None))
    if filter_user_id is not None:
        material_stmt = material_stmt.where(Material.created_by == filter_user_id)
    material_count = (await db.execute(material_stmt)).scalar() or 0

    ai_stmt = select(func.count()).select_from(AITask)
    if filter_user_id is not None:
        ai_stmt = ai_stmt.where(AITask.user_id == filter_user_id)
    ai_task_count = (await db.execute(ai_stmt)).scalar() or 0

    if filter_user_id is not None:
        workflow_stmt = (
            select(func.count(func.distinct(DifyTask.workflow_id)))
            .select_from(DifyTask)
            .where(DifyTask.user_id == filter_user_id)
        )
    else:
        workflow_stmt = select(func.count()).select_from(DifyWorkflowConfig)
    workflow_count = (await db.execute(workflow_stmt)).scalar() or 0

    run_log_stmt = select(func.count()).select_from(DifyRunLog)
    if filter_user_id is not None:
        run_log_stmt = run_log_stmt.where(DifyRunLog.user_id == filter_user_id)
    run_log_count = (await db.execute(run_log_stmt)).scalar() or 0

    storage_stmt = select(func.sum(Material.file_size)).where(Material.deleted_at.is_(None))
    if filter_user_id is not None:
        storage_stmt = storage_stmt.where(Material.created_by == filter_user_id)
    storage_bytes = (await db.execute(storage_stmt)).scalar() or 0

    now_cst = _now_cst_naive()
    today_start_cst, _ = _today_cst_bounds(now_cst)
    today_start_utc = _cst_naive_to_utc_naive(today_start_cst)
    now_utc = _cst_naive_to_utc_naive(now_cst)

    today_total_stmt = select(func.count()).select_from(AITask).where(
        AITask.created_at >= today_start_utc,
        AITask.created_at < now_utc,
    )
    today_failed_stmt = select(func.count()).select_from(AITask).where(
        AITask.created_at >= today_start_utc,
        AITask.created_at < now_utc,
        AITask.status == "failed",
    )
    if filter_user_id is not None:
        today_total_stmt = today_total_stmt.where(AITask.user_id == filter_user_id)
        today_failed_stmt = today_failed_stmt.where(AITask.user_id == filter_user_id)

    total_today = (await db.execute(today_total_stmt)).scalar() or 0
    failed_today = (await db.execute(today_failed_stmt)).scalar() or 0
    success_rate_today = round((total_today - failed_today) / total_today * 100, 1) if total_today > 0 else 0

    return ApiResponse(data={
        "user_count": user_count,
        "project_count": project_count,
        "material_count": material_count,
        "ai_task_count": ai_task_count,
        "workflow_count": workflow_count,
        "run_log_count": run_log_count,
        "storage_bytes": storage_bytes,
        "storage_mb": round(storage_bytes / (1024 * 1024), 2),
        # 保持兼容：历史字段沿用，但值改为“今日累计（北京时间）”
        "ai_tasks_24h": total_today,
        "ai_success_rate_24h": success_rate_today,
        "ai_tasks_today": total_today,
        "ai_success_rate_today": success_rate_today,
    })


@router.get("/ai-trend")
async def get_ai_trend(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """AI task trend for recent days"""
    cutoff = datetime.now() - timedelta(days=days)

    # AI tasks grouped by date
    result = await db.execute(
        select(AITask.created_at, AITask.model_name, AITask.status, AITask.elapsed_seconds)
        .where(AITask.created_at >= cutoff)
    )
    ai_rows = result.all()

    daily = {}
    by_model = {}
    for row in ai_rows:
        date_str = str(row[0])[:10]
        model = row[1]
        status = row[2]
        elapsed = row[3] or 0

        if date_str not in daily:
            daily[date_str] = {"date": date_str, "total": 0, "by_model": {}}
        daily[date_str]["total"] += 1
        daily[date_str]["by_model"][model] = daily[date_str]["by_model"].get(model, 0) + 1

        if model not in by_model:
            by_model[model] = {"model": model, "total": 0, "success": 0, "failed": 0, "elapsed_sum": 0.0}
        by_model[model]["total"] += 1
        if status == "completed":
            by_model[model]["success"] += 1
        elif status == "failed":
            by_model[model]["failed"] += 1
        by_model[model]["elapsed_sum"] += elapsed

    models = []
    for m in by_model.values():
        models.append({
            "model": m["model"],
            "total": m["total"],
            "success": m["success"],
            "failed": m["failed"],
            "avg_seconds": round(m["elapsed_sum"] / m["total"], 1) if m["total"] else 0,
        })

    # Workflow stats
    wf_result = await db.execute(
        select(DifyRunLog.started_at, DifyRunLog.status)
        .where(DifyRunLog.started_at >= cutoff)
    )
    wf_daily = {}
    for row in wf_result.all():
        date_str = str(row[0])[:10]
        status = row[1]
        if date_str not in wf_daily:
            wf_daily[date_str] = {"date": date_str, "succeeded": 0, "failed": 0, "running": 0, "stopped": 0}
        if status in wf_daily[date_str]:
            wf_daily[date_str][status] += 1

    return ApiResponse(data={
        "ai_daily": list(daily.values()),
        "ai_models": [
            {**m, "avg_seconds": round(m["elapsed_sum"] / m["success"], 2) if m["success"] > 0 else 0}
            for m in by_model.values()
        ],
        "wf_daily": list(wf_daily.values())
    })


@router.get("/active-tasks")
async def get_active_tasks(
    username: str | None = Query(default=None, description="按用户名筛选"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """获取全站活跃任务"""
    _ = current_user
    filter_user_id = await _resolve_user_id(db, username)
    if username and filter_user_id is None:
        return ApiResponse(data=[])

    # 活跃 AI 生图任务
    ai_stmt = (
        select(AITask, User.username)
        .join(User, AITask.user_id == User.id)
        .where(AITask.status == "processing")
        .order_by(desc(AITask.created_at))
        .limit(10)
    )
    if filter_user_id is not None:
        ai_stmt = ai_stmt.where(AITask.user_id == filter_user_id)
    ai_result = await db.execute(ai_stmt)
    active_ai = [
        {
            "id": task.id,
            "type": "ai_image",
            "username": username,
            "model": task.model_name,
            "created_at": str(task.created_at),
        }
        for task, username in ai_result.all()
    ]

    # 活跃 Dify 工作流任务
    from app.models.dify_task import DifyTask
    wf_stmt = (
        select(DifyTask, User.username, DifyWorkflowConfig.app_name)
        .join(User, DifyTask.user_id == User.id)
        .join(DifyWorkflowConfig, DifyTask.workflow_id == DifyWorkflowConfig.id)
        .where(DifyTask.status.in_(["pending", "running"]))
        .order_by(desc(DifyTask.created_at))
        .limit(10)
    )
    if filter_user_id is not None:
        wf_stmt = wf_stmt.where(DifyTask.user_id == filter_user_id)
    wf_result = await db.execute(wf_stmt)
    active_wf = [
        {
            "id": task.id,
            "type": "workflow",
            "username": username,
            "model": app_name,
            "status": task.status,
            "created_at": str(task.created_at),
        }
        for task, username, app_name in wf_result.all()
    ]

    return ApiResponse(data=active_ai + active_wf)


@router.get("/usage-series")
async def get_usage_series(
    granularity: str = Query(default="day", pattern="^(hour|day|week)$"),
    username: str | None = Query(default=None, description="按用户名筛选"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """全用户任务调用趋势（生图+工作流），按小时/日/周聚合。"""
    _ = current_user
    now = _now_cst_naive()

    if granularity == "hour":
        bucket_count = 24
        bucket_delta = timedelta(hours=1)
        start, _ = _today_cst_bounds(now)
        key_fmt = "%Y-%m-%d %H"
        label_fmt = "%H:00"
    elif granularity == "day":
        bucket_count = 14
        bucket_delta = timedelta(days=1)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=bucket_count - 1)
        key_fmt = "%Y-%m-%d"
        label_fmt = "%m/%d"
    else:
        bucket_count = 8
        bucket_delta = timedelta(days=7)
        day = now.weekday()  # Mon=0
        this_week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=day)
        start = this_week_start - timedelta(days=7 * (bucket_count - 1))
        key_fmt = "%Y-%m-%d"
        label_fmt = "%m/%d"

    buckets = []
    bucket_index: dict[str, int] = {}
    end = start + bucket_delta * bucket_count
    cur = start
    for i in range(bucket_count):
        bucket_end = cur + bucket_delta
        if granularity == "week":
            label = f"{cur.strftime(label_fmt)}-{(bucket_end - timedelta(days=1)).strftime(label_fmt)}"
        else:
            label = cur.strftime(label_fmt)
        key = cur.strftime(key_fmt)
        buckets.append({
            "key": key,
            "label": label,
            "start": cur.isoformat(sep=" "),
            "end": bucket_end.isoformat(sep=" "),
        })
        bucket_index[key] = i
        cur = bucket_end

    def bucket_key(dt: datetime) -> str | None:
        if dt < start or dt >= end:
            return None
        if granularity == "hour":
            return dt.replace(minute=0, second=0, microsecond=0).strftime(key_fmt)
        if granularity == "day":
            return dt.replace(hour=0, minute=0, second=0, microsecond=0).strftime(key_fmt)
        wk = dt.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=dt.weekday())
        return wk.strftime(key_fmt)

    filter_user_id = await _resolve_user_id(db, username)
    if username and filter_user_id is None:
        return ApiResponse(data={
            "granularity": granularity,
            "buckets": buckets,
            "ai": {"names": [], "series": {}, "total_records": 0, "matched_records": 0, "raw_model_counts": {}},
            "workflow": {"names": [], "series": {}, "total_records": 0},
        })

    ai_start_utc = _cst_naive_to_utc_naive(start)
    ai_end_utc = _cst_naive_to_utc_naive(end)
    ai_stmt = select(AITask.model_name, AITask.created_at).where(
        AITask.created_at >= ai_start_utc,
        AITask.created_at < ai_end_utc,
    )
    if filter_user_id is not None:
        ai_stmt = ai_stmt.where(AITask.user_id == filter_user_id)
    ai_rows = await db.execute(ai_stmt)
    ai_name_totals: dict[str, int] = {}
    ai_temp: list[tuple[str, int]] = []
    raw_model_counts: dict[str, int] = {}
    for model_name, created_at in ai_rows.all():
        if not created_at:
            continue
        raw_key = (model_name or "").strip().lower() or "(empty)"
        raw_model_counts[raw_key] = raw_model_counts.get(raw_key, 0) + 1
        created_cst = _utc_naive_to_cst_naive(created_at)
        key = bucket_key(created_cst)
        if key is None:
            continue
        idx = bucket_index.get(key)
        if idx is None:
            continue
        display_name = (model_name or "").strip() or "unknown"
        ai_name_totals[display_name] = ai_name_totals.get(display_name, 0) + 1
        ai_temp.append((display_name, idx))

    ai_names = [name for name, _ in sorted(ai_name_totals.items(), key=lambda x: x[1], reverse=True)]
    ai_series = {name: [0] * bucket_count for name in ai_names}
    for name, idx in ai_temp:
        if name in ai_series:
            ai_series[name][idx] += 1
    ai_total = sum(ai_name_totals.values())

    wf_stmt = (
        select(DifyTask.created_at, DifyWorkflowConfig.app_name)
        .outerjoin(DifyWorkflowConfig, DifyTask.workflow_id == DifyWorkflowConfig.id)
        .where(DifyTask.created_at >= start, DifyTask.created_at < end)
    )
    if filter_user_id is not None:
        wf_stmt = wf_stmt.where(DifyTask.user_id == filter_user_id)
    wf_rows = await db.execute(wf_stmt)
    wf_name_totals: dict[str, int] = {}
    wf_temp: list[tuple[str, int]] = []
    for created_at, app_name in wf_rows.all():
        if not created_at:
            continue
        key = bucket_key(created_at)
        if key is None:
            continue
        idx = bucket_index.get(key)
        if idx is None:
            continue
        name = app_name or "未命名工作流"
        wf_name_totals[name] = wf_name_totals.get(name, 0) + 1
        wf_temp.append((name, idx))

    wf_names = [name for name, _ in sorted(wf_name_totals.items(), key=lambda x: x[1], reverse=True)[:6]]
    wf_series = {name: [0] * bucket_count for name in wf_names}
    for name, idx in wf_temp:
        if name in wf_series:
            wf_series[name][idx] += 1

    return ApiResponse(data={
        "granularity": granularity,
        "buckets": buckets,
        "ai": {
            "names": ai_names,
            "series": ai_series,
            "total_records": ai_total,
            "matched_records": ai_total,
            "raw_model_counts": dict(sorted(raw_model_counts.items(), key=lambda x: x[1], reverse=True)[:12]),
        },
        "workflow": {
            "names": wf_names,
            "series": wf_series,
            "total_records": sum(wf_name_totals.values()),
        },
    })


@router.get("/xhs-publish-series")
async def get_xhs_publish_series(
    granularity: str = Query(default="day", pattern="^(hour|day|week)$"),
    username: str | None = Query(default=None, description="按用户名筛选"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """小红书发帖趋势（仅统计已发布帖子）"""
    _ = current_user
    now = _now_cst_naive()

    if granularity == "hour":
        bucket_count = 24
        bucket_delta = timedelta(hours=1)
        start, _ = _today_cst_bounds(now)
        key_fmt = "%Y-%m-%d %H"
        label_fmt = "%H:00"
    elif granularity == "day":
        bucket_count = 14
        bucket_delta = timedelta(days=1)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=bucket_count - 1)
        key_fmt = "%Y-%m-%d"
        label_fmt = "%m/%d"
    else:
        bucket_count = 8
        bucket_delta = timedelta(days=7)
        day = now.weekday()  # Mon=0
        this_week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=day)
        start = this_week_start - timedelta(days=7 * (bucket_count - 1))
        key_fmt = "%Y-%m-%d"
        label_fmt = "%m/%d"

    buckets = []
    bucket_index: dict[str, int] = {}
    end = start + bucket_delta * bucket_count
    cur = start
    for i in range(bucket_count):
        bucket_end = cur + bucket_delta
        if granularity == "week":
            label = f"{cur.strftime(label_fmt)}-{(bucket_end - timedelta(days=1)).strftime(label_fmt)}"
        else:
            label = cur.strftime(label_fmt)
        key = cur.strftime(key_fmt)
        buckets.append({
            "key": key,
            "label": label,
            "start": cur.isoformat(sep=" "),
            "end": bucket_end.isoformat(sep=" "),
        })
        bucket_index[key] = i
        cur = bucket_end

    def bucket_key(dt: datetime) -> str | None:
        if dt < start or dt >= end:
            return None
        if granularity == "hour":
            return dt.replace(minute=0, second=0, microsecond=0).strftime(key_fmt)
        if granularity == "day":
            return dt.replace(hour=0, minute=0, second=0, microsecond=0).strftime(key_fmt)
        wk = dt.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=dt.weekday())
        return wk.strftime(key_fmt)

    filter_user_id = await _resolve_user_id(db, username)
    if username and filter_user_id is None:
        return ApiResponse(data={
            "granularity": granularity,
            "buckets": buckets,
            "series": {
                XHS_PUBLISH_SOURCE_AUTO_LABEL: [0] * bucket_count,
                XHS_PUBLISH_SOURCE_SELF_LABEL: [0] * bucket_count,
            },
            "total_records": 0,
        })

    user_environment_ids = await _resolve_user_environment_ids(db, filter_user_id)

    start_utc = _cst_naive_to_utc_naive(start)
    end_utc = _cst_naive_to_utc_naive(end)
    auto_stmt = select(XHSPost.published_at).where(
        XHSPost.status == "success",
        XHSPost.published_at.is_not(None),
        XHSPost.published_at >= start_utc,
        XHSPost.published_at < end_utc,
    )
    if filter_user_id is not None:
        auto_stmt = auto_stmt.where(XHSPost.user_id == filter_user_id)
    auto_rows = await db.execute(auto_stmt)

    manual_series = [0] * bucket_count
    auto_series = [0] * bucket_count
    auto_total_records = 0
    manual_total_records = 0

    for (published_at,) in auto_rows.all():
        if not published_at:
            continue
        published_cst = _utc_naive_to_cst_naive(published_at)
        key = bucket_key(published_cst)
        if key is None:
            continue
        idx = bucket_index.get(key)
        if idx is None:
            continue
        auto_series[idx] += 1
        auto_total_records += 1

    manual_stmt = select(XHSAccountNote.published_at).where(
        XHSAccountNote.published_at.is_not(None),
        XHSAccountNote.published_at >= start_utc,
        XHSAccountNote.published_at < end_utc,
        _self_managed_account_note_condition(),
    )
    if filter_user_id is not None:
        if not user_environment_ids:
            manual_rows = []
        else:
            manual_stmt = manual_stmt.where(XHSAccountNote.environment_id.in_(user_environment_ids))
            manual_rows = (await db.execute(manual_stmt)).all()
    else:
        manual_rows = (await db.execute(manual_stmt)).all()

    for (published_at,) in manual_rows:
        if not published_at:
            continue
        published_cst = _utc_naive_to_cst_naive(published_at)
        key = bucket_key(published_cst)
        if key is None:
            continue
        idx = bucket_index.get(key)
        if idx is None:
            continue
        manual_series[idx] += 1
        manual_total_records += 1

    return ApiResponse(data={
        "granularity": granularity,
        "buckets": buckets,
        "series": {
            XHS_PUBLISH_SOURCE_AUTO_LABEL: auto_series,
            XHS_PUBLISH_SOURCE_SELF_LABEL: manual_series,
        },
        "total_records": auto_total_records + manual_total_records,
    })


@router.get("/xhs-published-posts")
async def get_xhs_published_posts(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    username: str | None = Query(default=None, description="按用户名筛选"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """小红书已发布帖子只读列表（管理员查看）"""
    _ = current_user

    filter_user_id = await _resolve_user_id(db, username)
    if username and filter_user_id is None:
        return ApiResponse(data={"items": [], "total": 0, "page": page, "limit": limit})

    user_environment_ids = await _resolve_user_environment_ids(db, filter_user_id)

    count_stmt = select(func.count()).select_from(XHSPost).where(XHSPost.status == "success")
    if filter_user_id is not None:
        count_stmt = count_stmt.where(XHSPost.user_id == filter_user_id)
    auto_total = (await db.execute(count_stmt)).scalar() or 0

    manual_count_stmt = select(func.count()).select_from(XHSAccountNote).where(
        XHSAccountNote.published_at.is_not(None),
        _self_managed_account_note_condition(),
    )
    if filter_user_id is not None:
        if not user_environment_ids:
            manual_total = 0
        else:
            manual_count_stmt = manual_count_stmt.where(XHSAccountNote.environment_id.in_(user_environment_ids))
            manual_total = (await db.execute(manual_count_stmt)).scalar() or 0
    else:
        manual_total = (await db.execute(manual_count_stmt)).scalar() or 0
    total = auto_total + manual_total

    auto_stmt = (
        select(
            XHSPost.id.label("id"),
            literal(XHS_PUBLISH_SOURCE_AUTO).label("source_type"),
            literal(XHS_PUBLISH_SOURCE_AUTO_LABEL).label("source_label"),
            User.username.label("username"),
            XHSPost.environment_id.label("environment_id"),
            XHSEnvironment.account_name.label("environment_name"),
            XHSPost.title.label("title"),
            XHSPost.post_url.label("post_url"),
            XHSPost.feed_id.label("feed_id"),
            XHSPost.published_at.label("published_at"),
            XHSPost.like_count.label("like_count"),
            XHSPost.comment_count.label("comment_count"),
            XHSPost.collect_count.label("collect_count"),
            XHSPost.share_count.label("share_count"),
            XHSPost.created_at.label("created_at"),
        )
        .join(User, XHSPost.user_id == User.id)
        .join(XHSEnvironment, XHSPost.environment_id == XHSEnvironment.id, isouter=True)
        .where(XHSPost.status == "success")
    )
    if filter_user_id is not None:
        auto_stmt = auto_stmt.where(XHSPost.user_id == filter_user_id)

    manual_stmt = (
        select(
            XHSAccountNote.id.label("id"),
            literal(XHS_PUBLISH_SOURCE_SELF).label("source_type"),
            literal(XHS_PUBLISH_SOURCE_SELF_LABEL).label("source_label"),
            literal("").label("username"),
            XHSAccountNote.environment_id.label("environment_id"),
            func.coalesce(XHSEnvironment.account_name, XHSAccountNote.account_name).label("environment_name"),
            XHSAccountNote.title.label("title"),
            XHSAccountNote.post_url.label("post_url"),
            XHSAccountNote.feed_id.label("feed_id"),
            XHSAccountNote.published_at.label("published_at"),
            XHSAccountNote.liked_count.label("like_count"),
            XHSAccountNote.comment_count.label("comment_count"),
            XHSAccountNote.collected_count.label("collect_count"),
            XHSAccountNote.share_count.label("share_count"),
            XHSAccountNote.first_synced_at.label("created_at"),
        )
        .join(XHSEnvironment, XHSAccountNote.environment_id == XHSEnvironment.id, isouter=True)
        .where(
            XHSAccountNote.published_at.is_not(None),
            _self_managed_account_note_condition(),
        )
    )
    if filter_user_id is not None:
        if not user_environment_ids:
            manual_stmt = manual_stmt.where(literal(False))
        else:
            manual_stmt = manual_stmt.where(XHSAccountNote.environment_id.in_(user_environment_ids))

    combined_subquery = union_all(auto_stmt, manual_stmt).subquery()
    combined_stmt = (
        select(combined_subquery)
        .order_by(
            desc(combined_subquery.c.published_at),
            desc(combined_subquery.c.created_at),
            desc(combined_subquery.c.id),
        )
        .offset((page - 1) * limit)
        .limit(limit)
    )
    rows = (await db.execute(combined_stmt)).mappings().all()
    manual_env_usernames = await _load_environment_usernames(
        db,
        {
            int(row["environment_id"])
            for row in rows
            if row["source_type"] == XHS_PUBLISH_SOURCE_SELF and row["environment_id"] is not None
        },
    )

    items = []
    for row in rows:
        username_value = row["username"] or ""
        if row["source_type"] == XHS_PUBLISH_SOURCE_SELF:
            if filter_user_id is not None and username:
                username_value = username.strip()
            else:
                username_value = (
                    manual_env_usernames.get(int(row["environment_id"]), XHS_PUBLISH_SOURCE_SELF_LABEL)
                    if row["environment_id"] is not None
                    else XHS_PUBLISH_SOURCE_SELF_LABEL
                )
        items.append({
            "id": row["id"],
            "source_type": row["source_type"],
            "source_label": row["source_label"],
            "title": row["title"],
            "username": username_value,
            "environment_name": row["environment_name"] or "",
            "post_url": row["post_url"],
            "feed_id": row["feed_id"],
            "published_at": utc_naive_to_aware_iso(row["published_at"]),
            "like_count": row["like_count"] or 0,
            "comment_count": row["comment_count"] or 0,
            "collect_count": row["collect_count"] or 0,
            "share_count": row["share_count"] or 0,
            "created_at": utc_naive_to_aware_iso(row["created_at"]),
        })

    return ApiResponse(data={
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.get("/storage")
async def get_storage_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Storage usage breakdown by type"""
    rows = await db.execute(
        select(
            Material.type,
            func.count().label("count"),
            func.sum(Material.file_size).label("total_size"),
        )
        .where(Material.deleted_at.is_(None))
        .group_by(Material.type)
    )

    by_type = []
    total_bytes = 0
    for row in rows.all():
        size = row[2] or 0
        total_bytes += size
        by_type.append({
            "type": row[0],
            "count": row[1],
            "bytes": size,
            "mb": round(size / (1024 * 1024), 2),
        })

    return ApiResponse(data={
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / (1024 * 1024), 2),
        "by_type": by_type,
    })


@router.get("/rankings")
async def get_rankings(
    username: str | None = Query(default=None, description="按用户名筛选"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Various administrative rankings"""
    _ = current_user
    filter_user_id = await _resolve_user_id(db, username)
    if username and filter_user_id is None:
        return ApiResponse(data={
            "storage_ranking": [],
            "workflow_ranking": [],
            "active_users": [],
        })

    storage_stmt = (
        select(
            User.username,
            func.sum(Material.file_size).label("total_size"),
            func.count(Material.id).label("material_count")
        )
        .join(Material, User.id == Material.created_by)
        .where(Material.deleted_at.is_(None))
        .group_by(User.username)
        .order_by(desc("total_size"))
        .limit(10)
    )
    if filter_user_id is not None:
        storage_stmt = storage_stmt.where(User.id == filter_user_id)
    storage_res = await db.execute(storage_stmt)
    storage_ranking = [
        {
            "username": row[0],
            "total_size": row[1] or 0,
            "total_mb": round((row[1] or 0) / (1024 * 1024), 2),
            "count": row[2]
        }
        for row in storage_res.all()
    ]

    wf_stmt = (
        select(
            DifyWorkflowConfig.app_name,
            func.count(DifyTask.id).label("run_count")
        )
        .join(DifyTask, DifyWorkflowConfig.id == DifyTask.workflow_id)
        .group_by(DifyWorkflowConfig.app_name)
        .order_by(desc("run_count"))
        .limit(10)
    )
    if filter_user_id is not None:
        wf_stmt = wf_stmt.where(DifyTask.user_id == filter_user_id)
    wf_res = await db.execute(wf_stmt)
    workflow_ranking = [
        {"name": row[0], "count": row[1]}
        for row in wf_res.all()
    ]

    cutoff_cst = _now_cst_naive() - timedelta(days=30)
    cutoff_utc = _cst_naive_to_utc_naive(cutoff_cst)
    user_stmt = (
        select(
            User.username,
            func.count(AITask.id).label("ai_count")
        )
        .join(AITask, User.id == AITask.user_id)
        .where(AITask.created_at >= cutoff_utc)
        .group_by(User.username)
        .order_by(desc("ai_count"))
        .limit(10)
    )
    if filter_user_id is not None:
        user_stmt = user_stmt.where(User.id == filter_user_id)
    user_res = await db.execute(user_stmt)
    active_users = [
        {"username": row[0], "task_count": row[1]}
        for row in user_res.all()
    ]

    return ApiResponse(data={
        "storage_ranking": storage_ranking,
        "workflow_ranking": workflow_ranking,
        "active_users": active_users
    })
