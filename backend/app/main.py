"""FastAPI 应用入口"""

import logging
import asyncio
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
from app.config import settings, validate_settings
from app.core.exceptions import (
    validation_exception_handler,
    integrity_exception_handler,
    sqlalchemy_exception_handler,
    general_exception_handler,
)
from app.utils.timezone import CST

# 启动时配置校验
missing_optional_settings = validate_settings()


# 日志配置
def _cst_log_converter(timestamp: float):
    return datetime.fromtimestamp(timestamp, CST).timetuple()


logging.Formatter.converter = staticmethod(_cst_log_converter)

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
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
    from app.services.scheduler import (
        sync_task_loop,
        scheduled_publish_loop,
        xhs_configured_task_loop,
    )
    from app.services.xhs_profile_stat_service import profile_stat_daily_sync_loop
    from app.services.ai_image_provider_service import AIImageProviderService
    from app.services.xhs_ad_dashboard_service import warm_default_ad_dashboard_cache

    async with async_session() as session:
        try:
            created_providers = await AIImageProviderService(session).ensure_default_providers()
            if created_providers:
                logger.info("Seeded %d default AI image providers", created_providers)
        except Exception as e:
            logger.warning("Skipped default AI image provider seed: %s", e)

    # 启动后台定时同步任务
    sync_task = (
        asyncio.create_task(sync_task_loop(async_session))
        if settings.xhs_enable_sync_task_loop
        else None
    )
    xhs_configured_task = asyncio.create_task(xhs_configured_task_loop(async_session))
    scheduled_publish_task = (
        asyncio.create_task(scheduled_publish_loop(async_session))
        if settings.xhs_enable_scheduled_publish_loop
        else None
    )
    profile_stat_sync_task = (
        asyncio.create_task(profile_stat_daily_sync_loop(async_session))
        if settings.xhs_enable_profile_stat_sync_loop
        else None
    )
    ad_dashboard_warm_task = asyncio.create_task(warm_default_ad_dashboard_cache())

    yield

    # 关闭时取消同步任务
    ad_dashboard_warm_task.cancel()
    if sync_task is not None:
        sync_task.cancel()
    xhs_configured_task.cancel()
    if scheduled_publish_task is not None:
        scheduled_publish_task.cancel()
    if profile_stat_sync_task is not None:
        profile_stat_sync_task.cancel()
    if sync_task is not None:
        try:
            await sync_task
        except asyncio.CancelledError:
            pass
    if scheduled_publish_task is not None:
        try:
            await scheduled_publish_task
        except asyncio.CancelledError:
            pass
    try:
        await xhs_configured_task
    except asyncio.CancelledError:
        pass
    if profile_stat_sync_task is not None:
        try:
            await profile_stat_sync_task
        except asyncio.CancelledError:
            pass
    try:
        await ad_dashboard_warm_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="AI Creative Studio API",
    description="Backend API for AI Creative Studio - Design editor with AI and Dify integration",
    version="0.1.0",
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
    return {"status": "ok", "version": "0.1.0"}

@app.api_route("/", methods=["GET", "HEAD"])
async def root_health():
    """根路径探针，避免外部探针打到 backend 根路径时报 404。"""
    return _health_payload()


@app.api_route("/health", methods=["GET", "HEAD"])
async def health_check():
    """健康检查（轻量）"""
    return _health_payload()


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

    # 存储检查
    try:
        from app.adapters.storage import storage
        checks["storage"] = f"ok ({settings.storage_type})"
    except Exception as e:
        checks["storage"] = f"error: {str(e)}"
        all_ok = False

    status_code = 200 if all_ok else 503
    return {"status": "ready" if all_ok else "degraded", "checks": checks}, status_code


@app.api_route("/health/ready", methods=["GET", "HEAD"])
async def readiness_check():
    payload, status_code = await _build_readiness_payload()
    return JSONResponse(content=payload, status_code=status_code)


@app.api_route("/ready", methods=["GET", "HEAD"])
async def ready_check():
    payload, status_code = await _build_readiness_payload()
    return JSONResponse(content=payload, status_code=status_code)
