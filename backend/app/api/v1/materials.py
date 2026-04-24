"""素材管理 API"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.services.material_service import MaterialService
from app.adapters.storage import storage
from app.models.user import User
from app.core.deps import get_current_user

router = APIRouter()

# 最大上传 10MB
MAX_UPLOAD_SIZE = 10 * 1024 * 1024

# 允许的 MIME 类型
ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml",
    "video/mp4", "video/webm",
}


@router.get("")
async def get_materials(
    page: int = 1,
    limit: int = 20,
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """获取素材列表"""
    service = MaterialService(db)
    items, total = await service.get_list(page, limit, category)
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
                "created_at": str(m.created_at),
            }
            for m in items
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.post("/upload")
async def upload_material(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传素材文件"""
    # 文件大小校验
    file_content = await file.read()
    if len(file_content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制 ({MAX_UPLOAD_SIZE // 1024 // 1024}MB)",
        )

    # 文件类型校验
    content_type = file.content_type or ""
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {content_type}",
        )

    url = await storage.save(file_content, file.filename or "upload", content_type)

    # 推断素材类型
    if content_type.startswith("image"):
        material_type = "image"
    elif content_type.startswith("video"):
        material_type = "video"
    else:
        material_type = "file"

    service = MaterialService(db)
    material = await service.create(
        name=file.filename or "upload",
        material_type=material_type,
        url=url,
        user_id=current_user.id,
    )
    return ApiResponse(data={
        "id": material.id,
        "name": material.name,
        "type": material.type,
        "url": material.url,
    })


@router.delete("/{material_id}")
async def delete_material(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除素材（需登录）"""
    service = MaterialService(db)
    deleted = await service.delete(material_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="素材不存在")
    return ApiResponse(message="已删除")
