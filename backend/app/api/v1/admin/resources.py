"""Admin resource management API (projects, AI tasks, copywritings)"""
from __future__ import annotations

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
from app.models.dify_workflow import DifyWorkflowConfig
from app.models.copywriting import Copywriting

router = APIRouter()


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
    conditions = []
    if username:
        user_result = await db.execute(select(User).where(User.username == username))
        u = user_result.scalar_one_or_none()
        if u:
            conditions.append(DifyTask.user_id == u.id)
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
    conditions = [Project.deleted_at.is_(None)]
    if username:
        conditions.append(User.username.ilike(f"%{username.strip()}%"))
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
    conditions = []
    if username:
        user_result = await db.execute(select(User).where(User.username == username))
        u = user_result.scalar_one_or_none()
        if u:
            conditions.append(AITask.user_id == u.id)
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
                "prompt": t.prompt[:100] if t.prompt else "",
                "status": t.status,
                "result_urls": t.result_urls,
                "error": t.error,
                "elapsed_seconds": t.elapsed_seconds,
                "created_at": str(t.created_at),
            }
            for t, uname in rows
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })


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
    conditions = [Copywriting.deleted_at.is_(None)]
    if username:
        user_result = await db.execute(select(User).where(User.username == username))
        u = user_result.scalar_one_or_none()
        if u:
            conditions.append(Copywriting.created_by == u.id)
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
