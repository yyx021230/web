"""Admin resource management API (projects, AI tasks, copywritings)"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.core.deps import require_admin
from app.models.user import User
from app.models.project import Project
from app.models.ai_task import AITask
from app.models.dify_task import DifyTask
from app.models.dify_run_log import DifyRunLog
from app.models.dify_workflow import DifyWorkflowConfig
from app.models.copywriting import Copywriting
from app.utils.timezone import utc_naive_to_aware_iso
from app.utils.timezone import cst_now_naive

router = APIRouter()


def _iso_or_none(value: datetime | None) -> str | None:
    return utc_naive_to_aware_iso(value) if value else None


def _serialize_ai_task_logs(task: AITask) -> list[dict]:
    params = task.params or {}
    upstream_debug = params.get("upstream_debug") if isinstance(params.get("upstream_debug"), dict) else None
    logs: list[dict] = [
        {
            "timestamp": _iso_or_none(task.created_at),
            "level": "info",
            "title": "任务已创建",
            "message": f"模型={task.model_name}，状态={task.status}",
            "payload": {
                "prompt": task.prompt,
                "negative_prompt": task.negative_prompt,
                "params": task.params or {},
            },
        }
    ]
    if task.status == "processing":
        logs.append({
            "timestamp": _iso_or_none(task.created_at),
            "level": "info",
            "title": "任务处理中",
            "message": "任务已进入处理队列并开始生成",
            "payload": None,
        })
    if task.result_urls:
        logs.append({
            "timestamp": _iso_or_none(task.finished_at) or _iso_or_none(task.created_at),
            "level": "success",
            "title": "生成完成",
            "message": f"已生成 {len(task.result_urls)} 张图片",
            "payload": {"result_urls": task.result_urls},
        })
    if task.error:
        logs.append({
            "timestamp": _iso_or_none(task.finished_at) or _iso_or_none(task.created_at),
            "level": "error" if task.status == "failed" else "warn",
            "title": "任务异常",
            "message": task.error,
            "payload": None,
        })
    if upstream_debug:
        response = upstream_debug.get("response") if isinstance(upstream_debug.get("response"), dict) else {}
        request = upstream_debug.get("request") if isinstance(upstream_debug.get("request"), dict) else {}
        logs.append({
            "timestamp": upstream_debug.get("captured_at") or _iso_or_none(task.finished_at) or _iso_or_none(task.created_at),
            "level": "error" if task.status == "failed" else "warn",
            "title": "上游响应快照",
            "message": (
                f"{request.get('method') or 'POST'} {request.get('url') or '-'} "
                f"-> HTTP {response.get('status_code') or '-'}"
            ),
            "payload": upstream_debug,
        })
    return logs


async def _resolve_user_id(db: AsyncSession, username: str | None) -> int | None:
    if not username:
        return None
    normalized = username.strip()
    if not normalized:
        return None
    result = await db.execute(select(User.id).where(User.username == normalized))
    return result.scalar_one_or_none()


# --- Dify Workflow Tasks ---

@router.get("/workflow-tasks")
async def list_workflow_tasks(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    username: str | None = Query(default=None, description="按用户名筛选"),
    status: str | None = Query(default=None, description="按状态筛选"),
    workflow_id: int | None = Query(default=None, description="按工作流筛选"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """工作流运行任务列表（管理员）"""
    filter_user_id = await _resolve_user_id(db, username)
    if (username or "").strip() and filter_user_id is None:
        return ApiResponse(data={"items": [], "total": 0, "page": page, "limit": limit})

    conditions = []
    if filter_user_id is not None:
        conditions.append(DifyTask.user_id == filter_user_id)
    if status:
        conditions.append(DifyTask.status == status)
    if workflow_id:
        conditions.append(DifyTask.workflow_id == workflow_id)

    count_stmt = select(func.count()).select_from(DifyTask).where(*conditions) if conditions else select(func.count()).select_from(DifyTask)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    base_stmt = (
        select(DifyTask, User.username, DifyWorkflowConfig.app_name)
        .outerjoin(User, DifyTask.user_id == User.id)
        .outerjoin(DifyWorkflowConfig, DifyTask.workflow_id == DifyWorkflowConfig.id)
    )
    if conditions:
        base_stmt = base_stmt.where(*conditions)

    stmt = (
        base_stmt
        .order_by(desc(DifyTask.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()

    return ApiResponse(data={
        "items": [
            {
                "id": t.id,
                "user_id": t.user_id,
                "username": uname,
                "workflow_id": t.workflow_id,
                "workflow_name": wname,
                "status": t.status,
                "inputs": t.inputs,
                "outputs": t.outputs,
                "error": t.error,
                "created_at": str(t.created_at),
                "finished_at": str(t.finished_at) if t.finished_at else None,
            }
            for t, uname, wname in rows
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.delete("/workflow-tasks/{task_id}")
async def delete_workflow_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """管理员删除工作流任务"""
    from sqlalchemy import delete
    from app.models.dify_run_log import DifyRunLog
    result = await db.execute(select(DifyTask).where(DifyTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 级联删除日志
    await db.execute(delete(DifyRunLog).where(DifyRunLog.task_id == task_id))
    await db.delete(task)
    await db.commit()
    return ApiResponse(message="已删除")


@router.get("/workflow-tasks/{task_id}")
async def get_workflow_task_detail(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """工作流任务详情（管理员）"""
    result = await db.execute(
        select(DifyTask, User.username, DifyWorkflowConfig.app_name)
        .outerjoin(User, DifyTask.user_id == User.id)
        .outerjoin(DifyWorkflowConfig, DifyTask.workflow_id == DifyWorkflowConfig.id)
        .where(DifyTask.id == task_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")

    task, username, workflow_name = row
    log_conditions = [
        DifyRunLog.workflow_id == task.workflow_id,
        DifyRunLog.user_id == task.user_id,
    ]
    if task.task_id:
        log_conditions.append(DifyRunLog.task_id == task.task_id)
    else:
        log_conditions.append(DifyRunLog.started_at >= task.created_at)

    logs_result = await db.execute(
        select(DifyRunLog)
        .where(*log_conditions)
        .order_by(desc(DifyRunLog.started_at))
        .limit(20)
    )
    run_logs = list(logs_result.scalars().all())

    return ApiResponse(data={
        "id": task.id,
        "user_id": task.user_id,
        "username": username,
        "workflow_id": task.workflow_id,
        "workflow_name": workflow_name or f"#{task.workflow_id}",
        "task_id": task.task_id,
        "status": task.status,
        "inputs": task.inputs,
        "outputs": task.outputs,
        "error": task.error,
        "progress": task.progress,
        "elapsed_ms": task.elapsed_ms,
        "created_at": _iso_or_none(task.created_at),
        "finished_at": _iso_or_none(task.finished_at),
        "logs": [
            {
                "id": log.id,
                "timestamp": _iso_or_none(log.started_at),
                "finished_at": _iso_or_none(log.finished_at),
                "level": "error" if log.status == "failed" else "success" if log.status == "succeeded" else "info",
                "title": f"运行日志 #{log.id}",
                "message": log.error or f"状态={log.status}",
                "status": log.status,
                "task_id": log.task_id,
                "elapsed_ms": log.elapsed_ms,
                "payload": {
                    "inputs": log.inputs,
                    "outputs": log.outputs,
                    "error": log.error,
                },
            }
            for log in run_logs
        ],
    })


# --- Projects ---

@router.get("/projects")
async def list_projects(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    username: str | None = Query(default=None, description="按用户名筛选"),
    status: str | None = Query(default=None, description="按状态筛选"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """项目列表（管理员）"""
    filter_user_id = await _resolve_user_id(db, username)
    if (username or "").strip() and filter_user_id is None:
        return ApiResponse(data={"items": [], "total": 0, "page": page, "limit": limit})

    conditions = [Project.deleted_at.is_(None)]
    if filter_user_id is not None:
        conditions.append(Project.user_id == filter_user_id)
    if status:
        conditions.append(Project.status == status)

    count_stmt = (
        select(func.count())
        .select_from(Project)
        .join(User, Project.user_id == User.id)
        .where(*conditions)
    )
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    stmt = (
        select(Project, User.username)
        .join(User, Project.user_id == User.id)
        .where(*conditions)
        .order_by(desc(Project.updated_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()

    return ApiResponse(data={
        "items": [
            {
                "id": p.id,
                "user_id": p.user_id,
                "username": uname,
                "name": p.name,
                "thumbnail": p.thumbnail,
                "status": p.status,
                "created_at": str(p.created_at),
                "updated_at": str(p.updated_at),
            }
            for p, uname in rows
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """管理员删除项目"""
    from datetime import datetime
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    project.deleted_at = datetime.now()
    await db.commit()
    return ApiResponse(message="已删除")


@router.post("/projects/batch-delete")
async def batch_delete_projects(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """管理员批量删除项目（软删除）"""
    _ = current_user
    ids = data.get("project_ids") or []
    if not isinstance(ids, list) or len(ids) == 0:
        raise HTTPException(status_code=400, detail="project_ids 不能为空")

    from datetime import datetime
    result = await db.execute(
        select(Project).where(
            Project.id.in_(ids),
            Project.deleted_at.is_(None),
        )
    )
    projects = result.scalars().all()
    now = datetime.now()
    for p in projects:
        p.deleted_at = now
    await db.commit()
    return ApiResponse(data={"deleted": len(projects)}, message=f"已删除 {len(projects)} 个项目")


# --- AI Tasks ---

@router.get("/ai-tasks")
async def list_ai_tasks(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    username: str | None = Query(default=None, description="按用户名筛选"),
    status: str | None = Query(default=None, description="按状态筛选"),
    model_name: str | None = Query(default=None, description="按模型筛选"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """AI 生图任务列表（管理员）"""
    filter_user_id = await _resolve_user_id(db, username)
    if (username or "").strip() and filter_user_id is None:
        return ApiResponse(data={"items": [], "total": 0, "page": page, "limit": limit})

    conditions = []
    if filter_user_id is not None:
        conditions.append(AITask.user_id == filter_user_id)
    if status:
        conditions.append(AITask.status == status)
    if model_name:
        conditions.append(AITask.model_name == model_name)

    count_stmt = select(func.count()).select_from(AITask).where(*conditions) if conditions else select(func.count()).select_from(AITask)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    base_stmt = (
        select(AITask, User.username)
        .outerjoin(User, AITask.user_id == User.id)
    )
    if conditions:
        base_stmt = base_stmt.where(*conditions)

    stmt = (
        base_stmt
        .order_by(desc(AITask.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()

    return ApiResponse(data={
        "items": [
            {
                "id": t.id,
                "user_id": t.user_id,
                "username": uname,
                "model_name": t.model_name,
                "provider_name": ((t.params or {}).get("provider") or {}).get("name"),
                "provider_kind": ((t.params or {}).get("provider") or {}).get("provider_kind"),
                "prompt": t.prompt[:100] if t.prompt else "",
                "status": t.status,
                "result_urls": t.result_urls,
                "error": t.error,
                "elapsed_seconds": t.elapsed_seconds,
                "created_at": utc_naive_to_aware_iso(t.created_at),
            }
            for t, uname in rows
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.get("/ai-tasks/{task_id}")
async def get_ai_task_detail(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """AI 生图任务详情（管理员）"""
    result = await db.execute(
        select(AITask, User.username)
        .outerjoin(User, AITask.user_id == User.id)
        .where(AITask.id == task_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")

    task, username = row
    params = task.params or {}
    provider = params.get("provider") or {}
    upstream_debug = params.get("upstream_debug") if isinstance(params.get("upstream_debug"), dict) else None
    return ApiResponse(data={
        "id": task.id,
        "user_id": task.user_id,
        "username": username,
        "model_name": task.model_name,
        "provider_name": provider.get("name"),
        "provider_kind": provider.get("provider_kind"),
        "prompt": task.prompt,
        "negative_prompt": task.negative_prompt,
        "params": task.params or {},
        "status": task.status,
        "result_urls": task.result_urls or [],
        "error": task.error,
        "upstream_debug": upstream_debug,
        "elapsed_seconds": task.elapsed_seconds,
        "created_at": _iso_or_none(task.created_at),
        "finished_at": _iso_or_none(task.finished_at),
        "logs": _serialize_ai_task_logs(task),
    })


@router.post("/ai-tasks/{task_id}/fail")
async def fail_ai_task(
    task_id: int,
    req: dict | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """管理员手动终止 AI 生图任务并标记失败"""
    result = await db.execute(select(AITask).where(AITask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status in ("completed", "failed"):
        raise HTTPException(status_code=400, detail=f"任务已{task.status}，无需重复终止")

    reason = ((req or {}).get("reason") or "").strip() or "管理员手动终止任务"
    task.status = "failed"
    task.error = reason
    task.finished_at = cst_now_naive()
    await db.commit()
    await db.refresh(task)
    return ApiResponse(data={"id": task.id, "status": task.status}, message="任务已终止并标记失败")


# --- Copywritings ---

@router.get("/copywritings")
async def list_copywritings(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    username: str | None = Query(default=None, description="按用户名筛选"),
    category: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """文案列表（管理员）"""
    filter_user_id = await _resolve_user_id(db, username)
    if (username or "").strip() and filter_user_id is None:
        return ApiResponse(data={"items": [], "total": 0, "page": page, "limit": limit})

    conditions = [Copywriting.deleted_at.is_(None)]
    if filter_user_id is not None:
        conditions.append(Copywriting.created_by == filter_user_id)
    if category:
        conditions.append(Copywriting.category == category)
    if search:
        conditions.append(
            and_(
                Copywriting.title.ilike(f"%{search}%"),
            )
        )

    count_stmt = select(func.count()).select_from(Copywriting).where(*conditions)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    stmt = (
        select(Copywriting)
        .where(*conditions)
        .order_by(desc(Copywriting.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    return ApiResponse(data={
        "items": [
            {
                "id": c.id,
                "title": c.title,
                "content": c.content[:200] if c.content else "",
                "tags": c.tags,
                "category": c.category,
                "created_by": c.created_by,
                "created_at": str(c.created_at),
            }
            for c in items
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.delete("/copywritings/{copywriting_id}")
async def delete_copywriting(
    copywriting_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """管理员删除文案"""
    from datetime import datetime
    result = await db.execute(select(Copywriting).where(Copywriting.id == copywriting_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="文案不存在")
    item.deleted_at = datetime.now()
    await db.commit()
    return ApiResponse(message="已删除")
