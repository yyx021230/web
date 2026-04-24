"""应用配置管理"""

from __future__ import annotations

from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache
import warnings


class Settings(BaseSettings):
    # App
    app_name: str = "AI Creative Studio"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_creative"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # File Storage
    storage_type: str = "local"  # local | s3 | minio
    storage_path: str = "./uploads"
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = ""

    # Dify
    dify_default_base_url: str = ""
    dify_default_api_key: str = ""

    # AI Models
    seedream_api_key: str = ""
    seedream_api_url: str = "https://ark.cn-beijing.volces.com/api/v3/images/generations"

    gpt_image2_api_key: str = ""
    gpt_image2_api_url: str = "https://api.openai.com/v1/images/generations"

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    model_config = {"env_file": ".env"}

    def validate_critical(self) -> list[str]:
        """检查关键配置项，返回缺失项列表"""
        missing = []
        if self.database_url == "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_creative":
            missing.append("DATABASE_URL")
        if not self.jwt_secret_key or self.jwt_secret_key == "change-me-in-production":
            missing.append("JWT_SECRET_KEY")
        return missing

    def validate_optional(self) -> list[str]:
        """检查可选配置项，返回缺失项列表"""
        missing = []
        if not self.dify_default_base_url:
            missing.append("DIFY_DEFAULT_BASE_URL")
        if not self.seedream_api_key:
            missing.append("SEEDREAM_API_KEY")
        return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def validate_settings() -> None:
    """启动时配置校验"""
    missing_critical = settings.validate_critical()
    if missing_critical:
        raise RuntimeError(
            f"Missing critical configuration: {', '.join(missing_critical)}"
        )

    missing_optional = settings.validate_optional()
    if missing_optional:
        warnings.warn(
            f"Optional configuration not set: {', '.join(missing_optional)}. "
            "Related features will not work.",
            stacklevel=2,
        )
