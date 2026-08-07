"""素材管理 API"""

from __future__ import annotations

import asyncio
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Form
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.services.material_service import MaterialService
from app.adapters.storage import storage
from app.models.user import User
from app.core.deps import get_current_user
from app.core.remote_download import download_allowed_remote_image

router = APIRouter()

# 最大上传 10MB
MAX_UPLOAD_SIZE = 10 * 1024 * 1024

# 允许的 MIME 类型
ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "video/mp4", "video/webm",
}


async def _download_remote_image(url: str) -> tuple[bytes, str, str]:
    """下载远程图片到本地存储

    Returns:
        (file_content, filename, content_type)
    """
    return await download_allowed_remote_image(url)


@router.get("")
async def get_materials(
    page: int = 1,
    limit: int = 20,
    category: str | None = None,
    exclude_category: str | None = Query(default=None, description="排除指定 category"),
    owner: bool = Query(True, description="默认只返回当前用户的素材"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取素材列表

    owner: 默认只返回当前用户的素材；仅显式传 false 时返回所有素材
    """
    service = MaterialService(db)
    user_id = current_user.id if owner else None
    items, total = await service.get_list(page, limit, category, user_id=user_id, exclude_category=exclude_category)
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
                # AI 模版包含 ai_meta（用于显示 prompt、参考图等）
                "ai_meta": m.ai_meta,
            }
            for m in items
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.get("/storage-usage")
async def get_storage_usage(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的存储使用情况"""
    service = MaterialService(db)
    total_size, file_count, total_items = await service.get_storage_usage(current_user.id)
    return ApiResponse(data={
        "used_bytes": total_size,
        "used_mb": round(total_size / (1024 * 1024), 2),
        "file_count": file_count,
        "total_items": total_items,
        "limit_bytes": 5 * 1024 * 1024 * 1024,  # 5GB
        "limit_mb": 5120,
        "percent": round(total_size / (5 * 1024 * 1024 * 1024) * 100, 1),
    })


@router.get("/{material_id}")
async def get_material(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取单个素材详情（用于编辑器加载设计稿）"""
    service = MaterialService(db)
    material = await service.get_by_id(material_id, user_id=current_user.id)
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
    target: str = Form(default="drafts", description="目标库: drafts 或 templates"),
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
    if content_type == "image/svg+xml":
        raise HTTPException(status_code=400, detail="当前不支持 SVG 上传")
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {content_type}",
        )

    subdir = "templates" if target == "templates" else "drafts"
    url = await storage.save(file_content, file.filename or "upload", content_type, subdir=subdir)
    category = "ai-template" if target == "templates" else None

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
        category=category,
        file_size=len(file_content),
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
    - tags: 标签列表
    """
    service = MaterialService(db)
    material = await service.update_design(
        material_id=material_id,
        name=data.get("name"),
        design_json=data.get("design_json"),
        thumbnail=data.get("thumbnail"),
        width=data.get("width"),
        height=data.get("height"),
        tags=data.get("tags"),
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
        "tags": material.tags,
    })


@router.post("/template")
async def save_template(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """保存 AI 生图结果到模版库

    请求体:
    - name: 模版名称
    - url: 生成图片的 URL（远程图片会自动下载到本地）
    - ai_meta: AI 生图元数据（包含 prompt, ref_images, model, size, style 等）
    - width: 图片宽度
    - height: 图片高度
    - tags: 标签列表
    """
    service = MaterialService(db)

    # 如果 URL 是远程的（http/https），先下载到本地
    image_url = data.get("url")
    if image_url and image_url.startswith(("http://", "https://")):
        try:
            content, filename, content_type = await _download_remote_image(image_url)
            local_url = await storage.save(content, filename, content_type, subdir="templates")
            image_url = local_url
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"下载图片失败: {e}")

    material = await service.create_template(
        name=data.get("name", "AI 模版"),
        url=image_url,
        ai_meta=data.get("ai_meta"),
        width=data.get("width"),
        height=data.get("height"),
        tags=data.get("tags"),
        user_id=current_user.id,
    )
    return ApiResponse(data={
        "id": material.id,
        "name": material.name,
        "type": material.type,
        "url": material.url,
        "width": material.width,
        "height": material.height,
        "ai_meta": material.ai_meta,
        "created_at": str(material.created_at),
    })


@router.post("/draft-ai")
async def save_ai_draft(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """保存 AI 生图结果到草稿箱（保留 ai_meta）"""
    service = MaterialService(db)

    image_url = data.get("url")
    if image_url and image_url.startswith(("http://", "https://")):
        try:
            content, filename, content_type = await _download_remote_image(image_url)
            local_url = await storage.save(content, filename, content_type, subdir="drafts")
            image_url = local_url
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"下载图片失败: {e}")

    material = await service.create_ai_draft(
        name=data.get("name", "AI 草稿"),
        url=image_url,
        ai_meta=data.get("ai_meta"),
        width=data.get("width"),
        height=data.get("height"),
        user_id=current_user.id,
    )
    return ApiResponse(data={
        "id": material.id,
        "name": material.name,
        "type": material.type,
        "url": material.url,
        "width": material.width,
        "height": material.height,
        "ai_meta": material.ai_meta,
        "created_at": str(material.created_at),
    })


@router.post("/{material_id}/download")
async def download_remote_image(
    material_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """下载远程图片到本地（用于过期链接重下载）

    请求体:
    - url: 远程图片 URL
    """
    service = MaterialService(db)
    material = await service.get_by_id(material_id, user_id=current_user.id)
    if not material:
        raise HTTPException(status_code=404, detail="素材不存在")

    remote_url = data.get("url") or material.url
    if not remote_url or not remote_url.startswith(("http://", "https://")):
        return ApiResponse(message="图片已保存在本地，无需重新下载", data={"url": material.url})

    content, filename, content_type = await _download_remote_image(remote_url)
    local_url = await storage.save(content, filename, content_type, subdir="templates")

    # 更新数据库记录
    material.url = local_url
    await db.commit()
    await db.refresh(material)

    return ApiResponse(message="图片已下载到本地", data={
        "id": material.id,
        "url": material.url,
    })


@router.put("/folders/{folder_name}")
async def rename_folder(
    folder_name: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """重命名模版文件夹

    请求体:
    - new_name: 新文件夹名称
    """
    new_name = data.get("new_name", "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="文件夹名称不能为空")

    service = MaterialService(db)
    count = await service.rename_folder(folder_name, new_name, current_user.id)
    return ApiResponse(message=f"已将 {count} 个素材移至「{new_name}」", data={"count": count})


@router.delete("/folders/{folder_name}")
async def delete_folder(
    folder_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除模版文件夹（仅移除标签，图片保留为未分类）"""
    service = MaterialService(db)
    result = await service.delete_folder(folder_name, current_user.id)
    return ApiResponse(
        message=f"已删除文件夹，{result['affected_count']} 个素材移至未分类",
        data=result,
    )
