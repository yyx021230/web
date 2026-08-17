"""AI 生图 API"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.ai_image import (
    AIImageRuntimeConfig,
    ActiveImageTasksResponse,
    GenerateImageRequest,
    ImageTaskResponse,
    ModelInfo,
)
from app.services.ai_image_service import AIImageService
from app.services.request_queue import image_generation_queue
from app.services.ai_task_queue import ai_image_task_queue
from app.models.user import User
from app.core.deps import get_current_user, require_admin
from app.core.roles import has_role

router = APIRouter()


@router.post("/generate", response_model=ApiResponse[ImageTaskResponse])
async def generate_image(
    req: GenerateImageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交生图任务（需登录）"""
    try:
        service = AIImageService(model_name=req.model, db=db)
        result = await service.submit(
            prompt=req.prompt,
            client_request_id=req.client_request_id,
            params={
                "negative_prompt": req.negative_prompt,
                "width": req.width,
                "height": req.height,
                "style": req.style,
                "quality": req.quality,
                "count": req.count,
                "image_data": req.image_data,
                "image_url": req.image_url,
                "images_data": req.images_data,
            },
            user_id=current_user.id,
        )
        return ApiResponse(data=ImageTaskResponse(**result))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")


@router.get("/active", response_model=ApiResponse[ActiveImageTasksResponse])
async def get_active_tasks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户正在排队/处理中的生图任务"""
    service = AIImageService(db=db)
    result = await service.get_active_tasks(current_user.id)
    return ApiResponse(data=ActiveImageTasksResponse(**result))


@router.get("/runtime-config", response_model=ApiResponse[AIImageRuntimeConfig])
async def get_runtime_config():
    """获取前端轮询和后端任务超时配置。"""
    return ApiResponse(data=AIImageRuntimeConfig(
        task_timeout_seconds=AIImageService._task_timeout_seconds(),
        poll_interval_seconds=2,
    ))


@router.get("/requests/{client_request_id}", response_model=ApiResponse[ImageTaskResponse])
async def get_task_by_client_request_id(
    client_request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """通过前端请求幂等 ID 找回本用户的生图任务。"""
    service = AIImageService(db=db)
    result = await service.get_task_by_client_request_id(current_user.id, client_request_id)
    if result is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return ApiResponse(data=ImageTaskResponse(**result))


@router.get("/tasks/{task_id}", response_model=ApiResponse[ImageTaskResponse])
async def get_task_status(
    task_id: str,
    model: str = "seedream",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询当前用户任务状态"""
    if task_id.isdigit():
        service = AIImageService(model_name=model, db=db)
        local = await service.get_local_task_status(
            int(task_id),
            user_id=current_user.id,
            allow_any_user=has_role(current_user, "admin"),
        )
        if local is not None:
            return ApiResponse(data=ImageTaskResponse(**local))
    raise HTTPException(status_code=404, detail="任务不存在")


@router.get("/tasks/{task_id}/wait", response_model=ApiResponse[ImageTaskResponse])
async def wait_for_task(
    task_id: str,
    model: str = "seedream",
    timeout_seconds: int = Query(default=540, ge=1, le=600),
    poll_seconds: int = Query(default=2, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """等待异步生图任务进入终态，供工作流在同一次运行中继续做成图质检。"""
    if not task_id.isdigit():
        raise HTTPException(status_code=404, detail="任务不存在")
    service = AIImageService(model_name=model, db=db)
    current_user_id = current_user.id
    allow_any_user = has_role(current_user, "admin")
    loop = asyncio.get_running_loop()
    # Dify 1.14.x 的 HTTP 节点单次读取会在约 30 秒被代理中断。
    # 将一次长等待拆成不超过 20 秒的可重试短轮询：终态返回 200，
    # 尚未完成返回 503，由工作流节点的 retry_config 继续请求。
    attempt_timeout_seconds = min(timeout_seconds, 20)
    deadline = loop.time() + attempt_timeout_seconds
    while True:
        db.expire_all()
        result = await service.get_local_task_status(
            int(task_id),
            user_id=current_user_id,
            allow_any_user=allow_any_user,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if result.get("status") in {"completed", "failed", "cancelled"}:
            return ApiResponse(data=ImageTaskResponse(**result))
        if loop.time() >= deadline:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "AI_IMAGE_TASK_PROCESSING",
                    "message": "任务仍在处理中，请重试",
                    "task_id": task_id,
                    "status": result.get("status"),
                },
            )
        await asyncio.sleep(min(poll_seconds, max(0.1, deadline - loop.time())))


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    model: str = "seedream",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """取消任务"""
    service = AIImageService(model_name=model, db=db)
    try:
        await service.cancel(task_id, user_id=current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return ApiResponse(message="已取消")


@router.get("/history")
async def get_history(
    page: int = Query(default=1, ge=1, description="页码"),
    limit: int = Query(default=60, ge=1, le=100, description="每页数量"),
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
                "client_request_id": t.client_request_id,
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
async def get_queue_status_endpoint(current_user: User = Depends(require_admin)):
    """获取生图队列状态（管理员监控）"""
    _ = current_user
    queue_status = await ai_image_task_queue.get_status()
    return ApiResponse(
        data={
            **queue_status,
            "local_fallback": image_generation_queue.get_status(),
        }
    )
