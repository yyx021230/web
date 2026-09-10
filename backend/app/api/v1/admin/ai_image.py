from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.db.session import async_session, get_db
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.ai_image_provider import (
    AIImageProviderCreate,
    AIImageProviderHealthResponse,
    AIImageProviderInfo,
    AIImageProviderTestRequest,
    AIImageProviderTestResponse,
    AIImageProviderUpdate,
)
from app.services.ai_image_provider_service import AIImageProviderService

router = APIRouter()


async def _run_provider_test_task(task_id: int) -> None:
    async with async_session() as db:
        await AIImageProviderService(db).execute_provider_test_task(task_id)


def _serialize_provider(provider) -> AIImageProviderInfo:
    runtime = AIImageProviderService.provider_runtime(provider)
    return AIImageProviderInfo(
        id=provider.id,
        name=provider.name,
        model_name=provider.model_name,
        provider_kind=provider.provider_kind,
        provider_model=provider.provider_model,
        endpoint_url=provider.endpoint_url,
        api_key_prefix=provider.api_key[:8] + "..." if provider.api_key else "",
        is_enabled=provider.is_enabled,
        is_default=provider.is_default,
        priority=provider.priority,
        weight=provider.weight,
        supports_text_input=provider.supports_text_input,
        supports_image_input=provider.supports_image_input,
        config=provider.config or {},
        last_health_status=provider.last_health_status,
        last_health_error=provider.last_health_error,
        last_checked_at=provider.last_checked_at.isoformat() if provider.last_checked_at else None,
        last_used_at=provider.last_used_at.isoformat() if provider.last_used_at else None,
        success_count=provider.success_count or 0,
        failure_count=provider.failure_count or 0,
        avg_latency_ms=provider.avg_latency_ms,
        current_running=runtime["current_running"],
        max_concurrent=runtime["max_concurrent"],
        created_by=provider.created_by,
        created_at=provider.created_at.isoformat() if provider.created_at else None,
        updated_at=provider.updated_at.isoformat() if provider.updated_at else None,
    )


@router.get("/providers")
async def admin_list_ai_image_providers(
    model_name: str | None = Query(default="gptimage2"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    service = AIImageProviderService(db)
    if model_name == "gptimage2":
        await service.ensure_default_providers(created_by=current_user.id)
    providers = await service.list_providers(model_name)
    return ApiResponse(data=[_serialize_provider(p).model_dump() for p in providers])


@router.post("/providers")
async def admin_create_ai_image_provider(
    req: AIImageProviderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    service = AIImageProviderService(db)
    provider = await service.create_provider(req.model_dump(), created_by=current_user.id)
    return ApiResponse(data=_serialize_provider(provider).model_dump())


@router.put("/providers/{provider_id}")
async def admin_update_ai_image_provider(
    provider_id: int,
    req: AIImageProviderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    service = AIImageProviderService(db)
    provider = await service.update_provider(provider_id, req.model_dump(exclude_unset=True))
    if not provider:
        raise HTTPException(status_code=404, detail="生图入口不存在")
    return ApiResponse(data=_serialize_provider(provider).model_dump())


@router.post("/providers/{provider_id}/default")
async def admin_set_default_ai_image_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    service = AIImageProviderService(db)
    provider = await service.set_default_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="生图入口不存在")
    return ApiResponse(data=_serialize_provider(provider).model_dump())


@router.delete("/providers/{provider_id}")
async def admin_delete_ai_image_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    service = AIImageProviderService(db)
    deleted = await service.delete_provider(provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="生图入口不存在")
    return ApiResponse(message="已删除")


@router.post("/providers/{provider_id}/enable")
async def admin_enable_ai_image_provider(
    provider_id: int,
    req: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    service = AIImageProviderService(db)
    provider = await service.toggle_provider(provider_id, bool(req.get("is_enabled", True)))
    if not provider:
        raise HTTPException(status_code=404, detail="生图入口不存在")
    return ApiResponse(data=_serialize_provider(provider).model_dump())


@router.post("/providers/{provider_id}/health-check")
async def admin_check_ai_image_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    service = AIImageProviderService(db)
    result = await service.health_check(provider_id)
    return ApiResponse(data=AIImageProviderHealthResponse(**result).model_dump())


@router.post("/providers/{provider_id}/test")
async def admin_test_ai_image_provider(
    provider_id: int,
    req: AIImageProviderTestRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    service = AIImageProviderService(db)
    params = {
        "width": req.width,
        "height": req.height,
        "count": req.count,
    }
    if req.quality:
        params["quality"] = req.quality
    if req.image_data:
        params["image_data"] = req.image_data
        # 管理员诊断要能测试被临时停用分流的图片编辑接口。
        params["_provider_test_force_image_edit"] = True
    result = await service.submit_provider_test(provider_id, req.prompt, params, user_id=current_user.id)
    if not result:
        raise HTTPException(status_code=404, detail="生图入口不存在")
    background_tasks.add_task(_run_provider_test_task, int(result["task_id"]))
    return ApiResponse(data=AIImageProviderTestResponse(**result).model_dump())


@router.get("/providers/test-tasks/{task_id}")
async def admin_get_ai_image_provider_test_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    service = AIImageProviderService(db)
    result = await service.get_provider_test_status(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="测试任务不存在")
    return ApiResponse(data=AIImageProviderTestResponse(**result).model_dump())


@router.post("/providers/health-check")
async def admin_check_ai_image_providers(
    model_name: str | None = Query(default="gptimage2"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    service = AIImageProviderService(db)
    providers = await service.list_providers(model_name)
    results = []
    for provider in providers:
        results.append(await service.health_check(provider.id))
    return ApiResponse(data=results)
