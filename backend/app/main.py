"""FastAPI 应用入口"""

import logging
from fastapi import FastAPI
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

# 启动时配置校验
validate_settings()

# 日志配置
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("app")

app = FastAPI(
    title="AI Creative Studio API",
    description="Backend API for AI Creative Studio - Design editor with AI and Dify integration",
    version="0.1.0",
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


@app.get("/health")
async def health_check():
    """健康检查（轻量）"""
    return {"status": "ok", "version": "0.1.0"}


@app.get("/health/ready")
async def readiness_check():
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
