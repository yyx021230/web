"""全局异常处理"""

from __future__ import annotations

import logging
import re
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from app.schemas.common import ApiResponse

logger = logging.getLogger("app.exceptions")

# 敏感信息正则：URL、文件路径、内部技术细节
_SENSITIVE_PATTERNS = [
    re.compile(r'http[s]?://\S+', re.IGNORECASE),  # URLs
    re.compile(r'/[a-zA-Z0-9_./-]+', re.MULTILINE),  # 文件路径
]

# 白名单：通用的错误提示
_SAFE_MESSAGES = {
    "already exists",
    "duplicate key",
    "unique constraint",
}


def _sanitize_error_message(message: str) -> str:
    """移除错误消息中的敏感信息（URL、文件路径等），返回安全提示"""
    for pattern in _SENSITIVE_PATTERNS:
        message = pattern.sub("[REDACTED]", message)
    return message


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Pydantic 验证错误"""
    errors = []
    for error in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
        })
    return JSONResponse(
        status_code=422,
        content=ApiResponse(
            code=422,
            message="参数验证失败",
            data=errors,
        ).model_dump(),
    )


async def integrity_exception_handler(request: Request, exc: IntegrityError):
    """唯一约束冲突等完整性错误"""
    # 提取 PostgreSQL 错误详情中的用户友好信息
    orig = exc.orig
    detail = None
    if orig and hasattr(orig, "pgerror"):
        pgerror = str(orig.pgerror)
        if "unique constraint" in pgerror.lower():
            detail = "数据已存在，请勿重复提交"
        elif "foreign key" in pgerror.lower():
            detail = "关联数据不存在"

    return JSONResponse(
        status_code=400,
        content=ApiResponse(
            code=400,
            message=detail or "数据完整性错误",
        ).model_dump(),
    )


async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    """数据库异常（非 IntegrityError）"""
    logger.exception("Database error: %s", exc)
    return JSONResponse(
        status_code=500,
        content=ApiResponse(
            code=500,
            message="数据库错误",
        ).model_dump(),
    )


async def general_exception_handler(request: Request, exc: Exception):
    """未捕获的通用异常"""
    logger.exception("Unhandled exception: %s", exc)
    # 安全处理：不暴露内部错误详情
    safe_msg = _sanitize_error_message(str(exc))
    return JSONResponse(
        status_code=500,
        content=ApiResponse(
            code=500,
            message="服务器内部错误",
        ).model_dump(),
    )
