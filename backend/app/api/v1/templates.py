from __future__ import annotations
"""模板管理 API"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.template import TemplateCreate, TemplateUpdate, TemplateResponse
from app.services.template_service import TemplateService
from app.models.user import User
from app.core.deps import get_current_user

router = APIRouter()


@router.get("", response_model=ApiResponse[dict])
async def get_templates(
    page: int = Query(default=1, ge=1, description="页码"),
    limit: int = Query(default=20, ge=1, le=100, description="每页数量"),
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """获取模板列表"""
    service = TemplateService(db)
    items, total = await service.get_list(page, limit, category)
    return ApiResponse(data={
        "items": [TemplateResponse.model_validate(t).model_dump() for t in items],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.get("/{template_id}", response_model=ApiResponse[TemplateResponse])
async def get_template(template_id: int, db: AsyncSession = Depends(get_db)):
    """获取模板详情"""
    service = TemplateService(db)
    template = await service.get_by_id(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    return ApiResponse(data=TemplateResponse.model_validate(template))


@router.post("", response_model=ApiResponse[TemplateResponse])
async def create_template(
    req: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建模板"""
    service = TemplateService(db)
    template = await service.create(req, user_id=current_user.id)
    return ApiResponse(data=TemplateResponse.model_validate(template))


@router.put("/{template_id}", response_model=ApiResponse[TemplateResponse])
async def update_template(
    template_id: int,
    req: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新模板"""
    service = TemplateService(db)
    template = await service.update(template_id, req, user_id=current_user.id)
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    return ApiResponse(data=TemplateResponse.model_validate(template))


@router.delete("/{template_id}")
async def delete_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除模板"""
    service = TemplateService(db)
    deleted = await service.delete(template_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="模板不存在")
    return ApiResponse(message="已删除")
