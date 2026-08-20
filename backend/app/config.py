"""应用配置管理"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import unquote, urlparse

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "AI Creative Studio"
    app_env: str = "development"
    deployment_environment: str = "development"
    production_confirmation: str = ""
    app_version: str = "0.3.10"
    git_commit: str = "unknown"
    build_time: str = "unknown"
    debug: bool = False

    # Database
    database_url: str = "sqlite+aiosqlite:///./dev.db"
    allow_default_database_password: bool = False

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # File Storage
    storage_type: str = "local"  # local | s3 | minio
    storage_path: str = "./uploads"
    uploads_public_base_url: str = ""
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
    duckcoding_gpt_image2_api_key: str = ""
    duckcoding_gpt_image2_api_url: str = "https://api.duckcoding.ai/v1"
    xhs_content_tagging_api_base_url: str = ""
    xhs_content_tagging_api_key: str = ""
    xhs_content_tagging_model: str = "gpt-5.4-mini"
    car_model_ocr_baidu_api_key: str = ""
    car_model_ocr_baidu_secret_key: str = ""
    car_model_oss_access_key_id: str = ""
    car_model_oss_access_key_secret: str = ""
    car_model_oss_endpoint: str = "https://oss-cn-hangzhou.aliyuncs.com"
    car_model_oss_bucket: str = "test260415"
    car_model_oss_prefix: str = "car_exterior"
    ai_task_timeout_seconds: int = 1800
    ai_task_stale_after_minutes: int = 30
    ai_task_cleanup_interval_seconds: int = 60
    ai_task_queue_key: str = "ai:image:tasks:pending"
    ai_task_processing_key: str = "ai:image:tasks:processing"
    ai_task_membership_key: str = "ai:image:tasks:membership"
    ai_task_worker_concurrency: int = 15
    ai_task_worker_poll_timeout_seconds: int = 5
    ai_task_worker_min_interval_seconds: float = 10.0
    ai_image_shadow_enabled: bool = False
    ai_image_reconciliation_enabled: bool = False
    ai_image_reconciliation_interval_seconds: int = 60
    ai_image_reconciliation_batch_size: int = 20

    # AI Watermark Removal (HTTP API)
    remove_ai_watermarks_enabled: bool = True
    remove_ai_watermarks_api_url: str = (
        "http://47.98.127.132/pureimage/watermark-api/remove-watermark"
    )
    remove_ai_watermarks_timeout: int = 240
    remove_ai_watermarks_strict: bool = True
    remove_ai_watermarks_max_concurrent: int = 4
    remove_ai_watermarks_retries: int = 5
    remove_ai_watermarks_retry_delay_seconds: float = 5.0

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]
    cors_origin_regex: str = (
        r"^https?://("
        r"localhost|127\.0\.0\.1|"
        r"10\.\d+\.\d+\.\d+|"
        r"172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+|"
        r"192\.168\.\d+\.\d+"
        r")(:\d+)?$"
    )

    # YunDeng Browser API
    yundeng_api_base_url: str = "http://localhost:50213"
    yundeng_cloud_api_base_url: str = "https://cloud.yunlogin.com"
    yundeng_cloud_open_token: str = ""
    xhs_mcp_port: int = 18061
    xhs_mcp_bin_path: str = ""
    xhs_mcp_api_base_url: str = ""
    xhs_host_upload_root: str = ""
    xhs_container_upload_root: str = ""
    xhs_mcp_browser_download_dir: str = ""
    xhs_mcp_container_download_dir: str = ""
    xhs_profile_fetch_timeout_seconds: float = 300.0
    xhs_publish_queue_workers: int = 2
    xhs_yundeng_sync_concurrency: int = 5
    xhs_yundeng_lease_seconds: int = 1800
    xhs_yundeng_acquire_timeout_seconds: int = 3600
    xhs_yundeng_start_stagger_seconds: float = 2.0
    xhs_yundeng_distributed_coordinator_enabled: bool = True
    xhs_browser_stop_cooldown_seconds: float = 2.0
    xhs_browser_ws_probe_timeout_seconds: float = 3.0
    xhs_browser_start_retry_attempts: int = 3
    xhs_browser_start_retry_delay_seconds: float = 2.0
    xhs_enable_local_browser_ops: bool = True
    xhs_worker_api_base_url: str = ""
    xhs_worker_internal_token: str = ""
    xhs_enable_sync_task_loop: bool = False
    xhs_enable_account_notes_sync_loop: bool = False
    xhs_homepage_sync_shadow_enabled: bool = False
    xhs_engagement_detail_sync_shadow_enabled: bool = False
    xhs_report_refresh_shadow_enabled: bool = False
    dify_task_shadow_enabled: bool = False
    scheduler_leader_enabled: bool = True
    scheduler_leader_lease_seconds: int = 30
    scheduler_leader_heartbeat_seconds: int = 10
    xhs_enable_scheduled_publish_loop: bool = True
    xhs_enable_profile_stat_sync_loop: bool = False
    xhs_account_scrape_environment_id: int = 0
    xhs_report_token_api: str = "https://v2-api.ztvcar.com/ztcar-api/carshow/market/xhs/token"
    xhs_report_worker_api_base_url: str = ""
    xhs_report_worker_internal_token: str = ""
    xhs_report_adapi_base_url: str = "https://adapi.xiaohongshu.com"
    xhs_profile_stat_api_base_url: str = "https://ai.youju360.com"
    xhs_profile_stat_app_id: str = ""
    xhs_profile_stat_secret: str = ""
    xhs_profile_stat_config_id: int = 157
    xhs_profile_stat_module: str = "custom_tag"
    xhs_profile_stat_script: str = "youju"
    xhs_profile_stat_daily_update_hour: int = 6
    xhs_profile_stat_backfill_days: int = 30
    xhs_profile_stat_sync_delay_seconds: float = 65.0
    # A throttled profileStat response explicitly asks clients to retry in five minutes.
    xhs_profile_stat_retry_delay_seconds: float = 305.0
    xhs_profile_stat_max_retries: int = 2
    xhs_scrape_lab_base_url: str = "http://127.0.0.1:8787"
    xhs_scrape_lab_python_path: str = "python3"
    xhs_scrape_lab_server_path: str = ""
    xhs_scrape_lab_log_dir: str = ""
    sms_code_center_base_url: str = "http://47.98.127.132"
    sms_code_center_open_api_client_id: str = ""
    sms_code_center_open_api_client_secret: str = ""
    sms_code_center_open_api_poll_interval_seconds: float = 4.0
    # Retained only because older deployments still provide this setting.
    sms_code_center_business_api_token: str = ""
    sms_code_center_admin_api_token: str = ""
    sms_code_center_admin_username: str = ""
    sms_code_center_admin_password: str = ""
    sms_code_center_wait_timeout_seconds: int = 60
    sms_code_center_activation_ttl_seconds: int = 300
    # A successful countdown does not guarantee carrier delivery.  Retry one
    # complete, isolated activation after the first bounded wait expires.
    sms_code_center_primary_send_attempts: int = 2
    sms_code_center_primary_attempt_timeout_seconds: int = 180
    sms_device_login_lock_enabled: bool = True
    sms_device_login_lock_lease_seconds: int = 1800
    sms_device_login_lock_acquire_timeout_seconds: int = 1800
    remote_image_allowed_hosts: list[str] = []

    model_config = {"env_file": ".env"}

    @staticmethod
    def _uses_default_database_password(database_url: str) -> bool:
        try:
            parsed = urlparse(database_url)
            return unquote(parsed.username or "") == "postgres" and unquote(parsed.password or "") == "postgres"
        except ValueError:
            return False

    def validate_critical(self) -> list[str]:
        """检查关键配置项，返回缺失项列表"""
        missing = []
        app_env = self.app_env.strip().lower()
        deployment_environment = self.deployment_environment.strip().lower()
        supported_environments = {"development", "test", "staging", "production"}
        if app_env not in supported_environments:
            missing.append("APP_ENV_VALID")
        if deployment_environment not in supported_environments:
            missing.append("DEPLOYMENT_ENVIRONMENT_VALID")
        if app_env != deployment_environment:
            missing.append("APP_ENV_MATCHES_DEPLOYMENT_ENVIRONMENT")
        if not self.jwt_secret_key or self.jwt_secret_key == "change-me-in-production":
            missing.append("JWT_SECRET_KEY")
        if app_env == "test" and not self.database_url.startswith("sqlite"):
            missing.append("TEST_DATABASE_MUST_BE_SQLITE")
        if app_env == "production":
            if self.production_confirmation != "ALLOW_PRODUCTION_DEPLOYMENT":
                missing.append("PRODUCTION_CONFIRMATION")
            if not self.database_url or self.database_url.startswith("sqlite"):
                missing.append("DATABASE_URL")
            if not self.allow_default_database_password and self._uses_default_database_password(self.database_url):
                missing.append("DATABASE_URL_NON_DEFAULT_PASSWORD")
            if not self.xhs_worker_internal_token:
                missing.append("XHS_WORKER_INTERNAL_TOKEN")
            if self.storage_type in {"s3", "minio"}:
                if not self.s3_access_key:
                    missing.append("S3_ACCESS_KEY")
                if not self.s3_secret_key:
                    missing.append("S3_SECRET_KEY")
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


def validate_settings() -> list[str]:
    """启动时配置校验"""
    missing_critical = settings.validate_critical()
    if missing_critical:
        raise RuntimeError(
            f"Missing critical configuration: {', '.join(missing_critical)}"
        )
    return settings.validate_optional()
