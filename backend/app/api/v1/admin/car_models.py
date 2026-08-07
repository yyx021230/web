"""Admin car models management API"""
from __future__ import annotations

import base64
import asyncio
import io
import json
import logging
import mimetypes
import os
import re
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

import oss2

from app.adapters.ai_model.gptimage2 import GPTImage2Adapter
from app.adapters.storage import get_storage
from app.config import settings
from app.core.deps import require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse
from app.services.vehicle_model_image_service import VehicleModelImageService

router = APIRouter()
logger = logging.getLogger(__name__)

_OCR_TOKEN_CACHE: dict[str, float | str] = {"token": "", "expires_at": 0.0}
_CANONICAL_ANGLES = ["正前方", "斜前方", "侧面", "斜后方", "正后方"]
_ANGLE_ALIASES: list[tuple[str, str]] = [
    ("正前方", "正前方"),
    ("斜前方", "斜前方"),
    ("斜后方", "斜后方"),
    ("正后方", "正后方"),
    ("正前", "正前方"),
    ("斜前", "斜前方"),
    ("前45", "斜前方"),
    ("45前", "斜前方"),
    ("前侧", "斜前方"),
    ("侧面", "侧面"),
    ("侧", "侧面"),
    ("斜后", "斜后方"),
    ("后45", "斜后方"),
    ("45后", "斜后方"),
    ("后侧", "斜后方"),
    ("正后", "正后方"),
    ("前脸", "正前方"),
    ("车头", "正前方"),
    ("车尾", "正后方"),
    ("front", "正前方"),
    ("rear", "正后方"),
    ("tail", "正后方"),
    ("side", "侧面"),
    ("left", "侧面"),
    ("right", "侧面"),
]
_ALLOWED_IMPORT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_OCR_KEYWORDS = ["易车", "懂车帝"]
_GPT_IMAGE2_CLEAN_PROMPT = (
    "Remove only the visible license plate, watermark text, or watermark logo from this car photo. "
    "Do not change the car body, wheels, color, reflections, background, perspective, composition, lighting, "
    "or any other detail. Keep everything else identical."
)
_ANGLE_FILE_BASENAMES = {
    "正前方": "正前",
    "斜前方": "斜前",
    "侧面": "侧面",
    "斜后方": "斜后",
    "正后方": "正后",
}


class CarImageItem(BaseModel):
    label: str = Field(..., min_length=1, max_length=50, description="角度标签")
    url: str = Field(..., min_length=1, description="图片 URL")

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        url = value.strip()
        if not url:
            raise ValueError("图片 URL 不能为空")
        if url.startswith("/uploads/"):
            return url
        if url.startswith("http://") or url.startswith("https://"):
            return url
        raise ValueError("图片 URL 必须是 http(s) 地址或 /uploads/ 相对路径")


class UpdateCarModelRequest(BaseModel):
    brand: str = Field(..., min_length=1, max_length=100, description="品牌")
    model: str = Field(..., min_length=1, max_length=100, description="车型")
    images: list[CarImageItem] = Field(..., min_length=1, max_length=20, description="车型图片列表")


class ImportFolderSummary(BaseModel):
    brand: str
    model: str
    already_cleaned: bool
    clean_method: str | None
    overwrite: bool
    imported_angles: list[str]
    missing_angles: list[str]
    warnings: list[str]
    images: list[CarImageItem]


class DeleteCarModelRequest(BaseModel):
    brand: str = Field(..., min_length=1, max_length=100, description="品牌")
    model: str = Field(..., min_length=1, max_length=100, description="车型")


class DeleteCarModelImageRequest(BaseModel):
    brand: str = Field(..., min_length=1, max_length=100, description="品牌")
    model: str = Field(..., min_length=1, max_length=100, description="车型")
    label: str = Field(..., min_length=1, max_length=50, description="角度标签")
    url: str = Field(..., min_length=1, description="图片 URL")


