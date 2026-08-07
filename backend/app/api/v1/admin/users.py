"""Admin user management API"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_
from sqlalchemy.orm import selectinload
from datetime import timedelta, datetime

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.core.deps import require_admin
from app.core.roles import (
    VALID_USER_ROLES,
    get_user_roles,
    normalize_roles,
    set_user_roles,
    validate_roles,
)
from app.core.security import hash_password
from app.models.user import User
from app.models.project import Project
from app.models.material import Material
from app.models.ai_task import AITask
from app.models.dify_workflow import DifyWorkflowConfig
from app.models.dify_task import DifyTask
from app.models.dify_run_log import DifyRunLog
from app.models.copywriting import Copywriting

router = APIRouter()


def _user_payload(user: User) -> dict:
    roles = get_user_roles(user)
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "avatar": user.avatar,
        "is_active": user.is_active,
        "role": user.role,
        "roles": roles,
        "created_at": str(user.created_at),
    }


@router.get("")
async def list_users(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """用户列表（管理员）"""
    count_stmt = select(func.count()).select_from(User)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    stmt = (
        select(User)
        .options(selectinload(User.role_assignments))
        .order_by(desc(User.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    users = list(result.scalars().all())

    return ApiResponse(data={
        "items": [_user_payload(u) for u in users],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.patch("/{user_id}/role")
async def update_user_role(
    user_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """修改用户角色"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    role = data.get("role")
    if role not in VALID_USER_ROLES:
        raise HTTPException(status_code=400, detail="无效的角色")

    await set_user_roles(db, user, [role])
    await db.commit()
    return ApiResponse(data={"id": user.id, "role": user.role, "roles": [role]})


