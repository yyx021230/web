from pydantic import BaseModel, Field
from typing import Optional


class GenerateImageRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000, description="提示词")
    negative_prompt: Optional[str] = Field(None, max_length=2000, description="负向提示词")
    model: str = Field(default="seedream", description="模型名称")
    width: int = Field(default=2048, ge=256, le=4096, description="宽度")
    height: int = Field(default=2048, ge=256, le=4096, description="高度")
    style: Optional[str] = Field(None, description="风格")
    quality: Optional[str] = Field(None, description="图像质量等级 (low/medium/high)，仅部分模型支持")
    image_data: Optional[str] = Field(
        None,
        max_length=10_000_000,
        description="参考图片（base64 编码，格式 data:image/...;base64,...）用于图生图",
    )


class ImageTaskResponse(BaseModel):
    task_id: str
    status: str
    image_urls: list[str] = []
    error: Optional[str] = None


class ModelInfo(BaseModel):
    id: str
    name: str
    description: str
    max_resolution: dict[str, int]
    styles: list[str] = []