def _validate_data(data: Any) -> dict[str, dict[str, list[dict[str, str]]]]:
    if not isinstance(data, dict):
        raise ValueError("车型库顶层必须是对象")

    normalized: dict[str, dict[str, list[dict[str, str]]]] = {}
    for brand, models in data.items():
        if not isinstance(brand, str) or not brand.strip():
            raise ValueError("品牌名称不能为空")
        if not isinstance(models, dict):
            raise ValueError(f"品牌 {brand} 的车型列表必须是对象")

        normalized_models: dict[str, list[dict[str, str]]] = {}
        for model, images in models.items():
            if not isinstance(model, str) or not model.strip():
                raise ValueError(f"品牌 {brand} 下存在空车型名")
            if not isinstance(images, list):
                raise ValueError(f"车型 {brand} / {model} 的图片列表必须是数组")

            normalized_images: list[dict[str, str]] = []
            for idx, image in enumerate(images):
                if not isinstance(image, dict):
                    raise ValueError(f"车型 {brand} / {model} 的第 {idx + 1} 条图片必须是对象")
                label = str(image.get("label") or "").strip()
                url = str(image.get("url") or "").strip()
                if not label or not url:
                    raise ValueError(f"车型 {brand} / {model} 的第 {idx + 1} 条图片缺少 label 或 url")
                normalized_images.append({"label": label, "url": url})
            normalized_models[model.strip()] = normalized_images

        normalized[brand.strip()] = normalized_models
    return normalized

async def _delete_storage_url_if_possible(url: str) -> None:
    cleaned = url.strip()
    if not cleaned:
        return
    if cleaned.startswith("/uploads/"):
        try:
            await get_storage().delete(cleaned)
        except Exception:
            return
        return

    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        storage = get_storage()
        if settings.storage_type in {"s3", "minio"} and settings.s3_endpoint and f"{settings.s3_endpoint}/{settings.s3_bucket}/" in cleaned:
            try:
                await storage.delete(cleaned)
            except Exception:
                return

    bucket = _get_car_model_oss_bucket()
    object_key = _car_model_oss_key_from_url(cleaned)
    if object_key:
        try:
            await _delete_car_model_oss_object(bucket, object_key)
        except Exception:
            return


def _normalize_key(text: str) -> str:
    return re.sub(r"[\s_\-.]+", "", text.strip().lower())


def _detect_angle(filename: str) -> str | None:
    stem = _normalize_key(Path(filename).stem)
    for alias, label in _ANGLE_ALIASES:
        if _normalize_key(alias) in stem:
            return label
    return None


def _slugify(value: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value.strip(), flags=re.UNICODE)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "car-model"


def _get_car_model_oss_bucket() -> oss2.Bucket:
    if not settings.car_model_oss_access_key_id or not settings.car_model_oss_access_key_secret:
        raise HTTPException(
            status_code=400,
            detail="未配置车型库 OSS 鉴权，请先设置 CAR_MODEL_OSS_ACCESS_KEY_ID / SECRET",
        )
    auth = oss2.Auth(settings.car_model_oss_access_key_id, settings.car_model_oss_access_key_secret)
    return oss2.Bucket(auth, settings.car_model_oss_endpoint, settings.car_model_oss_bucket)


def _car_model_oss_public_url(object_key: str) -> str:
    endpoint_host = settings.car_model_oss_endpoint.replace("https://", "").replace("http://", "").rstrip("/")
    return f"https://{settings.car_model_oss_bucket}.{endpoint_host}/{object_key}"


def _car_model_oss_key_from_url(url: str) -> str | None:
    endpoint_host = settings.car_model_oss_endpoint.replace("https://", "").replace("http://", "").rstrip("/")
    prefixes = [
        f"https://{settings.car_model_oss_bucket}.{endpoint_host}/",
        f"http://{settings.car_model_oss_bucket}.{endpoint_host}/",
    ]
    for prefix in prefixes:
        if url.startswith(prefix):
            return url[len(prefix):]
    return None


async def _upload_car_model_to_oss(
    *,
    bucket: oss2.Bucket,
    object_key: str,
    content: bytes,
    content_type: str,
) -> str:
    await asyncio.to_thread(
        bucket.put_object,
        object_key,
        content,
        headers={"Content-Type": content_type or "application/octet-stream"},
    )
    return _car_model_oss_public_url(object_key)


async def _delete_car_model_oss_object(bucket: oss2.Bucket, object_key: str) -> None:
    await asyncio.to_thread(bucket.delete_object, object_key)


def _guess_content_type(filename: str, upload_content_type: str | None) -> str:
    if upload_content_type and upload_content_type.startswith("image/"):
        return upload_content_type
    guessed, _ = mimetypes.guess_type(filename)
    if guessed and guessed.startswith("image/"):
        return guessed
    return "image/jpeg"


def _validate_image_bytes(file_name: str, content: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(content))
        image.load()
        return image.convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无法解析图片文件: {file_name}") from exc


