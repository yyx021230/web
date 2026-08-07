"""车型库 API - 只读公共数据"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.services.vehicle_catalog_service import VehicleCatalogService
from app.services.vehicle_model_image_service import VehicleModelImageService

router = APIRouter()


@router.get("/brands", response_model=ApiResponse[list[str]])
async def get_brands(db: AsyncSession = Depends(get_db)):
    """获取所有品牌列表"""
    return ApiResponse(data=await VehicleModelImageService(db).brands())


@router.get("/models", response_model=ApiResponse[dict[str, list[str]]])
async def get_models(
    brand: Optional[str] = Query(None, description="品牌名称，不传则返回全部"),
    db: AsyncSession = Depends(get_db),
):
    """获取指定品牌的车型列表"""
    data = await VehicleModelImageService(db).models(brand)
    if brand:
        if not data:
            raise HTTPException(status_code=404, detail=f"品牌不存在: {brand}")
    return ApiResponse(data=data)


@router.get("/images", response_model=ApiResponse[dict])
async def get_car_images(
    brand: str = Query(..., description="品牌"),
    model: Optional[str] = Query(None, description="车型，不传则返回该品牌下所有车型图片"),
    db: AsyncSession = Depends(get_db),
):
    """获取指定车型的图片（5角度），不传model则返回品牌下所有车型"""
    service = VehicleModelImageService(db)
    models = await service.models(brand)
    if brand not in models:
        raise HTTPException(status_code=404, detail=f"品牌不存在: {brand}")
    if model and model != "all" and model not in models.get(brand, []):
        raise HTTPException(status_code=404, detail=f"车型不存在: {brand} - {model}")
    images = await service.images(brand, model)
    if not model or model == "all":
        return ApiResponse(data={
            "brand": brand,
            "model": "all",
            "images": images,
        })
    return ApiResponse(data={
        "brand": brand,
        "model": model,
        "images": images,
    })


@router.get("/all", response_model=ApiResponse[dict])
async def get_all_data(db: AsyncSession = Depends(get_db)):
    """获取完整车型数据（适合初始化加载）"""
    return ApiResponse(data=await VehicleModelImageService(db).all_data())


@router.get("/vehicle-catalog", response_model=ApiResponse[list[dict]])
async def get_vehicle_catalog(db: AsyncSession = Depends(get_db)):
    """获取数据库中的品牌/车型基础词库。"""
    rows = await VehicleCatalogService(db).rows()
    return ApiResponse(data=rows)
