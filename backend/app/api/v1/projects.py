from __future__ import annotations
"""项目管理 API"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.services.project_service import ProjectService
from app.models.user import User
from app.core.deps import get_current_user

router = APIRouter()


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="项目名称")
    fabric_json: str | None = Field(None, description="Fabric.js 画布数据", max_length=5_000_000)
    thumbnail: str | None = Field(None, description="缩略图 URL")
    status: str | None = Field(None, description="状态: draft/published")


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255, description="项目名称")
    fabric_json: str | None = Field(None, description="Fabric.js 画布数据", max_length=5_000_000)
    thumbnail: str | None = Field(None, description="缩略图 URL")
    status: str | None = Field(None, description="状态: draft/published")


@router.get("")
async def get_projects(
    page: int = Query(default=1, ge=1, description="页码"),
    limit: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的项目列表"""
    service = ProjectService(db)
    items, total = await service.get_list(current_user.id, page, limit)
    return ApiResponse(data={
        "items": [
            {
                "id": p.id,
                "name": p.name,
                "thumbnail": p.thumbnail,
                "status": p.status,
                "created_at": str(p.created_at),
                "updated_at": str(p.updated_at),
            }
            for p in items
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.post("")
async def save_project(
    req: ProjectCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建新项目"""
    service = ProjectService(db)
    project = await service.create(
        current_user.id,
        req.name,
        fabric_json=req.fabric_json,
        thumbnail=req.thumbnail,
        status=req.status,
    )
    return ApiResponse(data={
        "id": project.id,
        "name": project.name,
        "thumbnail": project.thumbnail,
        "status": project.status,
        "created_at": str(project.created_at),
    })


@router.get("/{project_id}")
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取项目详情（含画布数据）"""
    service = ProjectService(db)
    project = await service.get_by_id(project_id, current_user.id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return ApiResponse(data={
        "id": project.id,
        "name": project.name,
        "fabric_json": project.fabric_json,
        "thumbnail": project.thumbnail,
        "status": project.status,
        "created_at": str(project.created_at),
        "updated_at": str(project.updated_at),
    })


@router.put("/{project_id}")
async def update_project(
    project_id: int,
    req: ProjectUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新项目"""
    service = ProjectService(db)
    project = await service.update(
        project_id, current_user.id,
        name=req.name,
        fabric_json=req.fabric_json,
        thumbnail=req.thumbnail,
        status=req.status,
    )
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return ApiResponse(data={
        "id": project.id,
        "name": project.name,
        "thumbnail": project.thumbnail,
        "status": project.status,
        "updated_at": str(project.updated_at),
    })


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除项目"""
    service = ProjectService(db)
    deleted = await service.delete(project_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="项目不存在")
    return ApiResponse(message="已删除")
