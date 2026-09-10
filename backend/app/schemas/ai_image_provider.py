from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AIImageProviderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    model_name: str = Field(default="gptimage2", min_length=1, max_length=50)
    provider_kind: str = Field(default="openai_images", min_length=1, max_length=50)
    provider_model: str = Field(default="gpt-image-2", min_length=1, max_length=100)
    endpoint_url: str = Field(..., min_length=8, max_length=500)
    api_key: str = Field(..., min_length=1, max_length=500)
    is_enabled: bool = True
    is_default: bool = False
    priority: int = Field(default=100, ge=0, le=10000)
    weight: int = Field(default=1, ge=1, le=1000)
    supports_text_input: bool = True
    supports_image_input: bool = False
    config: dict = Field(default_factory=dict)


class AIImageProviderUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    model_name: Optional[str] = Field(None, min_length=1, max_length=50)
    provider_kind: Optional[str] = Field(None, min_length=1, max_length=50)
    provider_model: Optional[str] = Field(None, min_length=1, max_length=100)
    endpoint_url: Optional[str] = Field(None, min_length=8, max_length=500)
    api_key: Optional[str] = Field(None, min_length=1, max_length=500)
    is_enabled: Optional[bool] = None
    is_default: Optional[bool] = None
    priority: Optional[int] = Field(None, ge=0, le=10000)
    weight: Optional[int] = Field(None, ge=1, le=1000)
    supports_text_input: Optional[bool] = None
    supports_image_input: Optional[bool] = None
    config: Optional[dict] = None


class AIImageProviderInfo(BaseModel):
    id: int
    name: str
    model_name: str
    provider_kind: str
    provider_model: str
    endpoint_url: str
    api_key_prefix: str
    is_enabled: bool
    is_default: bool
    priority: int
    weight: int
    supports_text_input: bool
    supports_image_input: bool
    config: dict
    last_health_status: str
    last_health_error: Optional[str]
    last_checked_at: Optional[str]
    last_used_at: Optional[str]
    success_count: int
    failure_count: int
    avg_latency_ms: Optional[float]
    current_running: int = 0
    max_concurrent: int = 1
    created_by: Optional[int]
    created_at: Optional[str]
    updated_at: Optional[str]


class AIImageProviderHealthResponse(BaseModel):
    id: int
    status: str
    healthy: bool
    error: Optional[str] = None
    checked_at: str


class AIImageProviderTestRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4000)
    width: int = Field(default=1024, ge=256, le=4096)
    height: int = Field(default=1024, ge=256, le=4096)
    quality: Optional[str] = Field(default=None, max_length=20)
    count: int = Field(default=1, ge=1, le=4)
    image_data: Optional[str] = Field(default=None, max_length=20_000_000)


class AIImageProviderTestResponse(BaseModel):
    id: int
    task_id: str = ""
    status: str
    image_urls: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    provider: dict = Field(default_factory=dict)
