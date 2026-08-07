import logging
import re
import time
import uuid
from contextvars import ContextVar

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


request_id_context: ContextVar[str] = ContextVar("request_id", default="-")
logger = logging.getLogger("app.request")
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def current_request_id() -> str:
    return request_id_context.get()


def install_request_id_log_factory() -> None:
    """Inject request_id into every log record without changing call sites."""
    current_factory = logging.getLogRecordFactory()
    if getattr(current_factory, "_ztqc_request_id_factory", False):
        return

    def record_factory(*args, **kwargs):
        record = current_factory(*args, **kwargs)
        record.request_id = current_request_id()
        return record

    record_factory._ztqc_request_id_factory = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(record_factory)


class RequestTimeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        supplied_request_id = request.headers.get("X-Request-ID", "").strip()
        request_id = (
            supplied_request_id
            if _SAFE_REQUEST_ID.fullmatch(supplied_request_id)
            else uuid.uuid4().hex
        )
        request.state.request_id = request_id
        token = request_id_context.set(request_id)
        start_time = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            process_time = time.perf_counter() - start_time
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time"] = f"{process_time:.6f}"
            return response
        finally:
            process_time = time.perf_counter() - start_time
            logger.info(
                "%s %s status=%s duration_ms=%.2f",
                request.method,
                request.url.path,
                status_code,
                process_time * 1000,
            )
            request_id_context.reset(token)
