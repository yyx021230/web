"""Admin material management API"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.core.deps import require_admin
from app.models.user import User
from app.models.material import Material

router = APIRouter()


@router.get("")
async def list_materials(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    category: str | None = None,
    type: str | None = None,
    username: str | None = Query(default=None, description="按用户名筛选"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """素材列表（管理员，可看所有用户）"""
    conditions = [Material.deleted_at.is_(None)]
    if category:
        conditions.append(Material.category == category)
    if type:
        conditions.append(Material.type == type)
    if username:
        conditions.append(User.username.ilike(f"%{username.strip()}%"))

    count_stmt = (
        select(func.count())
        .select_from(Material)
        .join(User, Material.created_by == User.id)
        .where(*conditions)
    )
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    stmt = (
        select(Material, User.username)
        .join(User, Material.created_by == User.id)
        .where(*conditions)
        .order_by(desc(Material.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()

    return ApiResponse(data={
        "items": [
            {
                "id": m.id,
                "name": m.name,
                "type": m.type,
                "url": m.url,
                "width": m.width,
                "height": m.height,
                "category": m.category,
                "tags": m.tags,
                "file_size": m.file_size,
                "created_by": m.created_by,
                "username": uname,
                "created_at": str(m.created_at),
            }
            for m, uname in rows
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.delete("/{material_id}")
async def delete_material(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """管理员删除素材（软删除，跳过 owner 校验）"""
    from datetime import datetime
    result = await db.execute(select(Material).where(Material.id == material_id))
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="素材不存在")

    material.deleted_at = datetime.now()
    await db.commit()
    return ApiResponse(message="已删除")


@router.post("/batch-delete")
async def batch_delete_materials(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """管理员批量删除素材（软删除）"""
    _ = current_user
    ids = data.get("material_ids") or []
    if not isinstance(ids, list) or len(ids) == 0:
        raise HTTPException(status_code=400, detail="material_ids 不能为空")

    from datetime import datetime

    result = await db.execute(
        select(Material).where(
            Material.id.in_(ids),
            Material.deleted_at.is_(None),
        )
    )
    materials = result.scalars().all()
    now = datetime.now()
    for m in materials:
        m.deleted_at = now
    await db.commit()
    return ApiResponse(data={"deleted": len(materials)}, message=f"已删除 {len(materials)} 条素材")


@router.get("/templates")
async def list_templates(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """模版列表（category=ai-template）"""
    conditions = [Material.deleted_at.is_(None), Material.category == "ai-template"]

    count_stmt = select(func.count()).select_from(Material).where(*conditions)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    stmt = (
        select(Material)
        .where(*conditions)
        .order_by(desc(Material.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    return ApiResponse(data={
        "items": [
            {
                "id": m.id,
                "name": m.name,
                "url": m.url,
                "width": m.width,
                "height": m.height,
                "ai_meta": m.ai_meta,
                "created_by": m.created_by,
                "created_at": str(m.created_at),
            }
            for m in items
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })
