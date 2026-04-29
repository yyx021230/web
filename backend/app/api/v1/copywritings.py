"""文案库管理 API"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.services.copywriting_service import CopywritingService
from app.models.user import User
from app.core.deps import get_current_user

router = APIRouter()


@router.get("")
async def get_copywritings(
    page: int = 1,
    limit: int = 20,
    category: str | None = None,
    keyword: str | None = None,
    owner: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取文案列表"""
    service = CopywritingService(db)
    user_id = current_user.id if owner else None
    items, total = await service.get_list(page, limit, category, keyword, user_id=user_id)
    return ApiResponse(data={
        "items": [
            {
                "id": c.id,
                "title": c.title,
                "content": c.content,
                "tags": c.tags,
                "category": c.category,
                "created_at": str(c.created_at),
            }
            for c in items
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.get("/categories")
async def get_categories(
    db: AsyncSession = Depends(get_db),
):
    """获取所有分类及其数量"""
    service = CopywritingService(db)
    categories = await service.get_categories()
    return ApiResponse(data={"categories": categories})


@router.get("/{item_id}")
async def get_copywriting(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取单条文案"""
    service = CopywritingService(db)
    item = await service.get_by_id(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="文案不存在")
    return ApiResponse(data={
        "id": item.id,
        "title": item.title,
        "content": item.content,
        "tags": item.tags,
        "category": item.category,
        "created_at": str(item.created_at),
    })


@router.post("")
async def create_copywriting(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建文案"""
    service = CopywritingService(db)
    item = await service.create(
        title=data.get("title", ""),
        content=data.get("content", ""),
        user_id=current_user.id,
    )
    return ApiResponse(data={
        "id": item.id,
        "title": item.title,
        "category": item.category,
        "tags": item.tags,
    })


@router.put("/{item_id}")
async def update_copywriting(
    item_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新文案"""
    service = CopywritingService(db)
    item = await service.update(
        item_id,
        title=data.get("title"),
        content=data.get("content"),
        user_id=current_user.id,
    )
    if not item:
        raise HTTPException(status_code=404, detail="文案不存在或无权操作")
    return ApiResponse(data={
        "id": item.id,
        "title": item.title,
        "content": item.content,
        "tags": item.tags,
        "category": item.category,
    })


@router.delete("/{item_id}")
async def delete_copywriting(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除文案"""
    service = CopywritingService(db)
    deleted = await service.delete(item_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="文案不存在或无权操作")
    return ApiResponse(message="已删除")


@router.post("/import")
async def import_copywritings(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """从 Excel 文件批量导入文案"""
    import openpyxl
    import re

    content = await file.read()
    wb = openpyxl.load_workbook(filename=__import__("io").BytesIO(content))
    ws = wb.active

    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        raw = row[0]
        if not raw or not str(raw).strip():
            continue
        text = str(raw).strip()
        # 提取标题：首行（以换行分割的第一行）
        first_line = text.split("\n")[0].strip()
        # 如果首行以"标题："开头，去掉前缀
        if first_line.startswith("标题："):
            title = first_line[3:].strip()
        elif first_line.startswith("标题:"):
            title = first_line[3:].strip()
        else:
            title = first_line
        # 内容：整段文本
        content_text = text

        if not title or not content_text:
            continue

        rows.append({"title": title, "content": content_text})

    service = CopywritingService(db)
    count = await service.bulk_import(rows, user_id=current_user.id)
    return ApiResponse(message=f"成功导入 {count} 条文案", data={"count": count})
