"""FastAPI 应用入口"""

import logging
import asyncio
import mimetypes
import os
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pathlib import Path

from app.api.v1.router import router as v1_router
from app.build_info import get_build_info
from app.config import settings, validate_settings
from app.core.exceptions import (
    validation_exception_handler,
    integrity_exception_handler,
    sqlalchemy_exception_handler,
    general_exception_handler,
)
from app.utils.timezone import CST

# Minimal Linux images do not always ship a complete mime.types database.
# Register browser-facing image formats before StaticFiles starts serving uploads.
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/avif", ".avif")
mimetypes.add_type("image/svg+xml", ".svg")

# 启动时配置校验
missing_optional_settings = validate_settings()


# 日志配置
def _cst_log_converter(timestamp: float):
    return datetime.fromtimestamp(timestamp, CST).timetuple()


logging.Formatter.converter = staticmethod(_cst_log_converter)

from app.core.middleware import install_request_id_log_factory

install_request_id_log_factory()
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | request_id=%(request_id)s | %(message)s",
)
logger = logging.getLogger("app")
if missing_optional_settings and settings.debug:
    logger.info(
        "Optional configuration not set: %s. Related features stay disabled.",
        ", ".join(missing_optional_settings),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动定时同步任务"""
    from app.db.session import async_session
    from app.services.scheduler_leader import (
        SchedulerLeaderCoordinator,
        build_scheduler_loop_specs,
        normalized_scheduler_lease_settings,
    )
    from app.services.ai_image_provider_service import AIImageProviderService
    from app.services.xhs_ad_dashboard_service import warm_default_ad_dashboard_cache

    async with async_session() as session:
        try:
            created_providers = await AIImageProviderService(session).ensure_default_providers()
            if created_providers:
                logger.info("Seeded %d default AI image providers", created_providers)
        except Exception as e:
            logger.warning("Skipped default AI image provider seed: %s", e)

    scheduler_specs = build_scheduler_loop_specs(async_session)
    if settings.scheduler_leader_enabled:
        lease_seconds, heartbeat_seconds = normalized_scheduler_lease_settings()
        scheduler_coordinator = SchedulerLeaderCoordinator(
            async_session,
            scheduler_specs,
            lease_seconds=lease_seconds,
            heartbeat_seconds=heartbeat_seconds,
        )
        scheduler_tasks = [
            asyncio.create_task(
                scheduler_coordinator.run(),
                name="scheduler-leader-coordinator",
            )
        ]
    else:
        logger.warning(
            "Scheduler leader lease is disabled; legacy loops are safe only with one API instance"
        )
        scheduler_tasks = [
            asyncio.create_task(spec.factory(), name=f"scheduler:{spec.name}")
            for spec in scheduler_specs
        ]
    ad_dashboard_warm_task = asyncio.create_task(warm_default_ad_dashboard_cache())

    yield

    # 关闭时取消同步任务
    ad_dashboard_warm_task.cancel()
    for scheduler_task in scheduler_tasks:
        scheduler_task.cancel()
    if scheduler_tasks:
        await asyncio.gather(*scheduler_tasks, return_exceptions=True)
    try:
        await ad_dashboard_warm_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="AI Creative Studio API",
    description="Backend API for AI Creative Studio - Design editor with AI and Dify integration",
    version=settings.app_version,
    lifespan=lifespan,
)

# 全局异常处理
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(IntegrityError, integrity_exception_handler)
app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request time middleware
from app.core.middleware import RequestTimeMiddleware
app.add_middleware(RequestTimeMiddleware)

# Serve uploaded files (local storage)
uploads_path = Path(settings.storage_path)
uploads_path.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_path)), name="uploads")

# Include routers
app.include_router(v1_router, prefix="/api/v1")


def _health_payload() -> dict[str, str]:
    return {"status": "ok", **get_build_info()}

@app.api_route("/", methods=["GET", "HEAD"])
async def root_health():
    """根路径探针，避免外部探针打到 backend 根路径时报 404。"""
    return _health_payload()


@app.api_route("/health", methods=["GET", "HEAD"])
async def health_check():
    """健康检查（轻量）"""
    return _health_payload()


@app.api_route("/version", methods=["GET", "HEAD"])
async def version_info():
    """Public build metadata used to identify the running release."""
    return get_build_info()


async def _build_readiness_payload() -> tuple[dict[str, object], int]:
    """就绪检查（验证数据库/存储连接）"""
    checks = {}
    all_ok = True

    # 数据库检查
    try:
        from app.db.session import async_session
        from sqlalchemy import text
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"
        all_ok = False

    # Redis 检查
    try:
        from redis.asyncio import Redis

        redis_client = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        try:
            await redis_client.ping()
        finally:
            await redis_client.aclose()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {type(e).__name__}"
        all_ok = False

    # 存储检查
    try:
        if settings.storage_type == "local":
            uploads_path.mkdir(parents=True, exist_ok=True)
            if not os.access(uploads_path, os.R_OK | os.W_OK):
                raise PermissionError("storage path is not readable and writable")
        else:
            from app.adapters.storage import storage  # noqa: F401
        checks["storage"] = f"ok ({settings.storage_type})"
    except Exception as e:
        checks["storage"] = f"error: {type(e).__name__}"
        all_ok = False

    status_code = 200 if all_ok else 503
    return {
        "status": "ready" if all_ok else "degraded",
        **get_build_info(),
        "checks": checks,
    }, status_code


@app.api_route("/health/ready", methods=["GET", "HEAD"])
async def readiness_check():
    payload, status_code = await _build_readiness_payload()
    return JSONResponse(content=payload, status_code=status_code)


@app.api_route("/ready", methods=["GET", "HEAD"])
async def ready_check():
    payload, status_code = await _build_readiness_payload()
    return JSONResponse(content=payload, status_code=status_code)
