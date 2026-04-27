"""AI 生图 API"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.ai_image import GenerateImageRequest, ImageTaskResponse, ModelInfo
from app.services.ai_image_service import AIImageService
from app.services.request_queue import image_generation_queue
from app.models.user import User
from app.core.deps import get_current_user
from app.core.security import decode_access_token

router = APIRouter()


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """尝试获取当前用户，无 token 时返回 None（不报错）"""
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    try:
        token = auth_header.split(" ", 1)[1]
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None
        result = await db.execute(select(User).where(User.id == int(user_id)))
        return result.scalar_one_or_none()
    except Exception:
        return None


@router.post("/generate", response_model=ApiResponse[ImageTaskResponse])
async def generate_image(
    req: GenerateImageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """生成图片（登录用户自动关联，匿名用户也可使用）"""
    try:
        service = AIImageService(model_name=req.model, db=db)
        result = await service.generate(
            prompt=req.prompt,
            params={
                "negative_prompt": req.negative_prompt,
                "width": req.width,
                "height": req.height,
                "style": req.style,
                "quality": req.quality,
                "image_data": req.image_data,
                "image_url": req.image_url,
                "images_data": req.images_data,
            },
            user_id=current_user.id if current_user else 0,
        )
        return ApiResponse(data=ImageTaskResponse(**result))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")


@router.get("/tasks/{task_id}", response_model=ApiResponse[ImageTaskResponse])
async def get_task_status(task_id: str, model: str = "seedream"):
    """查询任务状态"""
    service = AIImageService(model_name=model)
    result = await service.get_status(task_id)
    return ApiResponse(data=ImageTaskResponse(**result))


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, model: str = "seedream"):
    """取消任务"""
    service = AIImageService(model_name=model)
    await service.cancel(task_id)
    return ApiResponse(message="已取消")


@router.get("/history")
async def get_history(
    page: int = Query(default=1, ge=1, description="页码"),
    limit: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取生图历史"""
    service = AIImageService(db=db)
    items, total = await service.get_history(current_user.id, page, limit)
    return ApiResponse(data={
        "items": [
            {
                "id": t.id,
                "model_name": t.model_name,
                "prompt": t.prompt,
                "status": t.status,
                "result_urls": t.result_urls,
                "error": t.error,
                "elapsed_seconds": t.elapsed_seconds,
                "created_at": str(t.created_at),
                "finished_at": str(t.finished_at) if t.finished_at else None,
            }
            for t in items
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.get("/models", response_model=ApiResponse[list[ModelInfo]])
async def list_models():
    """列出可用模型"""
    models = AIImageService.list_available_models()
    return ApiResponse(data=[
        ModelInfo(
            id=m["id"],
            name=m["name"],
            description=m["description"],
            max_resolution={"width": 4096, "height": 4096},
            styles=[],
        )
        for m in models
    ])


@router.get("/queue/status")
async def get_queue_status_endpoint():
    """获取生图队列状态（用于监控排队情况）"""
    return ApiResponse(data=image_generation_queue.get_status())