async def _get_baidu_access_token() -> str:
    if not settings.car_model_ocr_baidu_api_key or not settings.car_model_ocr_baidu_secret_key:
        raise HTTPException(status_code=400, detail="未配置车型 OCR 百度鉴权，请先设置 CAR_MODEL_OCR_BAIDU_API_KEY / SECRET_KEY")

    now = time.time()
    cached = str(_OCR_TOKEN_CACHE.get("token") or "")
    expires_at = float(_OCR_TOKEN_CACHE.get("expires_at") or 0.0)
    if cached and now < expires_at:
        return cached

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            "https://aip.baidubce.com/oauth/2.0/token",
            params={
                "grant_type": "client_credentials",
                "client_id": settings.car_model_ocr_baidu_api_key,
                "client_secret": settings.car_model_ocr_baidu_secret_key,
            },
        )
    resp.raise_for_status()
    data = resp.json()
    token = str(data.get("access_token") or "")
    if not token:
        raise HTTPException(status_code=400, detail="百度 OCR 获取 access_token 失败")
    _OCR_TOKEN_CACHE["token"] = token
    _OCR_TOKEN_CACHE["expires_at"] = now + max(int(data.get("expires_in") or 2592000) - 300, 60)
    return token


async def _baidu_ocr_detect(image: Image.Image) -> list[dict[str, Any]]:
    token = await _get_baidu_access_token()
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=92)
    image_bytes = buf.getvalue()
    encoded = base64.b64encode(image_bytes).decode("utf-8")

    async with httpx.AsyncClient(timeout=40.0) as client:
        resp = await client.post(
            f"https://aip.baidubce.com/rest/2.0/ocr/v1/accurate?access_token={token}",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={
                "image": encoded,
                "detect_direction": "false",
                "detect_language": "false",
            },
        )
    resp.raise_for_status()
    result = resp.json()
    if "error_code" in result:
        raise HTTPException(status_code=400, detail=f"OCR 检测失败: {result.get('error_msg') or result['error_code']}")

    parsed: list[dict[str, Any]] = []
    for item in result.get("words_result", []):
        text = str(item.get("words") or "").strip()
        if not text:
            continue
        loc = item.get("location") or {}
        x0 = int(loc.get("left") or 0)
        y0 = int(loc.get("top") or 0)
        width = int(loc.get("width") or 0)
        height = int(loc.get("height") or 0)
        x1 = x0 + width
        y1 = y0 + height
        if x1 <= x0 or y1 <= y0:
            continue
        probability = item.get("probability") or {}
        score = float(probability.get("average") or 1.0)
        parsed.append({"text": text, "score": score, "bbox": (x0, y0, x1, y1)})
    return parsed


def _left_extend_for_filename(filename: str) -> int:
    stem = Path(filename).stem
    if "正前" in stem or "正后" in stem:
        return 44
    return 24


def _watermark_bboxes(ocr_items: Iterable[dict[str, Any]], keywords: list[str]) -> list[tuple[int, int, int, int]]:
    bboxes: list[tuple[int, int, int, int]] = []
    for item in ocr_items:
        text = str(item.get("text") or "").lower()
        if any(keyword.lower() in text for keyword in keywords):
            bbox = item.get("bbox")
            if isinstance(bbox, tuple) and len(bbox) == 4:
                bboxes.append(bbox)
    return bboxes


def _erase_watermark_with_fill(
    image: Image.Image,
    bboxes: list[tuple[int, int, int, int]],
    *,
    filename: str,
    dilate_pixels: int = 8,
) -> Image.Image:
    source = np.array(image.convert("RGB"))
    height, width = source.shape[:2]
    mask = np.zeros((height, width), dtype=bool)
    left_extend = _left_extend_for_filename(filename)

    for x0, y0, x1, y1 in bboxes:
        x0e = max(0, x0 - dilate_pixels - left_extend)
        y0e = max(0, y0 - dilate_pixels)
        x1e = min(width, x1 + dilate_pixels)
        y1e = min(height, y1 + dilate_pixels)
        mask[y0e:y1e, x0e:x1e] = True

    result = source.copy()
    result[mask] = np.array([255, 255, 255], dtype=np.uint8)
    return Image.fromarray(result)


async def _clean_with_ocr(content: bytes, *, filename: str) -> bytes:
    image = _validate_image_bytes(filename, content)
    ocr_items = await _baidu_ocr_detect(image)
    bboxes = _watermark_bboxes(ocr_items, _OCR_KEYWORDS)
    if not bboxes:
        return content

    cleaned = _erase_watermark_with_fill(image, bboxes, filename=filename)
    output = io.BytesIO()
    ext = Path(filename).suffix.lower()
    if ext in {".png", ".webp"}:
        cleaned.save(output, format="PNG")
    else:
        cleaned.save(output, format="JPEG", quality=96)
    return output.getvalue()


