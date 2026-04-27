"""车型库 API - 只读公共数据"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.schemas.common import ApiResponse

router = APIRouter()

# 加载车型数据
_DATA_FILE = Path(__file__).parent.parent.parent / "data" / "car_models.json"

def _load_data() -> dict:
    with open(_DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


@router.get("/brands", response_model=ApiResponse[list[str]])
async def get_brands():
    """获取所有品牌列表"""
    data = _load_data()
    return ApiResponse(data=sorted(data.keys()))


@router.get("/models", response_model=ApiResponse[dict[str, list[str]]])
async def get_models(
    brand: Optional[str] = Query(None, description="品牌名称，不传则返回全部"),
):
    """获取指定品牌的车型列表"""
    data = _load_data()
    if brand:
        if brand not in data:
            raise HTTPException(status_code=404, detail=f"品牌不存在: {brand}")
        return ApiResponse(data={brand: sorted(data[brand].keys())})
    return ApiResponse(data={b: sorted(v.keys()) for b, v in data.items()})


@router.get("/images", response_model=ApiResponse[dict])
async def get_car_images(
    brand: str = Query(..., description="品牌"),
    model: Optional[str] = Query(None, description="车型，不传则返回该品牌下所有车型图片"),
):
    """获取指定车型的图片（5角度），不传model则返回品牌下所有车型"""
    data = _load_data()
    if brand not in data:
        raise HTTPException(status_code=404, detail=f"品牌不存在: {brand}")

    if not model or model == 'all':
        # 返回该品牌下所有车型图片
        all_images = []
        for model_name, images in data[brand].items():
            for img in images:
                all_images.append({
                    **img,
                    "model": model_name,
                })
        return ApiResponse(data={
            "brand": brand,
            "model": "all",
            "images": all_images,
        })

    if model not in data[brand]:
        raise HTTPException(status_code=404, detail=f"车型不存在: {brand} - {model}")

    images = data[brand][model]
    return ApiResponse(data={
        "brand": brand,
        "model": model,
        "images": images,
    })


@router.get("/all", response_model=ApiResponse[dict])
async def get_all_data():
    """获取完整车型数据（适合初始化加载）"""
    return ApiResponse(data=_load_data())
