"""Admin dashboard stats API"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_, Integer
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

router = APIRouter()


def _normalize_ai_model(model_name: str | None) -> str:
    model = (model_name or "").strip().lower()
    if not model:
        return "unmatched"
    if "seedream" in model or "seed-dream" in model:
        return "seedream"
    if (
        "image2" in model
        or "image-2" in model
        or "image2.0" in model
        or "gptimage2" in model
        or "gpt-image" in model
        or "gpt_image" in model
    ):
        return "image2"
    return "unmatched"


@router.get("/overview")
async def get_overview_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Dashboard overview statistics"""
    user_count = await db.execute(select(func.count()).select_from(User))
    project_count = await db.execute(select(func.count()).select_from(Project).where(Project.deleted_at.is_(None)))
    material_count = await db.execute(select(func.count()).select_from(Material).where(Material.deleted_at.is_(None)))
    ai_task_count = await db.execute(select(func.count()).select_from(AITask))
    workflow_count = await db.execute(select(func.count()).select_from(DifyWorkflowConfig))
    run_log_count = await db.execute(select(func.count()).select_from(DifyRunLog))

    # Storage: sum of material file_size
    storage_result = await db.execute(select(func.sum(Material.file_size)).where(Material.deleted_at.is_(None)))
    storage_bytes = storage_result.scalar() or 0

    # Recent AI task success rate
    now = datetime.now()
    yesterday = now - timedelta(hours=24)
    total_24h = await db.execute(select(func.count()).select_from(AITask).where(AITask.created_at >= yesterday))
    failed_24h = await db.execute(select(func.count()).select_from(AITask).where(
        and_(AITask.created_at >= yesterday, AITask.status == "failed")
    ))

    total_24h = total_24h.scalar() or 0
    failed_24h = failed_24h.scalar() or 0
    success_rate = round((total_24h - failed_24h) / total_24h * 100, 1) if total_24h > 0 else 0

    return ApiResponse(data={
        "user_count": user_count.scalar() or 0,
        "project_count": project_count.scalar() or 0,
        "material_count": material_count.scalar() or 0,
        "ai_task_count": ai_task_count.scalar() or 0,
        "workflow_count": workflow_count.scalar() or 0,
        "run_log_count": run_log_count.scalar() or 0,
        "storage_bytes": storage_bytes,
        "storage_mb": round(storage_bytes / (1024 * 1024), 2),
        "ai_tasks_24h": total_24h,
        "ai_success_rate_24h": success_rate,
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """获取全站活跃任务"""
    # 活跃 AI 生图任务
    ai_stmt = (
        select(AITask, User.username)
        .join(User, AITask.user_id == User.id)
        .where(AITask.status == "processing")
        .order_by(desc(AITask.created_at))
        .limit(10)
    )
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
    now = datetime.now()

    if granularity == "hour":
        bucket_count = 24
        bucket_delta = timedelta(hours=1)
        start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=bucket_count - 1)
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
    cur = start
    for i in range(bucket_count):
        end = cur + bucket_delta
        if granularity == "week":
            label = f"{cur.strftime(label_fmt)}-{(end - timedelta(days=1)).strftime(label_fmt)}"
        else:
            label = cur.strftime(label_fmt)
        key = cur.strftime(key_fmt)
        buckets.append({
            "key": key,
            "label": label,
            "start": cur.isoformat(sep=" "),
            "end": end.isoformat(sep=" "),
        })
        bucket_index[key] = i
        cur = end

    def bucket_key(dt: datetime) -> str | None:
        if dt < start:
            return None
        if granularity == "hour":
            return dt.replace(minute=0, second=0, microsecond=0).strftime(key_fmt)
        if granularity == "day":
            return dt.replace(hour=0, minute=0, second=0, microsecond=0).strftime(key_fmt)
        wk = dt.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=dt.weekday())
        return wk.strftime(key_fmt)

    filter_user_id: int | None = None
    if username:
        ures = await db.execute(select(User.id).where(User.username == username))
        filter_user_id = ures.scalar_one_or_none()
        if filter_user_id is None:
            return ApiResponse(data={
                "granularity": granularity,
                "buckets": buckets,
                "ai": {"series": {"image2": [0] * bucket_count, "seedream": [0] * bucket_count}, "total_records": 0, "matched_records": 0, "raw_model_counts": {}},
                "workflow": {"names": [], "series": {}, "total_records": 0},
            })

    ai_stmt = select(AITask.model_name, AITask.created_at).where(AITask.created_at >= start)
    if filter_user_id is not None:
        ai_stmt = ai_stmt.where(AITask.user_id == filter_user_id)
    ai_rows = await db.execute(ai_stmt)
    ai_series = {"image2": [0] * bucket_count, "seedream": [0] * bucket_count}
    raw_model_counts: dict[str, int] = {}
    ai_total = 0
    ai_matched = 0
    for model_name, created_at in ai_rows.all():
        if not created_at:
            continue
        ai_total += 1
        raw_key = (model_name or "").strip().lower() or "(empty)"
        raw_model_counts[raw_key] = raw_model_counts.get(raw_key, 0) + 1
        key = bucket_key(created_at)
        if key is None:
            continue
        idx = bucket_index.get(key)
        if idx is None:
            continue
        norm = _normalize_ai_model(model_name)
        if norm in ai_series:
            ai_series[norm][idx] += 1
            ai_matched += 1

    # Workflow tasks (全量，不依赖用户关联)
    wf_stmt = (
        select(DifyTask.created_at, DifyWorkflowConfig.app_name)
        .outerjoin(DifyWorkflowConfig, DifyTask.workflow_id == DifyWorkflowConfig.id)
        .where(DifyTask.created_at >= start)
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
            "series": ai_series,
            "total_records": ai_total,
            "matched_records": ai_matched,
            "raw_model_counts": dict(sorted(raw_model_counts.items(), key=lambda x: x[1], reverse=True)[:12]),
        },
        "workflow": {
            "names": wf_names,
            "series": wf_series,
            "total_records": sum(wf_name_totals.values()),
        },
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Various administrative rankings"""
    # 1. Storage ranking by user
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

    # 2. Hot workflow ranking (by run count)
    from app.models.dify_task import DifyTask
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
    wf_res = await db.execute(wf_stmt)
    workflow_ranking = [
        {"name": row[0], "count": row[1]}
        for row in wf_res.all()
    ]

    # 3. Active users (by task count in last 30 days)
    cutoff = datetime.now() - timedelta(days=30)
    user_stmt = (
        select(
            User.username,
            func.count(AITask.id).label("ai_count")
        )
        .join(AITask, User.id == AITask.user_id)
        .where(AITask.created_at >= cutoff)
        .group_by(User.username)
        .order_by(desc("ai_count"))
        .limit(10)
    )
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
