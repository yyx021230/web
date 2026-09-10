from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class HermesAccountInput(BaseModel):
    environment_id: int = Field(..., gt=0, description="小红书账号环境 ID")
    vehicle_model: str = Field(..., min_length=2, max_length=160, description="生产车型")
    case_id: str | None = Field(None, max_length=120, description="Hermes 政策 case，可留空自动匹配")


class HermesRunCreate(BaseModel):
    name: str | None = Field(None, max_length=100)
    account_id: int = Field(..., gt=0, description="当前用户负责的小红书账号")
    vehicle_model: str = Field(..., min_length=2, max_length=160)
    case_id: str | None = Field(None, max_length=120)
    post_count: int = Field(default=1, ge=1, le=5)
    copy_type: str | None = Field(None, max_length=80)
    image_type: str | None = Field(None, max_length=80)
    instruction: str | None = Field(None, max_length=1000)


class HermesBatchAccountInput(BaseModel):
    environment_id: int = Field(..., gt=0)
    post_count: int = Field(default=5, ge=1, le=5)


class HermesBatchRunCreate(BaseModel):
    name: str | None = Field(None, max_length=100)
    accounts: list[HermesBatchAccountInput] = Field(..., min_length=1, max_length=8)
    vehicle_models: list[str] = Field(..., min_length=1, max_length=12)
    instruction: str | None = Field(None, max_length=1000)

    @field_validator("accounts")
    @classmethod
    def validate_unique_batch_accounts(cls, values: list[HermesBatchAccountInput]) -> list[HermesBatchAccountInput]:
        ids = [item.environment_id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("账号不能重复")
        return values

    @field_validator("vehicle_models")
    @classmethod
    def validate_vehicle_models(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if not normalized:
            raise ValueError("至少选择一个车型")
        if len(normalized) != len(set(normalized)):
            raise ValueError("车型不能重复")
        return normalized


class HermesAdminRunCreate(BaseModel):
    accounts: list[HermesAccountInput] = Field(..., min_length=1, max_length=8)
    posts_per_account: int = Field(default=5, ge=1, le=5)
    instruction: str | None = Field(None, max_length=1000)


class HermesReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    comment: str | None = Field(None, max_length=1000)
    expected_version: str | None = Field(None, max_length=64)
    regenerate: bool = False

    @model_validator(mode='after')
    def validate_regeneration(self):
        if self.regenerate and (self.action != 'reject' or not (self.expected_version or '').strip()):
            raise ValueError('重新生成仅用于不通过操作，且必须提供当前版本')
        return self


class HermesPostEdit(BaseModel):
    title: str = Field(..., min_length=1, max_length=80)
    content: str = Field(..., min_length=1, max_length=1000)
    comment: str = Field(..., min_length=1, max_length=1000)
    expected_version: str = Field(..., min_length=1, max_length=64)

    @field_validator('title', 'content', 'comment')
    @classmethod
    def strip_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('内容不能为空')
        return value.strip()


class HermesPublishPlanItem(BaseModel):
    post_id: int = Field(..., gt=0)
    environment_id: int = Field(..., gt=0)
    scheduled_at: str = Field(..., min_length=16, max_length=32)
    expected_version: str | None = Field(None, max_length=64)


class HermesPublishPlanRequest(BaseModel):
    items: list[HermesPublishPlanItem] = Field(..., min_length=1, max_length=40)


class HermesScheduleUpdate(BaseModel):
    enabled: bool = False
    run_time: str = "09:00"
    accounts: list[HermesAccountInput] = Field(default_factory=list, max_length=8)
    posts_per_account: int = Field(default=5, ge=1, le=5)
    instruction: str | None = Field(None, max_length=1000)

    @field_validator("run_time")
    @classmethod
    def validate_run_time(cls, value: str) -> str:
        parts = value.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError("run_time 必须是 HH:MM")
        hour, minute = map(int, parts)
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("run_time 必须是有效时间")
        return f"{hour:02d}:{minute:02d}"

    @field_validator("accounts")
    @classmethod
    def validate_unique_accounts(cls, values: list[HermesAccountInput]) -> list[HermesAccountInput]:
        ids = [item.environment_id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("账号不能重复")
        return values


class HermesWorkerClaim(BaseModel):
    worker_id: str = Field(..., min_length=2, max_length=160)
    status: Literal["idle", "running"] = "idle"
    current_run_id: int | None = Field(None, gt=0)
    capabilities: dict = Field(default_factory=dict)


class HermesWorkerComplete(BaseModel):
    worker_id: str = Field(..., min_length=2, max_length=160)
    delivery: dict = Field(default_factory=dict)


class HermesWorkerFail(BaseModel):
    worker_id: str = Field(..., min_length=2, max_length=160)
    error: str = Field(..., min_length=1, max_length=8000)