@router.patch("/{user_id}/profile")
async def update_user_profile(
    user_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """修改用户基础资料。目前只允许维护展示名，不影响登录用户名。"""
    result = await db.execute(
        select(User).options(selectinload(User.role_assignments)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if "display_name" in data:
        display_name = str(data.get("display_name") or "").strip()
        if len(display_name) > 80:
            raise HTTPException(status_code=400, detail="展示名最多 80 个字符")
        user.display_name = display_name or None

    await db.commit()
    await db.refresh(user)
    return ApiResponse(data=_user_payload(user), message="用户资料已更新")


@router.patch("/{user_id}/roles")
async def update_user_roles(
    user_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """修改用户多角色"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    roles = normalize_roles(data.get("roles"), fallback="viewer")
    try:
        validate_roles(roles)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    normalized = await set_user_roles(db, user, roles)
    await db.commit()
    return ApiResponse(data={"id": user.id, "role": user.role, "roles": normalized})


@router.get("/{user_id}/workflows")
async def get_user_workflows(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """获取用户有权访问的工作流"""
    stmt = (
        select(User)
        .where(User.id == user_id)
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 加载关联的工作流
    from sqlalchemy.orm import selectinload
    stmt = (
        select(User)
        .options(selectinload(User.workflows))
        .where(User.id == user_id)
    )
    result = await db.execute(stmt)
    user = result.scalar_one()

    return ApiResponse(data=[
        {
            "id": w.id,
            "app_name": w.app_name,
            "app_type": w.app_type,
            "description": w.description,
            "is_enabled": w.is_enabled,
        }
        for w in user.workflows
    ])


@router.post("/{user_id}/workflows")
async def set_user_workflows(
    user_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """设置用户有权访问的工作流"""
    workflow_ids = data.get("workflow_ids", [])
    
    # 查找用户
    from sqlalchemy.orm import selectinload
    stmt = (
        select(User)
        .options(selectinload(User.workflows))
        .where(User.id == user_id)
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 查找所有工作流
    stmt = select(DifyWorkflowConfig).where(DifyWorkflowConfig.id.in_(workflow_ids))
    result = await db.execute(stmt)
    workflows = list(result.scalars().all())

    # 更新关联
    user.workflows = workflows
    await db.commit()
    return ApiResponse(data={"id": user.id, "workflows": [w.id for w in user.workflows]})


@router.get("/{user_id}/stats")
async def get_user_stats(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """获取单个用户的统计数据"""
    # 任务数
    ai_task_count = await db.execute(select(func.count()).select_from(AITask).where(AITask.user_id == user_id))
    wf_task_count = await db.execute(select(func.count()).select_from(DifyTask).where(DifyTask.user_id == user_id))

    # 项目数
    project_count = await db.execute(select(func.count()).select_from(Project).where(and_(Project.user_id == user_id, Project.deleted_at.is_(None))))

    # 素材存储
    storage_result = await db.execute(select(func.sum(Material.file_size)).where(and_(Material.created_by == user_id, Material.deleted_at.is_(None))))
    storage_bytes = storage_result.scalar() or 0

    return ApiResponse(data={
        "ai_tasks": ai_task_count.scalar() or 0,
        "wf_tasks": wf_task_count.scalar() or 0,
        "projects": project_count.scalar() or 0,
        "storage_mb": round(storage_bytes / (1024 * 1024), 2),
    })


@router.post("/batch-delete-tasks")
async def batch_delete_user_tasks(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """批量删除用户任务历史记录（仅限管理员）"""
    user_id = data.get("user_id")
    task_type = data.get("type")  # 'ai' or 'workflow'

    if not user_id:
        raise HTTPException(status_code=400, detail="缺少 user_id")

    if task_type == 'ai':
        from sqlalchemy import delete
        await db.execute(delete(AITask).where(AITask.user_id == user_id))
    elif task_type == 'workflow':
        from sqlalchemy import delete
        await db.execute(delete(DifyTask).where(DifyTask.user_id == user_id))
        await db.execute(delete(DifyRunLog).where(DifyRunLog.user_id == user_id))
    else:
        raise HTTPException(status_code=400, detail="无效的任务类型")

    await db.commit()
    return ApiResponse(message="删除成功")


@router.patch("/{user_id}/active")
async def update_user_active(
    user_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """禁用/启用用户"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 防止禁用自己
    if user.id == current_user.id and data.get("is_active") is False:
        raise HTTPException(status_code=400, detail="不能禁用自己")

    user.is_active = data.get("is_active", True)
    await db.commit()
    return ApiResponse(data={"id": user.id, "is_active": user.is_active})


@router.post("")
async def create_user(
    req: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """创建用户（管理员）"""
    username = req.get("username", "").strip()
    email = req.get("email", "").strip().lower()
    password = req.get("password", "")
    roles = normalize_roles(req.get("roles") or req.get("role"), fallback="viewer")

    if not username or not email or not password:
        raise HTTPException(status_code=400, detail="用户名、邮箱和密码为必填项")
    try:
        validate_roles(roles)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 检查用户名是否已存在
    result = await db.execute(select(User).where(User.username == username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 检查邮箱是否已存在
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="邮箱已存在")

    user = User(
        username=username,
        display_name=str(req.get("display_name") or "").strip() or None,
        email=email,
        hashed_password=hash_password(password),
        role=roles[0],
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    normalized = await set_user_roles(db, user, roles)
    await db.commit()
    return ApiResponse(data={
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "role": user.role,
        "roles": normalized,
    })


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """删除用户（管理员）"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 防止删除自己
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己")

    await db.delete(user)
    await db.commit()
    return ApiResponse(message="已删除")


@router.get("/{user_id}/detail")
async def get_user_detail(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """获取用户详细统计"""
    user_result = await db.execute(
        select(User).options(selectinload(User.role_assignments)).where(User.id == user_id)
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    now = datetime.now()
    yesterday = now - timedelta(hours=24)

    # Counts by user
    project_count = await db.execute(select(func.count()).select_from(Project).where(
        and_(Project.user_id == user_id, Project.deleted_at.is_(None))
    ))
    material_count = await db.execute(select(func.count()).select_from(Material).where(
        and_(Material.created_by == user_id, Material.deleted_at.is_(None))
    ))
    ai_task_count = await db.execute(select(func.count()).select_from(AITask).where(AITask.user_id == user_id))
    ai_task_24h = await db.execute(select(func.count()).select_from(AITask).where(
        and_(AITask.user_id == user_id, AITask.created_at >= yesterday)
    ))
    workflow_count = await db.execute(select(func.count()).select_from(DifyWorkflowConfig).where(
        DifyWorkflowConfig.created_by == user_id
    ))
    task_count = await db.execute(select(func.count()).select_from(DifyTask).where(DifyTask.user_id == user_id))
    run_log_count = await db.execute(select(func.count()).select_from(DifyRunLog).where(DifyRunLog.user_id == user_id))
    copywriting_count = await db.execute(select(func.count()).select_from(Copywriting).where(
        and_(Copywriting.created_by == user_id, Copywriting.deleted_at.is_(None))
    ))

    # Recent AI tasks
    recent_tasks = await db.execute(
        select(AITask).where(AITask.user_id == user_id).order_by(desc(AITask.created_at)).limit(5)
    )

    # Recent Dify tasks
    recent_dify_tasks = await db.execute(
        select(DifyTask).where(DifyTask.user_id == user_id).order_by(desc(DifyTask.created_at)).limit(5)
    )

    return ApiResponse(data={
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
            "avatar": user.avatar,
            "role": user.role,
            "roles": get_user_roles(user),
            "is_active": user.is_active,
            "created_at": str(user.created_at),
        },
        "stats": {
            "project_count": project_count.scalar() or 0,
            "material_count": material_count.scalar() or 0,
            "ai_task_count": ai_task_count.scalar() or 0,
            "ai_task_24h": ai_task_24h.scalar() or 0,
            "workflow_count": workflow_count.scalar() or 0,
            "dify_task_count": task_count.scalar() or 0,
            "dify_run_log_count": run_log_count.scalar() or 0,
            "copywriting_count": copywriting_count.scalar() or 0,
        },
        "recent_ai_tasks": [
            {
                "id": t.id,
                "model_name": t.model_name,
                "prompt": t.prompt[:100] if t.prompt else "",
                "status": t.status,
                "created_at": str(t.created_at),
            }
            for t in recent_tasks.scalars().all()
        ],
        "recent_dify_tasks": [
            {
                "id": t.id,
                "workflow_id": t.workflow_id,
                "status": t.status,
                "created_at": str(t.created_at),
            }
            for t in recent_dify_tasks.scalars().all()
        ],
    })
