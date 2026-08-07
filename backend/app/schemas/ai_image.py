from pydantic import BaseModel, Field, field_validator
from typing import Optional
from urllib.parse import urlparse

from app.config import settings


def _allowed_reference_hosts() -> set[str]:
    hosts = {item.strip().lower() for item in settings.remote_image_allowed_hosts if item.strip()}
    endpoint_host = urlparse(settings.car_model_oss_endpoint).hostname
    if endpoint_host and settings.car_model_oss_bucket:
        hosts.add(f"{settings.car_model_oss_bucket}.{endpoint_host}".lower())
    return hosts


def _is_allowed_reference_source(value: str) -> bool:
    if value.startswith(("/uploads/", "data:image/")):
        return True
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and parsed.hostname.lower() in _allowed_reference_hosts()


class GenerateImageRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000, description="提示词")
    client_request_id: Optional[str] = Field(None, max_length=64, description="前端生成的请求幂等 ID")
    negative_prompt: Optional[str] = Field(None, max_length=8000, description="负向提示词")
    model: str = Field(default="seedream", description="模型名称")
    width: int = Field(default=2048, ge=256, le=4096, description="宽度")
    height: int = Field(default=2048, ge=256, le=4096, description="高度")
    style: Optional[str] = Field(None, description="风格")
    quality: Optional[str] = Field(None, description="图像质量等级 (low/medium/high)，仅部分模型支持")
    count: int = Field(default=1, ge=1, le=4, description="生成数量（当前支持 1/2/4，最大 4）")
    # 单图兼容（base64 或 URL）
    image_data: Optional[str] = Field(
        None,
        max_length=16_000_000,
        description="参考图片（base64 编码，格式 data:image/...;base64,...）用于图生图",
    )
    image_url: Optional[str] = Field(
        None,
        max_length=2048,
        description="参考图片（URL 地址，用于图生图，与 image_data 二选一）",
    )
    # 多图参考（Seedream 支持）
    images_data: Optional[list[str]] = Field(
        None,
        max_length=10,
        description="多张参考图片（base64 或 URL 数组，最多 10 张）",
    )

    @field_validator("quality")
    @classmethod
    def normalize_quality(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        quality = value.strip().lower()
        return quality if quality in {"low", "medium", "high"} else "low"

    @field_validator("image_url")
    @classmethod
    def reject_remote_reference_url(cls, value: Optional[str]) -> Optional[str]:
        if value and not _is_allowed_reference_source(value):
            raise ValueError("参考图片仅支持内部图库、车型库或 data:image 数据")
        return value

    @field_validator("images_data")
    @classmethod
    def reject_remote_reference_urls(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value:
            for item in value:
                if item and not _is_allowed_reference_source(item):
                    raise ValueError("参考图片仅支持内部图库、车型库或 data:image 数据")
        return value


class ImageTaskResponse(BaseModel):
    task_id: str
    status: str
    image_urls: list[str] = []
    error: Optional[str] = None
    client_request_id: Optional[str] = None
    created_at: Optional[str] = None
    finished_at: Optional[str] = None
    elapsed_seconds: Optional[float] = None


class AIImageRuntimeConfig(BaseModel):
    task_timeout_seconds: int
    poll_interval_seconds: int


class ActiveImageTask(BaseModel):
    id: int
    task_id: str
    model_name: str
    status: str
    prompt: str
    created_at: str
    finished_at: Optional[str] = None


class ActiveImageTasksResponse(BaseModel):
    active_count: int
    max_active: int
    can_submit: bool
    items: list[ActiveImageTask] = []


class ModelInfo(BaseModel):
    id: str
    name: str
    description: str
    max_resolution: dict[str, int]
    styles: list[str] = []