async def _clean_with_gpt_image2(content: bytes, *, filename: str, content_type: str) -> bytes:
    adapter = GPTImage2Adapter()
    encoded = base64.b64encode(content).decode("utf-8")
    source = f"data:{content_type};base64,{encoded}"
    image = _validate_image_bytes(filename, content)
    result = await adapter.generate_image(
        prompt=_GPT_IMAGE2_CLEAN_PROMPT,
        image_data=source,
        width=image.width,
        height=image.height,
        count=1,
    )
    image_urls = result.get("image_urls") or []
    if not image_urls:
        raise HTTPException(status_code=400, detail=result.get("error") or "GPT Image 2 去水印失败")

    image_url = str(image_urls[0])
    if image_url.startswith("data:"):
        _, b64_data = image_url.split(",", 1)
        return base64.b64decode(b64_data)

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.get(image_url)
    resp.raise_for_status()
    return resp.content


async def _store_car_model_image(
    *,
    bucket: oss2.Bucket,
    brand: str,
    model: str,
    angle: str,
    content: bytes,
    filename: str,
    content_type: str,
) -> dict[str, str]:
    ext = Path(filename).suffix.lower() or ".jpg"
    basename = _ANGLE_FILE_BASENAMES.get(angle, _slugify(angle))
    object_key = f"{settings.car_model_oss_prefix.strip('/')}/{brand.strip()}/{model.strip()}/{basename}{ext}"
    url = await _upload_car_model_to_oss(
        bucket=bucket,
        object_key=object_key,
        content=content,
        content_type=content_type,
    )
    return {"label": angle, "url": url}


