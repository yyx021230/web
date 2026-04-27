"""素材管理 API"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
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
                # 设计类素材包含 design_json（用于编辑器加载还原）
                "design_json": m.design_json,
            }
            for m in items
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.get("/{material_id}")
async def get_material(
    material_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取单个素材详情（用于编辑器加载设计稿）"""
    service = MaterialService(db)
    material = await service.get_by_id(material_id)
    if not material:
        raise HTTPException(status_code=404, detail="素材不存在")
    return ApiResponse(data={
        "id": material.id,
        "name": material.name,
        "type": material.type,
        "url": material.url,
        "width": material.width,
        "height": material.height,
        "category": material.category,
        "tags": material.tags,
        "created_at": str(material.created_at),
        "design_json": material.design_json,
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


@router.post("/design")
async def save_design(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """保存编辑器设计稿到草稿箱

    请求体:
    - name: 设计名称
    - design_json: 完整的 Fabric JSON（含所有图层、位置、样式关系）
    - thumbnail: 设计缩略图 URL 或 base64（用于草稿箱预览）
    - width: 画布宽度
    - height: 画布高度
    """
    service = MaterialService(db)
    material = await service.create_design(
        name=data.get("name", "未命名设计"),
        design_json=data.get("design_json"),
        thumbnail=data.get("thumbnail"),
        width=data.get("width"),
        height=data.get("height"),
        user_id=current_user.id,
    )
    return ApiResponse(data={
        "id": material.id,
        "name": material.name,
        "type": material.type,
        "url": material.url,  # 缩略图
        "width": material.width,
        "height": material.height,
        "category": material.category,
    })


@router.delete("/all")
async def delete_all_materials(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量删除所有素材（当前用户，谨慎使用）"""
    service = MaterialService(db)
    count = await service.delete_all(user_id=current_user.id)
    return ApiResponse(message=f"已删除 {count} 个素材", data={"count": count})


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


@router.put("/{material_id}")
async def update_material(
    material_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新已有设计稿（覆盖保存）

    请求体:
    - name: 设计名称
    - design_json: 完整的 Fabric JSON
    - thumbnail: 设计缩略图
    - width: 画布宽度
    - height: 画布高度
    """
    service = MaterialService(db)
    material = await service.update_design(
        material_id=material_id,
        name=data.get("name"),
        design_json=data.get("design_json"),
        thumbnail=data.get("thumbnail"),
        width=data.get("width"),
        height=data.get("height"),
        user_id=current_user.id,
    )
    if not material:
        raise HTTPException(status_code=404, detail="素材不存在或无权操作")
    return ApiResponse(data={
        "id": material.id,
        "name": material.name,
        "type": material.type,
        "url": material.url,
        "width": material.width,
        "height": material.height,
        "category": material.category,
    })