async def _collect_import_files(files: list[UploadFile]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    by_angle: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    for upload in files:
        if not upload.filename:
            continue
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in _ALLOWED_IMPORT_EXTENSIONS:
            warnings.append(f"已跳过非图片文件: {upload.filename}")
            continue
        angle = _detect_angle(upload.filename)
        if not angle:
            warnings.append(f"未识别角度，已跳过: {upload.filename}")
            continue
        if angle in by_angle:
            raise HTTPException(status_code=400, detail=f"检测到重复角度文件: {angle}")
        content = await upload.read()
        if not content:
            warnings.append(f"空文件已跳过: {upload.filename}")
            continue
        _validate_image_bytes(upload.filename, content)
        by_angle[angle] = {
            "filename": upload.filename,
            "content_type": _guess_content_type(upload.filename, upload.content_type),
            "content": content,
        }

    if not by_angle:
        raise HTTPException(status_code=400, detail="未识别到可导入的车型图片，请检查文件夹内图片命名")
    return by_angle, warnings


def _ordered_images(images: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    return [images[angle] for angle in _CANONICAL_ANGLES if angle in images]


@router.get("/all")
async def get_all_car_models(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _ = current_user
    return ApiResponse(data=await VehicleModelImageService(db).all_data())


@router.get("/export")
async def export_car_models_json(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _ = current_user
    data = await VehicleModelImageService(db).all_data()
    filename = f"car_models_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.put("/model")
async def update_car_model_images(
    req: UpdateCarModelRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _ = current_user
    try:
        await VehicleModelImageService(db).update_model_images(
            req.brand,
            req.model,
            [img.model_dump() for img in req.images],
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"车型不存在: {req.brand} - {req.model}")
    return ApiResponse(message="车型图片已更新")


@router.delete("/model")
async def delete_car_model(
    req: DeleteCarModelRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _ = current_user
    try:
        existing_model_name, images = await VehicleModelImageService(db).delete_model(req.brand, req.model)
    except KeyError as exc:
        message = str(exc).strip("'")
        if message == "brand_not_found":
            raise HTTPException(status_code=404, detail=f"品牌不存在: {req.brand}") from None
        raise HTTPException(status_code=404, detail=f"车型不存在: {req.brand} - {req.model}") from None

    for item in images:
        await _delete_storage_url_if_possible(str(item.get("url") or ""))

    return ApiResponse(
        message="车型已删除",
        data={
            "brand": req.brand,
            "model": existing_model_name,
            "deleted_images": len(images),
            "backup_file": "database",
        },
    )


@router.delete("/model/image")
async def delete_car_model_image(
    req: DeleteCarModelImageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _ = current_user
    try:
        remaining_images = await VehicleModelImageService(db).delete_image(req.brand, req.model, req.label, req.url)
    except ValueError as exc:
        if str(exc) == "last_image":
            raise HTTPException(status_code=400, detail="当前车型只剩最后一张图片，请直接删除车型") from None
        raise
    except KeyError as exc:
        message = str(exc).strip("'")
        if message == "brand_not_found":
            raise HTTPException(status_code=404, detail=f"品牌不存在: {req.brand}") from None
        if message == "model_not_found":
            raise HTTPException(status_code=404, detail=f"车型不存在: {req.brand} - {req.model}") from None
        raise HTTPException(status_code=404, detail="未找到要删除的车型图片") from None

    await _delete_storage_url_if_possible(req.url)

    return ApiResponse(
        message="车型图片已删除",
        data={
            "brand": req.brand,
            "model": req.model,
            "images": remaining_images,
            "backup_file": "database",
        },
    )


@router.post("/import-folder")
async def import_car_model_folder(
    brand: str = Form(...),
    model: str = Form(...),
    already_cleaned: bool = Form(...),
    clean_method: str = Form("ocr"),
    overwrite: bool = Form(False),
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _ = (db, current_user)
    brand = brand.strip()
    model = model.strip()
    clean_method = clean_method.strip().lower()
    if not brand or not model:
        raise HTTPException(status_code=400, detail="品牌和车型名称不能为空")
    if not already_cleaned and clean_method not in {"ocr", "gptimage2"}:
        raise HTTPException(status_code=400, detail="未去水印时必须选择 OCR 或 GPT Image 2")

    try:
        source_files, warnings = await _collect_import_files(files)
        service = VehicleModelImageService(db)
        existing_model_name = await service.find_existing_model_name(brand, model)
        target_model_name = existing_model_name or model
        if existing_model_name and not overwrite:
            raise HTTPException(status_code=400, detail=f"车型已存在: {brand} - {existing_model_name}，如需替换请勾选覆盖")

        imported_images: dict[str, dict[str, str]] = {}
        bucket = _get_car_model_oss_bucket()
        for angle, payload in source_files.items():
            raw_bytes = payload["content"]
            content_type = str(payload["content_type"])
            file_name = str(payload["filename"])

            if already_cleaned:
                final_bytes = raw_bytes
            elif clean_method == "ocr":
                final_bytes = await _clean_with_ocr(raw_bytes, filename=file_name)
            else:
                final_bytes = await _clean_with_gpt_image2(raw_bytes, filename=file_name, content_type=content_type)

            imported_images[angle] = await _store_car_model_image(
                bucket=bucket,
                brand=brand,
                model=target_model_name,
                angle=angle,
                content=final_bytes,
                filename=file_name,
                content_type=content_type,
            )

        ordered_images = _ordered_images(imported_images)
        await service.upsert_model_images(brand, target_model_name, ordered_images)
    except HTTPException as exc:
        logger.warning(
            "car model folder import rejected: brand=%r model=%r files=%s already_cleaned=%s clean_method=%s overwrite=%s detail=%s",
            brand,
            model,
            len(files),
            already_cleaned,
            clean_method,
            overwrite,
            exc.detail,
        )
        raise
    except Exception:
        logger.exception(
            "car model folder import failed: brand=%r model=%r files=%s already_cleaned=%s clean_method=%s overwrite=%s",
            brand,
            model,
            len(files),
            already_cleaned,
            clean_method,
            overwrite,
        )
        raise

    missing_angles = [angle for angle in _CANONICAL_ANGLES if angle not in imported_images]
    summary = ImportFolderSummary(
        brand=brand,
        model=target_model_name,
        already_cleaned=already_cleaned,
        clean_method=None if already_cleaned else clean_method,
        overwrite=overwrite,
        imported_angles=list(imported_images.keys()),
        missing_angles=missing_angles,
        warnings=warnings,
        images=[CarImageItem(**item) for item in ordered_images],
    )
    return ApiResponse(
        message="车型文件夹导入成功",
        data={
            **summary.model_dump(),
            "backup_file": "database",
        },
    )


@router.post("/replace")
async def replace_car_models_json(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _ = current_user
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="请上传 .json 文件")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")

    try:
        parsed = json.loads(raw.decode("utf-8"))
        data = _validate_data(parsed)
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件必须为 UTF-8 编码") from None
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON 格式错误: line {e.lineno} column {e.colno}") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    await VehicleModelImageService(db).replace_data(data)
    model_count = sum(len(models) for models in data.values())
    return ApiResponse(
        message="车型库已替换为最新版本",
        data={
            "brands": len(data),
            "models": model_count,
            "backup_file": "database",
        },
    )
