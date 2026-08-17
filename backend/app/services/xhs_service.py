from __future__ import annotations

import httpx
import asyncio
import csv
import os
import signal
import logging
import random
import re
import base64
import uuid
import json
import hashlib
import hmac
import threading
import socket
import io
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Optional, Awaitable, Callable
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse, unquote
from sqlalchemy import select, func, and_, delete, or_, insert, inspect as sa_inspect
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import NO_VALUE
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.xhs_environment import XHSEnvironment
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_creator_sync_row import XHSCreatorSyncRow
from app.models.xhs_account_note_browse_event import XHSAccountNoteBrowseEvent
from app.models.xhs_post import XHSPost
from app.models.user_xhs_env import UserXHSEnvironment
from app.models.xhs_ad_account_assignment import XHSAdAccountBuyerAssignment
from app.models.xhs_report import (
    XHSAdStatsDailyAccount,
    XHSAdStatsDailyBrand,
    XHSAdStatsDailyBuyer,
    XHSAdStatsDailyContentTag,
    XHSAdStatsDailyNote,
    XHSReportDaily,
    XHSReportToken,
)
from app.models.user import User
from app.config import settings
from app.core.roles import (
    ROLE_ADMIN,
    ROLE_BRAND_LEAD,
    ROLE_BRAND_OPS,
    ROLE_BUYER,
    ROLE_XHS_LEAD,
    ROLE_XHS_OPS,
    ROLE_VIEWER,
    get_primary_role,
    get_user_roles,
    has_role,
    load_roles_for_users,
    normalize_roles,
)
from app.services.copywriting_service import CopywritingService
from app.services.request_queue import xhs_publish_queue
from app.services.vehicle_catalog_service import VehicleCatalogService
from app.services.yundeng_sync_coordinator import yundeng_sync_coordinator, yundeng_sync_guard
from app.db.session import async_session
from app.utils.timezone import (
    aware_or_cst_naive_to_utc_naive,
    cst_now_naive,
    utc_now_naive,
)

logger = logging.getLogger(__name__)
_VEHICLE_CATALOG_CACHE: list[dict[str, Any]] | None = None
_VEHICLE_INDEX_CACHE: dict[str, Any] | None = None
_INSIGHTS_DASHBOARD_CACHE: dict[str, dict[str, Any]] = {}
_INSIGHTS_OWNER_ROLE_PRIORITY = [
    ROLE_XHS_LEAD,
    ROLE_BRAND_LEAD,
    ROLE_XHS_OPS,
    ROLE_BRAND_OPS,
    ROLE_ADMIN,
    ROLE_BUYER,
    ROLE_VIEWER,
]
_SYNC_BROWSER_CONFIG_RNG = random.SystemRandom()
YUNDENG_API = getattr(settings, "yundeng_api_base_url", "http://localhost:50213")
_yundeng_cloud_api = getattr(settings, "yundeng_cloud_api_base_url", "https://cloud.yunlogin.com") or "https://cloud.yunlogin.com"
YUNDENG_CLOUD_API = _yundeng_cloud_api.strip().rstrip("/")
YUNDENG_CLOUD_OPEN_TOKEN = getattr(settings, "yundeng_cloud_open_token", "") or ""
XHS_REPORT_TOKEN_API = getattr(settings, "xhs_report_token_api", "https://v2-api.ztvcar.com/ztcar-api/carshow/market/xhs/token")
XHS_REPORT_ADAPI_BASE = getattr(settings, "xhs_report_adapi_base_url", "https://adapi.xiaohongshu.com")
XHS_MCP_PORT = getattr(settings, "xhs_mcp_port", 18061)
XHS_MCP_API = f"http://localhost:{XHS_MCP_PORT}"
_xhs_bin = getattr(settings, "xhs_mcp_bin_path", "") or "xiaohongshu-mcp"
XHS_MCP_BIN = _xhs_bin
_external_mcp_api = getattr(settings, "xhs_mcp_api_base_url", "") or ""
XHS_MCP_EXTERNAL_API = _external_mcp_api.strip().rstrip("/")
_host_upload_root = getattr(settings, "xhs_host_upload_root", "") or ""
XHS_HOST_UPLOAD_ROOT = _host_upload_root.strip()
_container_upload_root = getattr(settings, "xhs_container_upload_root", "") or ""
XHS_CONTAINER_UPLOAD_ROOT = _container_upload_root.strip()
_mcp_browser_download_dir = getattr(settings, "xhs_mcp_browser_download_dir", "") or ""
XHS_MCP_BROWSER_DOWNLOAD_DIR = _mcp_browser_download_dir.strip()
_mcp_container_download_dir = getattr(settings, "xhs_mcp_container_download_dir", "") or ""
XHS_MCP_CONTAINER_DOWNLOAD_DIR = _mcp_container_download_dir.strip()
XHS_ENABLE_LOCAL_BROWSER_OPS = bool(getattr(settings, "xhs_enable_local_browser_ops", True))
_worker_api_base = getattr(settings, "xhs_worker_api_base_url", "") or ""
XHS_WORKER_API_BASE = _worker_api_base.strip().rstrip("/")
XHS_WORKER_INTERNAL_TOKEN = getattr(settings, "xhs_worker_internal_token", "") or ""
XHS_ACCOUNT_SCRAPE_ENVIRONMENT_ID = int(getattr(settings, "xhs_account_scrape_environment_id", 0) or 0)
XHS_YUNDENG_SYNC_CONCURRENCY = max(1, min(int(getattr(settings, "xhs_yundeng_sync_concurrency", 5) or 5), 5))
XHS_PROFILE_FETCH_TIMEOUT_SECONDS = max(
    90.0,
    float(getattr(settings, "xhs_profile_fetch_timeout_seconds", 300.0) or 300.0),
)
_report_worker_api_base = getattr(settings, "xhs_report_worker_api_base_url", "") or ""
XHS_REPORT_WORKER_API_BASE = _report_worker_api_base.strip().rstrip("/")
XHS_REPORT_WORKER_INTERNAL_TOKEN = getattr(settings, "xhs_report_worker_internal_token", "") or ""
SMS_CODE_CENTER_BASE_URL = (getattr(settings, "sms_code_center_base_url", "http://47.98.127.132") or "").strip().rstrip("/")
SMS_CODE_CENTER_OPEN_API_CLIENT_ID = (getattr(settings, "sms_code_center_open_api_client_id", "") or "").strip()
SMS_CODE_CENTER_OPEN_API_CLIENT_SECRET = getattr(settings, "sms_code_center_open_api_client_secret", "") or ""
SMS_CODE_CENTER_ADMIN_API_TOKEN = getattr(settings, "sms_code_center_admin_api_token", "") or ""
SMS_CODE_CENTER_ADMIN_USERNAME = (getattr(settings, "sms_code_center_admin_username", "") or "").strip()
SMS_CODE_CENTER_ADMIN_PASSWORD = getattr(settings, "sms_code_center_admin_password", "") or ""
SMS_CODE_CENTER_WAIT_TIMEOUT_SECONDS = max(5, int(getattr(settings, "sms_code_center_wait_timeout_seconds", 60) or 60))
SMS_CODE_CENTER_ACTIVATION_TTL_SECONDS = max(30, int(getattr(settings, "sms_code_center_activation_ttl_seconds", 300) or 300))
SMS_CODE_CENTER_OPEN_API_POLL_INTERVAL_SECONDS = min(
    5.0,
    max(3.0, float(getattr(settings, "sms_code_center_open_api_poll_interval_seconds", 4.0) or 4.0)),
)
_uploads_public_base = getattr(settings, "uploads_public_base_url", "") or ""
UPLOADS_PUBLIC_BASE_URL = _uploads_public_base.strip().rstrip("/")
XHS_BROWSER_STOP_COOLDOWN_SECONDS = max(
    0.0,
    float(getattr(settings, "xhs_browser_stop_cooldown_seconds", 2.0) or 0.0),
)
XHS_BROWSER_WS_PROBE_TIMEOUT_SECONDS = max(
    0.5,
    float(getattr(settings, "xhs_browser_ws_probe_timeout_seconds", 3.0) or 3.0),
)
XHS_BROWSER_START_RETRY_ATTEMPTS = max(
    1,
    int(getattr(settings, "xhs_browser_start_retry_attempts", 3) or 3),
)
XHS_BROWSER_START_RETRY_DELAY_SECONDS = max(
    0.0,
    float(getattr(settings, "xhs_browser_start_retry_delay_seconds", 2.0) or 0.0),
)
RUNNING_IN_DOCKER = os.path.exists("/.dockerenv")


def _join_env_path(root: str, child: str) -> str:
    root = (root or "").strip()
    child = (child or "").strip().strip("/\\")
    if not root:
        return child
    if "\\" in root:
        return root.rstrip("/\\") + "\\" + child
    return root.rstrip("/\\") + "/" + child


REPORT_API_PATHS: dict[str, str] = {
    "simple": "/api/open/jg/data/report/offline/easy/promotion/base",
    "simple_note": "/api/open/jg/data/report/offline/easy/promotion/note",
    "standard": "/api/open/jg/data/report/offline/campaign",
    "standard_note": "/api/open/jg/data/report/offline/note",
    "creative": "/api/open/jg/data/report/offline/creative",
}

CREATIVE_COMPARE_AI_LABELS: dict[str, str] = {
    "manual": "纯手工",
    "text_ai": "仅文案 AI",
    "image_ai": "仅图片 AI",
    "all_ai": "图文都 AI",
}
CREATIVE_COMPARE_SUM_KEYS = (
    "fee",
    "impression",
    "click",
    "interaction",
    "play_5s",
    "message_consult",
    "initiative_message",
    "msg_leads_num",
    "shop_pay_order_num_15d",
)

_AD_BRAND_ALIASES = {
    "奥迪AUDI": "奥迪",
    "上汽奥迪": "奥迪",
    "小鹏汽车": "小鹏",
    "岚图": "岚图汽车",
    "深蓝": "深蓝汽车",
    "零跑": "零跑汽车",
}
_AD_FALLBACK_BRANDS = (
    "比亚迪",
    "零跑汽车",
    "理想汽车",
    "小鹏",
    "极氪",
    "奔驰",
    "哈弗",
    "奥迪",
    "腾势",
    "岚图汽车",
    "深蓝汽车",
    "智己汽车",
    "吉利汽车",
    "红旗",
    "领克",
    "丰田",
    "阿维塔",
    "东风奕派",
    "广汽传祺",
)


@dataclass
class PostSyncResult:
    success: bool
    reason: str = ""
    message: str = ""


@dataclass(frozen=True)
class SyncSessionPersona:
    profile_prep_range: tuple[float, float]
    account_pause_range: tuple[float, float]
    account_long_pause_range: tuple[float, float]
    detail_pause_range: tuple[float, float]
    detail_long_pause_range: tuple[float, float]
    retry_backoff_range: tuple[float, float]
    context_switch_range: tuple[float, float]
    inter_batch_pause_range: tuple[float, float]
    env_order_window: tuple[int, int]
    detail_order_window: tuple[int, int]
    warmup_rounds: int
    warmup_note_limit: int
    use_profile_peek: bool
    warmup_detail_peek_probability: float
    extra_long_pause_probability: float


ProgressCallback = Callable[[dict[str, Any]], Optional[Awaitable[None]]]
CancelCheck = Callable[[], bool]


class XHSRemoteOperationUnsupported(ValueError):
    """Raised when current xiaohongshu-mcp has no required remote operation tool."""


class SyncJobCancelled(RuntimeError):
    """Raised when a cooperative XHS sync job is cancelled by the user."""


def _ad_to_float(value: object) -> float:
    try:
        raw = str(value if value is not None else "").strip().replace(",", "")
        if raw.endswith("%"):
            raw = raw[:-1]
        if not raw:
            return 0.0
        parsed = float(raw)
        return parsed if parsed == parsed else 0.0
    except Exception:
        return 0.0


def _ad_get(row: dict, *keys: str) -> object:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _ad_metric(row: dict, *keys: str) -> float:
    return _ad_to_float(_ad_get(row, *keys))


def _ad_sum(row: dict, *keys: str) -> float:
    return sum(_ad_to_float(row.get(key)) for key in keys)


def _ad_interaction(row: dict) -> float:
    direct = _ad_metric(row, "interaction")
    if direct:
        return direct
    return _ad_sum(row, "like", "collect", "comment", "share", "follow")


def _ad_conversion(row: dict) -> float:
    return _ad_metric(row, "msg_leads_num", "valid_leads", "leads", "conversion", "conversions")


def _ad_openings(row: dict) -> float:
    return _ad_metric(row, "initiative_message", "msg_chat_user_cnt")


def _ad_note_id(row: dict) -> str:
    return str(_ad_get(row, "note_id", "creative_id", "note_material", "feed_id", "material_id", "item_id") or "").strip()


def _ad_note_title(row: dict) -> str:
    return str(_ad_get(row, "note_title", "note_name", "creative_name", "creativity_name", "note_material") or "").strip() or "未命名笔记"


def _ad_clean_content_tag(tag: object) -> str:
    value = str(tag or "").strip().lstrip("#").strip()
    value = re.sub(r"[\[【(（]\s*话题\s*[\]】)）]?$", "", value).strip()
    value = re.sub(r"[#\s]*话题\s*[\]】)）]?$", "", value).strip()
    value = value.rstrip("#").strip()
    return value


def _ad_strip_brand_noise(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[🔴🟢🟡🟣🔵⭐️★☆]+", "", text)
    text = re.sub(r"^\s*(?:\d{1,2}[./月-]\d{1,2}(?:日)?|复投|新投|加投|续投|测试|素材|计划|推广)\s*", "", text)
    text = re.sub(r"\s+", "", text)
    return text.strip(" -_/#｜|·")


def _ad_normalize_brand_candidate(value: object, brand_catalog: tuple[str, ...]) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    candidates = [raw]
    candidates.extend(part.strip() for part in re.split(r"[#＃/｜|,，;；\s]+", raw) if part.strip())
    for candidate in candidates:
        cleaned = _ad_strip_brand_noise(candidate)
        if not cleaned:
            continue
        for alias, brand in _AD_BRAND_ALIASES.items():
            if alias in cleaned:
                return brand
        for brand in brand_catalog:
            # Avoid treating a one-character brand as a substring of an
            # operator/account name. Exact values remain valid brand fields.
            if brand and (cleaned == brand or (len(brand) > 1 and brand in cleaned)):
                return brand
    return ""


def _ad_brand(row: dict, brand_catalog: tuple[str, ...]) -> str:
    for key in ("brand", "brand_name", "car_brand", "series_name", "sub_brand", "brandName"):
        value = _ad_normalize_brand_candidate(row.get(key), brand_catalog)
        if value:
            return value
    text = str(_ad_get(row, "campaign_name", "unit_name", "creativity_name", "note_title") or "")
    value = _ad_normalize_brand_candidate(text, brand_catalog)
    if value:
        return value
    return "未知"


class XHSService:
    _env_publish_locks: dict[int, asyncio.Lock] = {}
    _env_publish_locks_by_loop: dict[int, dict[int, asyncio.Lock]] = {}
    _env_publish_locks_guard = threading.Lock()
    _browser_status_cache: dict[int, dict[str, Any]] = {}
    _browser_status_cache_guard = threading.Lock()
    _mcp_port_guard = threading.Lock()
    _reserved_mcp_ports: dict[int, float] = {}
    _mcp_ports_by_pid: dict[int, int] = {}

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    async def _emit_progress(progress_callback: ProgressCallback | None, payload: dict[str, Any]) -> None:
        if not progress_callback:
            return
        result = progress_callback(payload)
        if asyncio.iscoroutine(result):
            await result

    async def _raise_if_sync_cancelled(
        self,
        cancel_check: CancelCheck | None,
        *,
        on_cancel: Callable[[], Optional[Awaitable[None]]] | None = None,
    ) -> None:
        if not cancel_check or not cancel_check():
            return
        if on_cancel:
            cleanup = on_cancel()
            if asyncio.iscoroutine(cleanup):
                await cleanup
        raise SyncJobCancelled("任务已中止，已保留此前完成的数据")

    @staticmethod
    def _random_seconds(min_seconds: float, max_seconds: float) -> float:
        lower = max(0.0, float(min_seconds))
        upper = max(lower, float(max_seconds))
        if upper == lower:
            return lower
        return _SYNC_BROWSER_CONFIG_RNG.uniform(lower, upper)

    async def _sleep_humanized(self, min_seconds: float, max_seconds: float) -> None:
        await asyncio.sleep(self._random_seconds(min_seconds, max_seconds))

    @staticmethod
    def _build_sync_session_persona() -> SyncSessionPersona:
        styles = [
            {
                "profile_prep_range": (0.8, 1.9),
                "account_pause_range": (1.2, 2.7),
                "account_long_pause_range": (4.1, 7.2),
                "detail_pause_range": (0.9, 1.8),
                "detail_long_pause_range": (3.0, 5.5),
                "retry_backoff_range": (1.0, 2.2),
                "context_switch_range": (1.8, 3.5),
                "inter_batch_pause_range": (2.6, 4.8),
                "env_order_window": (2, 3),
                "detail_order_window": (3, 5),
                "warmup_rounds": 1,
                "warmup_note_limit": 4,
                "use_profile_peek": False,
                "warmup_detail_peek_probability": 0.28,
                "extra_long_pause_probability": 0.11,
            },
            {
                "profile_prep_range": (1.0, 2.2),
                "account_pause_range": (1.4, 3.1),
                "account_long_pause_range": (4.8, 8.2),
                "detail_pause_range": (1.0, 2.2),
                "detail_long_pause_range": (3.5, 6.6),
                "retry_backoff_range": (1.2, 2.8),
                "context_switch_range": (2.4, 4.4),
                "inter_batch_pause_range": (3.0, 5.8),
                "env_order_window": (2, 3),
                "detail_order_window": (4, 6),
                "warmup_rounds": 2,
                "warmup_note_limit": 5,
                "use_profile_peek": True,
                "warmup_detail_peek_probability": 0.45,
                "extra_long_pause_probability": 0.16,
            },
            {
                "profile_prep_range": (1.2, 2.6),
                "account_pause_range": (1.8, 3.6),
                "account_long_pause_range": (5.2, 9.0),
                "detail_pause_range": (1.2, 2.5),
                "detail_long_pause_range": (3.8, 7.0),
                "retry_backoff_range": (1.4, 3.0),
                "context_switch_range": (2.8, 4.9),
                "inter_batch_pause_range": (3.4, 6.3),
                "env_order_window": (2, 4),
                "detail_order_window": (4, 7),
                "warmup_rounds": 3,
                "warmup_note_limit": 6,
                "use_profile_peek": True,
                "warmup_detail_peek_probability": 0.58,
                "extra_long_pause_probability": 0.2,
            },
        ]
        selected = dict(_SYNC_BROWSER_CONFIG_RNG.choice(styles))
        return SyncSessionPersona(**selected)

    async def _sleep_sync_profile_prep(self, persona: SyncSessionPersona | None = None) -> None:
        active = persona or self._build_sync_session_persona()
        await self._sleep_humanized(*active.profile_prep_range)

    async def _sleep_between_account_note_accounts(self, persona: SyncSessionPersona | None = None) -> None:
        active = persona or self._build_sync_session_persona()
        if _SYNC_BROWSER_CONFIG_RNG.random() < 0.18:
            await self._sleep_humanized(*active.account_long_pause_range)
            return
        await self._sleep_humanized(*active.account_pause_range)

    async def _sleep_between_account_note_details(self, persona: SyncSessionPersona | None = None) -> None:
        active = persona or self._build_sync_session_persona()
        if _SYNC_BROWSER_CONFIG_RNG.random() < active.extra_long_pause_probability:
            await self._sleep_humanized(*active.detail_long_pause_range)
            return
        await self._sleep_humanized(*active.detail_pause_range)

    async def _sleep_sync_retry_backoff(self, persona: SyncSessionPersona | None = None) -> None:
        active = persona or self._build_sync_session_persona()
        await self._sleep_humanized(*active.retry_backoff_range)

    async def _sleep_between_account_note_context_switch(self, persona: SyncSessionPersona | None = None) -> None:
        active = persona or self._build_sync_session_persona()
        await self._sleep_humanized(*active.context_switch_range)

    async def _sleep_between_sync_batches(self, persona: SyncSessionPersona | None = None) -> None:
        active = persona or self._build_sync_session_persona()
        await self._sleep_humanized(*active.inter_batch_pause_range)

    @staticmethod
    def _parse_sync_json_object(raw: str, error_prefix: str) -> dict:
        normalized = str(raw or "").strip()
        if not normalized:
            return {}
        try:
            parsed = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{error_prefix} JSON 无效: {exc.msg}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{error_prefix} 必须是 JSON 对象")
        return XHSService._materialize_sync_browser_start_config(parsed)

    @staticmethod
    def _sync_exception_message(exc: BaseException) -> str:
        message = str(exc).strip()
        if message:
            return message
        if isinstance(exc, httpx.TimeoutException):
            return f"小红书接口等待超时（{type(exc).__name__}）"
        return type(exc).__name__

    @staticmethod
    def _http_error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except Exception:
            payload = None
        candidates: list[Any] = []
        if isinstance(payload, dict):
            candidates.extend((payload.get("message"), payload.get("msg"), payload.get("detail")))
            error = payload.get("error")
            if isinstance(error, dict):
                candidates.extend((error.get("message"), error.get("detail"), error.get("details")))
            else:
                candidates.append(error)
        details: list[str] = []
        for candidate in candidates:
            if candidate is None:
                continue
            if isinstance(candidate, (dict, list)):
                normalized = json.dumps(candidate, ensure_ascii=False)
            else:
                normalized = str(candidate).strip()
            if normalized and normalized not in details:
                details.append(normalized)
        if details:
            return "；".join(details)[:1600]
        return str(getattr(response, "text", "") or "").strip()[:1600]

    @staticmethod
    def _shuffle_in_windows(items: list, *, min_window: int, max_window: int) -> list:
        normalized = list(items)
        if len(normalized) < 2:
            return normalized
        lower = max(2, int(min_window))
        upper = max(lower, int(max_window))
        result: list = []
        index = 0
        while index < len(normalized):
            remaining = len(normalized) - index
            if remaining < 2:
                result.extend(normalized[index:])
                break
            window_size = min(remaining, _SYNC_BROWSER_CONFIG_RNG.randint(lower, upper))
            window_items = list(normalized[index:index + window_size])
            _SYNC_BROWSER_CONFIG_RNG.shuffle(window_items)
            result.extend(window_items)
            index += window_size
        return result

    @classmethod
    def _humanize_environment_sync_order(
        cls,
        envs: list[XHSEnvironment],
        persona: SyncSessionPersona | None = None,
    ) -> list[XHSEnvironment]:
        active = persona or cls._build_sync_session_persona()
        return cls._shuffle_in_windows(
            envs,
            min_window=active.env_order_window[0],
            max_window=active.env_order_window[1],
        )

    @classmethod
    def _humanize_account_note_detail_order(
        cls,
        notes: list[XHSAccountNote],
        persona: SyncSessionPersona | None = None,
    ) -> list[XHSAccountNote]:
        if len(notes) < 2:
            return list(notes)
        active = persona or cls._build_sync_session_persona()
        grouped: dict[int, list[XHSAccountNote]] = {}
        env_order: list[int] = []
        for note in notes:
            env_id = int(note.environment_id or 0)
            bucket = grouped.get(env_id)
            if bucket is None:
                bucket = []
                grouped[env_id] = bucket
                env_order.append(env_id)
            bucket.append(note)

        ordered_env_ids = (
            cls._shuffle_in_windows(
                env_order,
                min_window=active.env_order_window[0],
                max_window=active.env_order_window[1],
            )
            if len(env_order) > 1
            else env_order
        )
        result: list[XHSAccountNote] = []
        for env_id in ordered_env_ids:
            result.extend(
                cls._shuffle_in_windows(
                    grouped.get(env_id) or [],
                    min_window=active.detail_order_window[0],
                    max_window=active.detail_order_window[1],
                )
            )
        return result

    @staticmethod
    def _is_sync_runner_environment(env: XHSEnvironment) -> bool:
        return bool(getattr(env, "is_sync_runner", False)) or bool(re.search(r"测试[2345]", getattr(env, "account_name", "") or ""))

    @staticmethod
    def _local_browser_ops_enabled() -> bool:
        return XHS_ENABLE_LOCAL_BROWSER_OPS

    @staticmethod
    def _worker_api_available() -> bool:
        return bool(XHS_WORKER_API_BASE)

    @classmethod
    def _should_delegate_browser_ops(cls) -> bool:
        return (not cls._local_browser_ops_enabled()) and cls._worker_api_available()

    @classmethod
    def _require_local_browser_ops(cls, action: str) -> None:
        if cls._local_browser_ops_enabled():
            return
        if cls._worker_api_available():
            raise RuntimeError(f"{action} 需要通过 Windows 浏览器 Worker 执行，请走委派接口")
        raise RuntimeError(f"{action} 需要本地浏览器执行环境，请启用 Windows 浏览器 Worker")

    @staticmethod
    def _worker_headers() -> dict[str, str]:
        headers: dict[str, str] = {}
        if XHS_WORKER_INTERNAL_TOKEN:
            headers["X-XHS-Worker-Token"] = XHS_WORKER_INTERNAL_TOKEN
        return headers

    @staticmethod
    def _report_worker_api_available() -> bool:
        return bool(XHS_REPORT_WORKER_API_BASE)

    @staticmethod
    def _report_worker_headers() -> dict[str, str]:
        headers: dict[str, str] = {}
        if XHS_REPORT_WORKER_INTERNAL_TOKEN:
            headers["X-XHS-Worker-Token"] = XHS_REPORT_WORKER_INTERNAL_TOKEN
        return headers

    @staticmethod
    def _uploads_public_base_url() -> str:
        return UPLOADS_PUBLIC_BASE_URL

    @staticmethod
    def _normalize_account_note_sync_mode(value: str | None) -> str:
        normalized = str(value or "all").strip().lower()
        if normalized not in {"all", "unpublished_only"}:
            raise ValueError("sync_mode 仅支持 all 或 unpublished_only")
        return normalized

    @staticmethod
    def _normalize_account_note_sync_limit(value: int | None) -> int | None:
        if value is None:
            return None
        try:
            normalized = int(value)
        except Exception as exc:
            raise ValueError("sync_limit 必须是整数") from exc
        if normalized <= 0:
            raise ValueError("sync_limit 必须大于 0")
        return min(normalized, 1000)

    @staticmethod
    def _normalize_account_note_sync_account_limit(value: int | None) -> int | None:
        if value is None:
            return None
        try:
            normalized = int(value)
        except Exception as exc:
            raise ValueError("同步账号数量必须是整数") from exc
        if normalized <= 0:
            raise ValueError("同步账号数量必须大于 0")
        return min(normalized, 200)

    @staticmethod
    def _normalize_yundeng_sync_concurrency(value: int | None) -> int:
        if value is None:
            return XHS_YUNDENG_SYNC_CONCURRENCY
        try:
            normalized = int(value)
        except Exception as exc:
            raise ValueError("云登同步并发数必须是整数") from exc
        if normalized <= 0:
            raise ValueError("云登同步并发数必须大于 0")
        return min(normalized, XHS_YUNDENG_SYNC_CONCURRENCY, 5)

    @staticmethod
    def _normalize_account_note_sync_runner_assignments(
        value: str | dict[int | str, list[int] | tuple[int, ...] | set[int] | list[str] | tuple[str, ...]] | None
    ) -> dict[int, list[int]]:
        if value in (None, ""):
            return {}
        raw_mapping: Any = value
        if isinstance(value, str):
            try:
                raw_mapping = json.loads(value)
            except Exception as exc:
                raise ValueError("测试账号分配配置必须是合法 JSON") from exc
        if not isinstance(raw_mapping, dict):
            raise ValueError("测试账号分配配置必须是对象")

        normalized: dict[int, list[int]] = {}
        assigned_publish_ids: set[int] = set()
        for raw_runner_id, raw_publish_ids in raw_mapping.items():
            try:
                runner_id = int(str(raw_runner_id).strip())
            except Exception as exc:
                raise ValueError("测试账号 ID 必须是数字") from exc
            if runner_id <= 0:
                continue
            if not isinstance(raw_publish_ids, (list, tuple, set)):
                raise ValueError("每个测试账号对应的发布账号必须是数组")
            normalized_publish_ids: list[int] = []
            seen_publish_ids: set[int] = set()
            for raw_publish_id in raw_publish_ids:
                try:
                    publish_id = int(str(raw_publish_id).strip())
                except Exception as exc:
                    raise ValueError("发布账号 ID 必须是数字") from exc
                if publish_id <= 0 or publish_id in seen_publish_ids:
                    continue
                if publish_id in assigned_publish_ids:
                    raise ValueError("同一个发布账号不能同时分配给多个测试账号")
                seen_publish_ids.add(publish_id)
                assigned_publish_ids.add(publish_id)
                normalized_publish_ids.append(publish_id)
            if normalized_publish_ids:
                normalized[runner_id] = normalized_publish_ids
        return normalized

    @staticmethod
    def _normalize_account_note_sync_runner_ids(value: str | list[int] | tuple[int, ...] | None) -> list[int]:
        if value is None:
            return []
        raw_items: list[object]
        if isinstance(value, str):
            raw_items = [item.strip() for item in value.split(",")]
        else:
            raw_items = list(value)

        normalized: list[int] = []
        seen: set[int] = set()
        for item in raw_items:
            if item in (None, ""):
                continue
            try:
                parsed = int(str(item).strip())
            except Exception as exc:
                raise ValueError("同步环境列表必须是数字 ID") from exc
            if parsed <= 0 or parsed in seen:
                continue
            seen.add(parsed)
            normalized.append(parsed)
        return normalized

    @staticmethod
    def _normalize_account_note_sync_limit_per_runner(value: int | None) -> int | None:
        if value is None:
            return None
        try:
            normalized = int(value)
        except Exception as exc:
            raise ValueError("每个同步环境处理条数必须是整数") from exc
        if normalized <= 0:
            raise ValueError("每个同步环境处理条数必须大于 0")
        return min(normalized, 60)

    @staticmethod
    def _normalize_account_note_max_age_days(value: int | None) -> int | None:
        if value is None:
            return 30
        try:
            normalized = int(value)
        except Exception as exc:
            raise ValueError("帖子天数范围必须是整数") from exc
        if normalized <= 0:
            return None
        return min(normalized, 3650)

    @staticmethod
    def _normalize_account_note_sync_pause_seconds(value: float | int | None, *, field_name: str) -> float | None:
        if value is None:
            return None
        try:
            normalized = float(value)
        except Exception as exc:
            raise ValueError(f"{field_name} 必须是数字") from exc
        if normalized < 0:
            raise ValueError(f"{field_name} 不能小于 0")
        return min(normalized, 900.0)

    @staticmethod
    def _xhs_timestamp_ms_to_utc_naive(value: object) -> datetime | None:
        try:
            raw = str(value or "").strip()
            if not raw:
                return None
            ms = int(float(raw))
            if ms <= 0:
                return None
            return datetime.utcfromtimestamp(ms / 1000.0)
        except Exception:
            return None

    @classmethod
    async def _call_worker_api(
        cls,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        timeout: float = 60.0,
    ) -> dict:
        if not cls._worker_api_available():
            raise RuntimeError("未配置 Windows 浏览器 Worker 地址")

        url = f"{XHS_WORKER_API_BASE}{path}"
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            resp = await client.request(
                method,
                url,
                json=json,
                params=params,
                headers=cls._worker_headers(),
            )
        payload = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            detail = (
                payload.get("detail")
                or payload.get("message")
                or payload.get("error")
                or f"HTTP {resp.status_code}"
            )
            raise RuntimeError(str(detail))
        if isinstance(payload, dict) and payload.get("code") not in (None, 0):
            raise RuntimeError(str(payload.get("message") or "Windows 浏览器 Worker 执行失败"))
        return payload

    @classmethod
    async def _call_report_worker_api(
        cls,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        timeout: float = 60.0,
    ) -> dict:
        if not cls._report_worker_api_available():
            raise RuntimeError("未配置报表 Worker 地址")

        url = f"{XHS_REPORT_WORKER_API_BASE}{path}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(
                method,
                url,
                json=json,
                params=params,
                headers=cls._report_worker_headers(),
            )
        payload = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            detail = (
                payload.get("detail")
                or payload.get("message")
                or payload.get("error")
                or f"HTTP {resp.status_code}"
            )
            raise RuntimeError(str(detail))
        if isinstance(payload, dict) and payload.get("code") not in (None, 0):
            raise RuntimeError(str(payload.get("message") or "报表 Worker 执行失败"))
        return payload

    @classmethod
    async def trigger_worker_publish(cls, post_id: int) -> None:
        await cls._call_worker_api("POST", f"/api/v1/xhs/internal/posts/{post_id}/execute", timeout=30.0)

    @classmethod
    async def trigger_worker_sync_environments(cls) -> int:
        payload = await cls._call_worker_api("POST", "/api/v1/xhs/internal/sync-environments", timeout=120.0)
        data = payload.get("data") or {}
        return int(data.get("synced_count") or 0)

    @classmethod
    async def trigger_worker_sync_all_posts(cls) -> int:
        payload = await cls._call_worker_api("POST", "/api/v1/xhs/internal/sync-all-posts", timeout=600.0)
        data = payload.get("data") or {}
        return int(data.get("synced_count") or 0)

    @classmethod
    async def trigger_worker_sync_account_notes(
        cls,
        env_id: int | None = None,
        scrape_environment_id: int | None = None,
        scrape_environment_ids: str | None = None,
        sync_account_limit: int | None = None,
        runner_account_assignments: str | None = None,
    ) -> dict:
        params: dict[str, str | int] = {}
        if env_id:
            params["environment_id"] = env_id
        if scrape_environment_id:
            params["scrape_environment_id"] = scrape_environment_id
        if scrape_environment_ids:
            params["scrape_environment_ids"] = scrape_environment_ids
        if sync_account_limit:
            params["sync_account_limit"] = sync_account_limit
        if runner_account_assignments:
            params["runner_account_assignments"] = runner_account_assignments
        payload = await cls._call_worker_api(
            "POST",
            "/api/v1/xhs/internal/account-notes/sync",
            params=params or None,
            timeout=900.0,
        )
        return payload.get("data") or {}

    @classmethod
    async def trigger_worker_sync_account_note_engagements(
        cls,
        environment_id: int,
        sync_run_id: int | None = None,
    ) -> dict:
        params: dict[str, int] = {"environment_id": int(environment_id)}
        if sync_run_id:
            params["sync_run_id"] = int(sync_run_id)
        payload = await cls._call_worker_api(
            "POST",
            "/api/v1/xhs/internal/account-notes/sync-engagement",
            params=params,
            timeout=900.0,
        )
        return payload.get("data") or {}

    async def _delegate_account_note_engagement_sync(
        self,
        *,
        envs: list[XHSEnvironment],
        concurrency: int,
        sync_run_id: int | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> dict:
        semaphore = asyncio.Semaphore(
            max(1, min(int(concurrency or 1), len(envs) or 1, XHS_YUNDENG_SYNC_CONCURRENCY, 5))
        )

        async def run_environment(env: XHSEnvironment) -> tuple[XHSEnvironment, dict]:
            await self._raise_if_sync_cancelled(cancel_check)
            async with semaphore:
                result = await self.trigger_worker_sync_account_note_engagements(int(env.id), sync_run_id)
                return env, result

        raw_results = await asyncio.gather(
            *(run_environment(env) for env in envs),
            return_exceptions=True,
        )
        return await self._aggregate_parallel_engagement_results(
            envs=envs,
            raw_results=raw_results,
            progress_callback=progress_callback,
        )

    async def _delegate_account_note_sync_by_runner(
        self,
        *,
        envs: list[XHSEnvironment],
        runner_ids: list[int],
        runner_assignments: dict[int, list[int]],
        concurrency: int = 5,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> dict:
        """Send one independent worker request per browser runner.

        A runner can only drive one YunLogin browser safely, so accounts within
        its bucket remain serial. Different runners use different browsers and
        are deliberately dispatched concurrently.
        """
        effective_assignments = {
            int(runner_id): list(environment_ids)
            for runner_id, environment_ids in runner_assignments.items()
            if environment_ids
        }
        if not effective_assignments:
            for index, env in enumerate(envs):
                runner_id = runner_ids[index % len(runner_ids)]
                effective_assignments.setdefault(runner_id, []).append(int(env.id))

        buckets = list(effective_assignments.items())
        await self._emit_progress(
            progress_callback,
            {
                "phase": "dispatching_account_post_runners",
                "detail": f"正在并行下发 {len(buckets)} 个测试账号",
                "current": 0,
                "total": len(envs),
                "percent": 0,
                "runner_count": len(buckets),
            },
        )

        async def run_bucket(runner_id: int, environment_ids: list[int]) -> tuple[int, list[int], dict]:
            await self._raise_if_sync_cancelled(cancel_check)
            result = await self.trigger_worker_sync_account_notes(
                env_id=None,
                scrape_environment_id=runner_id,
                scrape_environment_ids=str(runner_id),
                sync_account_limit=len(environment_ids),
                runner_account_assignments=json.dumps({runner_id: environment_ids}, ensure_ascii=False),
            )
            return runner_id, environment_ids, result

        semaphore = asyncio.Semaphore(max(1, min(int(concurrency or 1), XHS_YUNDENG_SYNC_CONCURRENCY, 5)))

        async def run_bucket_bounded(runner_id: int, environment_ids: list[int]) -> tuple[int, list[int], dict]:
            async with semaphore:
                return await run_bucket(runner_id, environment_ids)

        raw_results = await asyncio.gather(
            *(run_bucket_bounded(runner_id, environment_ids) for runner_id, environment_ids in buckets),
            return_exceptions=True,
        )

        totals = {
            "synced_accounts": 0,
            "created_notes": 0,
            "updated_notes": 0,
            "metric_synced_notes": 0,
            "total_notes": 0,
        }
        failed_runners: list[dict[str, Any]] = []
        failed_accounts: list[dict[str, Any]] = []
        completed_targets = 0
        for bucket, raw_result in zip(buckets, raw_results):
            runner_id, environment_ids = bucket
            if isinstance(raw_result, Exception):
                error_message = self._sync_exception_message(raw_result)
                logger.warning(
                    "测试账号并行同步失败: runner_id=%s targets=%s error=%s",
                    runner_id,
                    environment_ids,
                    error_message,
                )
                failed_runners.append({
                    "runner_id": runner_id,
                    "environment_ids": environment_ids,
                    "error": error_message,
                })
                continue

            _, _, result = raw_result
            # A target with no new notes is still a completed target. Do not
            # leave the parent task below 100% merely because a worker reports
            # zero changed accounts.
            completed_targets += len(environment_ids)
            for key in totals:
                totals[key] += int(result.get(key) or 0)
            failed_accounts.extend(result.get("failed_accounts") or [])
            failed_runners.extend(result.get("failed_runners") or [])

        await self._emit_progress(
            progress_callback,
            {
                "phase": "account_post_runners_completed",
                "detail": "测试账号并行同步完成" if not failed_runners else "部分测试账号同步失败",
                "current": completed_targets,
                "total": len(envs),
                "percent": int((completed_targets / len(envs)) * 100) if envs else 100,
                "runner_count": len(buckets),
                "failed_runner_count": len(failed_runners),
                **totals,
            },
        )
        if failed_runners:
            totals["failed_runners"] = failed_runners
        if failed_accounts:
            totals["failed_accounts"] = failed_accounts
        return totals

    async def _delegate_account_note_detail_sync_by_runner(
        self,
        *,
        active_note_ids: list[int],
        matched_notes: int,
        skipped_notes: int,
        runner_ids: list[int],
        sync_limit_per_runner: int | None,
        pause_seconds_min: float | None,
        pause_seconds_max: float | None,
        max_post_age_days: int | None,
        concurrency: int = 5,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> dict:
        """Run detail-sync buckets concurrently across independent browsers."""
        buckets: dict[int, list[int]] = {runner_id: [] for runner_id in runner_ids}
        for index, note_id in enumerate(active_note_ids):
            buckets[runner_ids[index % len(runner_ids)]].append(note_id)
        buckets = {runner_id: note_ids for runner_id, note_ids in buckets.items() if note_ids}

        await self._emit_progress(
            progress_callback,
            {
                "phase": "dispatching_note_detail_runners",
                "detail": f"正在并行下发 {len(buckets)} 个测试账号",
                "current": 0,
                "total": len(active_note_ids),
                "percent": 0,
                "runner_count": len(buckets),
            },
        )

        async def run_bucket(runner_id: int, note_ids: list[int]) -> tuple[int, list[int], dict]:
            await self._raise_if_sync_cancelled(cancel_check)
            result = await self.trigger_worker_sync_account_note_details(
                env_id=None,
                target_note_ids=",".join(str(note_id) for note_id in note_ids),
                scrape_environment_id=runner_id,
                scrape_environment_ids=str(runner_id),
                sync_mode="all",
                sync_limit=None,
                sync_limit_per_runner=sync_limit_per_runner,
                pause_seconds_min=pause_seconds_min,
                pause_seconds_max=pause_seconds_max,
                max_post_age_days=max_post_age_days,
            )
            return runner_id, note_ids, result

        semaphore = asyncio.Semaphore(max(1, min(int(concurrency or 1), XHS_YUNDENG_SYNC_CONCURRENCY, 5)))

        async def run_bucket_bounded(runner_id: int, note_ids: list[int]) -> tuple[int, list[int], dict]:
            async with semaphore:
                return await run_bucket(runner_id, note_ids)

        raw_results = await asyncio.gather(
            *(run_bucket_bounded(runner_id, note_ids) for runner_id, note_ids in buckets.items()),
            return_exceptions=True,
        )

        totals: dict[str, Any] = {
            "total_notes": len(active_note_ids),
            "matched_notes": matched_notes,
            "synced_notes": 0,
            "failed_notes": 0,
            "skipped_notes": skipped_notes,
            "strategy_runner_count": len(buckets),
        }
        synced_note_ids: list[int] = []
        failed_note_ids: list[int] = []
        failed_runners: list[dict[str, Any]] = []
        completed_notes = 0
        for (runner_id, note_ids), raw_result in zip(buckets.items(), raw_results):
            completed_notes += len(note_ids)
            if isinstance(raw_result, Exception):
                logger.warning(
                    "测试账号并行同步帖子详情失败: runner_id=%s notes=%s error=%s",
                    runner_id,
                    len(note_ids),
                    raw_result,
                )
                totals["failed_notes"] += len(note_ids)
                failed_note_ids.extend(note_ids)
                failed_runners.append({"runner_id": runner_id, "note_ids": note_ids, "error": str(raw_result)})
                continue

            _, _, result = raw_result
            totals["synced_notes"] += int(result.get("synced_notes") or 0)
            totals["failed_notes"] += int(result.get("failed_notes") or 0)
            synced_note_ids.extend(int(note_id) for note_id in result.get("synced_note_ids") or [])
            failed_note_ids.extend(int(note_id) for note_id in result.get("failed_note_ids") or [])

        totals["synced_note_ids"] = synced_note_ids
        totals["failed_note_ids"] = failed_note_ids
        if failed_runners:
            totals["failed_runners"] = failed_runners
        await self._emit_progress(
            progress_callback,
            {
                "phase": "note_detail_runners_completed",
                "detail": "测试账号并行同步完成" if not failed_runners else "部分测试账号同步失败",
                "current": completed_notes,
                "total": len(active_note_ids),
                "percent": int((completed_notes / len(active_note_ids)) * 100) if active_note_ids else 100,
                "runner_count": len(buckets),
                "failed_runner_count": len(failed_runners),
                **totals,
            },
        )
        return totals

    @classmethod
    async def trigger_worker_sync_account_note_details(
        cls,
        env_id: int | None = None,
        target_note_ids: str | None = None,
        scrape_environment_id: int | None = None,
        scrape_environment_ids: str | None = None,
        sync_mode: str = "all",
        sync_limit: int | None = None,
        sync_limit_per_runner: int | None = None,
        pause_seconds_min: float | None = None,
        pause_seconds_max: float | None = None,
        max_post_age_days: int | None = None,
    ) -> dict:
        params: dict[str, str | int] = {"sync_mode": sync_mode}
        if env_id:
            params["environment_id"] = env_id
        if target_note_ids:
            params["target_note_ids"] = target_note_ids
        if scrape_environment_id:
            params["scrape_environment_id"] = scrape_environment_id
        if scrape_environment_ids:
            params["scrape_environment_ids"] = scrape_environment_ids
        if sync_limit:
            params["sync_limit"] = sync_limit
        if sync_limit_per_runner:
            params["sync_limit_per_runner"] = sync_limit_per_runner
        if max_post_age_days is not None:
            params["max_post_age_days"] = max_post_age_days
        if pause_seconds_min is not None:
            params["pause_seconds_min"] = f"{pause_seconds_min:.2f}"
        if pause_seconds_max is not None:
            params["pause_seconds_max"] = f"{pause_seconds_max:.2f}"
        payload = await cls._call_worker_api(
            "POST",
            "/api/v1/xhs/internal/account-notes/sync-details",
            params=params,
            timeout=1800.0,
        )
        return payload.get("data") or {}

    @classmethod
    async def trigger_worker_sync_single_post(cls, post_id: int) -> None:
        await cls._call_worker_api("POST", f"/api/v1/xhs/internal/posts/{post_id}/sync-stats", timeout=420.0)

    @classmethod
    async def trigger_worker_remote_edit(
        cls,
        *,
        post_id: int,
        title: str,
        content: str,
        tags: list[str] | None = None,
    ) -> None:
        await cls._call_worker_api(
            "POST",
            f"/api/v1/xhs/internal/posts/{post_id}/edit",
            json={"title": title, "content": content, "tags": tags or []},
            timeout=420.0,
        )

    @classmethod
    async def trigger_worker_remote_delete(cls, *, post_id: int) -> None:
        await cls._call_worker_api("POST", f"/api/v1/xhs/internal/posts/{post_id}/delete", timeout=420.0)

    @staticmethod
    def _extract_account_id_from_env(env: XHSEnvironment) -> Optional[str]:
        if env.id and env.id >= 100000:
            return str(env.id)
        candidates = [env.notes or "", env.labels or "", env.group_name or "", env.shop_id or "", env.account_name or ""]
        for text in candidates:
            m = re.search(r"(?<!\d)(\d{6,})(?!\d)", text)
            if m:
                return m.group(1)
        return None

    @staticmethod
    def _default_report_range(days: int = 30) -> tuple[str, str]:
        end_d = cst_now_naive().date()
        start_d = end_d - timedelta(days=max(days, 1) - 1)
        return start_d.isoformat(), end_d.isoformat()

    @classmethod
    def _normalize_report_date_range(
        cls,
        *,
        start_date: str | None,
        end_date: str | None,
        days: int = 30,
    ) -> tuple[str, str]:
        if not start_date or not end_date:
            return cls._default_report_range(days=days)

        try:
            start_d = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_d = datetime.strptime(end_date, "%Y-%m-%d").date()
        except Exception:
            return cls._default_report_range(days=days)

        max_end_d = cst_now_naive().date()
        if end_d > max_end_d:
            end_d = max_end_d
        if start_d > end_d:
            start_d = end_d - timedelta(days=max(days, 1) - 1)

        return start_d.isoformat(), end_d.isoformat()

    @staticmethod
    def _normalize_report_row(row: dict | None, *, account_id: str | None = None, account_name: str | None = None) -> dict:
        payload = dict(row or {})
        if account_id is not None:
            payload["account_id"] = account_id
        if account_name is not None:
            payload["account_name"] = account_name

        # The official CSV export for account 8343103 shows these two "人数" fields
        # following the corresponding "数" fields when the API payload omits them.
        if payload.get("msg_leads_user_cnt") in (None, ""):
            payload["msg_leads_user_cnt"] = payload.get("msg_leads_num")
        if payload.get("msg_chat_user_cnt") in (None, ""):
            payload["msg_chat_user_cnt"] = payload.get("initiative_message")
        return payload

    @staticmethod
    def _normalize_creative_report_row(row: dict | None, *, account_id: str | None = None, account_name: str | None = None) -> dict:
        payload = XHSService._normalize_report_row(row, account_id=account_id, account_name=account_name)

        def fill(target: str, *candidates: str) -> None:
            if str(payload.get(target) or "").strip():
                return
            for key in candidates:
                value = payload.get(key)
                if value not in (None, ""):
                    payload[target] = value
                    return

        fill("time", "date", "stat_date")
        fill("creative", "creative_type", "creative_style", "creative_form")
        fill("creative_name", "ad_name", "material_name", "note_name")
        fill("creative_id", "ad_id", "creativeId", "material_id", "note_id")
        fill("note_material", "note_name", "material_name", "note_material_name", "asset_name", "creative_id", "ad_id", "creativeId", "material_id", "item_id")
        fill("unit_name", "promotion_name", "unitName", "adgroup_name")
        fill("unit_id", "promotion_id", "unitId", "adgroup_id")
        fill("campaign_name", "plan_name")
        fill("campaign_id", "plan_id")
        fill("ctr", "click_rate")
        fill("cpc", "acp", "avg_click_cost", "click_avg_cost")
        fill("cpm", "avg_cpm", "thousand_impression_fee")
        fill("avg_interaction_cost", "interaction_cost", "interaction_avg_cost")
        fill("play_5s", "video_play_5s_cnt", "play_5s_count", "play5s")
        fill("play_5s_rate", "play_5s_finish_rate", "play5s_rate")
        fill("new_seed_crowd", "new_brand_search_user", "new_interest_user")
        fill("new_seed_crowd_cost", "new_brand_search_user_cost", "new_interest_user_cost")
        fill("new_deep_seed_crowd", "new_deep_brand_search_user", "new_deep_interest_user")
        fill("new_deep_seed_crowd_cost", "new_deep_brand_search_user_cost", "new_deep_interest_user_cost")
        fill("message_consult_cost", "message_consult_cpl", "message_user_cost", "message_consult_avg_cost")
        fill("initiative_message_cost", "initiative_message_cpl", "initiative_message_avg_cost", "message_avg_cost")
        fill("msg_leads_cost", "msg_leads_avg_cost", "message_leads_cost")
        fill("shop_pay_order_num_15d", "current_app_pay_cnt", "shop_order_cnt_15d")
        fill("shop_pay_order_cvr_15d", "click_order_cvr", "shop_order_cvr_15d")
        fill("shop_visit_num_15d", "goods_visit_cnt", "shop_visit_cnt_15d")
        fill("shop_visit_rate_15d", "goods_visit_rate", "shop_visit_cvr_15d")

        if payload.get("avg_interaction_cost") in (None, "", "-"):
            try:
                fee = float(str(payload.get("fee") or "0").strip() or 0)
                interaction = float(str(payload.get("interaction") or "0").strip() or 0)
                payload["avg_interaction_cost"] = f"{(fee / interaction):.2f}" if interaction > 0 else "0.00"
            except Exception:
                pass
        return payload

    @staticmethod
    def _normalize_note_report_row(row: dict | None, *, account_id: str | None = None, account_name: str | None = None) -> dict:
        payload = XHSService._normalize_report_row(row, account_id=account_id, account_name=account_name)

        def fill(target: str, *candidates: str) -> None:
            if str(payload.get(target) or "").strip():
                return
            for key in candidates:
                value = payload.get(key)
                if value not in (None, ""):
                    payload[target] = value
                    return

        fill("time", "date", "stat_date")
        fill("note_title", "note_name", "title", "note_material", "material_name")
        fill("note_id", "noteId", "feed_id", "item_id", "material_id")
        fill("note_image", "cover_url", "note_cover_url", "image_url", "material_image", "creativity_image")
        fill("campaign_name", "plan_name", "promotion_name")
        fill("campaign_id", "plan_id", "promotion_id")
        fill("ctr", "click_rate")
        return payload

    @staticmethod
    def _normalize_jg_report_row(report_type: str, row: dict | None, *, account_id: str | None = None, account_name: str | None = None) -> dict:
        if report_type == "creative":
            return XHSService._normalize_creative_report_row(row, account_id=account_id, account_name=account_name)
        if report_type in {"simple_note", "standard_note"}:
            return XHSService._normalize_note_report_row(row, account_id=account_id, account_name=account_name)
        return XHSService._normalize_report_row(row, account_id=account_id, account_name=account_name)

    @staticmethod
    def _report_row_campaign_key(report_type: str, payload: dict | None) -> str:
        data = dict(payload or {})
        if report_type == "standard":
            for key in ("campaign_id", "plan_id", "promotion_id", "unit_id"):
                value = str(data.get(key) or "").strip()
                if value:
                    return value
            for key in ("campaign_name", "plan_name", "promotion_name", "unit_name"):
                value = str(data.get(key) or "").strip()
                if value:
                    return value
        elif report_type in {"simple_note", "standard_note"}:
            stable = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            fingerprint = hashlib.md5(stable.encode("utf-8")).hexdigest()[:12]
            note_parts = [
                str(data.get("note_id") or data.get("noteId") or data.get("feed_id") or "").strip(),
                str(data.get("campaign_id") or data.get("plan_id") or data.get("promotion_id") or "").strip(),
                str(data.get("unit_id") or data.get("adgroup_id") or "").strip(),
                str(data.get("creation_type") or data.get("data_caliber") or "").strip(),
            ]
            if any(note_parts):
                return "|".join([part for part in note_parts if part] + [fingerprint])[:128]
            for key in ("note_title", "note_name", "title"):
                value = str(data.get(key) or "").strip()
                if value:
                    return f"{value}|{fingerprint}"[:128]
        elif report_type == "creative":
            creative_parts = [
                str(data.get("creativity_id") or "").strip(),
                str(data.get("creative_id") or data.get("ad_id") or data.get("creativeId") or data.get("material_id") or data.get("item_id") or "").strip(),
                str(data.get("unit_id") or data.get("promotion_id") or data.get("adgroup_id") or "").strip(),
                str(data.get("campaign_id") or data.get("plan_id") or "").strip(),
            ]
            if any(creative_parts):
                return "|".join(creative_parts)
            for key in ("creative_name", "creativeName", "ad_name", "material_name", "item_name"):
                value = str(data.get(key) or "").strip()
                if value:
                    return value
        else:
            for key in ("campaign_id", "promotion_id"):
                value = str(data.get(key) or "").strip()
                if value:
                    return value

        stable = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.md5(stable.encode("utf-8")).hexdigest()

    async def _fetch_report_token_local(self, account_id: str) -> str:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(XHS_REPORT_TOKEN_API, params={"id": account_id})
            data = resp.json()
            if data.get("code") == 401 or ("失效" in str(data.get("message", "")) and not data.get("result")):
                raise RuntimeError("Token失效，请在ztcar后台重新登录该账号后重试")
            if not data.get("success") or not data.get("result"):
                raise RuntimeError(f"token接口失败: {data.get('message') or data}")
            return str(data["result"])

    @classmethod
    async def trigger_worker_fetch_report_token(cls, account_id: str) -> str:
        payload = await cls._call_report_worker_api(
            "GET",
            "/api/v1/xhs/internal/report-token",
            params={"account_id": account_id},
            timeout=30.0,
        )
        data = payload.get("data") or {}
        token = str(data.get("token") or "").strip()
        if not token:
            raise RuntimeError("报表 Worker 未返回有效 token")
        return token

    async def _fetch_report_token(self, account_id: str, *, allow_remote: bool = True) -> str:
        normalized_account_id = str(account_id or "").strip()
        if not normalized_account_id:
            raise RuntimeError("缺少账户ID，无法获取报表 token")
        if allow_remote and self._report_worker_api_available():
            return await self.trigger_worker_fetch_report_token(normalized_account_id)
        return await self._fetch_report_token_local(normalized_account_id)

    async def _fetch_report_rows(
        self,
        token: str,
        advertiser_id: str,
        api_path: str,
        start_date: str,
        end_date: str,
    ) -> tuple[list[dict], dict]:
        headers = {"Access-Token": token, "Content-Type": "application/json"}
        rows: list[dict] = []
        page_num = 1
        page_size = 200
        aggregation_data: dict = {}
        async with httpx.AsyncClient(timeout=40.0) as client:
            while True:
                body = {
                    "advertiser_id": advertiser_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    "time_unit": "DAY",
                    "page_num": page_num,
                    "page_size": page_size,
                }
                resp = await client.post(f"{XHS_REPORT_ADAPI_BASE}{api_path}", headers=headers, json=body)
                data = resp.json()
                if not data.get("success"):
                    raise RuntimeError(f"报表接口失败: {data.get('msg') or data.get('message') or data}")
                payload = data.get("data") or {}
                batch = payload.get("data_list") or []
                aggregation_data = payload.get("aggregation_data") or aggregation_data
                rows.extend(batch)

                total_count = None
                page = payload.get("page")
                if isinstance(page, dict):
                    total_count = page.get("total_count")
                if total_count is None:
                    total_count = payload.get("total_count")

                if total_count is not None and len(rows) >= int(total_count):
                    break
                if not batch or len(batch) < page_size:
                    break
                page_num += 1
        return rows, aggregation_data

    async def get_jg_report(
        self,
        user: User,
        report_type: str,
        account_id: Optional[str] = None,
        account_name: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 30,
    ) -> dict:
        api_path = REPORT_API_PATHS.get(report_type)
        if not api_path:
            raise ValueError(f"不支持的报表类型: {report_type}")
        start_date, end_date = self._normalize_report_date_range(
            start_date=start_date,
            end_date=end_date,
            days=days,
        )

        envs = await self.list_environments(user)
        if account_id:
            envs = [x for x in envs if self._extract_account_id_from_env(x) == account_id]
        elif account_name:
            envs = [x for x in envs if x.account_name == account_name]

        reports: list[dict] = []
        for env in envs:
            account_id = self._extract_account_id_from_env(env)
            if not account_id:
                reports.append({
                    "account_name": env.account_name,
                    "account_id": None,
                    "row_count": 0,
                    "rows": [],
                    "aggregation_data": {},
                    "error": "未识别到账户ID（请在账号备注中写入纯数字账户ID）",
                })
                continue
            try:
                token = await self._fetch_report_token(account_id)
                rows, aggregation_data = await self._fetch_report_rows(
                    token=token,
                    advertiser_id=account_id,
                    api_path=api_path,
                    start_date=start_date,
                    end_date=end_date,
                )
                for row in rows:
                    if isinstance(row, dict):
                        normalized = self._normalize_jg_report_row(
                            report_type,
                            row,
                            account_id=account_id,
                            account_name=env.account_name,
                        )
                        row.clear()
                        row.update(normalized)
                reports.append({
                    "account_name": env.account_name,
                    "account_id": account_id,
                    "row_count": len(rows),
                    "rows": rows,
                    "aggregation_data": aggregation_data,
                    "error": None,
                })
            except Exception as e:
                reports.append({
                    "account_name": env.account_name,
                    "account_id": account_id,
                    "row_count": 0,
                    "rows": [],
                    "aggregation_data": {},
                    "error": str(e),
                })

        merged_rows: list[dict] = []
        for item in reports:
            merged_rows.extend(item.get("rows") or [])
        if report_type == "creative":
            merged_rows = await self._attach_account_note_ai_origin_to_report_rows(merged_rows)
        return {
            "report_type": report_type,
            "start_date": start_date,
            "end_date": end_date,
            "account_id": account_id,
            "account_name": account_name,
            "total_accounts": len(reports),
            "total_rows": len(merged_rows),
            "items": reports,
            "rows": merged_rows,
        }

    async def import_report_tokens_from_xls(self, file_path: str) -> dict:
        import xlrd

        wb = xlrd.open_workbook(file_path)
        if "导出信息" not in wb.sheet_names():
            raise RuntimeError("未找到 导出信息 sheet")
        sheet = wb.sheet_by_name("导出信息")
        header = [str(sheet.cell_value(0, c)).strip() for c in range(sheet.ncols)]
        header_map = {name: index for index, name in enumerate(header) if name}
        id_col = header_map.get("账户ID", 0)
        name_col = header_map.get("账户名称", 1 if sheet.ncols > 1 else 0)
        token_col = None
        for name in ("token(今日拉取)", "token", "Token", "TOKEN"):
            if name in header_map:
                token_col = header_map[name]
                break
        status_col = header_map.get("token状态")
        code_col = header_map.get("token接口code")
        msg_col = header_map.get("token接口message")
        ts_col = header_map.get("token时间戳")
        import_mode = "token_export" if token_col is not None else "account_info_only"

        upserted = 0
        valid = 0
        for r in range(1, sheet.nrows):
            account_id = str(sheet.cell_value(r, id_col)).strip().split(".")[0]
            account_name = str(sheet.cell_value(r, name_col)).strip()
            token = str(sheet.cell_value(r, token_col)).strip() if token_col is not None else ""
            token_status = str(sheet.cell_value(r, status_col)).strip() if status_col is not None else ""
            token_code = str(sheet.cell_value(r, code_col)).strip() if code_col is not None else ""
            token_msg = str(sheet.cell_value(r, msg_col)).strip() if msg_col is not None else ""
            token_ts = str(sheet.cell_value(r, ts_col)).strip() if ts_col is not None else ""
            if not account_id:
                continue
            result = await self.db.execute(select(XHSReportToken).where(XHSReportToken.account_id == account_id))
            row = result.scalar_one_or_none()
            if row is None:
                row = XHSReportToken(
                    account_id=account_id,
                    account_name=account_name or account_id,
                )
                self.db.add(row)
            row.account_name = account_name or row.account_name or account_id
            if token_col is not None:
                row.token = token or None
                row.token_status = token_status or None
                row.token_message = f"{token_code}|{token_msg}".strip("|") or None
                row.token_timestamp = token_ts or None
            upserted += 1
            if token:
                valid += 1
        await self.db.commit()
        return {"upserted": upserted, "valid_tokens": valid, "mode": import_mode}

    async def list_report_accounts(self) -> list[dict]:
        rows = (await self.db.execute(
            select(XHSReportToken).order_by(XHSReportToken.account_name.asc())
        )).scalars().all()
        return [{
            "account_id": x.account_id,
            "account_name": x.account_name,
            "has_token": bool(x.token),
            "token_status": x.token_status,
            "token_message": x.token_message,
            "token_timestamp": x.token_timestamp,
        } for x in rows]

    async def _xhs_ad_buyer_assignments(self) -> dict[str, dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(
                    XHSAdAccountBuyerAssignment.account_id,
                    XHSAdAccountBuyerAssignment.account_name,
                    User.id,
                    User.username,
                    User.display_name,
                ).join(User, User.id == XHSAdAccountBuyerAssignment.user_id)
            )
        ).all()
        assignments: dict[str, dict[str, Any]] = {}
        for account_id, account_name, user_id, username, display_name in rows:
            assignments[str(account_id)] = {
                "account_name": str(account_name or ""),
                "buyer_user_id": int(user_id),
                "buyer_name": str(display_name or username or ""),
            }
        return assignments

    async def _xhs_ad_note_metadata(self, note_ids: set[str]) -> dict[str, dict[str, str]]:
        if not note_ids:
            return {}
        note_map: dict[str, dict[str, str]] = {}
        values = sorted(note_ids)
        for offset in range(0, len(values), 1000):
            chunk = values[offset : offset + 1000]
            rows = (
                await self.db.execute(
                    select(
                        XHSAccountNote.feed_id,
                        XHSAccountNote.primary_content_tag,
                        XHSAccountNote.secondary_content_tag,
                        XHSAccountNote.profile_nickname,
                        XHSAccountNote.account_name,
                    ).where(XHSAccountNote.feed_id.in_(chunk))
                )
            ).all()
            for feed_id, primary_tag, secondary_tag, profile_nickname, account_name in rows:
                key = str(feed_id or "").strip()
                if not key:
                    continue
                note_map[key] = {
                    "primary": _ad_clean_content_tag(primary_tag),
                    "secondary": _ad_clean_content_tag(secondary_tag),
                    "owner_name": str(profile_nickname or account_name or "未知").strip() or "未知",
                }
        return note_map

    @staticmethod
    def _xhs_ad_metric_bucket() -> dict[str, float]:
        return {
            "fee": 0.0,
            "impression": 0.0,
            "click": 0.0,
            "message_consult": 0.0,
            "openings": 0.0,
            "conversion": 0.0,
            "interaction": 0.0,
            "comment": 0.0,
            "special_natural_leads": 0.0,
            "row_count": 0.0,
        }

    @staticmethod
    def _xhs_ad_add_metrics(bucket: dict[str, float], row: dict) -> None:
        bucket["fee"] += _ad_metric(row, "fee")
        bucket["impression"] += _ad_metric(row, "impression")
        bucket["click"] += _ad_metric(row, "click")
        bucket["message_consult"] += _ad_metric(row, "message_consult")
        bucket["openings"] += _ad_openings(row)
        bucket["conversion"] += _ad_conversion(row)
        bucket["interaction"] += _ad_interaction(row)
        bucket["comment"] += _ad_metric(row, "comment")
        bucket["special_natural_leads"] += _ad_metric(row, "special_natural_leads", "natural_leads", "organic_leads")
        bucket["row_count"] += 1

    async def refresh_xhs_ad_aggregates(
        self,
        *,
        report_type: str,
        start_date: date,
        end_date: date,
        account_id: str | None = None,
    ) -> dict[str, int]:
        if report_type not in {"simple", "standard", "creative", "simple_note", "standard_note"}:
            return {"account": 0, "buyer": 0, "brand": 0, "note": 0, "content_tag": 0}

        conditions = [
            XHSReportDaily.report_type == report_type,
            XHSReportDaily.report_date >= start_date,
            XHSReportDaily.report_date <= end_date,
        ]
        if account_id:
            conditions.append(XHSReportDaily.account_id == account_id)

        rows = (
            await self.db.execute(
                select(
                    XHSReportDaily.payload,
                    XHSReportDaily.report_date,
                    XHSReportDaily.account_id,
                    XHSReportDaily.account_name,
                ).where(and_(*conditions))
            )
        ).all()
        assignments = await self._xhs_ad_buyer_assignments()
        brand_catalog = tuple(set(_AD_FALLBACK_BRANDS) | set(await VehicleCatalogService(self.db).brands()))
        normalized_rows: list[dict[str, Any]] = []
        note_ids: set[str] = set()
        for payload, report_date, row_account_id, row_account_name in rows:
            normalized = self._normalize_jg_report_row(
                report_type,
                payload or {},
                account_id=str(row_account_id or ""),
                account_name=str(row_account_name or ""),
            )
            normalized["report_type"] = report_type
            normalized["report_date"] = report_date
            normalized["account_id"] = str(row_account_id or "")
            normalized["account_name"] = str(row_account_name or "")
            normalized_rows.append(normalized)
            note_id = _ad_note_id(normalized)
            if note_id:
                note_ids.add(note_id)

        note_metadata = await self._xhs_ad_note_metadata(note_ids)
        delete_conditions = [
            lambda model: model.report_type == report_type,
            lambda model: model.stat_date >= start_date,
            lambda model: model.stat_date <= end_date,
        ]
        if account_id:
            delete_conditions.append(lambda model: model.account_id == account_id)

        async def delete_for(model: Any, *, scoped_account: bool = True) -> None:
            model_conditions = [condition(model) for condition in delete_conditions if scoped_account or condition is not delete_conditions[-1]]
            if not scoped_account:
                model_conditions = [
                    model.report_type == report_type,
                    model.stat_date >= start_date,
                    model.stat_date <= end_date,
                ]
            await self.db.execute(delete(model).where(and_(*model_conditions)))

        result = {"account": 0, "buyer": 0, "brand": 0, "note": 0, "content_tag": 0}

        if report_type in {"simple", "standard"}:
            account_buckets: dict[tuple, dict[str, Any]] = {}
            buyer_buckets: dict[tuple, dict[str, Any]] = {}
            brand_buckets: dict[tuple, dict[str, Any]] = {}

            for row in normalized_rows:
                stat_date = row["report_date"]
                row_account_id = str(row.get("account_id") or "")
                assignment = assignments.get(row_account_id) or {}
                buyer_user_id = assignment.get("buyer_user_id")
                buyer_name = str(assignment.get("buyer_name") or "未分配")
                account_name = str(row.get("account_name") or assignment.get("account_name") or "")

                account_key = (stat_date, report_type, row_account_id)
                account_bucket = account_buckets.setdefault(account_key, {
                    **self._xhs_ad_metric_bucket(),
                    "stat_date": stat_date,
                    "report_type": report_type,
                    "account_id": row_account_id,
                    "account_name": account_name,
                    "buyer_user_id": buyer_user_id,
                    "buyer_name": buyer_name,
                })
                self._xhs_ad_add_metrics(account_bucket, row)

                buyer_key = (stat_date, report_type, buyer_user_id or 0)
                buyer_bucket = buyer_buckets.setdefault(buyer_key, {
                    **self._xhs_ad_metric_bucket(),
                    "stat_date": stat_date,
                    "report_type": report_type,
                    "buyer_user_id": buyer_user_id,
                    "buyer_name": buyer_name,
                    "account_ids": set(),
                })
                buyer_bucket["account_ids"].add(row_account_id)
                self._xhs_ad_add_metrics(buyer_bucket, row)

                brand = _ad_brand(row, brand_catalog)
                brand_key = (stat_date, report_type, row_account_id, brand)
                brand_bucket = brand_buckets.setdefault(brand_key, {
                    "stat_date": stat_date,
                    "report_type": report_type,
                    "account_id": row_account_id,
                    "account_name": account_name,
                    "buyer_user_id": buyer_user_id,
                    "buyer_name": buyer_name,
                    "brand": brand,
                    "fee": 0.0,
                    "impression": 0.0,
                    "click": 0.0,
                    "conversion": 0.0,
                    "interaction": 0.0,
                    "row_count": 0.0,
                })
                brand_bucket["fee"] += _ad_metric(row, "fee")
                brand_bucket["impression"] += _ad_metric(row, "impression")
                brand_bucket["click"] += _ad_metric(row, "click")
                brand_bucket["conversion"] += _ad_conversion(row)
                brand_bucket["interaction"] += _ad_interaction(row)
                brand_bucket["row_count"] += 1

            await delete_for(XHSAdStatsDailyAccount)
            if not account_id:
                await delete_for(XHSAdStatsDailyBuyer, scoped_account=False)
            await delete_for(XHSAdStatsDailyBrand)
            if account_buckets:
                await self.db.execute(insert(XHSAdStatsDailyAccount), [
                    {**bucket, "row_count": int(bucket["row_count"])}
                    for bucket in account_buckets.values()
                ])
            if buyer_buckets and not account_id:
                await self.db.execute(insert(XHSAdStatsDailyBuyer), [
                    {
                        **{key: value for key, value in bucket.items() if key != "account_ids"},
                        "account_count": len(bucket["account_ids"]),
                        "row_count": int(bucket["row_count"]),
                    }
                    for bucket in buyer_buckets.values()
                ])
            if brand_buckets:
                await self.db.execute(insert(XHSAdStatsDailyBrand), [
                    {**bucket, "row_count": int(bucket["row_count"])}
                    for bucket in brand_buckets.values()
                ])
            result["account"] = len(account_buckets)
            result["buyer"] = len(buyer_buckets) if not account_id else 0
            result["brand"] = len(brand_buckets)

        if report_type in {"simple_note", "standard_note", "creative"}:
            note_buckets: dict[tuple, dict[str, Any]] = {}
            tag_buckets: dict[tuple, dict[str, Any]] = {}
            for row in normalized_rows:
                note_id = _ad_note_id(row)
                if not note_id:
                    continue
                stat_date = row["report_date"]
                row_account_id = str(row.get("account_id") or "")
                assignment = assignments.get(row_account_id) or {}
                buyer_user_id = assignment.get("buyer_user_id")
                buyer_name = str(assignment.get("buyer_name") or "未分配")
                account_name = str(row.get("account_name") or assignment.get("account_name") or "")
                metadata = note_metadata.get(note_id) or {}
                primary_tag = _ad_clean_content_tag(metadata.get("primary") or "")
                secondary_tag = _ad_clean_content_tag(metadata.get("secondary") or "")
                xhs_account_name = str(metadata.get("owner_name") or "未知")

                note_key = (stat_date, report_type, row_account_id, note_id)
                note_bucket = note_buckets.setdefault(note_key, {
                    "stat_date": stat_date,
                    "report_type": report_type,
                    "account_id": row_account_id,
                    "account_name": account_name,
                    "buyer_user_id": buyer_user_id,
                    "buyer_name": buyer_name,
                    "note_id": note_id,
                    "note_title": _ad_note_title(row),
                    "xhs_account_name": xhs_account_name,
                    "primary_content_tag": primary_tag,
                    "secondary_content_tag": secondary_tag,
                    "fee": 0.0,
                    "impression": 0.0,
                    "click": 0.0,
                    "message_consult": 0.0,
                    "openings": 0.0,
                    "conversion": 0.0,
                    "interaction": 0.0,
                    "row_count": 0.0,
                })
                note_bucket["fee"] += _ad_metric(row, "fee")
                note_bucket["impression"] += _ad_metric(row, "impression")
                note_bucket["click"] += _ad_metric(row, "click")
                note_bucket["message_consult"] += _ad_metric(row, "message_consult")
                note_bucket["openings"] += _ad_openings(row)
                note_bucket["conversion"] += _ad_conversion(row)
                note_bucket["interaction"] += _ad_interaction(row)
                note_bucket["row_count"] += 1

                if primary_tag:
                    tag_key = (stat_date, report_type, row_account_id, primary_tag, secondary_tag or "未打二级标签")
                    tag_bucket = tag_buckets.setdefault(tag_key, {
                        "stat_date": stat_date,
                        "report_type": report_type,
                        "account_id": row_account_id,
                        "account_name": account_name,
                        "buyer_user_id": buyer_user_id,
                        "buyer_name": buyer_name,
                        "primary_content_tag": primary_tag,
                        "secondary_content_tag": secondary_tag or "未打二级标签",
                        "fee": 0.0,
                        "conversion": 0.0,
                        "click": 0.0,
                        "interaction": 0.0,
                        "row_count": 0.0,
                    })
                    tag_bucket["fee"] += _ad_metric(row, "fee")
                    tag_bucket["conversion"] += _ad_conversion(row)
                    tag_bucket["click"] += _ad_metric(row, "click")
                    tag_bucket["interaction"] += _ad_interaction(row)
                    tag_bucket["row_count"] += 1

            await delete_for(XHSAdStatsDailyNote)
            await delete_for(XHSAdStatsDailyContentTag)
            if note_buckets:
                await self.db.execute(insert(XHSAdStatsDailyNote), [
                    {**bucket, "row_count": int(bucket["row_count"])}
                    for bucket in note_buckets.values()
                ])
            if tag_buckets:
                await self.db.execute(insert(XHSAdStatsDailyContentTag), [
                    {**bucket, "row_count": int(bucket["row_count"])}
                    for bucket in tag_buckets.values()
                ])
            result["note"] = len(note_buckets)
            result["content_tag"] = len(tag_buckets)

        await self.db.commit()
        return result

    async def refresh_jg_report_cache(
        self,
        report_type: str,
        account_id: Optional[str] = None,
        account_name: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 30,
    ) -> dict:
        api_path = REPORT_API_PATHS.get(report_type)
        if not api_path:
            raise ValueError(f"不支持的报表类型: {report_type}")
        start_date, end_date = self._normalize_report_date_range(
            start_date=start_date,
            end_date=end_date,
            days=days,
        )
        tokens_stmt = select(XHSReportToken)
        if account_id:
            tokens_stmt = tokens_stmt.where(XHSReportToken.account_id == account_id)
        elif account_name:
            tokens_stmt = tokens_stmt.where(XHSReportToken.account_name == account_name)
        token_rows = (await self.db.execute(tokens_stmt.order_by(XHSReportToken.account_name.asc()))).scalars().all()

        updated_accounts = 0
        updated_rows = 0
        changed_rows = 0
        errors: list[str] = []
        start_d = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date()
        semaphore = asyncio.Semaphore(4)

        async def fetch_account_report(tk: XHSReportToken) -> dict:
            async with semaphore:
                try:
                    token = await self._fetch_report_token(tk.account_id)
                    rows, _ = await self._fetch_report_rows(
                        token=token,
                        advertiser_id=tk.account_id,
                        api_path=api_path,
                        start_date=start_date,
                        end_date=end_date,
                    )
                    return {
                        "account_id": tk.account_id,
                        "account_name": tk.account_name,
                        "token": token,
                        "rows": rows,
                        "error": None,
                    }
                except Exception as e:
                    return {
                        "account_id": tk.account_id,
                        "account_name": tk.account_name,
                        "token": None,
                        "rows": [],
                        "error": str(e),
                    }

        fetched_results = await asyncio.gather(*(fetch_account_report(tk) for tk in token_rows))
        token_row_by_account_id = {tk.account_id: tk for tk in token_rows}

        for result in fetched_results:
            tk = token_row_by_account_id.get(str(result.get("account_id") or ""))
            if not tk:
                continue

            error = result.get("error")
            if error:
                tk.token_status = "失败"
                tk.token_message = str(error)
                errors.append(f"{tk.account_name}: {error}")
                continue

            token = str(result.get("token") or "")
            rows = result.get("rows") or []
            tk.token = token
            tk.token_status = "成功"
            tk.token_message = None

            insert_rows: list[dict] = []
            seen_cache_keys: set[tuple[date, str]] = set()
            for row in rows:
                payload = self._normalize_jg_report_row(
                    report_type,
                    row,
                    account_id=tk.account_id,
                    account_name=tk.account_name,
                )
                t = str(payload.get("time") or "").strip()
                if not t:
                    continue
                try:
                    d = datetime.strptime(t, "%Y-%m-%d").date()
                except Exception:
                    continue
                campaign_key_base = self._report_row_campaign_key(report_type, payload)
                campaign_key = campaign_key_base
                dedupe_index = 2
                while (d, campaign_key) in seen_cache_keys:
                    suffix = f"#{dedupe_index}"
                    campaign_key = f"{campaign_key_base[:128 - len(suffix)]}{suffix}"
                    dedupe_index += 1
                seen_cache_keys.add((d, campaign_key))
                insert_rows.append(
                    {
                        "report_type": report_type,
                        "account_id": tk.account_id,
                        "account_name": tk.account_name,
                        "report_date": d,
                        "campaign_id": campaign_key,
                        "payload": payload,
                    }
                )

            existing_rows = list(
                (
                    await self.db.execute(
                        select(XHSReportDaily).where(
                            and_(
                                XHSReportDaily.report_type == report_type,
                                XHSReportDaily.account_id == tk.account_id,
                                XHSReportDaily.report_date >= start_d,
                                XHSReportDaily.report_date <= end_d,
                            )
                        )
                    )
                ).scalars().all()
            )
            existing_by_key = {
                (row.report_date, row.campaign_id): row
                for row in existing_rows
            }
            incoming_by_key = {
                (row["report_date"], row["campaign_id"]): row
                for row in insert_rows
            }

            stale_ids = [
                row.id
                for key, row in existing_by_key.items()
                if key not in incoming_by_key
            ]
            if stale_ids:
                await self.db.execute(
                    delete(XHSReportDaily).where(XHSReportDaily.id.in_(stale_ids))
                )
                changed_rows += len(stale_ids)

            new_rows: list[dict] = []
            for key, incoming in incoming_by_key.items():
                existing = existing_by_key.get(key)
                if existing is None:
                    new_rows.append(incoming)
                    continue
                if existing.account_name != incoming["account_name"] or existing.payload != incoming["payload"]:
                    existing.account_name = incoming["account_name"]
                    existing.payload = incoming["payload"]
                    changed_rows += 1
            if new_rows:
                await self.db.execute(insert(XHSReportDaily), new_rows)
                changed_rows += len(new_rows)
            updated_rows += len(insert_rows)
            updated_accounts += 1
        await self.db.commit()
        if changed_rows and report_type in {"creative", "simple", "simple_note", "standard_note"}:
            await self.backfill_promoted_flags_from_reports(start_date=start_d, end_date=end_d)
        aggregate_result: dict[str, int] | None = None
        aggregate_error: str | None = None
        if changed_rows:
            try:
                aggregate_result = await self.refresh_xhs_ad_aggregates(
                    report_type=report_type,
                    start_date=start_d,
                    end_date=end_d,
                    account_id=account_id,
                )
                try:
                    from app.services.xhs_ad_dashboard_service import invalidate_ad_dashboard_caches

                    invalidate_ad_dashboard_caches()
                except Exception as cache_exc:
                    logger.warning("投流看板缓存清理失败: %s", cache_exc)
            except Exception as exc:
                aggregate_error = str(exc)
                logger.exception(
                    "投流聚合表刷新失败: report_type=%s start=%s end=%s account_id=%s",
                    report_type,
                    start_d,
                    end_d,
                    account_id,
                )
        return {
            "report_type": report_type,
            "start_date": start_date,
            "end_date": end_date,
            "account_id": account_id,
            "updated_accounts": updated_accounts,
            "updated_rows": updated_rows,
            "changed_rows": changed_rows,
            "aggregate_result": aggregate_result,
            "aggregate_error": aggregate_error,
            "errors": errors,
        }

    async def get_jg_report_cached(
        self,
        report_type: str,
        account_id: Optional[str] = None,
        account_name: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 30,
        page: int = 1,
        limit: int = 20,
        creative_ai_filter: Optional[str] = None,
        include_all_rows: bool = False,
    ) -> dict:
        start_date, end_date = self._normalize_report_date_range(
            start_date=start_date,
            end_date=end_date,
            days=days,
        )
        start_d = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date()
        normalized_page = max(1, int(page or 1))
        normalized_limit = max(1, min(int(limit or 20), 200))

        filters = and_(
            XHSReportDaily.report_type == report_type,
            XHSReportDaily.report_date >= start_d,
            XHSReportDaily.report_date <= end_d,
        )
        stmt = select(XHSReportDaily).where(and_(filters))
        if account_id:
            stmt = stmt.where(XHSReportDaily.account_id == account_id)
        elif account_name:
            stmt = stmt.where(XHSReportDaily.account_name == account_name)
        count_stmt = select(func.count()).select_from(XHSReportDaily).where(filters)
        account_count_stmt = select(func.count(func.distinct(XHSReportDaily.account_name))).where(filters)
        if account_id:
            count_stmt = count_stmt.where(XHSReportDaily.account_id == account_id)
            account_count_stmt = account_count_stmt.where(XHSReportDaily.account_id == account_id)
        elif account_name:
            count_stmt = count_stmt.where(XHSReportDaily.account_name == account_name)
            account_count_stmt = account_count_stmt.where(XHSReportDaily.account_name == account_name)
        if report_type == "creative" and creative_ai_filter:
            all_rows = (
                await self.db.execute(
                    stmt.order_by(
                        XHSReportDaily.report_date.desc(),
                        XHSReportDaily.account_name.asc(),
                        XHSReportDaily.campaign_id.asc(),
                    )
                )
            ).scalars().all()
            normalized_rows = [
                self._normalize_report_row(x.payload, account_id=x.account_id, account_name=x.account_name)
                for x in all_rows
            ]
            enriched_rows = await self._attach_account_note_ai_origin_to_report_rows(normalized_rows)
            filtered_rows = self._filter_creative_rows_by_ai_origin(enriched_rows, creative_ai_filter)
            total_rows = len(filtered_rows)
            total_accounts = len({str((row or {}).get("account_name") or "").strip() for row in filtered_rows if str((row or {}).get("account_name") or "").strip()})
            if include_all_rows:
                data_rows = filtered_rows
            else:
                start = (normalized_page - 1) * normalized_limit
                data_rows = filtered_rows[start:start + normalized_limit]
        else:
            total_rows = int((await self.db.execute(count_stmt)).scalar() or 0)
            total_accounts = int((await self.db.execute(account_count_stmt)).scalar() or 0)
            ordered_stmt = stmt.order_by(
                XHSReportDaily.report_date.desc(),
                XHSReportDaily.account_name.asc(),
                XHSReportDaily.campaign_id.asc(),
            )
            if not include_all_rows:
                ordered_stmt = ordered_stmt.offset((normalized_page - 1) * normalized_limit).limit(normalized_limit)
            rows = (await self.db.execute(ordered_stmt)).scalars().all()
            data_rows = [
                self._normalize_jg_report_row(report_type, x.payload, account_id=x.account_id, account_name=x.account_name)
                for x in rows
            ]
            if report_type == "creative":
                data_rows = await self._attach_account_note_ai_origin_to_report_rows(data_rows)
            elif report_type == "simple_note":
                data_rows = await self._attach_account_note_cover_to_note_report_rows(data_rows)
        return {
            "report_type": report_type,
            "start_date": start_date,
            "end_date": end_date,
            "account_id": account_id,
            "account_name": account_name,
            "total_accounts": total_accounts,
            "total_rows": total_rows,
            "page": normalized_page,
            "limit": normalized_limit,
            "items": [],
            "rows": data_rows,
        }

    @staticmethod
    def _safe_float(value: object) -> float:
        try:
            raw = str(value or "").strip().replace(",", "")
            if raw.endswith("%"):
                raw = raw[:-1]
            if not raw:
                return 0.0
            parsed = float(raw)
            return parsed if parsed == parsed else 0.0
        except Exception:
            return 0.0

    @classmethod
    def _init_creative_compare_accumulator(cls) -> dict[str, float]:
        return {
            "fee": 0.0,
            "impression": 0.0,
            "click": 0.0,
            "interaction": 0.0,
            "play_5s": 0.0,
            "message_consult": 0.0,
            "initiative_message": 0.0,
            "msg_leads_num": 0.0,
            "shop_pay_order_num_15d": 0.0,
        }

    @classmethod
    def _accumulate_creative_compare_row(cls, bucket: dict[str, float], row: dict) -> None:
        for key in CREATIVE_COMPARE_SUM_KEYS:
            bucket[key] += cls._safe_float(row.get(key))

    @classmethod
    def _finalize_creative_compare_metrics(cls, bucket: dict[str, float]) -> dict[str, float]:
        fee = float(bucket.get("fee") or 0.0)
        impression = float(bucket.get("impression") or 0.0)
        click = float(bucket.get("click") or 0.0)
        interaction = float(bucket.get("interaction") or 0.0)
        message_consult = float(bucket.get("message_consult") or 0.0)
        initiative_message = float(bucket.get("initiative_message") or 0.0)
        msg_leads_num = float(bucket.get("msg_leads_num") or 0.0)
        shop_pay_order_num_15d = float(bucket.get("shop_pay_order_num_15d") or 0.0)

        def ratio(numerator: float, denominator: float, *, multiplier: float = 1.0) -> float:
            if denominator <= 0:
                return 0.0
            return numerator / denominator * multiplier

        return {
            "fee": round(fee, 2),
            "impression": int(round(impression)),
            "click": int(round(click)),
            "ctr": round(ratio(click, impression, multiplier=100.0), 2),
            "cpc": round(ratio(fee, click), 2),
            "cpm": round(ratio(fee, impression, multiplier=1000.0), 2),
            "interaction": int(round(interaction)),
            "avg_interaction_cost": round(ratio(fee, interaction), 2),
            "play_5s": int(round(float(bucket.get("play_5s") or 0.0))),
            "message_consult": int(round(message_consult)),
            "initiative_message": int(round(initiative_message)),
            "msg_leads_num": int(round(msg_leads_num)),
            "message_consult_cost": round(ratio(fee, message_consult), 2),
            "initiative_message_cost": round(ratio(fee, initiative_message), 2),
            "msg_leads_cost": round(ratio(fee, msg_leads_num), 2),
            "shop_pay_order_num_15d": int(round(shop_pay_order_num_15d)),
            "shop_pay_order_cvr_15d": round(ratio(shop_pay_order_num_15d, click, multiplier=100.0), 2),
        }

    @staticmethod
    def _creative_compare_period_parts(report_date: date, granularity: str) -> tuple[str, str, str, str]:
        if granularity == "day":
            iso = report_date.isoformat()
            return iso, iso, iso, iso
        if granularity == "week":
            week_start = report_date - timedelta(days=report_date.weekday())
            week_end = week_start + timedelta(days=6)
            iso_year, iso_week, _ = report_date.isocalendar()
            return (
                f"{iso_year}-W{iso_week:02d}",
                f"{week_start.strftime('%m-%d')} ~ {week_end.strftime('%m-%d')}",
                week_start.isoformat(),
                week_end.isoformat(),
            )
        month_start = report_date.replace(day=1)
        if report_date.month == 12:
            next_month = report_date.replace(year=report_date.year + 1, month=1, day=1)
        else:
            next_month = report_date.replace(month=report_date.month + 1, day=1)
        month_end = next_month - timedelta(days=1)
        return (
            month_start.strftime("%Y-%m"),
            month_start.strftime("%Y-%m"),
            month_start.isoformat(),
            month_end.isoformat(),
        )

    async def get_creative_report_ai_compare(
        self,
        *,
        account_id: str | None = None,
        account_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        days: int = 30,
    ) -> dict:
        start_date, end_date = self._normalize_report_date_range(
            start_date=start_date,
            end_date=end_date,
            days=days,
        )
        start_d = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date()

        stmt = (
            select(XHSReportDaily)
            .where(
                and_(
                    XHSReportDaily.report_type == "creative",
                    XHSReportDaily.report_date >= start_d,
                    XHSReportDaily.report_date <= end_d,
                )
            )
            .order_by(
                XHSReportDaily.report_date.asc(),
                XHSReportDaily.account_name.asc(),
                XHSReportDaily.campaign_id.asc(),
            )
        )
        if account_id:
            stmt = stmt.where(XHSReportDaily.account_id == account_id)
        elif account_name:
            stmt = stmt.where(XHSReportDaily.account_name == account_name)

        rows = (await self.db.execute(stmt)).scalars().all()
        normalized_rows = [
            self._normalize_creative_report_row(item.payload, account_id=item.account_id, account_name=item.account_name)
            for item in rows
        ]
        enriched_rows = await self._attach_account_note_ai_origin_to_report_rows(normalized_rows)

        filtered_rows: list[dict] = []
        for row in enriched_rows:
            matched = bool((row or {}).get("account_note_matched"))
            ai_origin_type = str((row or {}).get("ai_origin_type") or "").strip()
            if not matched or not ai_origin_type or ai_origin_type not in CREATIVE_COMPARE_AI_LABELS:
                continue
            filtered_rows.append(row)

        all_time_note_totals_by_tag = {
            tag_key: set()
            for tag_key in CREATIVE_COMPARE_AI_LABELS.keys()
        }
        for row in filtered_rows:
            ai_origin_type = str((row or {}).get("ai_origin_type") or "").strip()
            note_key = str((row or {}).get("note_material") or (row or {}).get("feed_id") or "").strip()
            if ai_origin_type in all_time_note_totals_by_tag and note_key:
                all_time_note_totals_by_tag[ai_origin_type].add(note_key)

        granularities: dict[str, dict] = {}
        for granularity in ("day", "week", "month"):
            period_buckets: dict[str, dict] = {}
            totals_by_tag = {
                tag_key: self._init_creative_compare_accumulator()
                for tag_key in CREATIVE_COMPARE_AI_LABELS.keys()
            }
            totals_note_ids_by_tag = {
                tag_key: set()
                for tag_key in CREATIVE_COMPARE_AI_LABELS.keys()
            }
            overall_bucket = self._init_creative_compare_accumulator()
            overall_note_ids: set[str] = set()

            for row in filtered_rows:
                time_value = str((row or {}).get("time") or "").strip()
                ai_origin_type = str((row or {}).get("ai_origin_type") or "").strip()
                if not time_value or ai_origin_type not in totals_by_tag:
                    continue
                try:
                    report_date = datetime.strptime(time_value, "%Y-%m-%d").date()
                except Exception:
                    continue
                period_key, period_label, period_start, period_end = self._creative_compare_period_parts(report_date, granularity)
                period_entry = period_buckets.get(period_key)
                if period_entry is None:
                    period_entry = {
                        "period_key": period_key,
                        "period_label": period_label,
                        "period_start": period_start,
                        "period_end": period_end,
                        "tag_buckets": {
                            tag_key: self._init_creative_compare_accumulator()
                            for tag_key in CREATIVE_COMPARE_AI_LABELS.keys()
                        },
                        "tag_note_ids": {
                            tag_key: set()
                            for tag_key in CREATIVE_COMPARE_AI_LABELS.keys()
                        },
                    }
                    period_buckets[period_key] = period_entry

                self._accumulate_creative_compare_row(period_entry["tag_buckets"][ai_origin_type], row)
                self._accumulate_creative_compare_row(totals_by_tag[ai_origin_type], row)
                self._accumulate_creative_compare_row(overall_bucket, row)
                note_key = str((row or {}).get("note_material") or (row or {}).get("feed_id") or "").strip()
                if note_key:
                    period_entry["tag_note_ids"][ai_origin_type].add(note_key)
                    totals_note_ids_by_tag[ai_origin_type].add(note_key)
                    overall_note_ids.add(note_key)

            periods = []
            for period_key in sorted(period_buckets.keys()):
                period_entry = period_buckets[period_key]
                tags = {}
                for tag_key in CREATIVE_COMPARE_AI_LABELS.keys():
                    metrics = self._finalize_creative_compare_metrics(period_entry["tag_buckets"][tag_key])
                    metrics["note_count"] = len(period_entry["tag_note_ids"][tag_key])
                    tags[tag_key] = metrics
                periods.append(
                    {
                        "period_key": period_entry["period_key"],
                        "period_label": period_entry["period_label"],
                        "period_start": period_entry["period_start"],
                        "period_end": period_entry["period_end"],
                        "tags": tags,
                    }
                )

            granularities[granularity] = {
                "periods": periods,
                "totals_by_tag": {
                    tag_key: {
                        **self._finalize_creative_compare_metrics(bucket),
                        "note_count": len(totals_note_ids_by_tag[tag_key]),
                    }
                    for tag_key, bucket in totals_by_tag.items()
                },
                "overall": {
                    **self._finalize_creative_compare_metrics(overall_bucket),
                    "note_count": len(overall_note_ids),
                },
            }

        return {
            "report_type": "creative",
            "start_date": start_date,
            "end_date": end_date,
            "account_id": account_id,
            "account_name": account_name,
            "days": days,
            "tags": [
                {
                    "key": key,
                    "label": label,
                    "all_time_note_count": len(all_time_note_totals_by_tag[key]),
                }
                for key, label in CREATIVE_COMPARE_AI_LABELS.items()
            ],
            "all_time_note_totals_by_tag": {
                key: len(value)
                for key, value in all_time_note_totals_by_tag.items()
            },
            "granularities": granularities,
        }

    @staticmethod
    def _filter_creative_rows_by_ai_origin(rows: list[dict], ai_filter: str) -> list[dict]:
        value = str(ai_filter or "").strip()
        if not value or value == "all":
            return rows
        filtered: list[dict] = []
        for row in rows:
            matched = bool((row or {}).get("account_note_matched"))
            ai_origin = str((row or {}).get("ai_origin_type") or "").strip()
            if value == "__missing__":
                if not matched:
                    filtered.append(row)
            elif value == "__unset__":
                if matched and not ai_origin:
                    filtered.append(row)
            elif ai_origin == value:
                filtered.append(row)
        return filtered

    async def _attach_account_note_ai_origin_to_report_rows(self, rows: list[dict]) -> list[dict]:
        if not rows:
            return rows

        note_keys = {
            str((row or {}).get("note_material") or "").strip()
            for row in rows
            if str((row or {}).get("note_material") or "").strip()
        }
        if not note_keys:
            return rows

        stmt = select(XHSAccountNote.feed_id, XHSAccountNote.ai_origin_type).where(
            XHSAccountNote.feed_id.in_(note_keys)
        )
        note_rows = (await self.db.execute(stmt)).all()
        ai_origin_by_feed_id = {
            str(feed_id): (ai_origin_type or "")
            for feed_id, ai_origin_type in note_rows
            if str(feed_id or "").strip()
        }
        matched_feed_ids = set(ai_origin_by_feed_id.keys())

        enriched: list[dict] = []
        for row in rows:
            item = dict(row or {})
            key = str(item.get("note_material") or "").strip()
            item["ai_origin_type"] = ai_origin_by_feed_id.get(key, "")
            item["account_note_matched"] = key in matched_feed_ids
            enriched.append(item)
        return enriched

    async def _attach_account_note_cover_to_note_report_rows(self, rows: list[dict]) -> list[dict]:
        if not rows:
            return rows

        note_ids = {
            str((row or {}).get("note_id") or (row or {}).get("feed_id") or "").strip()
            for row in rows
            if str((row or {}).get("note_id") or (row or {}).get("feed_id") or "").strip()
        }
        if not note_ids:
            return rows

        stmt = select(XHSAccountNote.feed_id, XHSAccountNote.cover_image_url, XHSAccountNote.title).where(
            XHSAccountNote.feed_id.in_(note_ids)
        )
        note_rows = (await self.db.execute(stmt)).all()
        cover_by_feed_id = {
            str(feed_id): {
                "cover_image_url": cover_image_url or "",
                "title": title or "",
            }
            for feed_id, cover_image_url, title in note_rows
            if str(feed_id or "").strip()
        }

        enriched: list[dict] = []
        for row in rows:
            item = dict(row or {})
            key = str(item.get("note_id") or item.get("feed_id") or "").strip()
            note_info = cover_by_feed_id.get(key) or {}
            if not str(item.get("note_image") or "").strip():
                item["note_image"] = note_info.get("cover_image_url") or ""
            if not str(item.get("note_title") or "").strip():
                item["note_title"] = note_info.get("title") or ""
            item["account_note_matched"] = key in cover_by_feed_id
            enriched.append(item)
        return enriched

    async def list_account_notes(
        self,
        user: User,
        page: int = 1,
        limit: int = 20,
        environment_id: int | None = None,
        keyword: str | None = None,
        ai_origin_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[XHSAccountNote], int, int]:
        envs = await self.list_environments(user, include_inactive=True)
        allowed_env_ids = {env.id for env in envs}
        if not allowed_env_ids:
            return [], 0, 0
        if environment_id is not None and environment_id not in allowed_env_ids:
            return [], 0, 0

        conditions = [XHSAccountNote.environment_id.in_(allowed_env_ids)]
        if environment_id is not None:
            conditions.append(XHSAccountNote.environment_id == environment_id)
        ai_origin_value = (ai_origin_type or "").strip()
        if ai_origin_value:
            if ai_origin_value == "__unset__":
                conditions.append(or_(XHSAccountNote.ai_origin_type == "", XHSAccountNote.ai_origin_type.is_(None)))
            else:
                conditions.append(XHSAccountNote.ai_origin_type == ai_origin_value)
        status_value = (status or "").strip()
        if status_value and status_value != "all":
            conditions.append(XHSAccountNote.status == status_value)
        keyword_value = (keyword or "").strip()
        if keyword_value:
            pattern = f"%{keyword_value}%"
            conditions.append(
                or_(
                    XHSAccountNote.title.ilike(pattern),
                    XHSAccountNote.feed_id.ilike(pattern),
                    XHSAccountNote.red_id.ilike(pattern),
                )
            )

        where_clause = and_(*conditions)
        total_stmt = select(func.count()).select_from(XHSAccountNote).where(where_clause)
        total = int((await self.db.execute(total_stmt)).scalar() or 0)

        account_count_stmt = (
            select(func.count(func.distinct(XHSAccountNote.environment_id)))
            .select_from(XHSAccountNote)
            .where(where_clause)
        )
        total_accounts = int((await self.db.execute(account_count_stmt)).scalar() or 0)

        stmt = (
            select(XHSAccountNote)
            .where(where_clause)
            .options(
                selectinload(XHSAccountNote.environment),
                selectinload(XHSAccountNote.assigned_runner_environment),
            )
            .order_by(
                XHSAccountNote.environment_id.asc(),
                XHSAccountNote.sort_index.asc(),
                XHSAccountNote.id.desc(),
            )
            .offset((page - 1) * limit)
            .limit(limit)
        )
        items = list((await self.db.execute(stmt)).scalars().all())
        if items:
            today_value = date.today()
            note_ids = [int(item.id) for item in items]
            browse_stmt = (
                select(
                    XHSAccountNoteBrowseEvent.note_id,
                    func.count(XHSAccountNoteBrowseEvent.id),
                )
                .where(
                    and_(
                        XHSAccountNoteBrowseEvent.note_id.in_(note_ids),
                        func.date(XHSAccountNoteBrowseEvent.created_at) == today_value,
                    )
                )
                .group_by(XHSAccountNoteBrowseEvent.note_id)
            )
            browse_rows = await self.db.execute(browse_stmt)
            today_browse_counts = {int(row[0]): int(row[1] or 0) for row in browse_rows.all()}
            for item in items:
                setattr(item, "today_browse_count", today_browse_counts.get(int(item.id), 0))
        await self._attach_environment_owners(items)
        return items, total, total_accounts

    async def _attach_environment_owners(self, items: list[XHSAccountNote]) -> None:
        env_ids = sorted({int(item.environment_id or 0) for item in items if int(item.environment_id or 0) > 0})
        if not env_ids:
            return
        owner_stmt = (
            select(
                UserXHSEnvironment.environment_id,
                User.id,
                User.username,
                User.display_name,
                User.role,
            )
            .join(User, User.id == UserXHSEnvironment.user_id)
            .where(UserXHSEnvironment.environment_id.in_(env_ids))
        )
        owner_rows = await self.db.execute(owner_stmt)
        rows = owner_rows.all()
        roles_by_user = await load_roles_for_users(self.db, [int(row[1]) for row in rows])
        owner_by_env = {
            int(environment_id): {
                "owner_user_id": int(user_id),
                "owner_username": display_name or username,
                "owner_role": self._insights_owner_role(
                    roles_by_user.get(int(user_id), []) or [str(role or ROLE_VIEWER)]
                ),
            }
            for environment_id, user_id, username, display_name, role in rows
        }
        for item in items:
            owner = owner_by_env.get(int(item.environment_id or 0)) or {}
            setattr(item, "owner_user_id", owner.get("owner_user_id"))
            setattr(item, "owner_username", owner.get("owner_username"))
            setattr(item, "owner_role", owner.get("owner_role"))

    @staticmethod
    def _paid_report_note_keys(report_type: str, payload: dict | None) -> set[str]:
        normalized = XHSService._normalize_jg_report_row(report_type, payload)
        keys: set[str] = set()
        for key in (
            "feed_id",
            "note_id",
            "noteId",
            "note_title",
            "note_name",
            "note_material",
            "creative_id",
            "creativeId",
            "material_id",
            "item_id",
            "ad_id",
            "asset_id",
        ):
            value = str(normalized.get(key) or "").strip()
            if not value:
                continue
            keys.add(value)
            url_match = re.search(r"/explore/([a-zA-Z0-9_-]+)", value)
            if url_match:
                keys.add(url_match.group(1))
        return keys

    async def _attach_paid_report_flags(
        self,
        items: list[XHSAccountNote],
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        resolve_from_reports: bool = True,
    ) -> None:
        feed_ids = {str(item.feed_id or "").strip() for item in items if str(item.feed_id or "").strip()}
        matched: dict[str, dict[str, Any]] = {}
        if feed_ids and resolve_from_reports:
            report_types = ("creative", "simple", "simple_note", "standard_note")
            conditions = [XHSReportDaily.report_type.in_(report_types)]
            if start_date is not None:
                conditions.append(XHSReportDaily.report_date >= start_date)
            if end_date is not None:
                conditions.append(XHSReportDaily.report_date <= end_date)

            try:
                bind = self.db.get_bind()
            except Exception:
                bind = getattr(self.db, "bind", None)
            dialect_name = getattr(bind, "dialect", None)
            dialect_name = getattr(dialect_name, "name", "")
            if dialect_name == "sqlite":
                note_key_exprs = [
                    func.json_extract(XHSReportDaily.payload, "$.feed_id"),
                    func.json_extract(XHSReportDaily.payload, "$.note_id"),
                    func.json_extract(XHSReportDaily.payload, "$.noteId"),
                    func.json_extract(XHSReportDaily.payload, "$.creative_id"),
                    func.json_extract(XHSReportDaily.payload, "$.creativeId"),
                    func.json_extract(XHSReportDaily.payload, "$.material_id"),
                    func.json_extract(XHSReportDaily.payload, "$.item_id"),
                    func.json_extract(XHSReportDaily.payload, "$.ad_id"),
                    func.json_extract(XHSReportDaily.payload, "$.asset_id"),
                ]
                conditions.append(or_(*(expr.in_(feed_ids) for expr in note_key_exprs)))

            stmt = select(XHSReportDaily.report_type, XHSReportDaily.report_date, XHSReportDaily.payload).where(and_(*conditions))
            result = await self.db.execute(stmt)
            for report_type, report_date, payload in result.all():
                keys = self._paid_report_note_keys(str(report_type or ""), payload)
                for feed_id in feed_ids.intersection(keys):
                    info = matched.setdefault(feed_id, {
                        "first_seen": report_date,
                        "last_seen": report_date,
                        "sources": set(),
                    })
                    if report_date and (not info["first_seen"] or report_date < info["first_seen"]):
                        info["first_seen"] = report_date
                    if report_date and (not info["last_seen"] or report_date > info["last_seen"]):
                        info["last_seen"] = report_date
                    info["sources"].add(str(report_type or ""))

        source_labels = {
            "simple": "简单投",
            "simple_note": "简单投笔记报表",
            "standard_note": "标准投笔记报表",
            "creative": "创意报表",
        }
        for item in items:
            feed_id = str(item.feed_id or "").strip()
            info = matched.get(feed_id)
            is_promoted = bool(getattr(item, "is_promoted", False))
            sources = set(info.get("sources") or []) if info else set()
            has_paid_report = is_promoted or bool(sources.intersection({"simple", "simple_note", "standard_note"}))
            has_creative_report = is_promoted or "creative" in sources
            setattr(item, "is_promoted", is_promoted or has_paid_report or has_creative_report)
            setattr(item, "has_paid_report", has_paid_report)
            setattr(item, "has_creative_report", has_creative_report)
            if info:
                if info.get("first_seen") and not getattr(item, "promoted_first_seen_at", None):
                    setattr(item, "promoted_first_seen_at", datetime.combine(info["first_seen"], datetime.min.time()))
                if info.get("last_seen") and not getattr(item, "promoted_last_seen_at", None):
                    setattr(item, "promoted_last_seen_at", datetime.combine(info["last_seen"], datetime.min.time()))
                if sources and not getattr(item, "promoted_source", None):
                    setattr(item, "promoted_source", "、".join(source_labels.get(source, source) for source in sorted(sources)))

    async def backfill_promoted_flags_from_reports(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, int]:
        conditions = [XHSReportDaily.report_type.in_(("creative", "simple", "simple_note", "standard_note"))]
        if start_date is not None:
            conditions.append(XHSReportDaily.report_date >= start_date)
        if end_date is not None:
            conditions.append(XHSReportDaily.report_date <= end_date)

        stmt = select(XHSReportDaily.report_type, XHSReportDaily.report_date, XHSReportDaily.payload).where(and_(*conditions))
        result = await self.db.execute(stmt)
        note_sources: dict[str, dict[str, Any]] = {}
        for report_type, report_date, payload in result.all():
            for note_id in self._paid_report_note_keys(str(report_type or ""), payload):
                value = note_sources.setdefault(note_id, {
                    "first_seen": report_date,
                    "last_seen": report_date,
                    "sources": set(),
                })
                if report_date and (not value["first_seen"] or report_date < value["first_seen"]):
                    value["first_seen"] = report_date
                if report_date and (not value["last_seen"] or report_date > value["last_seen"]):
                    value["last_seen"] = report_date
                value["sources"].add(str(report_type or ""))

        if not note_sources:
            return {"promoted_note_ids": 0, "updated_notes": 0}

        existing_rows = await self.db.execute(
            select(XHSAccountNote).where(XHSAccountNote.feed_id.in_(list(note_sources.keys())))
        )
        notes = list(existing_rows.scalars().all())
        source_labels = {
            "simple": "简单投",
            "simple_note": "简单投笔记报表",
            "standard_note": "标准投笔记报表",
            "creative": "创意报表",
        }
        for note in notes:
            info = note_sources.get(str(note.feed_id or "").strip()) or {}
            sources = sorted(info.get("sources") or [])
            note.is_promoted = True
            note.promoted_first_seen_at = datetime.combine(info["first_seen"], datetime.min.time()) if info.get("first_seen") else note.promoted_first_seen_at
            note.promoted_last_seen_at = datetime.combine(info["last_seen"], datetime.min.time()) if info.get("last_seen") else note.promoted_last_seen_at
            note.promoted_source = "、".join(source_labels.get(source, source) for source in sources) or note.promoted_source
        await self.db.commit()
        return {"promoted_note_ids": len(note_sources), "updated_notes": len(notes)}

    @staticmethod
    def _insights_note_number(note: XHSAccountNote, field: str) -> float:
        value = getattr(note, field, 0) or 0
        try:
            number_value = float(value)
        except (TypeError, ValueError):
            return 0.0
        return number_value if number_value == number_value else 0.0

    @staticmethod
    def _insights_note_account_name(note: XHSAccountNote) -> str:
        return (
            str(getattr(note, "profile_nickname", "") or "").strip()
            or str(getattr(note, "account_name", "") or "").strip()
            or "未命名账号"
        )

    @staticmethod
    def _insights_note_account_key(note: XHSAccountNote) -> str:
        return str(getattr(note, "environment_id", "") or XHSService._insights_note_account_name(note))

    @staticmethod
    def _insights_note_date(note: XHSAccountNote) -> datetime | None:
        for field in ("published_at", "created_at", "updated_at"):
            value = getattr(note, field, None)
            if isinstance(value, datetime):
                return value
        return None

    @staticmethod
    def _insights_round(value: float, digits: int = 2) -> float:
        return round(float(value or 0), digits)

    @staticmethod
    def _insights_ratio(numerator: float, denominator: float) -> float:
        return float(numerator or 0) / float(denominator or 1) if denominator else 0.0

    @staticmethod
    def _insights_score_curve(value: float, points: list[tuple[float, float]]) -> float:
        if not points:
            return 0.0
        if value <= points[0][0]:
            return points[0][1]
        for index in range(1, len(points)):
            prev_x, prev_y = points[index - 1]
            next_x, next_y = points[index]
            if value <= next_x:
                span = next_x - prev_x
                ratio = 0.0 if span == 0 else (value - prev_x) / span
                return prev_y + (next_y - prev_y) * ratio
        return points[-1][1]

    @classmethod
    def _insights_is_quality_note(cls, note: XHSAccountNote) -> bool:
        return cls._insights_note_number(note, "view_count") >= 4000 or cls._insights_note_number(note, "comment_count") >= 30

    @classmethod
    def _insights_is_low_quality_note(cls, note: XHSAccountNote) -> bool:
        return cls._insights_note_number(note, "view_count") < 100 and cls._insights_note_number(note, "comment_count") < 3

    @classmethod
    def _insights_is_promoted_note(cls, note: XHSAccountNote) -> bool:
        return bool(
            getattr(note, "is_promoted", False)
            or getattr(note, "has_paid_report", False)
            or getattr(note, "has_creative_report", False)
        )

    @staticmethod
    def _insights_owner_role_label(role: str | None) -> str:
        if role == "xhs_lead":
            return "小红书部门负责人"
        if role == "xhs_ops":
            return "小红书运营"
        if role in {"buyer", "xhs_buyer"}:
            return "投手"
        if role == "brand_lead":
            return "品牌责任人"
        if role == "brand_ops":
            return "品牌运营"
        if role == "admin":
            return "管理员"
        return "未分配"

    @staticmethod
    def _insights_is_reportable_owner(role: str | None) -> bool:
        return role in {"xhs_ops", "xhs_lead", "brand_ops", "brand_lead", "admin"}

    @staticmethod
    def _insights_owner_role(roles: list[str]) -> str:
        normalized = normalize_roles(roles, fallback=ROLE_VIEWER)
        for role in _INSIGHTS_OWNER_ROLE_PRIORITY:
            if role in normalized:
                return role
        return get_primary_role(normalized)

    @staticmethod
    def _insights_trend_bucket(value: datetime, start_date: date | None, end_date: date | None) -> tuple[str, str]:
        current_date = value.date()
        if not start_date or not end_date or (end_date - start_date).days + 1 <= 31:
            key = current_date.isoformat()
            return key, current_date.strftime("%m/%d")
        offset = max(0, (current_date - start_date).days // 7)
        week_start = start_date + timedelta(days=offset * 7)
        week_end = min(week_start + timedelta(days=6), end_date)
        return f"week-{offset}", f"{week_start.strftime('%m/%d')}~{week_end.strftime('%m/%d')}"

    @staticmethod
    def _vehicle_normalize(value: str) -> str:
        return re.sub(r"[^0-9a-z\u4e00-\u9fa5]+", "", (value or "").lstrip("\ufeff").lower())

    @classmethod
    def _vehicle_useful_key(cls, value: str) -> bool:
        generic_terms = {"汽车", "新能源", "车", "suv", "mpv", "轿车", "买车", "车型", "政策", "电车", "油车"}
        key = cls._vehicle_normalize(value)
        return bool(key and len(key) >= 2 and key not in generic_terms)

    @classmethod
    def _vehicle_keys(cls, values: list[str]) -> list[str]:
        return sorted({cls._vehicle_normalize(value) for value in values if cls._vehicle_useful_key(value)}, key=len, reverse=True)

    @classmethod
    def _vehicle_brand_keys(cls, brand: str) -> list[str]:
        ambiguous = {"北京", "上海", "广州", "长城", "大运", "远程", "创维", "哪吒", "极越"}
        chinese_only = re.sub(r"[A-Za-z]+", "", brand or "")
        without_suffix = re.sub(r"(汽车|新能源|集团)$", "", chinese_only)
        english_only = re.sub(r"[\u4e00-\u9fa5]+", "", brand or "")
        return [key for key in cls._vehicle_keys([brand, chinese_only, without_suffix, english_only]) if key not in ambiguous]

    @classmethod
    def _vehicle_model_keys(cls, brand: str, model: str) -> list[str]:
        candidates = [model or ""]
        for prefix in [brand, re.sub(r"[A-Za-z]+", "", brand or ""), re.sub(r"(汽车|新能源|集团)$", "", brand or "")]:
            if prefix and model.startswith(prefix) and len(model) > len(prefix):
                candidates.append(model[len(prefix):])
        suffixless: list[str] = []
        for candidate in candidates:
            suffixless.append(re.sub(r"\s*(phev|ev|dm-i|dmi|em-p|增程版|纯电版|燃油版|插电混动|新能源|闪充版|hatchback)$", "", candidate, flags=re.I))
            suffixless.append(re.sub(r"\s*(phev|ev|dm-i|dmi|em-p|增程版|纯电版|燃油版|插电混动|新能源|闪充版|hatchback).*", "", candidate, flags=re.I))
        normalized = cls._vehicle_normalize(model or "")
        tails = re.findall(r"[a-z]*\d+[a-z0-9]*|[a-z]+\d+[a-z0-9]*", normalized)
        return cls._vehicle_keys([*candidates, *suffixless, *[tail for tail in tails if len(tail) >= 3]])

    @classmethod
    def set_vehicle_catalog_entries(cls, rows: list[dict[str, str]]) -> None:
        global _VEHICLE_CATALOG_CACHE
        global _VEHICLE_INDEX_CACHE
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            brand = str(row.get("brand") or "").strip()
            model = str(row.get("model") or "").strip()
            if not brand or not model:
                continue
            key = f"{cls._vehicle_normalize(brand)}:{cls._vehicle_normalize(model)}"
            if key in seen:
                continue
            seen.add(key)
            brand_keys = cls._vehicle_brand_keys(brand)
            model_keys = cls._vehicle_model_keys(brand, model)
            if brand_keys and model_keys:
                entries.append({
                    "brand": brand,
                    "model": model,
                    "brand_keys": brand_keys,
                    "model_keys": model_keys,
                })
        _VEHICLE_CATALOG_CACHE = sorted(entries, key=lambda row: max((len(key) for key in row["model_keys"]), default=0), reverse=True)
        _VEHICLE_INDEX_CACHE = None

    @classmethod
    def _vehicle_catalog(cls) -> list[dict[str, Any]]:
        global _VEHICLE_CATALOG_CACHE
        if _VEHICLE_CATALOG_CACHE is not None:
            return _VEHICLE_CATALOG_CACHE
        _VEHICLE_CATALOG_CACHE = []
        return _VEHICLE_CATALOG_CACHE

    @classmethod
    def _vehicle_index(cls) -> dict[str, Any]:
        global _VEHICLE_INDEX_CACHE
        if _VEHICLE_INDEX_CACHE is not None:
            return _VEHICLE_INDEX_CACHE
        entries = cls._vehicle_catalog()
        model_by_key: dict[str, list[int]] = {}
        brand_by_key: dict[str, list[int]] = {}
        for index, entry in enumerate(entries):
            for key in entry["model_keys"]:
                model_by_key.setdefault(key, []).append(index)
            for key in entry["brand_keys"]:
                brand_by_key.setdefault(key, []).append(index)
        keys = sorted({*model_by_key.keys(), *brand_by_key.keys()}, key=len, reverse=True)
        pattern = re.compile("|".join(re.escape(key) for key in keys)) if keys else None
        _VEHICLE_INDEX_CACHE = {
            "entries": entries,
            "model_by_key": model_by_key,
            "brand_by_key": brand_by_key,
            "pattern": pattern,
        }
        return _VEHICLE_INDEX_CACHE

    @classmethod
    def _vehicle_text_sections(cls, note: XHSAccountNote) -> dict[str, str]:
        title = str(getattr(note, "title", "") or "")
        content = str(getattr(note, "content", "") or "")
        topics = " ".join(match.group(1) for match in re.finditer(r"#([^#\[\]\n]+)(?:\[话题\])?#", f"{title} {content}"))
        return {
            "title": cls._vehicle_normalize(title),
            "topics": cls._vehicle_normalize(topics),
            "lead": cls._vehicle_normalize(f"{title} {content[:160]}"),
            "full": cls._vehicle_normalize(f"{title} {content}"),
        }

    @staticmethod
    def _vehicle_section_score(key: str, sections: dict[str, str]) -> int:
        if not key:
            return 0
        if key in sections["title"]:
            return 30
        if key in sections["topics"]:
            return 25
        if key in sections["lead"]:
            return 12
        if key in sections["full"]:
            return 5
        return 0

    @classmethod
    def _vehicle_best_score(cls, keys: list[str], sections: dict[str, str]) -> tuple[str, int]:
        best_key = ""
        best_score = 0
        for key in keys:
            score = cls._vehicle_section_score(key, sections)
            if score > best_score or (score == best_score and len(key) > len(best_key)):
                best_key = key
                best_score = score
        return best_key, best_score

    @staticmethod
    def _vehicle_short_ambiguous(key: str) -> bool:
        if not key or len(key) <= 1:
            return True
        if re.fullmatch(r"\d+", key):
            return True
        if re.fullmatch(r"[a-z]\d{1,2}", key, flags=re.I):
            return True
        return len(key) <= 2 and not re.search(r"[a-z0-9]", key, flags=re.I)

    @classmethod
    def _vehicle_section_key_scores(cls, sections: dict[str, str]) -> dict[str, int]:
        index = cls._vehicle_index()
        pattern = index.get("pattern")
        if pattern is None:
            return {}
        scores: dict[str, int] = {}
        for section_name, section_score in (("title", 30), ("topics", 25)):
            text = sections.get(section_name) or ""
            for match in pattern.finditer(text):
                key = match.group(0)
                if section_score > scores.get(key, 0):
                    scores[key] = section_score
        if scores:
            return scores
        text = sections.get("lead") or ""
        for match in pattern.finditer(text):
            key = match.group(0)
            if 12 > scores.get(key, 0):
                scores[key] = 12
        if scores:
            return scores
        text = sections.get("full") or ""
        for match in pattern.finditer(text):
            key = match.group(0)
            if 5 > scores.get(key, 0):
                scores[key] = 5
        return scores

    @classmethod
    def _vehicle_best_from_scores(cls, keys: list[str], scores: dict[str, int]) -> tuple[str, int]:
        best_key = ""
        best_score = 0
        for key in keys:
            score = scores.get(key, 0)
            if score > best_score or (score == best_score and len(key) > len(best_key)):
                best_key = key
                best_score = score
        return best_key, best_score

    @classmethod
    def _vehicle_match(cls, note: XHSAccountNote) -> dict[str, Any]:
        sections = cls._vehicle_text_sections(note)
        if not sections["full"]:
            return {"brand": "未识别品牌", "model": "未识别车型", "score": 0}
        index = cls._vehicle_index()
        key_scores = cls._vehicle_section_key_scores(sections)
        if key_scores:
            candidate_indexes: set[int] = set()
            for key in key_scores:
                candidate_indexes.update(index["model_by_key"].get(key, []))
                candidate_indexes.update(index["brand_by_key"].get(key, []))
            best_indexed: dict[str, Any] | None = None
            for entry_index in candidate_indexes:
                entry = index["entries"][entry_index]
                brand_key, brand_score = cls._vehicle_best_from_scores(entry["brand_keys"], key_scores)
                model_key, model_score = cls._vehicle_best_from_scores(entry["model_keys"], key_scores)
                brand_matched = brand_score > 0
                if model_score > 0:
                    short_model = cls._vehicle_short_ambiguous(model_key)
                    if not short_model or brand_matched or model_key in sections["topics"] or model_key in sections["title"]:
                        exact_model = cls._vehicle_normalize(entry["model"]) == model_key
                        score = (100 if exact_model else 82) + model_score + (24 if brand_matched else 0) + min(len(model_key), 12)
                        candidate = {"brand": entry["brand"], "model": entry["model"], "score": score}
                        if not best_indexed or candidate["score"] > best_indexed["score"]:
                            best_indexed = candidate
                if brand_matched:
                    candidate = {"brand": entry["brand"], "model": "未识别车型", "score": 20 + brand_score + min(len(brand_key), 8)}
                    if not best_indexed or candidate["score"] > best_indexed["score"]:
                        best_indexed = candidate
            if best_indexed:
                return best_indexed
        best: dict[str, Any] | None = None
        for entry in cls._vehicle_catalog():
            brand_key, brand_score = cls._vehicle_best_score(entry["brand_keys"], sections)
            model_key, model_score = cls._vehicle_best_score(entry["model_keys"], sections)
            brand_matched = brand_score > 0
            if model_score > 0:
                short_model = cls._vehicle_short_ambiguous(model_key)
                if not short_model or brand_matched or model_key in sections["topics"] or model_key in sections["title"]:
                    exact_model = cls._vehicle_normalize(entry["model"]) == model_key
                    score = (100 if exact_model else 82) + model_score + (24 if brand_matched else 0) + min(len(model_key), 12)
                    candidate = {"brand": entry["brand"], "model": entry["model"], "score": score}
                    if not best or candidate["score"] > best["score"]:
                        best = candidate
            if brand_matched:
                candidate = {"brand": entry["brand"], "model": "未识别车型", "score": 20 + brand_score + min(len(brand_key), 8)}
                if not best or candidate["score"] > best["score"]:
                    best = candidate
        return best or {"brand": "未识别品牌", "model": "未识别车型", "score": 0}

    @classmethod
    def _build_insights_car_type_stats(cls, items: list[XHSAccountNote]) -> list[dict[str, Any]]:
        brand_map: dict[str, dict[str, Any]] = {}
        total_posts = max(1, len(items))
        for note in items:
            match = cls._vehicle_match(note)
            brand = match["brand"]
            model = match["model"]
            views = int(cls._insights_note_number(note, "view_count"))
            comments = int(cls._insights_note_number(note, "comment_count"))
            engagement = int(
                cls._insights_note_number(note, "liked_count")
                + cls._insights_note_number(note, "comment_count")
                + cls._insights_note_number(note, "collected_count")
                + cls._insights_note_number(note, "share_count")
            )
            group = brand_map.setdefault(brand, {"brand": brand, "models": {}, "posts": 0, "totalViews": 0, "totalComments": 0, "totalEngagement": 0, "qualityCount": 0})
            model_group = group["models"].setdefault(model, {"name": model, "brand": brand, "model": model, "posts": 0, "totalViews": 0, "totalComments": 0, "totalEngagement": 0, "qualityCount": 0})
            for target in (group, model_group):
                target["posts"] += 1
                target["totalViews"] += views
                target["totalComments"] += comments
                target["totalEngagement"] += engagement
                target["qualityCount"] += 1 if cls._insights_is_quality_note(note) else 0

        rows: list[dict[str, Any]] = []
        for group in brand_map.values():
            posts = max(1, group["posts"])
            row = {
                "name": group["brand"],
                "brand": group["brand"],
                "posts": group["posts"],
                "totalViews": group["totalViews"],
                "totalComments": group["totalComments"],
                "totalEngagement": group["totalEngagement"],
                "avgViews": cls._insights_ratio(group["totalViews"], posts),
                "avgComments": cls._insights_ratio(group["totalComments"], posts),
                "qualityCount": group["qualityCount"],
                "share": cls._insights_ratio(group["posts"], total_posts),
                "models": [],
            }
            row["models"] = sorted([
                {
                    **model,
                    "avgViews": cls._insights_ratio(model["totalViews"], max(1, model["posts"])),
                    "avgComments": cls._insights_ratio(model["totalComments"], max(1, model["posts"])),
                    "share": cls._insights_ratio(model["posts"], posts),
                }
                for model in group["models"].values()
            ], key=lambda model: (-model["posts"], -model["totalViews"]))
            rows.append(row)
        return sorted(rows, key=lambda row: (-row["posts"], -row["totalViews"])) or [{
            "name": "暂无样本",
            "brand": "暂无样本",
            "posts": 0,
            "totalViews": 0,
            "totalComments": 0,
            "totalEngagement": 0,
            "avgViews": 0,
            "avgComments": 0,
            "qualityCount": 0,
            "share": 0,
            "models": [],
        }]

    @classmethod
    def build_insights_dashboard(
        cls,
        items: list[XHSAccountNote],
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        latest_updated = max((getattr(note, "updated_at", None) or getattr(note, "created_at", None) or datetime.min for note in items), default=datetime.min)
        owner_signature = "|".join(
            sorted({
                f"{getattr(note, 'owner_user_id', '')}:{getattr(note, 'owner_username', '')}:{getattr(note, 'owner_role', '')}"
                for note in items
                if getattr(note, "owner_user_id", None)
            })
        )
        cache_key = "|".join([
            start_date.isoformat() if start_date else "",
            end_date.isoformat() if end_date else "",
            str(len(items)),
            str(getattr(items[0], "id", "") if items else ""),
            str(getattr(items[-1], "id", "") if items else ""),
            latest_updated.isoformat(),
            owner_signature,
        ])
        cached = _INSIGHTS_DASHBOARD_CACHE.get(cache_key)
        if cached is not None:
            return cached

        metrics = {
            "activeAccounts": len({cls._insights_note_account_key(note) for note in items}),
            "totalPosts": len(items),
            "totalViews": 0,
            "totalLikes": 0,
            "totalComments": 0,
            "totalCollects": 0,
            "totalShares": 0,
            "totalEngagement": 0,
            "avgViews": 0,
            "avgComments": 0,
            "qualityCount": 0,
            "lowQualityCount": 0,
        }

        trend_map: dict[str, dict[str, Any]] = {}
        if start_date and end_date and (end_date - start_date).days + 1 <= 31:
            cursor = start_date
            while cursor <= end_date:
                trend_map[cursor.isoformat()] = {
                    "label": cursor.strftime("%m/%d"),
                    "posts": 0,
                    "views": 0,
                    "engagement": 0,
                    "comments": 0,
                }
                cursor += timedelta(days=1)

        accounts: dict[str, dict[str, Any]] = {}
        operators: dict[str, dict[str, Any]] = {}
        post_rankings: list[dict[str, Any]] = []

        for note in items:
            views = int(cls._insights_note_number(note, "view_count"))
            likes = int(cls._insights_note_number(note, "liked_count"))
            comments = int(cls._insights_note_number(note, "comment_count"))
            collects = int(cls._insights_note_number(note, "collected_count"))
            shares = int(cls._insights_note_number(note, "share_count"))
            engagement = likes + comments + collects + shares
            is_quality = cls._insights_is_quality_note(note)
            is_low_quality = cls._insights_is_low_quality_note(note)
            is_promoted = cls._insights_is_promoted_note(note)

            metrics["totalViews"] += views
            metrics["totalLikes"] += likes
            metrics["totalComments"] += comments
            metrics["totalCollects"] += collects
            metrics["totalShares"] += shares
            metrics["totalEngagement"] += engagement
            metrics["qualityCount"] += 1 if is_quality else 0
            metrics["lowQualityCount"] += 1 if is_low_quality else 0

            note_date = cls._insights_note_date(note)
            if note_date:
                bucket_key, bucket_label = cls._insights_trend_bucket(note_date, start_date, end_date)
                bucket = trend_map.setdefault(bucket_key, {
                    "label": bucket_label,
                    "posts": 0,
                    "views": 0,
                    "engagement": 0,
                    "comments": 0,
                })
                bucket["posts"] += 1
                bucket["views"] += views
                bucket["comments"] += comments
                bucket["engagement"] += engagement

            account_key = cls._insights_note_account_key(note)
            account = accounts.setdefault(account_key, {
                "accountKey": account_key,
                "accountName": cls._insights_note_account_name(note),
                "posts": 0,
                "totalViews": 0,
                "totalLikes": 0,
                "totalComments": 0,
                "totalCollects": 0,
                "totalShares": 0,
                "totalEngagement": 0,
                "strongPostCount": 0,
                "weakPostCount": 0,
                "activePostCount": 0,
            })
            account["posts"] += 1
            account["totalViews"] += views
            account["totalLikes"] += likes
            account["totalComments"] += comments
            account["totalCollects"] += collects
            account["totalShares"] += shares
            account["totalEngagement"] += engagement
            account["strongPostCount"] += 1 if is_quality else 0
            account["weakPostCount"] += 1 if is_low_quality else 0
            account["activePostCount"] += 1 if views >= 300 or comments >= 3 or likes >= 8 else 0

            owner_id = getattr(note, "owner_user_id", None)
            owner_role = getattr(note, "owner_role", None)
            if owner_id and cls._insights_is_reportable_owner(owner_role):
                owner_key = str(owner_id)
                operator = operators.setdefault(owner_key, {
                    "ownerId": owner_key,
                    "ownerName": getattr(note, "owner_username", None) or "未分配",
                    "ownerRole": cls._insights_owner_role_label(owner_role),
                    "accountNames": {},
                    "accountCount": 0,
                    "posts": 0,
                    "views": 0,
                    "likes": 0,
                    "collects": 0,
                    "comments": 0,
                    "shares": 0,
                    "engagement": 0,
                    "qualityCount": 0,
                    "lowQualityCount": 0,
                    "paidPosts": 0,
                    "organicPosts": 0,
                    "paidRatio": 0,
                    "naturalLeads": 0,
                    "specialNaturalLeads": 0,
                    "adLeads": 0,
                })
                operator["accountNames"][account_key] = cls._insights_note_account_name(note)
                operator["posts"] += 1
                operator["views"] += views
                operator["likes"] += likes
                operator["collects"] += collects
                operator["comments"] += comments
                operator["shares"] += shares
                operator["engagement"] += engagement
                operator["qualityCount"] += 1 if is_quality else 0
                operator["lowQualityCount"] += 1 if is_low_quality else 0
                operator["paidPosts"] += 1 if is_promoted else 0
                operator["organicPosts"] += 0 if is_promoted else 1

            title = (getattr(note, "title", None) or getattr(note, "content", None) or "未命名帖子").strip()
            image_urls = getattr(note, "image_urls", None) or []
            cover_image_url = getattr(note, "cover_image_url", None) or (image_urls[0] if image_urls else "")
            post_rankings.append({
                "noteId": int(getattr(note, "id", 0) or 0),
                "feedId": str(getattr(note, "feed_id", "") or ""),
                "title": re.sub(r"\s+", " ", title),
                "accountName": cls._insights_note_account_name(note),
                "coverImageUrl": str(cover_image_url or ""),
                "postUrl": str(getattr(note, "post_url", "") or ""),
                "views": views,
                "comments": comments,
                "engagement": engagement,
                "score": views + comments * 180 + engagement * 18,
            })

        total_posts = max(1, int(metrics["totalPosts"]))
        metrics["avgViews"] = cls._insights_ratio(metrics["totalViews"], total_posts)
        metrics["avgComments"] = cls._insights_ratio(metrics["totalComments"], total_posts)

        account_summaries: list[dict[str, Any]] = []
        for account in accounts.values():
            posts = max(1, int(account["posts"]))
            avg_views = cls._insights_round(cls._insights_ratio(account["totalViews"], posts), 2)
            avg_likes = cls._insights_round(cls._insights_ratio(account["totalLikes"], posts), 2)
            avg_comments = cls._insights_round(cls._insights_ratio(account["totalComments"], posts), 2)
            avg_collects = cls._insights_round(cls._insights_ratio(account["totalCollects"], posts), 2)
            avg_shares = cls._insights_round(cls._insights_ratio(account["totalShares"], posts), 2)
            avg_engagement = cls._insights_round(cls._insights_ratio(account["totalEngagement"], posts), 2)
            weak_rate = cls._insights_ratio(account["weakPostCount"], posts)
            strong_rate = cls._insights_ratio(account["strongPostCount"], posts)
            score_parts = {
                "sampleConfidenceScore": cls._insights_score_curve(posts, [(0, 0), (1, 1), (3, 3), (7, 5)]),
                "avgViewsScore": cls._insights_score_curve(avg_views, [(0, 0), (100, 5), (300, 14), (600, 19), (1000, 22), (2000, 27), (4000, 32)]),
                "avgCommentsScore": cls._insights_score_curve(avg_comments, [(0, 0), (1, 4), (3, 9), (8, 16), (15, 19), (20, 21), (30, 25), (45, 28)]),
                "avgEngagementScore": cls._insights_score_curve(avg_engagement, [(0, 0), (3, 4), (8, 10), (15, 13), (20, 15), (30, 17), (50, 20), (80, 22)]),
                "avgCollectShareScore": cls._insights_score_curve(avg_collects + avg_shares * 1.4, [(0, 0), (0.5, 1.5), (1.5, 3.5), (3, 6), (6, 8), (12, 9)]),
                "avgLikesScore": cls._insights_score_curve(avg_likes, [(0, 0), (1, 1), (3, 2.5), (8, 4), (20, 4)]),
                "strongRateScore": cls._insights_score_curve(strong_rate, [(0, 0), (0.05, 2), (0.1, 3.5), (0.2, 5)]),
                "weakPenalty": cls._insights_score_curve(weak_rate, [(0, 0), (0.2, 2), (0.5, 5), (1, 6)]),
            }
            score = max(0.0, min(100.0, sum(value for key, value in score_parts.items() if key != "weakPenalty") - score_parts["weakPenalty"]))
            status = "主推" if account["strongPostCount"] >= 2 and avg_views >= 800 else "修正" if avg_views >= 300 or avg_comments >= 3 else "补样本" if posts < 3 else "观察"
            account_summaries.append({
                "accountKey": str(account["accountKey"]),
                "accountName": account["accountName"],
                "posts": account["posts"],
                "totalViews": account["totalViews"],
                "totalComments": account["totalComments"],
                "totalEngagement": account["totalEngagement"],
                "avgViews": avg_views,
                "avgComments": avg_comments,
                "avgEngagement": avg_engagement,
                "weakRate": weak_rate,
                "strongRate": strong_rate,
                "strongPostCount": account["strongPostCount"],
                "weakPostCount": account["weakPostCount"],
                "activePostCount": account["activePostCount"],
                "missingInteractionMetrics": account["posts"] > 0 and account["totalViews"] > 0 and account["totalComments"] == 0 and account["totalCollects"] == 0 and account["totalShares"] == 0,
                "score": cls._insights_round(score, 2),
                "scoreBreakdown": {key: cls._insights_round(value, 2) for key, value in score_parts.items()},
                "status": status,
                "strongestSignal": f"累计浏览 {int(account['totalViews']):,}、评论 {int(account['totalComments']):,}，高信号样本 {int(account['strongPostCount']):,} 条。",
                "biggestProblem": f"低信号样本 {int(account['weakPostCount']):,} 条，继续观察自然反馈稳定性。",
                "nextAction": "继续放大" if status == "主推" else "修正表达" if status == "修正" else "补控变量样本",
            })

        operator_rows: list[dict[str, Any]] = []
        for operator in operators.values():
            operator["accountNames"] = sorted(operator["accountNames"].values())
            operator["accountCount"] = len(operator["accountNames"])
            operator["paidRatio"] = cls._insights_ratio(operator["paidPosts"], operator["posts"])
            operator_rows.append(operator)

        dashboard = {
            "metrics": metrics,
            "trend": [
                point for point in trend_map.values()
                if point["posts"] > 0 or point["views"] > 0 or point["comments"] > 0 or point["engagement"] > 0
            ],
            "accountSummaries": sorted(account_summaries, key=lambda row: (-row["score"], -row["avgComments"], -row["avgViews"])),
            "postRankings": sorted(post_rankings, key=lambda row: -row["score"])[:50],
            "operatorRows": sorted(operator_rows, key=lambda row: (-row["posts"], -row["views"], row["ownerName"])),
            "carTypeStats": cls._build_insights_car_type_stats(items),
        }
        if len(_INSIGHTS_DASHBOARD_CACHE) > 12:
            _INSIGHTS_DASHBOARD_CACHE.clear()
        _INSIGHTS_DASHBOARD_CACHE[cache_key] = dashboard
        return dashboard

    async def list_account_notes_for_insights(
        self,
        user: User,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 5000,
        status: str | None = "active",
    ) -> tuple[list[XHSAccountNote], int, int]:
        envs = await self.list_environments(user, include_inactive=True)
        allowed_env_ids = {env.id for env in envs}
        if not allowed_env_ids:
            return [], 0, 0

        note_date = func.coalesce(
            XHSAccountNote.published_at,
            XHSAccountNote.created_at,
            XHSAccountNote.updated_at,
        )
        conditions = [XHSAccountNote.environment_id.in_(allowed_env_ids)]
        status_value = (status or "").strip()
        if status_value and status_value != "all":
            conditions.append(XHSAccountNote.status == status_value)
        if start_date is not None:
            conditions.append(note_date >= datetime.combine(start_date, datetime.min.time()))
        if end_date is not None:
            conditions.append(note_date < datetime.combine(end_date + timedelta(days=1), datetime.min.time()))

        where_clause = and_(*conditions)
        total_stmt = select(func.count()).select_from(XHSAccountNote).where(where_clause)
        total = int((await self.db.execute(total_stmt)).scalar() or 0)

        account_count_stmt = (
            select(func.count(func.distinct(XHSAccountNote.environment_id)))
            .select_from(XHSAccountNote)
            .where(where_clause)
        )
        total_accounts = int((await self.db.execute(account_count_stmt)).scalar() or 0)

        stmt = (
            select(XHSAccountNote)
            .where(where_clause)
            .options(
                selectinload(XHSAccountNote.environment),
                selectinload(XHSAccountNote.assigned_runner_environment),
            )
            .order_by(note_date.desc(), XHSAccountNote.id.desc())
            .limit(limit)
        )
        items = list((await self.db.execute(stmt)).scalars().all())
        await self._attach_environment_owners(items)
        # The dashboard already persists promoted flags during report refresh. Avoid
        # re-scanning ad report JSON on every dashboard load; that scan dominates
        # page latency and does not change the note list content.
        await self._attach_paid_report_flags(items, start_date=start_date, end_date=end_date, resolve_from_reports=False)
        return items, total, total_accounts

    async def list_sync_runner_environments(self) -> list[XHSEnvironment]:
        explicit_stmt = (
            select(XHSEnvironment)
            .where(and_(XHSEnvironment.status == "active", XHSEnvironment.is_sync_runner.is_(True)))
            .order_by(XHSEnvironment.account_name.asc(), XHSEnvironment.id.asc())
        )
        explicit_envs = list((await self.db.execute(explicit_stmt)).scalars().all())
        fallback_stmt = (
            select(XHSEnvironment)
            .where(
                and_(
                    XHSEnvironment.status == "active",
                    or_(
                        XHSEnvironment.account_name.like("%测试2%"),
                        XHSEnvironment.account_name.like("%测试3%"),
                        XHSEnvironment.account_name.like("%测试4%"),
                        XHSEnvironment.account_name.like("%测试5%"),
                    ),
                )
            )
            .order_by(XHSEnvironment.account_name.asc(), XHSEnvironment.id.asc())
        )
        fallback_envs = list((await self.db.execute(fallback_stmt)).scalars().all())
        merged: list[XHSEnvironment] = []
        seen_ids: set[int] = set()
        for env in [*explicit_envs, *fallback_envs]:
            env_id = int(env.id)
            if env_id in seen_ids:
                continue
            seen_ids.add(env_id)
            merged.append(env)
        return merged

    async def rebalance_account_note_runner_assignments(
        self,
        notes: list[XHSAccountNote],
        *,
        runner_envs: list[XHSEnvironment] | None = None,
    ) -> dict[int, int]:
        if not notes:
            return {}
        active_runners = runner_envs or await self.list_sync_runner_environments()
        if not active_runners:
            return {}

        runner_ids = [int(env.id) for env in active_runners]
        target_environment_ids = sorted({int(note.environment_id or 0) for note in notes if int(note.environment_id or 0) > 0})
        if not target_environment_ids:
            return {}
        target_notes_stmt = (
            select(XHSAccountNote)
            .where(XHSAccountNote.environment_id.in_(target_environment_ids))
            .order_by(XHSAccountNote.environment_id.asc(), XHSAccountNote.sort_index.asc(), XHSAccountNote.id.asc())
        )
        effective_notes = list((await self.db.execute(target_notes_stmt)).scalars().all())
        if not effective_notes:
            return {}
        assignment_count_stmt = (
            select(
                XHSAccountNote.assigned_runner_environment_id,
                func.count(func.distinct(XHSAccountNote.environment_id)),
            )
            .where(XHSAccountNote.assigned_runner_environment_id.in_(runner_ids))
            .group_by(XHSAccountNote.assigned_runner_environment_id)
        )
        assignment_rows = await self.db.execute(assignment_count_stmt)
        assignment_counts = {int(row[0]): int(row[1] or 0) for row in assignment_rows.all() if row[0] is not None}

        grouped_notes: dict[int, list[XHSAccountNote]] = {}
        for note in effective_notes:
            env_id = int(note.environment_id or 0)
            grouped_notes.setdefault(env_id, []).append(note)

        for env_id, grouped in grouped_notes.items():
            current_runner_ids = {
                int(note.assigned_runner_environment_id or 0)
                for note in grouped
                if int(note.assigned_runner_environment_id or 0) in assignment_counts
            }
            for current_runner_id in current_runner_ids:
                assignment_counts[current_runner_id] = max(0, assignment_counts.get(current_runner_id, 0) - 1)

        now = utc_now_naive()
        note_to_runner: dict[int, int] = {}
        for env_id in sorted(grouped_notes):
            selected_runner = min(
                active_runners,
                key=lambda env: (assignment_counts.get(int(env.id), 0), env.account_name or "", int(env.id)),
            )
            selected_runner_id = int(selected_runner.id)
            for note in grouped_notes.get(env_id) or []:
                note.assigned_runner_environment_id = selected_runner_id
                note.assignment_updated_at = now
                note.assigned_runner_environment = selected_runner
                if note.id is not None:
                    note_to_runner[int(note.id)] = selected_runner_id
            assignment_counts[selected_runner_id] = assignment_counts.get(selected_runner_id, 0) + 1
        return note_to_runner

    @staticmethod
    def _assign_account_note_runner(
        notes: list[XHSAccountNote],
        runner_env: XHSEnvironment,
    ) -> dict[int, int]:
        note_to_runner: dict[int, int] = {}
        now = utc_now_naive()
        runner_id = int(runner_env.id)
        for note in notes:
            note.assigned_runner_environment_id = runner_id
            note.assignment_updated_at = now
            note.assigned_runner_environment = runner_env
            if note.id is not None:
                note_to_runner[int(note.id)] = runner_id
        return note_to_runner

    async def _ensure_note_assigned_runner(self, note: XHSAccountNote) -> XHSEnvironment:
        current_runner_id = int(note.assigned_runner_environment_id or 0)
        if current_runner_id > 0:
            current_runner = await self.get_environment(current_runner_id)
            if current_runner and current_runner.status == "active" and (current_runner.is_sync_runner or re.search(r"测试[2345]", current_runner.account_name or "")):
                note.assigned_runner_environment = current_runner
                return current_runner

        runner_envs = await self.list_sync_runner_environments()
        if not runner_envs:
            raise RuntimeError("未找到可用的测试同步环境，请先在后台给测试账号开启“同步环境”")
        await self.rebalance_account_note_runner_assignments([note], runner_envs=runner_envs)
        loaded_runner = self._get_loaded_relationship(note, "assigned_runner_environment")
        return loaded_runner or runner_envs[0]

    async def _resolve_sync_scrape_env_candidates(self, preferred_env_id: int | None = None) -> list[XHSEnvironment]:
        candidates: list[XHSEnvironment] = []
        seen_ids: set[int] = set()

        if preferred_env_id and preferred_env_id > 0:
            env = await self.get_environment(preferred_env_id)
            if env and env.status == "active":
                candidates.append(env)
                seen_ids.add(int(env.id))

        for env in await self.list_sync_runner_environments():
            env_id = int(env.id)
            if env_id in seen_ids or env.status != "active":
                continue
            candidates.append(env)
            seen_ids.add(env_id)

        if candidates:
            return candidates

        fallback = await self._resolve_account_scrape_environment(preferred_env_id)
        return [fallback]

    async def _acquire_ready_sync_browser_ws_with_fallback(
        self,
        preferred_env_id: int | None = None,
        *,
        allow_fallback: bool = True,
    ) -> tuple[XHSEnvironment | None, str | None]:
        candidates = await self._resolve_sync_scrape_env_candidates(preferred_env_id)
        if not allow_fallback and preferred_env_id and candidates:
            candidates = candidates[:1]
        for index, candidate in enumerate(candidates):
            ws_url = await self._acquire_ready_sync_browser_ws(candidate)
            if ws_url:
                if index > 0:
                    logger.warning(
                        "同步环境启动失败后已切换备用账号: preferred=%s active=%s",
                        preferred_env_id,
                        candidate.account_name,
                    )
                return candidate, ws_url
        return None, None

    async def record_account_note_browse(
        self,
        note: XHSAccountNote,
        *,
        browse_source: str,
        runner_env: XHSEnvironment | None = None,
        job_id: str | None = None,
        commit: bool = True,
    ) -> XHSAccountNoteBrowseEvent:
        active_runner = runner_env or await self._ensure_note_assigned_runner(note)
        owner_runner = await self._resolve_account_note_owner_runner(note, fallback_runner=active_runner)
        event = XHSAccountNoteBrowseEvent(
            note_id=int(note.id),
            runner_environment_id=int(active_runner.id),
            browse_source=browse_source,
            job_id=(job_id or "").strip() or None,
            note_feed_id=note.feed_id or None,
            note_title=(note.title or "").strip() or None,
            note_post_url=(note.post_url or "").strip() or None,
            source_environment_id=int(note.environment_id or 0) or None,
            source_account_name=(note.account_name or "").strip() or None,
            owner_runner_environment_id=int(owner_runner.id) if owner_runner else None,
            owner_runner_account_name=(owner_runner.account_name or "").strip() if owner_runner else None,
            runner_account_name=(active_runner.account_name or "").strip() or None,
        )
        self.db.add(event)
        if commit:
            await self.db.commit()
        return event

    @staticmethod
    def _get_loaded_relationship(instance: object, attr_name: str) -> Any | None:
        """Read an ORM relationship only when it is already loaded."""
        loaded_value = sa_inspect(instance).attrs[attr_name].loaded_value
        if loaded_value is NO_VALUE:
            return None
        return loaded_value

    async def _resolve_account_note_owner_runner(
        self,
        note: XHSAccountNote,
        *,
        fallback_runner: XHSEnvironment | None = None,
    ) -> XHSEnvironment | None:
        owner_runner_id = int(getattr(note, "assigned_runner_environment_id", 0) or 0)
        if owner_runner_id > 0:
            loaded_owner = self._get_loaded_relationship(note, "assigned_runner_environment")
            if loaded_owner is not None and int(getattr(loaded_owner, "id", 0) or 0) == owner_runner_id:
                return loaded_owner
            owner_runner = await self.get_environment(owner_runner_id)
            if owner_runner:
                note.assigned_runner_environment = owner_runner
                return owner_runner
        ensured_owner = await self._ensure_note_assigned_runner(note)
        if ensured_owner:
            return ensured_owner
        return fallback_runner

    async def get_sync_runner_browse_overview(self, days: int = 7, limit: int = 80) -> dict:
        normalized_days = max(1, min(int(days or 7), 30))
        normalized_limit = max(20, min(int(limit or 80), 300))
        runner_envs = await self.list_sync_runner_environments()
        if not runner_envs:
            return {
                "date": date.today().isoformat(),
                "days": normalized_days,
                "total_views_today": 0,
                "runners": [],
                "recent_events": [],
            }

        runner_ids = [int(env.id) for env in runner_envs]
        today_value = date.today().isoformat()
        period_start = date.today() - timedelta(days=normalized_days - 1)

        assigned_stmt = (
            select(
                XHSAccountNote.assigned_runner_environment_id,
                func.count(XHSAccountNote.id),
            )
            .where(XHSAccountNote.assigned_runner_environment_id.in_(runner_ids))
            .group_by(XHSAccountNote.assigned_runner_environment_id)
        )
        assigned_rows = await self.db.execute(assigned_stmt)
        assigned_counts = {int(row[0]): int(row[1] or 0) for row in assigned_rows.all() if row[0] is not None}

        assigned_account_stmt = (
            select(
                XHSAccountNote.assigned_runner_environment_id,
                XHSAccountNote.environment_id,
                func.max(XHSAccountNote.account_name),
                func.count(XHSAccountNote.id),
            )
            .where(XHSAccountNote.assigned_runner_environment_id.in_(runner_ids))
            .group_by(
                XHSAccountNote.assigned_runner_environment_id,
                XHSAccountNote.environment_id,
            )
            .order_by(
                XHSAccountNote.assigned_runner_environment_id.asc(),
                func.max(XHSAccountNote.account_name).asc(),
                XHSAccountNote.environment_id.asc(),
            )
        )
        assigned_account_rows = await self.db.execute(assigned_account_stmt)
        assigned_accounts_by_runner: dict[int, list[dict[str, Any]]] = {}
        for runner_id, environment_id, account_name, note_count in assigned_account_rows.all():
            if runner_id is None or environment_id is None:
                continue
            assigned_accounts_by_runner.setdefault(int(runner_id), []).append(
                {
                    "environment_id": int(environment_id),
                    "account_name": (account_name or "").strip() or f"环境 {environment_id}",
                    "note_count": int(note_count or 0),
                }
            )

        owner_runner_expr = func.coalesce(
            XHSAccountNoteBrowseEvent.owner_runner_environment_id,
            XHSAccountNote.assigned_runner_environment_id,
        )
        owner_period_stmt = (
            select(
                owner_runner_expr,
                func.date(XHSAccountNoteBrowseEvent.created_at),
                XHSAccountNoteBrowseEvent.browse_source,
                func.count(XHSAccountNoteBrowseEvent.id),
            )
            .select_from(XHSAccountNoteBrowseEvent)
            .outerjoin(XHSAccountNote, XHSAccountNote.id == XHSAccountNoteBrowseEvent.note_id)
            .where(
                and_(
                    owner_runner_expr.in_(runner_ids),
                    func.date(XHSAccountNoteBrowseEvent.created_at) >= period_start,
                )
            )
            .group_by(
                owner_runner_expr,
                func.date(XHSAccountNoteBrowseEvent.created_at),
                XHSAccountNoteBrowseEvent.browse_source,
            )
        )
        owner_period_rows = await self.db.execute(owner_period_stmt)
        owner_day_counts: dict[tuple[int, str, str], int] = {}
        for runner_id, day_value, browse_source, count in owner_period_rows.all():
            if runner_id is None or day_value is None or browse_source is None:
                continue
            owner_day_counts[(int(runner_id), str(day_value), str(browse_source))] = int(count or 0)

        executor_period_stmt = (
            select(
                XHSAccountNoteBrowseEvent.runner_environment_id,
                func.date(XHSAccountNoteBrowseEvent.created_at),
                XHSAccountNoteBrowseEvent.browse_source,
                func.count(XHSAccountNoteBrowseEvent.id),
            )
            .where(
                and_(
                    XHSAccountNoteBrowseEvent.runner_environment_id.in_(runner_ids),
                    func.date(XHSAccountNoteBrowseEvent.created_at) >= period_start,
                )
            )
            .group_by(
                XHSAccountNoteBrowseEvent.runner_environment_id,
                func.date(XHSAccountNoteBrowseEvent.created_at),
                XHSAccountNoteBrowseEvent.browse_source,
            )
        )
        executor_period_rows = await self.db.execute(executor_period_stmt)
        executor_day_counts: dict[tuple[int, str, str], int] = {}
        for runner_id, day_value, browse_source, count in executor_period_rows.all():
            if runner_id is None or day_value is None or browse_source is None:
                continue
            executor_day_counts[(int(runner_id), str(day_value), str(browse_source))] = int(count or 0)

        recent_stmt = (
            select(XHSAccountNoteBrowseEvent)
            .where(XHSAccountNoteBrowseEvent.runner_environment_id.in_(runner_ids))
            .order_by(XHSAccountNoteBrowseEvent.created_at.desc(), XHSAccountNoteBrowseEvent.id.desc())
            .limit(normalized_limit)
        )
        recent_events = list((await self.db.execute(recent_stmt)).scalars().all())

        runners_payload: list[dict[str, Any]] = []
        total_views_today = 0
        day_keys = [(date.today() - timedelta(days=offset)).isoformat() for offset in range(normalized_days)]
        day_keys.reverse()
        for env in runner_envs:
            env_id = int(env.id)
            timeline = []
            today_link_clicks = 0
            today_sync_views = 0
            today_executor_link_clicks = 0
            today_executor_sync_views = 0
            for day_key in day_keys:
                link_clicks = owner_day_counts.get((env_id, day_key, "link_click"), 0)
                single_syncs = owner_day_counts.get((env_id, day_key, "single_sync"), 0)
                bulk_syncs = owner_day_counts.get((env_id, day_key, "bulk_sync"), 0)
                sync_views = single_syncs + bulk_syncs
                total_views = link_clicks + sync_views
                executor_link_clicks = executor_day_counts.get((env_id, day_key, "link_click"), 0)
                executor_single_syncs = executor_day_counts.get((env_id, day_key, "single_sync"), 0)
                executor_bulk_syncs = executor_day_counts.get((env_id, day_key, "bulk_sync"), 0)
                executor_sync_views = executor_single_syncs + executor_bulk_syncs
                if day_key == today_value:
                    today_link_clicks = link_clicks
                    today_sync_views = sync_views
                    today_executor_link_clicks = executor_link_clicks
                    today_executor_sync_views = executor_sync_views
                    total_views_today += total_views
                timeline.append(
                    {
                        "date": day_key,
                        "link_clicks": link_clicks,
                        "sync_views": sync_views,
                        "total_views": total_views,
                        "executor_link_clicks": executor_link_clicks,
                        "executor_sync_views": executor_sync_views,
                    }
                )
            runners_payload.append(
                {
                    "environment_id": env_id,
                    "account_name": env.account_name,
                    "assigned_notes": assigned_counts.get(env_id, 0),
                    "assigned_accounts": assigned_accounts_by_runner.get(env_id, []),
                    "today_link_clicks": today_link_clicks,
                    "today_sync_views": today_sync_views,
                    "today_total_views": today_link_clicks + today_sync_views,
                    "today_executor_link_clicks": today_executor_link_clicks,
                    "today_executor_sync_views": today_executor_sync_views,
                    "today_executor_total_views": today_executor_link_clicks + today_executor_sync_views,
                    "timeline": timeline,
                }
            )

        return {
            "date": today_value,
            "days": normalized_days,
            "total_views_today": total_views_today,
            "runners": runners_payload,
            "recent_events": [
                {
                    "id": int(event.id),
                    "runner_environment_id": int(event.runner_environment_id),
                    "runner_account_name": event.runner_account_name,
                    "note_id": int(event.note_id),
                    "note_feed_id": event.note_feed_id,
                    "note_title": event.note_title,
                    "note_post_url": event.note_post_url,
                    "source_environment_id": event.source_environment_id,
                    "source_account_name": event.source_account_name,
                    "owner_runner_environment_id": event.owner_runner_environment_id,
                    "owner_runner_account_name": event.owner_runner_account_name,
                    "browse_source": event.browse_source,
                    "job_id": event.job_id,
                    "created_at": event.created_at.isoformat() if event.created_at else None,
                }
                for event in recent_events
            ],
        }

    async def sync_account_notes(
        self,
        *,
        user: User | None = None,
        environment_id: int | None = None,
        scrape_environment_id: int | None = None,
        scrape_environment_ids: str | list[int] | tuple[int, ...] | None = None,
        sync_account_limit: int | None = None,
        runner_account_assignments: str | dict[int | str, list[int] | tuple[int, ...] | set[int] | list[str] | tuple[str, ...]] | None = None,
        concurrency: int | None = None,
        limit_per_env: int = 60,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> dict:
        normalized_limit = max(1, min(limit_per_env, 60))
        normalized_runner_ids = self._normalize_account_note_sync_runner_ids(scrape_environment_ids)
        normalized_account_limit = self._normalize_account_note_sync_account_limit(sync_account_limit)
        normalized_runner_assignments = self._normalize_account_note_sync_runner_assignments(runner_account_assignments)
        normalized_concurrency = self._normalize_yundeng_sync_concurrency(concurrency)
        if normalized_runner_assignments:
            normalized_runner_ids = list(normalized_runner_assignments.keys())
        await self._raise_if_sync_cancelled(cancel_check)
        persona = self._build_sync_session_persona()
        if user is not None:
            envs = await self.list_environments(user)
            if environment_id is not None:
                envs = [env for env in envs if env.id == environment_id]
        else:
            stmt = (
                select(XHSEnvironment)
                .where(XHSEnvironment.status == "active")
                .order_by(XHSEnvironment.account_name.asc())
            )
            if environment_id is not None:
                stmt = stmt.where(XHSEnvironment.id == environment_id)
            envs = list((await self.db.execute(stmt)).scalars().all())

        if environment_id is not None and not envs:
            raise ValueError("云登环境不存在或无权限")
        if environment_id is None:
            envs = [env for env in envs if not self._is_sync_runner_environment(env)]
        envs_by_id = {int(env.id): env for env in envs}
        if normalized_runner_assignments:
            explicit_env_ids = [env_id for env_ids in normalized_runner_assignments.values() for env_id in env_ids]
            missing_env_ids = [env_id for env_id in explicit_env_ids if env_id not in envs_by_id]
            if missing_env_ids:
                raise ValueError(f"部分发布账号不存在、不可用，或当前不在可同步范围内: {missing_env_ids[0]}")
            envs = [envs_by_id[env_id] for env_id in explicit_env_ids]
        else:
            envs = self._humanize_environment_sync_order(envs, persona)
            if normalized_account_limit is not None:
                envs = envs[:normalized_account_limit]

        # Environment discovery is read-only. Release that transaction before
        # delegating to a worker, which can wait on YunDeng for several minutes.
        await self.db.commit()

        if self._should_delegate_browser_ops():
            if len(normalized_runner_ids) > 1 and len(envs) > 1:
                return await self._delegate_account_note_sync_by_runner(
                    envs=envs,
                    runner_ids=normalized_runner_ids,
                    runner_assignments=normalized_runner_assignments,
                    concurrency=normalized_concurrency,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                )
            if environment_id is not None or user is None or getattr(user, "role", "") == "admin":
                return await self.trigger_worker_sync_account_notes(
                    environment_id,
                    scrape_environment_id,
                    ",".join(str(item) for item in normalized_runner_ids) or None,
                    normalized_account_limit,
                    json.dumps(normalized_runner_assignments, ensure_ascii=False) if normalized_runner_assignments else None,
                )

            synced_accounts = 0
            created_notes = 0
            updated_notes = 0
            metric_synced_notes = 0
            total_notes = 0
            failed_accounts: list[dict[str, Any]] = []
            failed_runners: list[dict[str, Any]] = []
            for env in envs:
                await self._raise_if_sync_cancelled(cancel_check)
                result = await self.trigger_worker_sync_account_notes(
                    env.id,
                    scrape_environment_id,
                    ",".join(str(item) for item in normalized_runner_ids) or None,
                    1,
                    json.dumps({next(iter(normalized_runner_ids), 0): [int(env.id)]}, ensure_ascii=False) if normalized_runner_assignments else None,
                )
                synced_accounts += int(result.get("synced_accounts") or 0)
                created_notes += int(result.get("created_notes") or 0)
                updated_notes += int(result.get("updated_notes") or 0)
                metric_synced_notes += int(result.get("metric_synced_notes") or 0)
                total_notes += int(result.get("total_notes") or 0)
                failed_accounts.extend(result.get("failed_accounts") or [])
                failed_runners.extend(result.get("failed_runners") or [])
            result = {
                "synced_accounts": synced_accounts,
                "created_notes": created_notes,
                "updated_notes": updated_notes,
                "metric_synced_notes": metric_synced_notes,
                "total_notes": total_notes,
            }
            if failed_accounts:
                result["failed_accounts"] = failed_accounts
            if failed_runners:
                result["failed_runners"] = failed_runners
            return result

        self._require_local_browser_ops("同步账号帖子")
        synced_accounts = 0
        created_notes = 0
        updated_notes = 0
        metric_synced_notes = 0
        total_notes = 0
        failed_accounts: list[dict[str, Any]] = []
        failed_runners: list[dict[str, Any]] = []

        if not envs:
            return {
                "synced_accounts": 0,
                "created_notes": 0,
                "updated_notes": 0,
                "metric_synced_notes": 0,
                "total_notes": 0,
            }

        scrape_envs = await self._resolve_account_scrape_environments(
            scrape_environment_id=scrape_environment_id,
            scrape_environment_ids=normalized_runner_ids,
        )
        runner_env_by_id = {int(env.id): env for env in scrape_envs}
        if len(envs) == 1:
            try:
                target_scrape_env = runner_env_by_id.get(next(iter(normalized_runner_assignments.keys()), 0), scrape_envs[0]) if normalized_runner_assignments else scrape_envs[0]
                env_lock = await self._get_env_publish_lock(target_scrape_env.id)
                async with env_lock:
                    result = await self._sync_account_notes_for_environment_locked(
                        envs[0],
                        scrape_env=target_scrape_env,
                        limit=normalized_limit,
                        persona=persona,
                        progress_callback=progress_callback,
                        cancel_check=cancel_check,
                        total_accounts=1,
                        current_account_index=1,
                        aggregate_created_notes=0,
                        aggregate_updated_notes=0,
                        runner_envs=scrape_envs,
                    )
                synced_accounts += 1
                created_notes += int(result.get("created_notes") or 0)
                updated_notes += int(result.get("updated_notes") or 0)
                metric_synced_notes += int(result.get("metric_synced_notes") or 0)
                total_notes += int(result.get("total_notes") or 0)
            except Exception as e:
                error_message = self._sync_exception_message(e)
                logger.warning("同步账号帖子失败: env_id=%s, account=%s, error=%s", envs[0].id, envs[0].account_name, error_message)
                failed_accounts.append(
                    {
                        "environment_id": int(envs[0].id),
                        "account_name": envs[0].account_name,
                        "error": error_message,
                    }
                )
                await self._emit_progress(
                    progress_callback,
                    {
                        "phase": "account_posts_failed",
                        "detail": f"{envs[0].account_name} 的账号帖子同步失败",
                        "account_name": envs[0].account_name,
                        "account_index": 1,
                        "account_total": 1,
                        "error": error_message,
                    },
                )
        else:
            if normalized_runner_assignments:
                runner_buckets = [
                    (runner_env_by_id[runner_id], [envs_by_id[env_id] for env_id in env_ids])
                    for runner_id, env_ids in normalized_runner_assignments.items()
                    if runner_id in runner_env_by_id and env_ids
                ]
                batch_result = await self._sync_account_notes_with_strategy(
                    envs=envs,
                    scrape_envs=scrape_envs,
                    limit=normalized_limit,
                    persona=persona,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                    runner_buckets=runner_buckets,
                    concurrency=normalized_concurrency,
                )
            elif len(scrape_envs) == 1:
                env_lock = await self._get_env_publish_lock(scrape_envs[0].id)
                async with env_lock:
                    batch_result = await self._sync_account_notes_batch_locked(
                        envs,
                        scrape_env=scrape_envs[0],
                        limit=normalized_limit,
                        persona=persona,
                        progress_callback=progress_callback,
                        cancel_check=cancel_check,
                        runner_envs=scrape_envs,
                        processed_offset=0,
                        total_accounts=len(envs),
                        base_synced_accounts=0,
                        base_created_notes=0,
                        base_updated_notes=0,
                    )
            else:
                batch_result = await self._sync_account_notes_with_strategy(
                    envs=envs,
                    scrape_envs=scrape_envs,
                    limit=normalized_limit,
                    persona=persona,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                    concurrency=normalized_concurrency,
                )
            synced_accounts += int(batch_result.get("synced_accounts") or 0)
            created_notes += int(batch_result.get("created_notes") or 0)
            updated_notes += int(batch_result.get("updated_notes") or 0)
            metric_synced_notes += int(batch_result.get("metric_synced_notes") or 0)
            total_notes += int(batch_result.get("total_notes") or 0)
            failed_accounts.extend(batch_result.get("failed_accounts") or [])
            failed_runners.extend(batch_result.get("failed_runners") or [])

        result = {
            "synced_accounts": synced_accounts,
            "created_notes": created_notes,
            "updated_notes": updated_notes,
            "metric_synced_notes": metric_synced_notes,
            "total_notes": total_notes,
        }
        if failed_accounts:
            result["failed_accounts"] = failed_accounts
        if failed_runners:
            result["failed_runners"] = failed_runners
        return result

    async def _sync_account_notes_for_environment(
        self,
        env: XHSEnvironment,
        *,
        scrape_environment_id: int | None = None,
        limit: int = 120,
        persona: SyncSessionPersona | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        total_accounts: int | None = None,
        current_account_index: int | None = None,
        aggregate_created_notes: int = 0,
        aggregate_updated_notes: int = 0,
        runner_envs: list[XHSEnvironment] | None = None,
    ) -> dict:
        target_scrape_environment_id = scrape_environment_id
        if target_scrape_environment_id is None:
            if runner_envs:
                target_scrape_environment_id = int(runner_envs[0].id)
            else:
                target_scrape_environment_id = int((await self._resolve_account_scrape_environment(None)).id)
        scrape_env = await self._resolve_account_scrape_environment(target_scrape_environment_id)
        env_lock = await self._get_env_publish_lock(scrape_env.id)
        async with env_lock:
            return await self._sync_account_notes_for_environment_locked(
                env,
                scrape_env=scrape_env,
                limit=limit,
                persona=persona or self._build_sync_session_persona(),
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                total_accounts=total_accounts,
                current_account_index=current_account_index,
                aggregate_created_notes=aggregate_created_notes,
                aggregate_updated_notes=aggregate_updated_notes,
                runner_envs=runner_envs,
            )

    @yundeng_sync_guard("scrape_env", "homepage_posts")
    async def _sync_account_notes_batch_locked(
        self,
        envs: list[XHSEnvironment],
        *,
        scrape_env: XHSEnvironment,
        limit: int = 120,
        persona: SyncSessionPersona,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        runner_envs: list[XHSEnvironment] | None = None,
        processed_offset: int = 0,
        total_accounts: int | None = None,
        base_synced_accounts: int = 0,
        base_created_notes: int = 0,
        base_updated_notes: int = 0,
    ) -> dict:
        mcp_pid = None
        use_external_mcp = bool(XHS_MCP_EXTERNAL_API)
        mcp_port = None if use_external_mcp else await self._allocate_free_port()
        mcp_api = XHS_MCP_EXTERNAL_API if use_external_mcp else f"http://localhost:{mcp_port}"
        previous_mcp_api = getattr(self, "_active_mcp_api", None)
        synced_accounts = 0
        created_notes = 0
        updated_notes = 0
        total_notes = 0
        failed_accounts: list[dict[str, Any]] = []

        try:
            self._active_mcp_api = mcp_api
            active_scrape_env, ws_url = await self._acquire_ready_sync_browser_ws_with_fallback(
                int(scrape_env.id), allow_fallback=False
            )
            if active_scrape_env is not None:
                scrape_env = active_scrape_env
            if not ws_url:
                raise RuntimeError(f"无法获取采集环境 {scrape_env.shop_id} 的浏览器连接")

            if use_external_mcp:
                if not await self._check_mcp_running(mcp_api):
                    raise RuntimeError("外部小红书发布服务不可用，请先启动 XHS MCP 服务")
            else:
                mcp_pid = await self._start_mcp(ws_url, mcp_port or 0)
                if not mcp_pid:
                    raise RuntimeError("启动小红书发布服务失败，请稍后重试")
                await self._wait_mcp_ready(mcp_api)

            await self._run_sync_browser_warmup(api_base=mcp_api, persona=persona)

            overall_total_accounts = max(1, total_accounts or len(envs))
            for index, env in enumerate(envs):
                await self._raise_if_sync_cancelled(cancel_check)
                account_position = processed_offset + index + 1
                try:
                    await self._emit_progress(
                        progress_callback,
                        {
                            "phase": "opening_runner",
                            "detail": f"正在进入 {env.account_name} 的账号主页",
                            "runner_id": int(scrape_env.id),
                            "runner_name": scrape_env.account_name,
                            "account_name": env.account_name,
                            "account_index": account_position,
                            "account_total": overall_total_accounts,
                            "current": processed_offset + synced_accounts,
                            "total": overall_total_accounts,
                            "percent": int(((processed_offset + synced_accounts) / overall_total_accounts) * 100) if overall_total_accounts > 0 else 0,
                            "synced_accounts": base_synced_accounts + synced_accounts,
                            "created_notes": base_created_notes + created_notes,
                            "updated_notes": base_updated_notes + updated_notes,
                        },
                    )
                    result = await self._sync_account_notes_with_api(
                        env,
                        api_base=mcp_api,
                        limit=limit,
                        persona=persona,
                        progress_callback=progress_callback,
                        cancel_check=cancel_check,
                        total_accounts=overall_total_accounts,
                        current_account_index=account_position,
                        aggregate_created_notes=base_created_notes + created_notes,
                        aggregate_updated_notes=base_updated_notes + updated_notes,
                        runner_id=int(scrape_env.id),
                        runner_name=scrape_env.account_name,
                        runner_envs=runner_envs,
                        assigned_runner_env=scrape_env,
                    )
                    synced_accounts += 1
                    created_notes += int(result.get("created_notes") or 0)
                    updated_notes += int(result.get("updated_notes") or 0)
                    total_notes += int(result.get("total_notes") or 0)
                except Exception as e:
                    error_message = self._sync_exception_message(e)
                    logger.warning("同步账号帖子失败: env_id=%s, account=%s, error=%s", env.id, env.account_name, error_message)
                    failed_accounts.append(
                        {
                            "environment_id": int(env.id),
                            "account_name": env.account_name,
                            "error": error_message,
                        }
                    )
                    await self._emit_progress(
                        progress_callback,
                        {
                            "phase": "account_posts_failed",
                            "detail": f"{env.account_name} 的账号帖子同步失败",
                            "account_name": env.account_name,
                            "account_index": account_position,
                            "account_total": overall_total_accounts,
                            "error": error_message,
                        },
                    )
                if index < len(envs) - 1:
                    await self._raise_if_sync_cancelled(cancel_check)
                    await self._sleep_between_account_note_accounts(persona)
            result = {
                "synced_accounts": synced_accounts,
                "created_notes": created_notes,
                "updated_notes": updated_notes,
                "metric_synced_notes": 0,
                "total_notes": total_notes,
            }
            if failed_accounts:
                result["failed_accounts"] = failed_accounts
            return result
        finally:
            self._active_mcp_api = previous_mcp_api
            if mcp_pid is not None:
                await self._stop_mcp(mcp_pid)

    async def _sync_account_notes_with_strategy(
        self,
        *,
        envs: list[XHSEnvironment],
        scrape_envs: list[XHSEnvironment],
        limit: int,
        persona: SyncSessionPersona,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        runner_buckets: list[tuple[XHSEnvironment, list[XHSEnvironment]]] | None = None,
        concurrency: int = 1,
    ) -> dict:
        if not envs:
            return {
                "synced_accounts": 0,
                "created_notes": 0,
                "updated_notes": 0,
                "metric_synced_notes": 0,
                "total_notes": 0,
            }

        effective_runner_buckets = runner_buckets or [(runner_env, []) for runner_env in scrape_envs]
        if runner_buckets is None:
            for index, env in enumerate(envs):
                effective_runner_buckets[index % len(effective_runner_buckets)][1].append(env)

        overall_total_accounts = len(envs)

        await self._emit_progress(
            progress_callback,
            {
                "phase": "planning_account_posts",
                "detail": f"准备使用 {len(scrape_envs)} 个测试账号分摊 {overall_total_accounts} 个发布账号",
                "current": 0,
                "total": overall_total_accounts,
                "percent": 0,
                "synced_accounts": 0,
                "created_notes": 0,
                "updated_notes": 0,
                "runner_count": len([1 for _, assigned_envs in effective_runner_buckets if assigned_envs]),
            },
        )

        active_buckets: list[tuple[int, list[int], int]] = []
        processed_offset = 0
        for runner_env, assigned_envs in effective_runner_buckets:
            if assigned_envs:
                active_buckets.append((int(runner_env.id), [int(env.id) for env in assigned_envs], processed_offset))
                processed_offset += len(assigned_envs)

        semaphore = asyncio.Semaphore(max(1, min(concurrency, len(active_buckets) or 1)))

        async def run_bucket(runner_id: int, environment_ids: list[int], offset: int) -> dict:
            await self._raise_if_sync_cancelled(cancel_check)
            async with semaphore:
                async with async_session() as session:
                    service = XHSService(session)
                    rows = list(
                        (
                            await session.execute(
                                select(XHSEnvironment).where(
                                    XHSEnvironment.id.in_([runner_id, *environment_ids])
                                )
                            )
                        ).scalars().all()
                    )
                    rows_by_id = {int(row.id): row for row in rows}
                    runner = rows_by_id.get(runner_id)
                    if runner is None:
                        raise RuntimeError(f"同步环境 {runner_id} 不存在")
                    assigned = [rows_by_id[env_id] for env_id in environment_ids if env_id in rows_by_id]
                    if len(assigned) != len(environment_ids):
                        raise RuntimeError(f"同步环境 {runner_id} 的部分发布账号不存在")
                    env_lock = await service._get_env_publish_lock(runner_id)
                    async with env_lock:
                        return await service._sync_account_notes_batch_locked(
                            assigned,
                            scrape_env=runner,
                            limit=limit,
                            persona=persona,
                            progress_callback=progress_callback,
                            cancel_check=cancel_check,
                            runner_envs=[runner],
                            processed_offset=offset,
                            total_accounts=overall_total_accounts,
                            base_synced_accounts=0,
                            base_created_notes=0,
                            base_updated_notes=0,
                        )

        raw_results = await asyncio.gather(
            *(run_bucket(runner_id, environment_ids, offset) for runner_id, environment_ids, offset in active_buckets),
            return_exceptions=True,
        )
        synced_accounts = 0
        created_notes = 0
        updated_notes = 0
        total_notes = 0
        failed_runners: list[dict[str, Any]] = []
        failed_accounts: list[dict[str, Any]] = []
        for (runner_id, environment_ids, _), raw_result in zip(active_buckets, raw_results):
            if isinstance(raw_result, Exception):
                error_message = self._sync_exception_message(raw_result)
                logger.warning(
                    "并行同步主页帖子失败: runner_id=%s targets=%s error=%s",
                    runner_id,
                    environment_ids,
                    error_message,
                )
                failed_runners.append(
                    {"runner_id": runner_id, "environment_ids": environment_ids, "error": error_message}
                )
                continue
            synced_accounts += int(raw_result.get("synced_accounts") or 0)
            created_notes += int(raw_result.get("created_notes") or 0)
            updated_notes += int(raw_result.get("updated_notes") or 0)
            total_notes += int(raw_result.get("total_notes") or 0)
            failed_accounts.extend(raw_result.get("failed_accounts") or [])
            failed_runners.extend(raw_result.get("failed_runners") or [])

        result = {
            "synced_accounts": synced_accounts,
            "created_notes": created_notes,
            "updated_notes": updated_notes,
            "metric_synced_notes": 0,
            "total_notes": total_notes,
        }
        if failed_runners:
            result["failed_runners"] = failed_runners
        if failed_accounts:
            result["failed_accounts"] = failed_accounts
        return result

    @yundeng_sync_guard("scrape_env", "homepage_posts")
    async def _sync_account_notes_for_environment_locked(
        self,
        env: XHSEnvironment,
        *,
        scrape_env: XHSEnvironment,
        limit: int = 120,
        persona: SyncSessionPersona,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        total_accounts: int | None = None,
        current_account_index: int | None = None,
        aggregate_created_notes: int = 0,
        aggregate_updated_notes: int = 0,
        runner_envs: list[XHSEnvironment] | None = None,
    ) -> dict:
        if not (env.profile_url or "").strip():
            raise RuntimeError(f"环境 {env.account_name} 未配置个人主页链接")

        # Runner/environment objects were loaded by the caller. Do not keep the
        # corresponding read transaction open while starting and warming MCP.
        await self.db.commit()

        mcp_pid = None
        use_external_mcp = bool(XHS_MCP_EXTERNAL_API)
        mcp_port = None if use_external_mcp else await self._allocate_free_port()
        mcp_api = XHS_MCP_EXTERNAL_API if use_external_mcp else f"http://localhost:{mcp_port}"
        previous_mcp_api = getattr(self, "_active_mcp_api", None)

        try:
            self._active_mcp_api = mcp_api
            active_scrape_env, ws_url = await self._acquire_ready_sync_browser_ws_with_fallback(
                int(scrape_env.id), allow_fallback=False
            )
            if active_scrape_env is not None:
                scrape_env = active_scrape_env
            if not ws_url:
                raise RuntimeError(f"无法获取采集环境 {scrape_env.shop_id} 的浏览器连接")

            if use_external_mcp:
                if not await self._check_mcp_running(mcp_api):
                    raise RuntimeError("外部小红书发布服务不可用，请先启动 XHS MCP 服务")
            else:
                mcp_pid = await self._start_mcp(ws_url, mcp_port or 0)
                if not mcp_pid:
                    raise RuntimeError("启动小红书发布服务失败，请稍后重试")
                await self._wait_mcp_ready(mcp_api)

            await self._run_sync_browser_warmup(
                api_base=mcp_api,
                persona=persona,
                target_profile_url=str(env.profile_url or "").strip(),
            )
            return await self._sync_account_notes_with_api(
                env,
                api_base=mcp_api,
                limit=limit,
                persona=persona,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                total_accounts=total_accounts,
                current_account_index=current_account_index,
                aggregate_created_notes=aggregate_created_notes,
                aggregate_updated_notes=aggregate_updated_notes,
                runner_id=int(scrape_env.id),
                runner_name=scrape_env.account_name,
                runner_envs=runner_envs,
                assigned_runner_env=scrape_env,
            )
        finally:
            self._active_mcp_api = previous_mcp_api
            if mcp_pid is not None:
                await self._stop_mcp(mcp_pid)

    @classmethod
    def _match_homepage_item_to_note(
        cls,
        item: dict[str, Any],
        notes: list[XHSAccountNote],
    ) -> tuple[XHSAccountNote | None, str | None, float | None]:
        feed_id = str(item.get("feed_id") or "").strip()
        if feed_id:
            feed_matches = [note for note in notes if str(note.feed_id or "").strip() == feed_id]
            if len(feed_matches) == 1:
                return feed_matches[0], "feed_id", 1.0

        title_key = cls._normalize_creator_identity_title(item.get("title"))
        if not title_key:
            return None, None, None
        unresolved = [
            note for note in notes
            if not str(note.feed_id or "").strip()
            and cls._normalize_creator_identity_title(note.title) == title_key
        ]
        published_at = item.get("published_at")
        if isinstance(published_at, datetime):
            timed = [
                note for note in unresolved
                if isinstance(note.published_at, datetime)
                and abs((note.published_at.replace(tzinfo=None) - published_at.replace(tzinfo=None)).total_seconds()) <= 180
            ]
            if len(timed) == 1:
                return timed[0], "homepage_title_time", 0.96
            if len(timed) > 1:
                return None, None, None
        if len(unresolved) == 1:
            return unresolved[0], "homepage_title_unique", 0.72
        return None, None, None

    async def _sync_account_notes_with_api(
        self,
        env: XHSEnvironment,
        *,
        api_base: str,
        limit: int = 120,
        persona: SyncSessionPersona | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        total_accounts: int | None = None,
        current_account_index: int | None = None,
        aggregate_created_notes: int = 0,
        aggregate_updated_notes: int = 0,
        runner_id: int | None = None,
        runner_name: str | None = None,
        runner_envs: list[XHSEnvironment] | None = None,
        assigned_runner_env: XHSEnvironment | None = None,
    ) -> dict:
        if not (env.profile_url or "").strip():
            raise RuntimeError(f"环境 {env.account_name} 未配置个人主页链接")

        existing_note_stmt = (
            select(XHSAccountNote)
            .where(XHSAccountNote.environment_id == env.id)
            .order_by(XHSAccountNote.sort_index.asc(), XHSAccountNote.id.asc())
        )
        existing_notes = list((await self.db.execute(existing_note_stmt)).scalars().all())
        existing_feed_ids = [
            str(note.feed_id or "").strip()
            for note in existing_notes
            if str(note.feed_id or "").strip()
        ]
        known_feed_id_set = set(existing_feed_ids)
        oldest_known_feed_id = existing_feed_ids[-1] if existing_feed_ids else None
        max_profile_feeds = self._estimate_account_note_profile_fetch_max_feeds(
            known_note_count=len(existing_feed_ids),
            limit=limit,
        )
        max_scroll_rounds = self._estimate_account_note_profile_scroll_rounds(
            known_note_count=len(existing_feed_ids),
            limit=limit,
        )

        # The remote profile request may legitimately take minutes. The loaded
        # ORM objects remain usable because sessions use expire_on_commit=False.
        await self.db.commit()

        await self._sleep_sync_profile_prep(persona)
        await self._emit_progress(
            progress_callback,
            {
                "phase": "fetching_account_posts",
                "detail": f"正在拉取 {env.account_name} 的主页帖子",
                "runner_id": runner_id,
                "runner_name": runner_name,
                "account_name": env.account_name,
                "account_index": current_account_index,
                "account_total": total_accounts,
                "current": 0,
                "total": 0,
                "percent": 0,
                "created_notes": aggregate_created_notes,
                "updated_notes": aggregate_updated_notes,
            },
        )
        should_scroll_profile = bool(oldest_known_feed_id)
        payload = await self._fetch_profile_account_notes(
            str(env.profile_url or "").strip(),
            api_base,
            limit=limit,
            scroll_mode="input" if should_scroll_profile else None,
            stop_feed_id=oldest_known_feed_id,
            max_feeds=max_profile_feeds if should_scroll_profile else None,
            max_scroll_rounds=max_scroll_rounds if should_scroll_profile else None,
            max_stagnant_rounds=2 if should_scroll_profile else None,
        )
        now = utc_now_naive()
        created_notes = 0
        updated_notes = 0
        raw_items = payload.get("feeds") or []
        # A transient XHS response or expired profile token can look like a
        # successful request with zero feeds. Do not let that mark all known
        # notes as offline in the stale-record sweep below.
        if known_feed_id_set and not raw_items:
            raise RuntimeError(
                f"{env.account_name} 的主页返回 0 篇帖子，已保留现有 {len(known_feed_id_set)} 篇记录"
            )
        items_to_apply: list[dict] = []
        known_feed_streak = 0
        history_streak_threshold = 10
        min_scan_before_history_cutoff = 20
        for item in raw_items:
            feed_id = str(item.get("feed_id") or "").strip()
            if not feed_id:
                continue
            if feed_id in known_feed_id_set:
                known_feed_streak += 1
                items_to_apply.append(item)
                continue

            if (
                known_feed_id_set
                and len(items_to_apply) >= min_scan_before_history_cutoff
                and known_feed_streak >= history_streak_threshold
            ):
                continue

            known_feed_streak = 0
            items_to_apply.append(item)
        total_notes = len(items_to_apply)
        applied_feed_ids: list[str] = []
        applied_feed_id_set: set[str] = set()
        touched_notes: list[XHSAccountNote] = []
        pending_cover_localizations: list[tuple[int, str, str | None, str]] = []
        source_posts = list((await self.db.execute(
            select(XHSPost).where(XHSPost.environment_id == env.id)
        )).scalars().all())
        source_posts_by_feed = {
            str(post.feed_id or "").strip(): post
            for post in source_posts
            if str(post.feed_id or "").strip()
        }

        async def finalize_partial_sync() -> None:
            if touched_notes:
                if assigned_runner_env is not None:
                    self._assign_account_note_runner(touched_notes, assigned_runner_env)
                else:
                    effective_runner_envs = runner_envs or await self.list_sync_runner_environments()
                    if effective_runner_envs:
                        await self.rebalance_account_note_runner_assignments(touched_notes, runner_envs=effective_runner_envs)
            await self.db.commit()
            if pending_cover_localizations:
                await self._apply_pending_account_note_cover_localizations(pending_cover_localizations)

        await self._emit_progress(
            progress_callback,
            {
                "phase": "processing_account_posts",
                "detail": f"正在整理 {env.account_name} 的帖子数据",
                "runner_id": runner_id,
                "runner_name": runner_name,
                "account_name": env.account_name,
                "account_index": current_account_index,
                "account_total": total_accounts,
                "current": 0,
                "total": total_notes,
                "percent": 0,
                "created_notes": aggregate_created_notes,
                "updated_notes": aggregate_updated_notes,
            },
        )
        for item_index, item in enumerate(items_to_apply, start=1):
            await self._raise_if_sync_cancelled(cancel_check, on_cancel=finalize_partial_sync)
            feed_id = str(item.get("feed_id") or "").strip()
            if not feed_id:
                continue
            if feed_id not in applied_feed_id_set:
                applied_feed_ids.append(feed_id)
                applied_feed_id_set.add(feed_id)

            note, match_method, match_confidence = self._match_homepage_item_to_note(item, existing_notes)
            if note is None:
                note = XHSAccountNote(
                    environment_id=env.id,
                    feed_id=feed_id,
                    ai_origin_type="",
                    status="active",
                    identity_status="homepage_only",
                    identity_match_method="homepage_new",
                    identity_match_confidence=0.6,
                    first_synced_at=now,
                )
                self.db.add(note)
                existing_notes.append(note)
                created_notes += 1
            else:
                updated_notes += 1

            has_creator_metrics = note.creator_synced_at is not None
            note.feed_id = feed_id
            note.identity_status = "resolved"
            note.identity_match_method = match_method or note.identity_match_method or "feed_id"
            note.identity_match_confidence = (
                match_confidence if match_confidence is not None else note.identity_match_confidence
            )
            note.homepage_synced_at = now

            note.account_name = env.account_name or ""
            note.profile_nickname = payload.get("profile_nickname") or env.account_name or ""
            note.red_id = payload.get("red_id")
            note.xsec_token = item.get("xsec_token") or note.xsec_token
            note.post_url = self._build_account_note_url(feed_id, note.xsec_token)
            note.cover_image_url, pending_cover_url = self._prepare_account_note_cover_image(
                item.get("cover_image_url"),
                existing_url=note.cover_image_url,
            )
            if pending_cover_url:
                pending_cover_localizations.append((
                    int(env.id),
                    feed_id,
                    note.cover_image_url,
                    pending_cover_url,
                ))
            if not has_creator_metrics or not note.title:
                note.title = item.get("title") or note.title or ""
            if not has_creator_metrics or note.published_at is None:
                note.published_at = item.get("published_at") or note.published_at
            note.status = "active"
            if not has_creator_metrics and item.get("liked_count") is not None:
                note.liked_count = self._merge_metric_count(note.liked_count, item.get("liked_count"))
            if not has_creator_metrics and item.get("comment_count") is not None:
                note.comment_count = self._merge_metric_count(note.comment_count, item.get("comment_count"))
            if not has_creator_metrics and item.get("collected_count") is not None:
                note.collected_count = self._merge_metric_count(note.collected_count, item.get("collected_count"))
            if not has_creator_metrics and item.get("share_count") is not None:
                note.share_count = self._merge_metric_count(note.share_count, item.get("share_count"))
            note.sort_index = int(item.get("sort_index") or 0)
            note.last_seen_at = now
            source_post = source_posts_by_feed.get(feed_id)
            if source_post is not None:
                note.source_post_id = int(source_post.id)
            touched_notes.append(note)
            await self._emit_progress(
                progress_callback,
                {
                    "phase": "processing_account_posts",
                    "detail": f"正在整理 {env.account_name} 的帖子数据 {item_index}/{total_notes}",
                    "runner_id": runner_id,
                    "runner_name": runner_name,
                    "account_name": env.account_name,
                    "account_index": current_account_index,
                    "account_total": total_accounts,
                    "current": item_index,
                    "total": total_notes,
                    "percent": int((item_index / total_notes) * 100) if total_notes > 0 else 100,
                    "created_notes": aggregate_created_notes + created_notes,
                    "updated_notes": aggregate_updated_notes + updated_notes,
                },
            )

        await self._raise_if_sync_cancelled(cancel_check, on_cancel=finalize_partial_sync)

        stale_stmt = (
            select(XHSAccountNote)
            .where(XHSAccountNote.environment_id == env.id)
            .order_by(XHSAccountNote.sort_index.asc(), XHSAccountNote.id.asc())
        )
        stale_notes = list((await self.db.execute(stale_stmt)).scalars().all())
        next_sort_index = len(applied_feed_ids)
        for stale_note in stale_notes:
            stale_feed_id = str(stale_note.feed_id or "").strip()
            if not stale_feed_id or stale_note.creator_synced_at is not None:
                continue
            if stale_feed_id in applied_feed_id_set:
                continue
            stale_note.status = "offline"
            stale_note.sort_index = next_sort_index
            next_sort_index += 1

        if touched_notes and assigned_runner_env is not None:
            self._assign_account_note_runner(touched_notes, assigned_runner_env)
        else:
            effective_runner_envs = runner_envs or await self.list_sync_runner_environments()
            if touched_notes and effective_runner_envs:
                await self.rebalance_account_note_runner_assignments(touched_notes, runner_envs=effective_runner_envs)

        await self.db.commit()
        if pending_cover_localizations:
            await self._apply_pending_account_note_cover_localizations(pending_cover_localizations)
        await self._emit_progress(
            progress_callback,
            {
                "phase": "account_posts_completed",
                "detail": f"{env.account_name} 的账号帖子已入库",
                "runner_id": runner_id,
                "runner_name": runner_name,
                "account_name": env.account_name,
                "account_index": current_account_index,
                "account_total": total_accounts,
                "current": total_notes,
                "total": total_notes,
                "percent": 100,
                "created_notes": aggregate_created_notes + created_notes,
                "updated_notes": aggregate_updated_notes + updated_notes,
            },
        )
        return {
            "created_notes": created_notes,
            "updated_notes": updated_notes,
            "metric_synced_notes": 0,
            "total_notes": total_notes,
        }

    async def update_account_note_ai_origin_type(
        self,
        user: User,
        note_id: int,
        ai_origin_type: str | None,
    ) -> XHSAccountNote:
        envs = await self.list_environments(user)
        allowed_env_ids = {env.id for env in envs}
        stmt = select(XHSAccountNote).where(XHSAccountNote.id == note_id)
        if user.role != "admin":
            stmt = stmt.where(XHSAccountNote.environment_id.in_(allowed_env_ids))
        note = (await self.db.execute(stmt)).scalar_one_or_none()
        if note is None:
            raise ValueError("账号帖子不存在")
        normalized = (ai_origin_type or "").strip()
        if not normalized:
            raise ValueError("账号数据标记不能为空")
        note.ai_origin_type = normalized
        await self.db.commit()
        await self.db.refresh(note)
        return note

    async def batch_update_account_note_ai_origin_type(
        self,
        user: User,
        note_ids: list[int],
        ai_origin_type: str,
    ) -> dict:
        envs = await self.list_environments(user)
        allowed_env_ids = {env.id for env in envs}
        normalized = (ai_origin_type or "").strip()
        if not normalized:
            raise ValueError("账号数据标记不能为空")
        normalized_ids = sorted({int(note_id) for note_id in note_ids if int(note_id) > 0})
        if not normalized_ids:
            raise ValueError("请选择至少一条账号帖子")

        stmt = select(XHSAccountNote.id).where(XHSAccountNote.id.in_(normalized_ids))
        if user.role != "admin":
            stmt = stmt.where(XHSAccountNote.environment_id.in_(allowed_env_ids))
        found_ids = [row[0] for row in (await self.db.execute(stmt)).all()]
        if not found_ids:
            raise ValueError("所选账号帖子不存在或无权限")

        update_stmt = (
            XHSAccountNote.__table__.update()
            .where(XHSAccountNote.id.in_(found_ids))
            .values(ai_origin_type=normalized)
        )
        await self.db.execute(update_stmt)
        await self.db.commit()
        return {
            "updated_count": len(found_ids),
            "requested_count": len(normalized_ids),
            "note_ids": found_ids,
            "ai_origin_type": normalized,
        }

    @staticmethod
    def _should_skip_old_account_note_detail_sync(
        note: XHSAccountNote,
        *,
        max_post_age_days: int | None = 30,
    ) -> bool:
        if max_post_age_days is None:
            return False
        if note.published_at is None:
            return False
        return note.published_at < (utc_now_naive() - timedelta(days=max_post_age_days))

    async def sync_account_note_stats(
        self,
        user: User,
        note_id: int,
        scrape_environment_id: int | None = None,
    ) -> tuple[XHSAccountNote, bool, bool]:
        envs = await self.list_environments(user)
        allowed_env_ids = {env.id for env in envs}
        stmt = select(XHSAccountNote).where(XHSAccountNote.id == note_id)
        if user.role != "admin":
            stmt = stmt.where(XHSAccountNote.environment_id.in_(allowed_env_ids))
        note = (await self.db.execute(stmt)).scalar_one_or_none()
        if note is None:
            raise ValueError("账号帖子不存在")
        if not str(note.feed_id or "").strip():
            raise ValueError("该帖子尚未由主页同步补齐帖子 ID，暂不能同步详情")

        if self._should_skip_old_account_note_detail_sync(note):
            return note, False, True

        scrape_env = await self._resolve_account_scrape_environment(scrape_environment_id)
        lease_context = yundeng_sync_coordinator.lease(int(scrape_env.id), "single_note_detail")
        await lease_context.__aenter__()
        mcp_pid = None
        use_external_mcp = bool(XHS_MCP_EXTERNAL_API)
        mcp_port = None if use_external_mcp else await self._allocate_free_port()
        mcp_api = XHS_MCP_EXTERNAL_API if use_external_mcp else f"http://localhost:{mcp_port}"
        previous_mcp_api = getattr(self, "_active_mcp_api", None)

        try:
            self._active_mcp_api = mcp_api
            active_scrape_env, ws_url = await self._acquire_ready_sync_browser_ws_with_fallback(
                int(scrape_env.id), allow_fallback=False
            )
            if active_scrape_env is not None:
                scrape_env = active_scrape_env
            if not ws_url:
                raise RuntimeError(f"无法获取采集环境 {scrape_env.shop_id} 的浏览器连接")

            if use_external_mcp:
                if not await self._check_mcp_running(mcp_api):
                    raise RuntimeError("外部小红书发布服务不可用，请先启动 XHS MCP 服务")
            else:
                mcp_pid = await self._start_mcp(ws_url, mcp_port or 0)
                if not mcp_pid:
                    raise RuntimeError("启动小红书发布服务失败，请稍后重试")
                await self._wait_mcp_ready(mcp_api)

            await self.record_account_note_browse(
                note,
                browse_source="single_sync",
                runner_env=scrape_env,
                commit=False,
            )
            pending_cover_localizations: list[tuple[int, str, str | None, str]] = []
            synced = await self._sync_account_note_metrics(
                note,
                api_base=mcp_api,
                pending_cover_localizations=pending_cover_localizations,
            )
            if synced:
                await self.db.commit()
                if pending_cover_localizations:
                    await self._apply_pending_account_note_cover_localizations(pending_cover_localizations)
                await self.db.refresh(note)
                return note, True, False
            await self.db.refresh(note)
            return note, False, False
        finally:
            self._active_mcp_api = previous_mcp_api
            if mcp_pid is not None:
                await self._stop_mcp(mcp_pid)
            await lease_context.__aexit__(None, None, None)

    async def sync_account_note_engagement_stats(
        self,
        user: User,
        note_id: int,
    ) -> tuple[XHSAccountNote, bool]:
        envs = await self.list_environments(user)
        allowed_env_ids = {env.id for env in envs}
        stmt = select(XHSAccountNote).where(XHSAccountNote.id == note_id)
        if user.role != "admin":
            stmt = stmt.where(XHSAccountNote.environment_id.in_(allowed_env_ids))
        note = (await self.db.execute(stmt)).scalar_one_or_none()
        if note is None:
            raise ValueError("账号帖子不存在")

        publish_env = await self.get_environment(int(note.environment_id))
        if publish_env is None:
            raise RuntimeError("帖子对应的发布账号环境不存在")

        lease_context = yundeng_sync_coordinator.lease(int(publish_env.id), "single_note_engagement")
        await lease_context.__aenter__()
        mcp_pid = None
        use_external_mcp = bool(XHS_MCP_EXTERNAL_API)
        mcp_port = None if use_external_mcp else await self._allocate_free_port()
        mcp_api = XHS_MCP_EXTERNAL_API if use_external_mcp else f"http://localhost:{mcp_port}"
        previous_mcp_api = getattr(self, "_active_mcp_api", None)

        try:
            self._active_mcp_api = mcp_api
            active_env, ws_url = await self._acquire_ready_sync_browser_ws_with_fallback(
                int(publish_env.id), allow_fallback=False
            )
            if active_env is not None:
                publish_env = active_env
            if not ws_url:
                raise RuntimeError(f"无法获取发布账号环境 {publish_env.shop_id} 的浏览器连接")

            if use_external_mcp:
                if not await self._check_mcp_running(mcp_api):
                    raise RuntimeError("外部小红书发布服务不可用，请先启动 XHS MCP 服务")
            else:
                mcp_pid = await self._start_mcp(ws_url, mcp_port or 0)
                if not mcp_pid:
                    raise RuntimeError("启动小红书发布服务失败，请稍后重试")
                await self._wait_mcp_ready(mcp_api)

            synced = await self._sync_account_note_engagement_metrics(note, api_base=mcp_api, env=publish_env)
            if synced:
                await self.db.commit()
            await self.db.refresh(note)
            return note, synced
        finally:
            self._active_mcp_api = previous_mcp_api
            if mcp_pid is not None:
                await self._stop_mcp(mcp_pid)
            await lease_context.__aexit__(None, None, None)

    async def _aggregate_parallel_engagement_results(
        self,
        *,
        envs: list[XHSEnvironment],
        raw_results: list[Any],
        progress_callback: ProgressCallback | None = None,
    ) -> dict:
        totals: dict[str, Any] = {
            "synced_accounts": 0,
            "created_notes": 0,
            "updated_notes": 0,
            "metric_synced_notes": 0,
            "total_notes": 0,
            "ambiguous_notes": 0,
        }
        failed_accounts: list[dict[str, Any]] = []
        for env, raw_result in zip(envs, raw_results):
            if isinstance(raw_result, Exception):
                logger.warning(
                    "并行同步创作者中心互动失败: env_id=%s account=%s error=%s",
                    env.id,
                    env.account_name,
                    raw_result,
                )
                failed_accounts.append(
                    {"environment_id": int(env.id), "account_name": env.account_name, "error": str(raw_result)}
                )
                await self._emit_progress(
                    progress_callback,
                    {
                        "phase": "account_engagement_failed",
                        "detail": f"{env.account_name} 的互动数据同步失败",
                        "account_name": env.account_name,
                        "error": str(raw_result),
                    },
                )
                continue
            _, result = raw_result
            for key in (
                "synced_accounts",
                "created_notes",
                "updated_notes",
                "metric_synced_notes",
                "total_notes",
                "ambiguous_notes",
            ):
                totals[key] += int(result.get(key) or 0)
        if failed_accounts:
            totals["failed_accounts"] = failed_accounts
        return totals

    async def sync_account_note_engagement_environment(
        self,
        environment_id: int,
        *,
        sync_run_id: int | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        current_account_index: int = 1,
        total_accounts: int = 1,
    ) -> dict:
        env = await self.get_environment(int(environment_id))
        if env is None or env.status != "active":
            raise RuntimeError(f"发布账号环境 {environment_id} 不存在或未启用")
        env_lock = await self._get_env_publish_lock(int(env.id))
        async with env_lock:
            return await self._sync_account_note_engagements_for_environment_locked(
                env,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                current_account_index=current_account_index,
                total_accounts=total_accounts,
                aggregate_synced_accounts=0,
                aggregate_metric_synced_notes=0,
                sync_run_id=sync_run_id,
            )

    async def sync_account_note_engagements(
        self,
        *,
        user: User,
        environment_id: int | None = None,
        target_environment_ids: str | list[int] | tuple[int, ...] | None = None,
        sync_account_limit: int | None = None,
        runner_account_assignments: str | dict[int | str, list[int] | tuple[int, ...] | set[int] | list[str] | tuple[str, ...]] | None = None,
        concurrency: int | None = None,
        sync_run_id: int | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> dict:
        normalized_target_env_ids = self._normalize_account_note_sync_runner_ids(target_environment_ids)
        normalized_account_limit = self._normalize_account_note_sync_account_limit(sync_account_limit)
        normalized_runner_assignments = self._normalize_account_note_sync_runner_assignments(runner_account_assignments)
        normalized_concurrency = self._normalize_yundeng_sync_concurrency(concurrency)

        envs = await self.list_environments(user)
        if environment_id is not None:
            envs = [env for env in envs if env.id == environment_id]
        elif environment_id is None:
            envs = [env for env in envs if not self._is_sync_runner_environment(env)]

        if environment_id is not None and not envs:
            raise ValueError("云登环境不存在或无权限")

        envs_by_id = {int(env.id): env for env in envs}
        if normalized_target_env_ids:
            missing_env_ids = [env_id for env_id in normalized_target_env_ids if env_id not in envs_by_id]
            if missing_env_ids:
                raise ValueError(f"部分发布账号不存在、不可用，或当前不在可同步范围内: {missing_env_ids[0]}")
            envs = [envs_by_id[env_id] for env_id in normalized_target_env_ids]
        elif normalized_runner_assignments:
            explicit_env_ids = [env_id for env_ids in normalized_runner_assignments.values() for env_id in env_ids]
            missing_env_ids = [env_id for env_id in explicit_env_ids if env_id not in envs_by_id]
            if missing_env_ids:
                raise ValueError(f"部分发布账号不存在、不可用，或当前不在可同步范围内: {missing_env_ids[0]}")
            envs = [envs_by_id[env_id] for env_id in explicit_env_ids]
        else:
            envs = self._humanize_environment_sync_order(envs, self._build_sync_session_persona())
            if normalized_account_limit is not None:
                envs = envs[:normalized_account_limit]

        if not envs:
            return {
                "synced_accounts": 0,
                "created_notes": 0,
                "updated_notes": 0,
                "metric_synced_notes": 0,
                "total_notes": 0,
            }

        if self._should_delegate_browser_ops():
            if len(envs) > 1:
                return await self._delegate_account_note_engagement_sync(
                    envs=envs,
                    concurrency=normalized_concurrency,
                    sync_run_id=sync_run_id,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                )
            result = await self.trigger_worker_sync_account_note_engagements(int(envs[0].id), sync_run_id)
            return result

        await self._emit_progress(
            progress_callback,
            {
                "phase": "planning_account_engagements",
                "detail": f"准备同步 {len(envs)} 个发布账号的互动数据",
                "current": 0,
                "total": len(envs),
                "percent": 0,
                "synced_accounts": 0,
                "metric_synced_notes": 0,
            },
        )

        if len(envs) == 1:
            return await self.sync_account_note_engagement_environment(
                int(envs[0].id),
                sync_run_id=sync_run_id,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )

        semaphore = asyncio.Semaphore(max(1, min(normalized_concurrency, len(envs))))

        async def run_environment(index: int, env: XHSEnvironment) -> tuple[XHSEnvironment, dict]:
            await self._raise_if_sync_cancelled(cancel_check)
            async with semaphore:
                async with async_session() as session:
                    service = XHSService(session)
                    result = await service.sync_account_note_engagement_environment(
                        int(env.id),
                        sync_run_id=sync_run_id,
                        progress_callback=progress_callback,
                        cancel_check=cancel_check,
                        current_account_index=index,
                        total_accounts=len(envs),
                    )
                    return env, result

        raw_results = await asyncio.gather(
            *(run_environment(index, env) for index, env in enumerate(envs, start=1)),
            return_exceptions=True,
        )
        return await self._aggregate_parallel_engagement_results(
            envs=envs,
            raw_results=raw_results,
            progress_callback=progress_callback,
        )

    @yundeng_sync_guard("env", "creator_engagement")
    async def _sync_account_note_engagements_for_environment_locked(
        self,
        env: XHSEnvironment,
        *,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        current_account_index: int,
        total_accounts: int,
        aggregate_synced_accounts: int,
        aggregate_metric_synced_notes: int,
        sync_run_id: int | None = None,
    ) -> dict:
        mcp_pid = None
        use_external_mcp = bool(XHS_MCP_EXTERNAL_API)
        mcp_port = None if use_external_mcp else await self._allocate_free_port()
        mcp_api = XHS_MCP_EXTERNAL_API if use_external_mcp else f"http://localhost:{mcp_port}"
        previous_mcp_api = getattr(self, "_active_mcp_api", None)

        try:
            self._active_mcp_api = mcp_api
            active_env, ws_url = await self._acquire_ready_sync_browser_ws_with_fallback(int(env.id), allow_fallback=False)
            if active_env is not None:
                env = active_env
            if not ws_url:
                raise RuntimeError(f"无法获取发布账号环境 {env.shop_id} 的浏览器连接")

            if use_external_mcp:
                if not await self._check_mcp_running(mcp_api):
                    raise RuntimeError("外部小红书发布服务不可用，请先启动 XHS MCP 服务")
            else:
                mcp_pid = await self._start_mcp(ws_url, mcp_port or 0)
                if not mcp_pid:
                    raise RuntimeError("启动小红书发布服务失败，请稍后重试")
                await self._wait_mcp_ready(mcp_api)

            await self._emit_progress(
                progress_callback,
                {
                    "phase": "fetching_account_engagements",
                    "detail": f"正在读取 {env.account_name} 创作中心互动数据",
                    "account_name": env.account_name,
                    "account_index": current_account_index,
                    "account_total": total_accounts,
                    "current": aggregate_synced_accounts,
                    "total": total_accounts,
                    "percent": int((aggregate_synced_accounts / total_accounts) * 100) if total_accounts > 0 else 0,
                    "synced_accounts": aggregate_synced_accounts,
                    "metric_synced_notes": aggregate_metric_synced_notes,
                },
            )

            stats_rows = await self._fetch_creator_note_stats(api_base=mcp_api, env=env)
            await self._raise_if_sync_cancelled(cancel_check)
            import_result = await self._import_creator_note_stats_rows(
                env,
                stats_rows,
                sync_run_id=sync_run_id,
            )
            await self.db.commit()
            metric_updates = int(import_result.get("metric_synced_notes") or 0)
            total_notes = int(import_result.get("total_notes") or 0)
            await self._emit_progress(
                progress_callback,
                {
                    "phase": "account_engagement_completed",
                    "detail": f"{env.account_name} 的互动数据已同步完成",
                    "account_name": env.account_name,
                    "account_index": current_account_index,
                    "account_total": total_accounts,
                    "current": aggregate_synced_accounts + 1,
                    "total": total_accounts,
                    "percent": int(((aggregate_synced_accounts + 1) / total_accounts) * 100) if total_accounts > 0 else 100,
                    "synced_accounts": aggregate_synced_accounts + 1,
                    "metric_synced_notes": aggregate_metric_synced_notes + metric_updates,
                    "created_notes": int(import_result.get("created_notes") or 0),
                    "updated_notes": int(import_result.get("updated_notes") or 0),
                    "ambiguous_notes": int(import_result.get("ambiguous_notes") or 0),
                    "exported_rows": len(stats_rows),
                },
            )
            return {
                "synced_accounts": 1,
                "created_notes": int(import_result.get("created_notes") or 0),
                "updated_notes": int(import_result.get("updated_notes") or 0),
                "metric_synced_notes": metric_updates,
                "total_notes": total_notes,
                "ambiguous_notes": int(import_result.get("ambiguous_notes") or 0),
                "exported_rows": len(stats_rows),
            }
        finally:
            self._active_mcp_api = previous_mcp_api
            if mcp_pid is not None:
                await self._stop_mcp(mcp_pid)

    async def sync_existing_account_note_stats(
        self,
        *,
        environment_id: int | None = None,
        target_note_ids: str | list[int] | tuple[int, ...] | None = None,
        scrape_environment_id: int | None = None,
        scrape_environment_ids: str | list[int] | tuple[int, ...] | None = None,
        sync_mode: str = "all",
        sync_limit: int | None = None,
        sync_limit_per_runner: int | None = None,
        pause_seconds_min: float | None = None,
        pause_seconds_max: float | None = None,
        max_post_age_days: int | None = None,
        concurrency: int | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> dict:
        normalized_sync_mode = self._normalize_account_note_sync_mode(sync_mode)
        normalized_sync_limit = self._normalize_account_note_sync_limit(sync_limit)
        normalized_target_note_ids = self._normalize_account_note_sync_runner_ids(target_note_ids)
        normalized_runner_ids = self._normalize_account_note_sync_runner_ids(scrape_environment_ids)
        normalized_limit_per_runner = self._normalize_account_note_sync_limit_per_runner(sync_limit_per_runner)
        normalized_pause_min = self._normalize_account_note_sync_pause_seconds(pause_seconds_min, field_name="最小暂停秒数")
        normalized_pause_max = self._normalize_account_note_sync_pause_seconds(pause_seconds_max, field_name="最大暂停秒数")
        normalized_max_post_age_days = self._normalize_account_note_max_age_days(max_post_age_days)
        normalized_concurrency = self._normalize_yundeng_sync_concurrency(concurrency)
        if normalized_pause_min is not None and normalized_pause_max is not None and normalized_pause_max < normalized_pause_min:
            normalized_pause_min, normalized_pause_max = normalized_pause_max, normalized_pause_min
        if self._should_delegate_browser_ops() and len(normalized_runner_ids) > 1:
            # Select the target notes once in the parent, then split the exact
            # IDs across runners. Each worker request owns one browser, so the
            # requests can overlap without competing for a single browser.
            persona = self._build_sync_session_persona()
            active_notes, matched_notes, skipped_notes = await self._prepare_account_note_detail_sync_notes(
                environment_id=environment_id,
                target_note_ids=normalized_target_note_ids,
                sync_mode=normalized_sync_mode,
                sync_limit=normalized_sync_limit,
                max_post_age_days=normalized_max_post_age_days,
                persona=persona,
            )
            if not active_notes:
                return {
                    "total_notes": 0,
                    "matched_notes": matched_notes,
                    "synced_notes": 0,
                    "failed_notes": 0,
                    "skipped_notes": skipped_notes,
                    "strategy_runner_count": 0,
                }
            return await self._delegate_account_note_detail_sync_by_runner(
                active_note_ids=[int(note.id) for note in active_notes],
                matched_notes=matched_notes,
                skipped_notes=skipped_notes,
                runner_ids=normalized_runner_ids,
                sync_limit_per_runner=normalized_limit_per_runner,
                pause_seconds_min=normalized_pause_min,
                pause_seconds_max=normalized_pause_max,
                max_post_age_days=normalized_max_post_age_days,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                concurrency=normalized_concurrency,
            )
        if self._should_delegate_browser_ops():
            return await self.trigger_worker_sync_account_note_details(
                environment_id,
                ",".join(str(item) for item in normalized_target_note_ids) or None,
                scrape_environment_id,
                ",".join(str(item) for item in normalized_runner_ids) or None,
                normalized_sync_mode,
                normalized_sync_limit,
                normalized_limit_per_runner,
                normalized_pause_min,
                normalized_pause_max,
                normalized_max_post_age_days,
            )
        persona = self._build_sync_session_persona()
        await self._raise_if_sync_cancelled(cancel_check)
        active_notes, matched_notes, skipped_notes = await self._prepare_account_note_detail_sync_notes(
            environment_id=environment_id,
            target_note_ids=normalized_target_note_ids,
            sync_mode=normalized_sync_mode,
            sync_limit=normalized_sync_limit,
            max_post_age_days=normalized_max_post_age_days,
            persona=persona,
        )
        await self._emit_progress(
            progress_callback,
            {
                "phase": "preparing_notes",
                "detail": f"已筛出 {len(active_notes)} 条待同步帖子",
                "current": 0,
                "total": len(active_notes),
                "percent": 0,
                "matched_notes": matched_notes,
                "skipped_notes": skipped_notes,
                "sync_mode": normalized_sync_mode,
            },
        )
        if not active_notes:
            return {
                "total_notes": 0,
                "matched_notes": matched_notes,
                "synced_notes": 0,
                "failed_notes": 0,
                "skipped_notes": skipped_notes,
                "strategy_runner_count": 0,
            }

        self._require_local_browser_ops("同步账号帖子详情数据")
        scrape_envs = await self._resolve_account_scrape_environments(
            scrape_environment_id=scrape_environment_id,
            scrape_environment_ids=normalized_runner_ids,
        )
        await self._emit_progress(
            progress_callback,
            {
                "phase": "ready_to_sync",
                "detail": f"准备使用 {len(scrape_envs)} 个同步环境开始执行",
                "current": 0,
                "total": len(active_notes),
                "percent": 0,
                "matched_notes": matched_notes,
                "skipped_notes": skipped_notes,
                "runner_count": len(scrape_envs),
                "sync_mode": normalized_sync_mode,
            },
        )
        if len(scrape_envs) == 1 and not normalized_limit_per_runner and normalized_pause_min is None and normalized_pause_max is None:
            env_lock = await self._get_env_publish_lock(scrape_envs[0].id)
            async with env_lock:
                result = await self._sync_existing_account_note_stats_chunk_locked(
                    scrape_env=scrape_envs[0],
                    active_notes=active_notes,
                    persona=persona,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                    processed_offset=0,
                    total_notes=len(active_notes),
                    base_synced=0,
                    base_failed=0,
                    round_index=1,
                    runner_index=1,
                    runner_count=1,
                )
        else:
            result = await self._sync_existing_account_note_stats_with_strategy(
                scrape_envs=scrape_envs,
                active_notes=active_notes,
                persona=persona,
                sync_limit_per_runner=normalized_limit_per_runner,
                pause_seconds_min=normalized_pause_min,
                pause_seconds_max=normalized_pause_max,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                concurrency=normalized_concurrency,
            )
        result["matched_notes"] = matched_notes
        result["skipped_notes"] = skipped_notes
        result["strategy_runner_count"] = len(scrape_envs)
        return result

    async def _prepare_account_note_detail_sync_notes(
        self,
        *,
        environment_id: int | None,
        target_note_ids: list[int] | None,
        sync_mode: str,
        sync_limit: int | None,
        max_post_age_days: int | None,
        persona: SyncSessionPersona,
    ) -> tuple[list[XHSAccountNote], int, int]:
        stmt = select(XHSAccountNote).options(
            selectinload(XHSAccountNote.assigned_runner_environment)
        ).order_by(
            XHSAccountNote.environment_id.asc(),
            XHSAccountNote.sort_index.asc(),
            XHSAccountNote.id.asc(),
        )
        stmt = stmt.where(or_(XHSAccountNote.status == "active", XHSAccountNote.status.is_(None)))
        stmt = stmt.where(
            XHSAccountNote.feed_id.is_not(None),
            func.trim(XHSAccountNote.feed_id) != "",
        )
        if environment_id is not None:
            stmt = stmt.where(XHSAccountNote.environment_id == environment_id)
        if target_note_ids:
            stmt = stmt.where(XHSAccountNote.id.in_(target_note_ids))
        if sync_mode == "unpublished_only":
            stmt = stmt.where(
                or_(
                    XHSAccountNote.published_at.is_(None),
                    XHSAccountNote.content.is_(None),
                    func.trim(XHSAccountNote.content) == "",
                )
            )
        notes = list((await self.db.execute(stmt)).scalars().all())
        if not notes:
            return [], 0, 0

        skipped_notes = 0
        active_notes: list[XHSAccountNote] = []
        for note in notes:
            if self._should_skip_old_account_note_detail_sync(note, max_post_age_days=max_post_age_days):
                skipped_notes += 1
                continue
            active_notes.append(note)
        active_notes = self._humanize_account_note_detail_order(active_notes, persona)
        matched_notes = len(active_notes)
        if sync_limit:
            active_notes = active_notes[:sync_limit]
        return active_notes, matched_notes, skipped_notes

    @yundeng_sync_guard("scrape_env", "note_details")
    async def _sync_existing_account_note_stats_chunk_locked(
        self,
        *,
        scrape_env: XHSEnvironment,
        active_notes: list[XHSAccountNote],
        persona: SyncSessionPersona,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        processed_offset: int = 0,
        total_notes: int | None = None,
        base_synced: int = 0,
        base_failed: int = 0,
        round_index: int = 1,
        runner_index: int = 1,
        runner_count: int = 1,
    ) -> dict:
        if not active_notes:
            return {"total_notes": 0, "synced_notes": 0, "failed_notes": 0}

        mcp_pid = None
        use_external_mcp = bool(XHS_MCP_EXTERNAL_API)
        mcp_port = None if use_external_mcp else await self._allocate_free_port()
        mcp_api = XHS_MCP_EXTERNAL_API if use_external_mcp else f"http://localhost:{mcp_port}"
        previous_mcp_api = getattr(self, "_active_mcp_api", None)
        synced_notes = 0
        failed_notes = 0
        synced_note_ids: list[int] = []
        failed_note_ids: list[int] = []

        try:
            self._active_mcp_api = mcp_api
            active_scrape_env, ws_url = await self._acquire_ready_sync_browser_ws_with_fallback(
                int(scrape_env.id), allow_fallback=False
            )
            if active_scrape_env is not None:
                scrape_env = active_scrape_env
            if not ws_url:
                raise RuntimeError(f"无法获取采集环境 {scrape_env.shop_id} 的浏览器连接")

            if use_external_mcp:
                if not await self._check_mcp_running(mcp_api):
                    raise RuntimeError("外部小红书发布服务不可用，请先启动 XHS MCP 服务")
            else:
                mcp_pid = await self._start_mcp(ws_url, mcp_port or 0)
                if not mcp_pid:
                    raise RuntimeError("启动小红书发布服务失败，请稍后重试")
                await self._wait_mcp_ready(mcp_api)

            await self._run_sync_browser_warmup(api_base=mcp_api, persona=persona)
            await self._emit_progress(
                progress_callback,
                {
                    "phase": "runner_processing",
                    "detail": f"第 {round_index} 轮开始，当前账号 {scrape_env.account_name}",
                    "runner_id": int(scrape_env.id),
                    "runner_name": scrape_env.account_name,
                    "round": round_index,
                    "runner_index": runner_index,
                    "runner_count": runner_count,
                    "current": processed_offset,
                    "total": total_notes or len(active_notes),
                    "percent": int((processed_offset / (total_notes or len(active_notes))) * 100) if (total_notes or len(active_notes)) > 0 else 0,
                    "synced_notes": base_synced,
                    "failed_notes": base_failed,
                },
            )

            previous_env_id: int | None = None
            pending_cover_localizations: list[tuple[int, str, str | None, str]] = []
            async def finalize_partial_sync() -> None:
                await self.db.commit()
                if pending_cover_localizations:
                    await self._apply_pending_account_note_cover_localizations(pending_cover_localizations)
            for index, note in enumerate(active_notes):
                await self._raise_if_sync_cancelled(cancel_check, on_cancel=finalize_partial_sync)
                note_sync_error: str | None = None
                note_sync_succeeded = False
                try:
                    current_env_id = int(note.environment_id or 0)
                    if previous_env_id is not None and current_env_id != previous_env_id:
                        await self._sleep_between_account_note_context_switch(persona)
                    await self._sleep_between_account_note_details(persona)
                    await self.record_account_note_browse(
                        note,
                        browse_source="bulk_sync",
                        runner_env=scrape_env,
                        commit=False,
                    )
                    synced = await self._sync_account_note_metrics(
                        note,
                        api_base=mcp_api,
                        persona=persona,
                        pending_cover_localizations=pending_cover_localizations,
                    )
                    if synced:
                        synced_notes += 1
                        synced_note_ids.append(int(note.id))
                        note_sync_succeeded = True
                    else:
                        failed_notes += 1
                        failed_note_ids.append(int(note.id))
                        note_sync_error = "未获取到帖子指标数据"
                    previous_env_id = current_env_id
                except Exception as exc:
                    failed_notes += 1
                    failed_note_ids.append(int(note.id))
                    note_sync_error = str(exc)
                    logger.warning("同步账号帖子互动数据失败: note_id=%s feed_id=%s error=%s", note.id, note.feed_id, exc)
                await self._emit_progress(
                    progress_callback,
                    {
                        "phase": "runner_processing",
                        "detail": f"{scrape_env.account_name} 正在同步第 {processed_offset + index + 1} / {total_notes or len(active_notes)} 条",
                        "runner_id": int(scrape_env.id),
                        "runner_name": scrape_env.account_name,
                        "round": round_index,
                        "runner_index": runner_index,
                        "runner_count": runner_count,
                        "current": processed_offset + index + 1,
                        "total": total_notes or len(active_notes),
                        "percent": int(((processed_offset + index + 1) / (total_notes or len(active_notes))) * 100) if (total_notes or len(active_notes)) > 0 else 100,
                        "synced_notes": base_synced + synced_notes,
                        "failed_notes": base_failed + failed_notes,
                        "current_note_id": int(note.id),
                        "current_feed_id": note.feed_id,
                        "current_note_succeeded": note_sync_succeeded,
                        "current_note_error": note_sync_error,
                    },
                )
                if index < len(active_notes) - 1 and _SYNC_BROWSER_CONFIG_RNG.random() < max(0.08, persona.extra_long_pause_probability / 2):
                    await self._raise_if_sync_cancelled(cancel_check, on_cancel=finalize_partial_sync)
                    await self._sleep_between_sync_batches(persona)

            await self._raise_if_sync_cancelled(cancel_check, on_cancel=finalize_partial_sync)
            await self.db.commit()
            if pending_cover_localizations:
                await self._apply_pending_account_note_cover_localizations(pending_cover_localizations)
            return {
                "total_notes": len(active_notes),
                "synced_notes": synced_notes,
                "failed_notes": failed_notes,
                "synced_note_ids": synced_note_ids,
                "failed_note_ids": failed_note_ids,
            }
        finally:
            self._active_mcp_api = previous_mcp_api
            if mcp_pid is not None:
                await self._stop_mcp(mcp_pid)

    async def _sync_existing_account_note_stats_with_strategy(
        self,
        *,
        scrape_envs: list[XHSEnvironment],
        active_notes: list[XHSAccountNote],
        persona: SyncSessionPersona,
        sync_limit_per_runner: int | None = None,
        pause_seconds_min: float | None = None,
        pause_seconds_max: float | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        concurrency: int = 1,
    ) -> dict:
        if not active_notes:
            return {"total_notes": 0, "synced_notes": 0, "failed_notes": 0}

        chunk_size = max(1, sync_limit_per_runner or len(active_notes))
        queue_by_runner: dict[int, list[XHSAccountNote]] = {int(env.id): [] for env in scrape_envs}
        for index, note in enumerate(active_notes):
            runner_env = scrape_envs[index % len(scrape_envs)]
            queue_by_runner[int(runner_env.id)].append(note)
        total_synced = 0
        total_failed = 0
        synced_note_ids: list[int] = []
        failed_note_ids: list[int] = []
        strategy_rounds = 0
        processed_notes = 0
        pause_min = pause_seconds_min if pause_seconds_min is not None else 0.0
        pause_max = pause_seconds_max if pause_seconds_max is not None else pause_min

        while any(queue_by_runner.get(int(env.id)) for env in scrape_envs):
            await self._raise_if_sync_cancelled(cancel_check)
            strategy_rounds += 1
            round_chunks: list[tuple[int, str, list[int], int, int]] = []
            round_offset = processed_notes
            for index, scrape_env in enumerate(scrape_envs):
                runner_queue = queue_by_runner.get(int(scrape_env.id)) or []
                if not runner_queue:
                    continue
                current_chunk = runner_queue[:chunk_size]
                queue_by_runner[int(scrape_env.id)] = runner_queue[chunk_size:]
                round_chunks.append(
                    (
                        int(scrape_env.id),
                        scrape_env.account_name,
                        [int(note.id) for note in current_chunk],
                        index + 1,
                        round_offset,
                    )
                )
                round_offset += len(current_chunk)
                await self._emit_progress(
                    progress_callback,
                    {
                        "phase": "runner_switch",
                        "detail": f"第 {strategy_rounds} 轮 {scrape_env.account_name} 准备处理 {len(current_chunk)} 条",
                        "runner_id": int(scrape_env.id),
                        "runner_name": scrape_env.account_name,
                        "round": strategy_rounds,
                        "runner_index": index + 1,
                        "runner_count": len(scrape_envs),
                        "current": processed_notes,
                        "total": len(active_notes),
                        "percent": int((processed_notes / len(active_notes)) * 100) if active_notes else 0,
                        "synced_notes": total_synced,
                        "failed_notes": total_failed,
                    },
                )

            semaphore = asyncio.Semaphore(max(1, min(concurrency, len(round_chunks) or 1)))

            async def run_chunk(
                runner_id: int,
                note_ids: list[int],
                runner_index: int,
                offset: int,
            ) -> dict:
                await self._raise_if_sync_cancelled(cancel_check)
                async with semaphore:
                    async with async_session() as session:
                        service = XHSService(session)
                        runner = await session.get(XHSEnvironment, runner_id)
                        if runner is None:
                            raise RuntimeError(f"同步环境 {runner_id} 不存在")
                        notes = list(
                            (
                                await session.execute(
                                    select(XHSAccountNote).where(XHSAccountNote.id.in_(note_ids))
                                )
                            ).scalars().all()
                        )
                        notes_by_id = {int(note.id): note for note in notes}
                        ordered_notes = [notes_by_id[note_id] for note_id in note_ids if note_id in notes_by_id]
                        if len(ordered_notes) != len(note_ids):
                            raise RuntimeError(f"同步环境 {runner_id} 的部分帖子已不存在")
                        env_lock = await service._get_env_publish_lock(runner_id)
                        async with env_lock:
                            return await service._sync_existing_account_note_stats_chunk_locked(
                                scrape_env=runner,
                                active_notes=ordered_notes,
                                persona=persona,
                                progress_callback=progress_callback,
                                cancel_check=cancel_check,
                                processed_offset=offset,
                                total_notes=len(active_notes),
                                base_synced=total_synced,
                                base_failed=total_failed,
                                round_index=strategy_rounds,
                                runner_index=runner_index,
                                runner_count=len(scrape_envs),
                            )

            raw_results = await asyncio.gather(
                *(
                    run_chunk(runner_id, note_ids, runner_index, offset)
                    for runner_id, _, note_ids, runner_index, offset in round_chunks
                ),
                return_exceptions=True,
            )

            for (runner_id, runner_name, note_ids, runner_index, _), raw_result in zip(round_chunks, raw_results):
                try:
                    if isinstance(raw_result, Exception):
                        raise raw_result
                    result = raw_result
                    total_synced += int(result.get("synced_notes") or 0)
                    total_failed += int(result.get("failed_notes") or 0)
                    synced_note_ids.extend(int(item) for item in result.get("synced_note_ids") or [])
                    failed_note_ids.extend(int(item) for item in result.get("failed_note_ids") or [])
                    processed_notes += len(note_ids)
                except Exception as exc:
                    total_failed += len(note_ids)
                    failed_note_ids.extend(note_ids)
                    processed_notes += len(note_ids)
                    logger.warning(
                        "按策略同步账号帖子互动数据失败: scrape_env=%s chunk=%s error=%s",
                        runner_name,
                        len(note_ids),
                        exc,
                    )
                    await self._emit_progress(
                        progress_callback,
                        {
                            "phase": "runner_failed",
                            "detail": f"{runner_name} 本轮执行失败，已跳过这批任务",
                            "runner_id": runner_id,
                            "runner_name": runner_name,
                            "round": strategy_rounds,
                            "runner_index": runner_index,
                            "runner_count": len(scrape_envs),
                            "current": processed_notes,
                            "total": len(active_notes),
                            "percent": int((processed_notes / len(active_notes)) * 100) if active_notes else 100,
                            "synced_notes": total_synced,
                            "failed_notes": total_failed,
                        },
                    )

            has_remaining = any(queue_by_runner.get(int(env.id)) for env in scrape_envs)
            if has_remaining and (pause_min > 0 or pause_max > 0):
                await self._raise_if_sync_cancelled(cancel_check)
                await self._emit_progress(
                    progress_callback,
                    {
                        "phase": "runner_pausing",
                        "detail": f"第 {strategy_rounds} 轮已完成，暂停后继续下一轮",
                        "round": strategy_rounds,
                        "runner_count": len(scrape_envs),
                        "current": processed_notes,
                        "total": len(active_notes),
                        "percent": int((processed_notes / len(active_notes)) * 100) if active_notes else 100,
                        "synced_notes": total_synced,
                        "failed_notes": total_failed,
                    },
                )
                await self._sleep_humanized(pause_min, pause_max)

        return {
            "total_notes": len(active_notes),
            "synced_notes": total_synced,
            "failed_notes": total_failed,
            "synced_note_ids": synced_note_ids,
            "failed_note_ids": failed_note_ids,
            "strategy_rounds": strategy_rounds,
        }

    async def _fetch_current_account_notes(self, api_base: str | None = None, limit: int = 60) -> dict:
        api_base = self._resolve_active_mcp_api(api_base)
        async with httpx.AsyncClient(**self._httpx_client_kwargs(api_base, timeout=45.0)) as client:
            resp = await client.get(f"{api_base}/api/v1/user/me")
        if resp.status_code != 200:
            raise RuntimeError(f"获取当前账号主页失败: HTTP {resp.status_code}")

        payload = resp.json() if resp.content else {}
        if not isinstance(payload, dict) or not (payload.get("success") or payload.get("code") == 0):
            raise RuntimeError(str(payload.get("message") or "获取当前账号主页失败"))

        data = payload.get("data") or {}
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data.get("data") or {}
        if not isinstance(data, dict):
            raise RuntimeError("当前账号主页返回结构异常")

        user_info = data.get("userBasicInfo") or {}
        feeds = data.get("feeds") or []
        normalized_feeds: list[dict] = []
        for index, raw in enumerate(feeds[: max(1, min(limit, 60))]):
            if not isinstance(raw, dict):
                continue
            note_card = raw.get("noteCard") or {}
            interact_info = note_card.get("interactInfo") or {}
            feed_id = str(raw.get("id") or raw.get("noteId") or "").strip()
            if not feed_id:
                continue
            normalized_feeds.append(
                {
                    "feed_id": feed_id,
                    "xsec_token": str(raw.get("xsecToken") or raw.get("xsec_token") or "").strip() or None,
                    "title": str(note_card.get("displayTitle") or raw.get("displayTitle") or "").strip(),
                    "published_at": self._xhs_timestamp_ms_to_utc_naive(
                        raw.get("time") or note_card.get("time") or raw.get("publishTime") or note_card.get("publishTime")
                    ),
                    "liked_count": self._extract_optional_count(interact_info, "likedCount"),
                    "comment_count": self._extract_optional_count(interact_info, "commentCount"),
                    "collected_count": self._extract_optional_count(interact_info, "collectedCount"),
                    "share_count": self._extract_optional_count(interact_info, "sharedCount", "shareCount"),
                    "sort_index": index,
                }
            )

        return {
            "profile_nickname": str(user_info.get("nickname") or "").strip() or None,
            "red_id": str(user_info.get("redId") or "").strip() or None,
            "feeds": normalized_feeds,
        }

    async def _resolve_account_scrape_environment(self, scrape_environment_id: int | None = None) -> XHSEnvironment:
        if scrape_environment_id and scrape_environment_id > 0:
            env = await self.get_environment(scrape_environment_id)
            if env and env.status == "active":
                return env
            raise RuntimeError("指定的同步环境不存在或未启用")
        if XHS_ACCOUNT_SCRAPE_ENVIRONMENT_ID > 0:
            env = await self.get_environment(XHS_ACCOUNT_SCRAPE_ENVIRONMENT_ID)
            if env:
                return env
        result = await self.db.execute(
            select(XHSEnvironment).where(
                and_(XHSEnvironment.status == "active", XHSEnvironment.is_sync_runner.is_(True))
            ).order_by(XHSEnvironment.account_name.asc(), XHSEnvironment.id.asc())
        )
        env = result.scalars().first()
        if env:
            return env
        result = await self.db.execute(
            select(XHSEnvironment).where(
                and_(XHSEnvironment.status == "active", XHSEnvironment.account_name == "测试2")
            )
        )
        env = result.scalars().first()
        if env:
            return env
        raise RuntimeError("未找到账号数据采集环境，请配置 XHS_ACCOUNT_SCRAPE_ENVIRONMENT_ID、显式传 scrape_environment_id，或先在后台把某个环境标记为“同步环境”")

    async def _resolve_account_scrape_environments(
        self,
        *,
        scrape_environment_id: int | None = None,
        scrape_environment_ids: list[int] | None = None,
    ) -> list[XHSEnvironment]:
        normalized_ids = [item for item in (scrape_environment_ids or []) if item > 0]
        if normalized_ids:
            envs: list[XHSEnvironment] = []
            for env_id in normalized_ids:
                env = await self.get_environment(env_id)
                if not env or env.status != "active":
                    raise RuntimeError(f"指定的同步环境不存在或未启用: {env_id}")
                envs.append(env)
            return envs
        return [await self._resolve_account_scrape_environment(scrape_environment_id)]

    @staticmethod
    def _parse_sync_browser_start_config(scrape_env: XHSEnvironment) -> dict:
        return XHSService._parse_sync_json_object(
            getattr(scrape_env, "sync_browser_start_config", "") or "",
            f"同步环境 {scrape_env.account_name} 的浏览器启动参数",
        )

    @staticmethod
    def _parse_sync_cloud_update_config(scrape_env: XHSEnvironment) -> dict:
        return XHSService._parse_sync_json_object(
            getattr(scrape_env, "sync_cloud_update_config", "") or "",
            f"同步环境 {scrape_env.account_name} 的开放平台指纹更新参数",
        )

    @staticmethod
    def _materialize_sync_browser_start_config(node):
        if isinstance(node, dict):
            if len(node) == 1 and "$pick" in node:
                options = node.get("$pick")
                if not isinstance(options, list) or not options:
                    raise RuntimeError("$pick 必须是非空数组")
                return XHSService._materialize_sync_browser_start_config(
                    _SYNC_BROWSER_CONFIG_RNG.choice(options)
                )
            if len(node) == 1 and "$rand_int" in node:
                spec = node.get("$rand_int")
                if isinstance(spec, list) and len(spec) == 2:
                    min_v, max_v = spec
                elif isinstance(spec, dict):
                    min_v = spec.get("min")
                    max_v = spec.get("max")
                else:
                    raise RuntimeError("$rand_int 必须是 [min,max] 或 {min,max}")
                try:
                    start = int(min_v)
                    end = int(max_v)
                except Exception as exc:
                    raise RuntimeError("$rand_int 的 min/max 必须是整数") from exc
                if start > end:
                    raise RuntimeError("$rand_int 的 min 不能大于 max")
                return _SYNC_BROWSER_CONFIG_RNG.randint(start, end)
            if len(node) == 1 and "$uuid" in node:
                if not bool(node.get("$uuid")):
                    raise RuntimeError("$uuid 只能设置为 true")
                return uuid.uuid4().hex
            if len(node) == 1 and "$bool" in node:
                if not bool(node.get("$bool")):
                    raise RuntimeError("$bool 只能设置为 true")
                return bool(_SYNC_BROWSER_CONFIG_RNG.getrandbits(1))
            return {
                str(key): XHSService._materialize_sync_browser_start_config(value)
                for key, value in node.items()
            }
        if isinstance(node, list):
            return [XHSService._materialize_sync_browser_start_config(value) for value in node]
        return node

    @staticmethod
    def _extract_profile_identifiers(profile_url: str) -> tuple[str | None, str | None]:
        try:
            parsed = urlparse(profile_url)
            match = re.search(r"/user/profile/([0-9a-zA-Z]+)", parsed.path or "")
            user_id = match.group(1) if match else None
            query = parse_qs(parsed.query or "")
            xsec_token = (query.get("xsec_token") or query.get("xsecToken") or [None])[0]
            if xsec_token:
                xsec_token = unquote(xsec_token).strip()
            return user_id, xsec_token or None
        except Exception:
            return None, None

    @staticmethod
    def _pick_warmup_feed(payload: dict | None) -> tuple[str | None, str | None]:
        feeds = payload.get("feeds") if isinstance(payload, dict) else None
        if not isinstance(feeds, list):
            return None, None
        candidates: list[tuple[str, str]] = []
        for raw in feeds[:6]:
            if not isinstance(raw, dict):
                continue
            feed_id = str(raw.get("feed_id") or "").strip()
            xsec_token = str(raw.get("xsec_token") or "").strip()
            if feed_id and xsec_token:
                candidates.append((feed_id, xsec_token))
        if not candidates:
            return None, None
        feed_id, xsec_token = _SYNC_BROWSER_CONFIG_RNG.choice(candidates[:3] or candidates)
        return feed_id, xsec_token

    async def _run_sync_browser_warmup(
        self,
        *,
        api_base: str,
        persona: SyncSessionPersona,
        target_profile_url: str | None = None,
    ) -> None:
        """在真正抓取前先做轻量访问，减少“刚启动就直扑目标”的轨迹。"""
        try:
            for round_index in range(persona.warmup_rounds):
                current_payload = await self._fetch_current_account_notes(
                    api_base=api_base,
                    limit=max(1, min(persona.warmup_note_limit, 8)),
                )
                await self._maybe_run_warmup_detail_peek(current_payload, api_base=api_base, persona=persona)
                if (
                    persona.use_profile_peek
                    and target_profile_url
                    and round_index == persona.warmup_rounds - 1
                    and _SYNC_BROWSER_CONFIG_RNG.random() < 0.72
                ):
                    profile_payload = await self._fetch_profile_account_notes(
                        target_profile_url,
                        api_base=api_base,
                        limit=max(1, min(persona.warmup_note_limit, 8)),
                    )
                    await self._maybe_run_warmup_detail_peek(profile_payload, api_base=api_base, persona=persona)
                if round_index < persona.warmup_rounds - 1:
                    await self._sleep_between_sync_batches(persona)
        except Exception as exc:
            logger.info("同步预热浏览已跳过: reason=%s", exc)

    async def _maybe_run_warmup_detail_peek(
        self,
        payload: dict | None,
        *,
        api_base: str,
        persona: SyncSessionPersona,
    ) -> None:
        if _SYNC_BROWSER_CONFIG_RNG.random() >= persona.warmup_detail_peek_probability:
            return
        feed_id, xsec_token = self._pick_warmup_feed(payload or {})
        if not feed_id or not xsec_token:
            return
        await self._sleep_between_account_note_details(persona)
        await self._fetch_account_note_detail_metrics(
            feed_id,
            xsec_token,
            api_base=api_base,
            persona=persona,
        )

    async def _fetch_profile_account_notes(
        self,
        profile_url: str,
        api_base: str | None = None,
        limit: int = 120,
        *,
        scroll_mode: str | None = None,
        stop_feed_id: str | None = None,
        max_feeds: int | None = None,
        max_scroll_rounds: int | None = None,
        max_stagnant_rounds: int | None = None,
    ) -> dict:
        user_id, xsec_token = self._extract_profile_identifiers(profile_url)
        if not user_id:
            raise RuntimeError("个人主页链接缺少 user_id")

        api_base = self._resolve_active_mcp_api(api_base)
        payload = {"user_id": user_id}
        if xsec_token:
            payload["xsec_token"] = xsec_token
        if scroll_mode:
            payload["scroll_mode"] = scroll_mode
        if stop_feed_id:
            payload["stop_feed_id"] = stop_feed_id
        if max_feeds and max_feeds > 0:
            payload["max_feeds"] = int(max_feeds)
        if max_scroll_rounds and max_scroll_rounds > 0:
            payload["max_scroll_rounds"] = int(max_scroll_rounds)
        if max_stagnant_rounds and max_stagnant_rounds > 0:
            payload["max_stagnant_rounds"] = int(max_stagnant_rounds)
        # A full profile scroll can take several minutes on a slow YunLogin
        # browser. Keep the client timeout above the MCP/browser operation.
        try:
            async with httpx.AsyncClient(
                **self._httpx_client_kwargs(api_base, timeout=XHS_PROFILE_FETCH_TIMEOUT_SECONDS)
            ) as client:
                resp = await client.post(
                    f"{api_base}/api/v1/user/profile",
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"获取账号主页超时（已等待 {int(XHS_PROFILE_FETCH_TIMEOUT_SECONDS)} 秒）"
            ) from exc
        if resp.status_code != 200:
            detail = self._http_error_detail(resp)
            suffix = f"，{detail}" if detail else ""
            raise RuntimeError(f"获取账号主页失败: HTTP {resp.status_code}{suffix}")

        payload = resp.json() if resp.content else {}
        if not isinstance(payload, dict) or not (payload.get("success") or payload.get("code") == 0):
            raise RuntimeError(str(payload.get("message") or "获取账号主页失败"))

        data = payload.get("data") or {}
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data.get("data") or {}
        if not isinstance(data, dict):
            raise RuntimeError("账号主页返回结构异常")

        user_info = data.get("userBasicInfo") or {}
        feeds = data.get("feeds") or []
        normalized_feeds: list[dict] = []
        max_items = max(1, int(limit or 0))
        if max_feeds and max_feeds > 0:
            max_items = max(max_items, int(max_feeds))
        for index, raw in enumerate(feeds[:max_items]):
            if not isinstance(raw, dict):
                continue
            note_card = raw.get("noteCard") or {}
            interact_info = note_card.get("interactInfo") or {}
            cover_info = note_card.get("cover") or {}
            feed_id = str(raw.get("id") or raw.get("noteId") or "").strip()
            if not feed_id:
                continue
            normalized_feeds.append(
                {
                    "feed_id": feed_id,
                    "xsec_token": str(raw.get("xsecToken") or raw.get("xsec_token") or "").strip() or None,
                    "cover_image_url": self._pick_note_cover_image_url(cover_info),
                    "title": str(note_card.get("displayTitle") or raw.get("displayTitle") or "").strip(),
                    "published_at": self._xhs_timestamp_ms_to_utc_naive(
                        raw.get("time") or note_card.get("time") or raw.get("publishTime") or note_card.get("publishTime")
                    ),
                    "liked_count": self._extract_optional_count(interact_info, "likedCount"),
                    "comment_count": self._extract_optional_count(interact_info, "commentCount"),
                    "collected_count": self._extract_optional_count(interact_info, "collectedCount"),
                    "share_count": self._extract_optional_count(interact_info, "sharedCount", "shareCount"),
                    "sort_index": index,
                }
            )

        return {
            "profile_nickname": str(user_info.get("nickname") or "").strip() or None,
            "red_id": str(user_info.get("redId") or "").strip() or None,
            "feeds": normalized_feeds,
        }

    @staticmethod
    def _estimate_account_note_profile_fetch_max_feeds(known_note_count: int, limit: int) -> int:
        baseline = max(1, int(limit or 0))
        if known_note_count <= 0:
            return baseline
        return min(1000, max(baseline, known_note_count + max(baseline, 60)))

    @staticmethod
    def _estimate_account_note_profile_scroll_rounds(known_note_count: int, limit: int) -> int:
        if known_note_count <= 0:
            return 0
        target_feed_count = known_note_count + max(int(limit or 0), 60)
        if target_feed_count <= 30:
            return 1
        estimated_rounds = (target_feed_count - 30 + 29) // 30
        return max(2, min(40, estimated_rounds))

    @staticmethod
    def _pick_note_cover_image_url(cover_info: dict | None) -> str | None:
        if not isinstance(cover_info, dict):
            return None

        for key in ("urlDefault", "urlPre", "url"):
            value = str(cover_info.get(key) or "").strip()
            if value:
                return value

        info_list = cover_info.get("infoList") or []
        if isinstance(info_list, list):
            for item in info_list:
                if not isinstance(item, dict):
                    continue
                value = str(item.get("url") or "").strip()
                if value:
                    return value
        return None

    @staticmethod
    def _extract_nested_payload_value(payload: Any, path: tuple[str, ...]) -> Any:
        current = payload
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    @classmethod
    def _normalize_note_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                normalized = cls._normalize_note_text(item)
                if normalized:
                    parts.append(normalized)
            if not parts:
                return None
            text = "\n".join(parts).strip()
            return text or None
        if isinstance(value, dict):
            for key in ("text", "content", "desc", "description", "noteContent", "note_desc", "value"):
                normalized = cls._normalize_note_text(value.get(key))
                if normalized:
                    return normalized
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _pick_note_image_item_url(image_item: Any) -> str | None:
        if not isinstance(image_item, dict):
            return None
        for key in ("urlDefault", "url", "urlPre"):
            value = str(image_item.get(key) or "").strip()
            if value:
                return value

        info_list = image_item.get("infoList") or []
        if isinstance(info_list, list):
            for preferred_scene in ("WB_DFT", ""):
                for info in info_list:
                    if not isinstance(info, dict):
                        continue
                    if preferred_scene and str(info.get("imageScene") or "").strip() != preferred_scene:
                        continue
                    value = str(info.get("url") or "").strip()
                    if value:
                        return value
            for info in info_list:
                if not isinstance(info, dict):
                    continue
                value = str(info.get("url") or "").strip()
                if value:
                    return value
        return None

    def _extract_account_note_detail_content(self, payload: dict, title: str | None = None) -> dict[str, str | None]:
        normalized_title = self._normalize_note_text(title)
        candidate_paths = (
            ("desc",),
            ("content",),
            ("description",),
            ("contents",),
            ("note_desc",),
            ("noteContent",),
            ("noteCard", "desc"),
            ("noteCard", "content"),
            ("noteCard", "description"),
            ("noteCard", "note_desc"),
            ("noteCard", "noteContent"),
            ("detail", "desc"),
            ("detail", "content"),
            ("detail", "description"),
            ("detail", "contents"),
            ("detail", "note_desc"),
            ("detail", "noteContent"),
            ("note", "desc"),
            ("note", "content"),
            ("note", "description"),
            ("note", "contents"),
            ("note", "note_desc"),
            ("detail", "note", "desc"),
            ("detail", "note", "content"),
            ("detail", "note", "description"),
            ("detail", "note", "contents"),
            ("detail", "note", "note_desc"),
            ("note_card", "desc"),
            ("note_card", "content"),
            ("note_card", "description"),
            ("note_card", "note_desc"),
            ("note_card", "noteContent"),
            ("detail", "note_card", "desc"),
            ("detail", "note_card", "content"),
            ("detail", "note_card", "description"),
            ("detail", "note_card", "note_desc"),
            ("detail", "note_card", "noteContent"),
            ("note", "note_card", "desc"),
            ("note", "note_card", "content"),
            ("note", "note_card", "description"),
            ("note", "note_card", "note_desc"),
            ("note", "note_card", "noteContent"),
            ("detail", "note", "note_card", "desc"),
            ("detail", "note", "note_card", "content"),
            ("detail", "note", "note_card", "description"),
            ("detail", "note", "note_card", "note_desc"),
            ("detail", "note", "note_card", "noteContent"),
        )
        saw_title_only = False
        for path in candidate_paths:
            value = self._normalize_note_text(self._extract_nested_payload_value(payload, path))
            if not value:
                continue
            if normalized_title and value == normalized_title:
                saw_title_only = True
                continue
            return {
                "content": value,
                "content_status": "from_detail",
                "content_missing_reason": None,
            }

        return {
            "content": None,
            "content_status": "missing_from_source",
            "content_missing_reason": "详情接口仅返回标题，未返回有效正文" if saw_title_only else "详情接口未返回正文（note 为空或无 desc/content 字段）",
        }

    def _extract_account_note_detail_images(self, payload: dict) -> dict[str, list[str]]:
        candidate_paths = (
            ("noteCard", "imageList"),
            ("detail", "noteCard", "imageList"),
            ("note_card", "imageList"),
            ("detail", "note_card", "imageList"),
            ("note", "imageList"),
            ("detail", "note", "imageList"),
            ("images",),
            ("detail", "images"),
            ("note", "images"),
            ("detail", "note", "images"),
        )
        seen: set[str] = set()
        image_urls: list[str] = []
        for path in candidate_paths:
            image_list = self._extract_nested_payload_value(payload, path)
            if not isinstance(image_list, list):
                continue
            for item in image_list:
                url = self._pick_note_image_item_url(item)
                if not url or url in seen:
                    continue
                seen.add(url)
                image_urls.append(url)
            if image_urls:
                break
        return {"image_urls": image_urls}

    def _extract_account_note_detail_cover_image_url(self, payload: dict, image_urls: list[str] | None = None) -> str | None:
        candidate_paths = (
            ("cover",),
            ("noteCard", "cover"),
            ("detail", "noteCard", "cover"),
            ("note_card", "cover"),
            ("detail", "note_card", "cover"),
            ("note", "cover"),
            ("detail", "note", "cover"),
        )
        for path in candidate_paths:
            cover_info = self._extract_nested_payload_value(payload, path)
            cover_url = self._pick_note_cover_image_url(cover_info if isinstance(cover_info, dict) else None)
            if cover_url:
                return cover_url
        if image_urls:
            return image_urls[0]
        return None

    def _extract_account_note_detail_metrics(self, payload: dict) -> dict[str, int | datetime | None]:
        nodes = [
            payload,
            self._extract_nested_payload_value(payload, ("detail",)),
            self._extract_nested_payload_value(payload, ("note",)),
            self._extract_nested_payload_value(payload, ("detail", "note")),
            self._extract_nested_payload_value(payload, ("noteCard",)),
            self._extract_nested_payload_value(payload, ("detail", "noteCard")),
            self._extract_nested_payload_value(payload, ("note_card",)),
            self._extract_nested_payload_value(payload, ("detail", "note_card")),
        ]

        def extract_count(keys: tuple[str, ...]) -> int | None:
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                for container_key in ("interactInfo", "interact_info"):
                    interact = node.get(container_key)
                    if isinstance(interact, dict):
                        for key in keys:
                            if interact.get(key) is not None:
                                return self._safe_int(interact.get(key))
                for key in keys:
                    if node.get(key) is not None:
                        return self._safe_int(node.get(key))
            return None

        published_at = None
        published_paths = (
            ("time",),
            ("publishTime",),
            ("note", "time"),
            ("note", "publishTime"),
            ("detail", "time"),
            ("detail", "publishTime"),
            ("detail", "note", "time"),
            ("detail", "note", "publishTime"),
            ("noteCard", "time"),
            ("noteCard", "publishTime"),
            ("detail", "noteCard", "time"),
            ("detail", "noteCard", "publishTime"),
            ("note_card", "time"),
            ("note_card", "publishTime"),
            ("detail", "note_card", "time"),
            ("detail", "note_card", "publishTime"),
        )
        for path in published_paths:
            raw_value = self._extract_nested_payload_value(payload, path)
            converted = self._xhs_timestamp_ms_to_utc_naive(raw_value)
            if converted:
                published_at = converted
                break

        return {
            "liked_count": extract_count(("likedCount", "liked_count", "likeCount", "like_count")),
            "comment_count": extract_count(("commentCount", "comment_count")),
            "collected_count": extract_count(("collectedCount", "collected_count", "collectCount", "collect_count")),
            "share_count": extract_count(("sharedCount", "shared_count", "shareCount", "share_count")),
            "published_at": published_at,
        }

    def _extract_account_note_detail_data(self, payload: dict, *, title: str | None = None) -> dict[str, Any]:
        metrics = self._extract_account_note_detail_metrics(payload)
        content = self._extract_account_note_detail_content(payload, title=title)
        images = self._extract_account_note_detail_images(payload)
        return {
            **metrics,
            **content,
            **images,
            "cover_image_url": self._extract_account_note_detail_cover_image_url(payload, images.get("image_urls")),
        }

    async def _sync_account_note_metrics(
        self,
        note: XHSAccountNote,
        api_base: str | None = None,
        persona: SyncSessionPersona | None = None,
        pending_cover_localizations: list[tuple[int, str, str | None, str]] | None = None,
    ) -> bool:
        detail_data = await self._fetch_account_note_detail_metrics(
            note.feed_id,
            note.xsec_token,
            title=note.title,
            api_base=api_base,
            persona=persona,
        )
        if not detail_data:
            return False
        if isinstance(detail_data.get("liked_count"), int):
            note.liked_count = self._merge_metric_count(note.liked_count, detail_data["liked_count"])
        if isinstance(detail_data.get("comment_count"), int):
            note.comment_count = self._merge_metric_count(note.comment_count, detail_data["comment_count"])
        if isinstance(detail_data.get("collected_count"), int):
            note.collected_count = self._merge_metric_count(note.collected_count, detail_data["collected_count"])
        if isinstance(detail_data.get("share_count"), int):
            note.share_count = self._merge_metric_count(note.share_count, detail_data["share_count"])
        if detail_data.get("published_at"):
            note.published_at = detail_data["published_at"]
        if detail_data.get("cover_image_url"):
            note.cover_image_url, pending_cover_url = self._prepare_account_note_cover_image(
                detail_data.get("cover_image_url"),
                existing_url=note.cover_image_url,
            )
            if pending_cover_url and pending_cover_localizations is not None:
                pending_cover_localizations.append((
                    int(note.environment_id or 0),
                    str(note.feed_id or "").strip(),
                    note.cover_image_url,
                    pending_cover_url,
                ))
        image_urls = detail_data.get("image_urls") or []
        if isinstance(image_urls, list) and image_urls:
            note.image_urls = image_urls
        content = self._normalize_note_text(detail_data.get("content"))
        if content:
            note.content = content
            note.content_status = "from_detail"
            note.content_missing_reason = None
        elif not self._normalize_note_text(note.content):
            note.content_status = str(detail_data.get("content_status") or "").strip() or "missing_from_source"
            note.content_missing_reason = self._normalize_note_text(detail_data.get("content_missing_reason"))
        note.detail_synced_at = utc_now_naive()
        note.last_seen_at = utc_now_naive()
        return True

    async def _sync_account_note_engagement_metrics(
        self,
        note: XHSAccountNote,
        *,
        api_base: str | None = None,
        env: XHSEnvironment | None = None,
    ) -> bool:
        stats_rows = await self._fetch_creator_note_stats(api_base=api_base, env=env)
        if not stats_rows:
            return False

        matched = self._match_creator_note_stats(note, stats_rows)
        if not matched:
            return False

        self._apply_creator_metrics(note, matched)
        now = utc_now_naive()
        note.creator_first_seen_at = note.creator_first_seen_at or now
        note.creator_last_seen_at = now
        note.creator_synced_at = now
        return True

    @classmethod
    def _normalize_creator_identity_title(cls, value: Any) -> str:
        title = cls._normalize_note_text(value) or ""
        return re.sub(r"\s+", " ", title).strip().casefold()

    @staticmethod
    def _creator_published_at_utc(value: Any) -> datetime | None:
        if not isinstance(value, datetime):
            return None
        return aware_or_cst_naive_to_utc_naive(value)

    @classmethod
    def _prepare_creator_stats_rows(cls, stats_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        occurrences: dict[str, int] = {}
        prepared: list[dict[str, Any]] = []
        for fallback_index, row in enumerate(stats_rows, start=1):
            payload = dict(row or {})
            payload["source_row_index"] = int(payload.get("source_row_index") or fallback_index)
            normalized_title = cls._normalize_creator_identity_title(payload.get("title"))
            published_at_utc = cls._creator_published_at_utc(payload.get("published_at"))
            published_part = (
                published_at_utc.isoformat(timespec="seconds")
                if published_at_utc
                else str(payload.get("published_at_raw") or "").strip()
            )
            base = f"{normalized_title}|{published_part}"
            occurrence = occurrences.get(base, 0) + 1
            occurrences[base] = occurrence
            payload["normalized_title"] = normalized_title
            payload["published_at_utc"] = published_at_utc
            payload["source_key"] = hashlib.sha256(f"{base}|{occurrence}".encode("utf-8")).hexdigest()
            prepared.append(payload)
        return prepared

    @classmethod
    def _match_creator_row_to_note(
        cls,
        row: dict[str, Any],
        notes: list[XHSAccountNote],
        *,
        used_note_ids: set[int] | None = None,
    ) -> tuple[XHSAccountNote | None, str | None, float | None, bool]:
        used_note_ids = used_note_ids or set()
        available = [note for note in notes if not note.id or int(note.id) not in used_note_ids]
        note_id = str(row.get("note_id") or "").strip()
        if note_id:
            direct = [note for note in available if str(note.feed_id or "").strip() == note_id]
            if len(direct) == 1:
                return direct[0], "feed_id", 1.0, False
            if len(direct) > 1:
                return None, None, None, True

        source_key = str(row.get("source_key") or "").strip()
        if source_key:
            keyed = [note for note in available if str(note.creator_identity_key or "").strip() == source_key]
            if len(keyed) == 1:
                return keyed[0], "creator_key", 1.0, False
            if len(keyed) > 1:
                return None, None, None, True

        normalized_title = str(row.get("normalized_title") or "").strip()
        if not normalized_title:
            return None, None, None, False
        title_matches = [
            note for note in available
            if cls._normalize_creator_identity_title(note.title) == normalized_title
        ]
        all_title_matches = [
            note for note in notes
            if cls._normalize_creator_identity_title(note.title) == normalized_title
        ]
        published_at_utc = row.get("published_at_utc")
        if isinstance(published_at_utc, datetime):
            timed_matches = [
                note for note in title_matches
                if isinstance(note.published_at, datetime)
                and abs((note.published_at.replace(tzinfo=None) - published_at_utc).total_seconds()) <= 180
            ]
            if len(timed_matches) == 1:
                return timed_matches[0], "title_time", 0.96, False
            if len(timed_matches) > 1:
                return None, None, None, True

        if len(title_matches) == 1:
            return title_matches[0], "title_unique", 0.72, False
        if len(title_matches) > 1:
            return None, None, None, True
        if all_title_matches:
            return None, None, None, True
        return None, None, None, False

    @staticmethod
    def _apply_creator_metrics(note: XHSAccountNote, row: dict[str, Any]) -> None:
        metric_fields = {
            "like_count": "liked_count",
            "comment_count": "comment_count",
            "collect_count": "collected_count",
            "share_count": "share_count",
            "view_count": "view_count",
            "exposure_count": "exposure_count",
        }
        for source, target in metric_fields.items():
            value = row.get(source)
            if value is not None:
                setattr(note, target, max(0, int(value)))
        if row.get("cover_click_rate") is not None:
            note.cover_click_rate = max(0.0, float(row["cover_click_rate"]))

    async def _import_creator_note_stats_rows(
        self,
        env: XHSEnvironment,
        stats_rows: list[dict[str, Any]],
        *,
        sync_run_id: int | None = None,
    ) -> dict[str, int]:
        prepared_rows = self._prepare_creator_stats_rows(stats_rows)
        if sync_run_id is not None:
            await self.db.execute(
                delete(XHSCreatorSyncRow).where(
                    and_(
                        XHSCreatorSyncRow.sync_run_id == sync_run_id,
                        XHSCreatorSyncRow.environment_id == env.id,
                    )
                )
            )

        notes = list((await self.db.execute(
            select(XHSAccountNote)
            .where(XHSAccountNote.environment_id == env.id)
            .order_by(XHSAccountNote.sort_index.asc(), XHSAccountNote.id.asc())
        )).scalars().all())
        posts = list((await self.db.execute(
            select(XHSPost).where(XHSPost.environment_id == env.id)
        )).scalars().all())
        posts_by_feed = {
            str(post.feed_id or "").strip(): post
            for post in posts
            if str(post.feed_id or "").strip()
        }
        posts_by_title: dict[str, list[XHSPost]] = {}
        for post in posts:
            title_key = self._normalize_creator_identity_title(post.title)
            if title_key:
                posts_by_title.setdefault(title_key, []).append(post)

        now = utc_now_naive()
        used_note_ids: set[int] = set()
        created_notes = 0
        updated_notes = 0
        ambiguous_notes = 0
        metric_synced_notes = 0
        next_sort_index = max((int(note.sort_index or 0) for note in notes), default=-1) + 1

        for row in prepared_rows:
            note, match_method, confidence, is_ambiguous = self._match_creator_row_to_note(
                row,
                notes,
                used_note_ids=used_note_ids,
            )
            was_created = note is None
            if note is None:
                feed_id = str(row.get("note_id") or "").strip() or None
                note = XHSAccountNote(
                    environment_id=env.id,
                    account_name=env.account_name or "",
                    profile_nickname=env.account_name or "",
                    feed_id=feed_id,
                    title=str(row.get("title") or ""),
                    ai_origin_type="",
                    status="active",
                    identity_status="ambiguous" if is_ambiguous else ("resolved" if feed_id else "creator_only"),
                    identity_match_method="creator_ambiguous" if is_ambiguous else ("feed_id" if feed_id else "creator_new"),
                    identity_match_confidence=0.0 if is_ambiguous else (1.0 if feed_id else 0.6),
                    sort_index=next_sort_index,
                    first_synced_at=now,
                )
                next_sort_index += 1
                self.db.add(note)
                notes.append(note)
                created_notes += 1
                if is_ambiguous:
                    ambiguous_notes += 1
            else:
                updated_notes += 1
                if row.get("note_id") and not str(note.feed_id or "").strip():
                    note.feed_id = str(row["note_id"]).strip()
                if str(note.feed_id or "").strip():
                    note.identity_status = "resolved"
                elif note.identity_status != "ambiguous":
                    note.identity_status = "creator_only"
                note.identity_match_method = match_method or note.identity_match_method
                note.identity_match_confidence = confidence if confidence is not None else note.identity_match_confidence

            if not note.creator_identity_key:
                note.creator_identity_key = str(row.get("source_key") or "") or None
            note.account_name = env.account_name or note.account_name or ""
            note.profile_nickname = note.profile_nickname or env.account_name or ""
            note.title = str(row.get("title") or note.title or "")
            published_at_utc = row.get("published_at_utc")
            if isinstance(published_at_utc, datetime):
                note.published_at = published_at_utc
            note.creator_published_at_raw = str(row.get("published_at_raw") or "") or None
            note.creator_first_seen_at = note.creator_first_seen_at or now
            note.creator_last_seen_at = now
            note.creator_synced_at = now
            note.status = "active"
            self._apply_creator_metrics(note, row)
            metric_synced_notes += 1

            source_post = posts_by_feed.get(str(note.feed_id or "").strip())
            if source_post is None:
                title_posts = posts_by_title.get(self._normalize_creator_identity_title(note.title), [])
                if (
                    len(title_posts) == 1
                    and isinstance(note.published_at, datetime)
                    and isinstance(title_posts[0].published_at, datetime)
                    and abs((title_posts[0].published_at.replace(tzinfo=None) - note.published_at.replace(tzinfo=None)).total_seconds()) <= 180
                ):
                    source_post = title_posts[0]
            if source_post is not None:
                note.source_post_id = int(source_post.id)

            await self.db.flush()
            if note.id:
                used_note_ids.add(int(note.id))
            metrics = {
                key: row.get(key)
                for key in (
                    "exposure_count",
                    "view_count",
                    "cover_click_rate",
                    "like_count",
                    "comment_count",
                    "collect_count",
                    "share_count",
                )
            }
            self.db.add(XHSCreatorSyncRow(
                sync_run_id=sync_run_id,
                environment_id=env.id,
                matched_note_id=note.id,
                source_row_index=int(row.get("source_row_index") or 0),
                source_key=str(row.get("source_key") or ""),
                title=str(row.get("title") or ""),
                published_at=row.get("published_at_utc"),
                published_at_raw=str(row.get("published_at_raw") or "") or None,
                metrics=metrics,
                raw_payload=dict(row.get("raw_payload") or {}),
                match_status="ambiguous" if is_ambiguous else ("created" if was_created else "matched"),
                match_method=note.identity_match_method,
                match_confidence=note.identity_match_confidence,
                message="存在同标题候选，已保留为待补 ID 帖子" if is_ambiguous else None,
            ))

        await self.db.flush()
        total_notes = int((await self.db.execute(
            select(func.count(XHSAccountNote.id)).where(XHSAccountNote.environment_id == env.id)
        )).scalar_one() or 0)
        return {
            "created_notes": created_notes,
            "updated_notes": updated_notes,
            "ambiguous_notes": ambiguous_notes,
            "metric_synced_notes": metric_synced_notes,
            "total_notes": total_notes,
        }

    async def _fetch_creator_note_stats(
        self,
        *,
        api_base: str | None = None,
        env: XHSEnvironment | None = None,
    ) -> list[dict[str, Any]]:
        resolved_api = self._resolve_active_mcp_api(api_base)
        await self._ensure_xhs_creator_login(resolved_api, env=env)
        started_at = time.monotonic()
        logger.info("开始导出创作中心笔记数据: api_base=%s", resolved_api)
        # Windows 指纹浏览器导出 Excel 常常接近 3 分钟，180s 会在下载成功后先超时断开。
        async with httpx.AsyncClient(**self._httpx_client_kwargs(resolved_api, timeout=420.0)) as client:
            resp = await client.get(f"{resolved_api}/api/v1/creator/stats/export")
        if resp.status_code != 200:
            raise RuntimeError(f"导出创作中心笔记数据失败: HTTP {resp.status_code}")

        payload = resp.json() if resp.content else {}
        if not isinstance(payload, dict) or not (payload.get("success") or payload.get("code") == 0):
            raise RuntimeError(str(payload.get("message") or "导出创作中心笔记数据失败"))

        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise RuntimeError("创作中心导出数据结构异常")
        file_base64 = str(data.get("file_base64") or data.get("content_base64") or "").strip()
        if not file_base64:
            raise RuntimeError("创作中心导出文件为空")
        try:
            content = base64.b64decode(file_base64)
        except Exception as exc:
            raise RuntimeError(f"创作中心导出文件解码失败: {exc}") from exc
        rows = self._parse_creator_stats_excel(content)
        logger.info(
            "创作中心笔记数据导出解析完成: rows=%s elapsed=%.1fs",
            len(rows),
            time.monotonic() - started_at,
        )
        return rows

    async def _ensure_xhs_creator_login(self, api_base: str, *, env: XHSEnvironment | None = None) -> None:
        flow_started_at = time.monotonic()
        login_status = await self._get_mcp_login_status(api_base)
        if bool(login_status.get("is_logged_in")):
            return

        phone_number = self._normalize_cn_phone_number(str(getattr(env, "login_phone_number", "") or ""))
        if not phone_number:
            account_name = str(getattr(env, "account_name", "") or "").strip()
            raise RuntimeError(f"{account_name or '当前环境'} 未登录且未配置手机号，无法自动接码登录")
        if not SMS_CODE_CENTER_BASE_URL:
            raise RuntimeError("未配置短信验证码中台地址，无法自动接码登录")
        if not SMS_CODE_CENTER_OPEN_API_CLIENT_ID or not SMS_CODE_CENTER_OPEN_API_CLIENT_SECRET:
            raise RuntimeError("未配置 SMS_CODE_CENTER_OPEN_API_CLIENT_ID / SMS_CODE_CENTER_OPEN_API_CLIENT_SECRET，无法自动接码登录")

        client_request_id = f"xhs-login-{getattr(env, 'id', 'env')}-{uuid.uuid4().hex}"
        request_id = ""
        sms_received = False
        try:
            sms_request = await self._create_open_sms_code_request(phone_number, client_request_id)
            request_id = str(sms_request.get("requestId") or sms_request.get("request_id") or "").strip()
            if not request_id:
                raise RuntimeError("验证码中台未返回 requestId")
            logger.info(
                "小红书自动登录第一条接码订单已创建: env_id=%s request_id=%s elapsed_ms=%s",
                getattr(env, "id", None),
                request_id,
                round((time.monotonic() - flow_started_at) * 1000),
            )

            request_status = str(sms_request.get("status") or "").strip()
            if request_status == "received":
                received_request = sms_request
            elif request_status == "waiting":
                # Start both the exact-SIM order poll and the same-device SMS
                # library fallback before asking Xiaohongshu to send the code.
                sms_wait_task = asyncio.create_task(
                    self._wait_open_sms_code_request(request_id, initial_request=sms_request)
                )
                try:
                    await asyncio.sleep(0)
                    async with httpx.AsyncClient(**self._httpx_client_kwargs(api_base, timeout=60.0)) as client:
                        resp = await client.post(
                            f"{api_base}/api/v1/login/phone/request-code",
                            json={"phone_number": phone_number},
                        )
                    payload = resp.json() if resp.content else {}
                    if resp.status_code != 200:
                        raise RuntimeError(
                            f"触发小红书发送验证码失败: HTTP {resp.status_code} "
                            f"{self._mcp_error_detail(payload)}"
                        )
                    if not isinstance(payload, dict) or not (payload.get("success") or payload.get("code") == 0):
                        raise RuntimeError(str(payload.get("message") or payload.get("error") or "触发小红书发送验证码失败"))
                    logger.info(
                        "小红书第一条验证码已触发发送: env_id=%s request_id=%s elapsed_ms=%s",
                        getattr(env, "id", None),
                        request_id,
                        round((time.monotonic() - flow_started_at) * 1000),
                    )
                    received_request = await sms_wait_task
                finally:
                    await self._stop_background_task(sms_wait_task)
            else:
                raise RuntimeError(f"验证码请求创建后状态异常: {request_status or 'unknown'}")

            sms_received = True
            code = str(received_request.get("code") or "").strip()
            if not code:
                raise RuntimeError("验证码中台返回 received 但 code 为空")
            result = await self._submit_mcp_phone_code(api_base, phone_number, code)
            logger.info(
                "小红书第一条验证码已提交: env_id=%s request_id=%s requires_qr=%s elapsed_ms=%s",
                getattr(env, "id", None),
                request_id,
                bool(result.get("requires_qr")),
                round((time.monotonic() - flow_started_at) * 1000),
            )
            if not bool(result.get("is_logged_in")):
                if bool(result.get("requires_qr")):
                    await self._complete_xhs_qr_login_if_needed(api_base, phone_number, received_request, env=env)
                    status = await self._get_mcp_login_status(api_base)
                    if not bool(status.get("is_logged_in")):
                        raise RuntimeError("验证码和二维码确认已处理，但小红书登录态确认失败")
                else:
                    status = await self._get_mcp_login_status(api_base)
                    if not bool(status.get("is_logged_in")):
                        await self._complete_xhs_qr_login_if_needed(api_base, phone_number, received_request, env=env)
                        status = await self._get_mcp_login_status(api_base)
                        if not bool(status.get("is_logged_in")):
                            raise RuntimeError("验证码和二维码确认已处理，但小红书登录态确认失败")
            logger.info(
                "小红书自动登录完成: env_id=%s request_id=%s elapsed_ms=%s",
                getattr(env, "id", None),
                request_id,
                round((time.monotonic() - flow_started_at) * 1000),
            )
        except Exception:
            if request_id and not sms_received:
                await self._cancel_open_sms_code_request(request_id)
            raise

    async def _get_mcp_login_status(self, api_base: str) -> dict[str, Any]:
        async with httpx.AsyncClient(**self._httpx_client_kwargs(api_base, timeout=45.0)) as client:
            resp = await client.get(f"{api_base}/api/v1/login/status")
        if resp.status_code != 200:
            raise RuntimeError(f"检查小红书登录状态失败: HTTP {resp.status_code}")
        payload = resp.json() if resp.content else {}
        if not isinstance(payload, dict) or not (payload.get("success") or payload.get("code") == 0):
            raise RuntimeError(str(payload.get("message") or payload.get("error") or "检查小红书登录状态失败"))
        data = payload.get("data") or {}
        return data if isinstance(data, dict) else {}

    async def _submit_mcp_phone_code(self, api_base: str, phone_number: str, code: str) -> dict[str, Any]:
        async with httpx.AsyncClient(**self._httpx_client_kwargs(api_base, timeout=90.0)) as client:
            resp = await client.post(
                f"{api_base}/api/v1/login/phone/submit-code",
                json={"phone_number": phone_number, "code": code},
            )
        payload = resp.json() if resp.content else {}
        if resp.status_code != 200:
            raise RuntimeError(
                f"提交小红书验证码失败: HTTP {resp.status_code} "
                f"{self._mcp_error_detail(payload)}"
            )
        if not isinstance(payload, dict) or not (payload.get("success") or payload.get("code") == 0):
            raise RuntimeError(str(payload.get("message") or payload.get("error") or "提交小红书验证码失败"))
        data = payload.get("data") or {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _mcp_error_detail(payload: Any) -> str:
        if not isinstance(payload, dict):
            return str(payload)[:500]
        values = [payload.get("error"), payload.get("message"), payload.get("details"), payload.get("code")]
        return " | ".join(str(value).strip() for value in values if value not in (None, ""))[:500]

    @staticmethod
    def _compact_json(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    def _open_sms_api_headers(
        self,
        method: str,
        path: str,
        raw_body: str = "",
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        nonce = uuid.uuid4().hex
        body_hash = hashlib.sha256(raw_body.encode("utf-8")).hexdigest()
        canonical = "\n".join((method.upper(), path, timestamp, nonce, body_hash))
        signature = hmac.new(
            SMS_CODE_CENTER_OPEN_API_CLIENT_SECRET.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Client-Id": SMS_CODE_CENTER_OPEN_API_CLIENT_ID,
            "X-Timestamp": timestamp,
            "X-Nonce": nonce,
            "X-Signature": signature,
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def _create_open_sms_code_request(self, phone_number: str, client_request_id: str) -> dict[str, Any]:
        path = "/api/v1/open/sms-code-requests"
        raw_body = self._compact_json({"phoneNumber": phone_number, "platform": "小红书"})
        headers = self._open_sms_api_headers("POST", path, raw_body, idempotency_key=client_request_id)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{SMS_CODE_CENTER_BASE_URL}{path}", headers=headers, content=raw_body.encode("utf-8"))
        data = resp.json() if resp.content else {}
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"创建验证码请求失败: HTTP {resp.status_code} {str(data)[:300]}")
        sms_request = data.get("request") if isinstance(data, dict) else None
        if not isinstance(sms_request, dict):
            raise RuntimeError("验证码中台创建请求响应结构异常")
        return sms_request

    async def _get_open_sms_code_request(self, request_id: str) -> dict[str, Any]:
        path = f"/api/v1/open/sms-code-requests/{request_id}"
        headers = self._open_sms_api_headers("GET", path)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{SMS_CODE_CENTER_BASE_URL}{path}", headers=headers)
        data = resp.json() if resp.content else {}
        if resp.status_code != 200:
            raise RuntimeError(f"查询验证码请求失败: HTTP {resp.status_code} {str(data)[:300]}")
        sms_request = data.get("request") if isinstance(data, dict) else None
        if not isinstance(sms_request, dict):
            raise RuntimeError("验证码中台查询响应结构异常")
        return sms_request

    async def _wait_open_sms_code_request(
        self,
        request_id: str,
        *,
        initial_request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + SMS_CODE_CENTER_ACTIVATION_TTL_SECONDS
        request_context = dict(initial_request or {})
        admin_token = ""
        fallback_enabled = bool(str(request_context.get("deviceId") or "").strip())
        if fallback_enabled:
            try:
                admin_token = await self._get_phone_cloud_admin_token()
            except Exception as exc:
                fallback_enabled = False
                logger.warning(
                    "同设备双卡验证码监听未启用，继续使用精确卡槽订单: request_id=%s error=%s",
                    request_id,
                    exc,
                )
        ignored_non_xhs_exact_message = False
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise RuntimeError("等待小红书验证码超时")
            if fallback_enabled:
                exact_result, fallback_result = await asyncio.gather(
                    self._get_open_sms_code_request(request_id),
                    self._find_same_device_xhs_sms(request_context, admin_token),
                    return_exceptions=True,
                )
                if isinstance(exact_result, BaseException):
                    raise exact_result
                sms_request = exact_result
                if isinstance(fallback_result, BaseException):
                    logger.warning(
                        "查询同设备双卡短信失败，继续等待精确卡槽订单: request_id=%s error=%s",
                        request_id,
                        fallback_result,
                    )
                    fallback_result = None
            else:
                sms_request = await self._get_open_sms_code_request(request_id)
                fallback_result = None
            status = str(sms_request.get("status") or "").strip()
            if status == "received":
                if self._is_xhs_code_message(sms_request):
                    return sms_request
                if not ignored_non_xhs_exact_message:
                    logger.warning(
                        "精确卡槽订单先命中非小红书短信，改由同设备双卡监听继续等待: request_id=%s sender=%s",
                        request_id,
                        sms_request.get("sender"),
                    )
                    ignored_non_xhs_exact_message = True
            if isinstance(fallback_result, dict):
                await self._cancel_open_sms_code_request(request_id)
                logger.info(
                    "小红书验证码由同设备双卡监听命中: request_id=%s device_id=%s slot_index=%s subscription_id=%s",
                    request_id,
                    fallback_result.get("deviceId"),
                    fallback_result.get("slotIndex"),
                    fallback_result.get("subscriptionId"),
                )
                return fallback_result
            if status in {"expired", "cancelled", "failed"}:
                raise RuntimeError(f"验证码请求未收到验证码: {status}")
            if status not in {"waiting", "received"}:
                raise RuntimeError(f"验证码请求状态异常: {status or 'unknown'}")
            await asyncio.sleep(min(SMS_CODE_CENTER_OPEN_API_POLL_INTERVAL_SECONDS, remaining))

    async def _find_same_device_xhs_sms(
        self,
        request_context: dict[str, Any],
        admin_token: str,
    ) -> dict[str, Any] | None:
        """Find one unambiguous XHS code on either SIM after the order started."""
        device_id = str(request_context.get("deviceId") or "").strip()
        started_at = self._iso_time_seconds(request_context.get("startedAt") or request_context.get("createdAt"))
        expires_at = self._iso_time_seconds(request_context.get("expiresAt"))
        if not device_id or started_at is None:
            return None

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{SMS_CODE_CENTER_BASE_URL}/api/v1/sms-library",
                headers={"Authorization": f"Bearer {admin_token}"},
                params={"deviceId": device_id, "box": "inbox", "limit": 100},
            )
        data = resp.json() if resp.content else {}
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code} {str(data)[:200]}")
        messages = data.get("messages") if isinstance(data, dict) else None
        if not isinstance(messages, list):
            return None

        candidates: list[tuple[float, dict[str, Any]]] = []
        for message in messages:
            if not isinstance(message, dict) or str(message.get("deviceId") or "") != device_id:
                continue
            message_time = self._iso_time_seconds(
                message.get("messageAt") or message.get("receivedAt") or message.get("createdAt")
            )
            if message_time is None or message_time < started_at - 1.0:
                continue
            if expires_at is not None and message_time > expires_at:
                continue
            if not self._is_xhs_code_message(message):
                continue
            candidates.append((message_time, message))

        if not candidates:
            return None
        codes = {str(message.get("code") or "").strip() for _, message in candidates}
        if len(codes) != 1:
            # Two different XHS codes on the same dual-SIM phone cannot be
            # safely attributed without the slot mapping.
            return None

        _, message = max(candidates, key=lambda item: item[0])
        return {
            "requestId": str(request_context.get("requestId") or request_context.get("request_id") or ""),
            "status": "received",
            "code": str(message.get("code") or "").strip(),
            "sender": str(message.get("address") or message.get("sender") or ""),
            "body": str(message.get("body") or ""),
            "platform": "小红书",
            "deviceId": device_id,
            "slotIndex": message.get("slotIndex"),
            "subscriptionId": message.get("subscriptionId"),
            "matchedAt": message.get("messageAt") or message.get("receivedAt") or "",
            "matchSource": "same_device_all_sims",
        }

    @staticmethod
    def _iso_time_seconds(value: Any) -> float | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None

    @staticmethod
    def _is_xhs_code_message(message: dict[str, Any]) -> bool:
        code = str(message.get("code") or "").strip()
        if not re.fullmatch(r"\d{4,8}", code):
            return False
        body = str(message.get("body") or "")
        sender = str(message.get("address") or message.get("sender") or "")
        return "小红书" in f"{body} {sender}"

    @staticmethod
    async def _stop_background_task(task: asyncio.Task[Any] | None) -> None:
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _cancel_open_sms_code_request(self, request_id: str) -> None:
        path = f"/api/v1/open/sms-code-requests/{request_id}/cancel"
        raw_body = "{}"
        headers = self._open_sms_api_headers("POST", path, raw_body)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(f"{SMS_CODE_CENTER_BASE_URL}{path}", headers=headers, content=raw_body.encode("utf-8"))
            if resp.status_code not in (200, 201, 204, 404, 409):
                logger.warning("取消验证码请求失败: request_id=%s status=%s", request_id, resp.status_code)
        except Exception:
            logger.warning("取消验证码请求异常: request_id=%s", request_id, exc_info=True)

    async def _complete_xhs_qr_login_if_needed(
        self,
        api_base: str,
        phone_number: str,
        activation: dict[str, Any],
        *,
        env: XHSEnvironment | None = None,
    ) -> None:
        qr_started_at = time.monotonic()
        qr_payload = await self._get_mcp_login_qrcode(api_base)
        if bool(qr_payload.get("is_logged_in")):
            return

        qr_image = str(qr_payload.get("img") or "").strip()
        if not qr_image:
            raise RuntimeError("验证码已提交但未登录，且未获取到小红书二维码图片")
        if not qr_image.startswith("data:image/"):
            qr_image = f"data:image/png;base64,{qr_image}"

        xhs_account = str(getattr(env, "account_name", "") or "").strip()
        if not xhs_account:
            raise RuntimeError("验证码已提交但未登录，当前环境未配置小红书账号名，无法下发二维码扫码任务")
        xhs_account_id = str(getattr(env, "xhs_account_id", "") or "").strip()

        # The post-scan verification SMS is sent automatically as soon as the
        # phone confirms the QR login. Arm the receiver before dispatching the
        # phone task so a fast device cannot click before an activation exists.
        secondary_request_id = ""
        secondary_code_consumed = False
        secondary_sms_wait_task: asyncio.Task[dict[str, Any]] | None = None
        try:
            secondary_request = await self._create_open_sms_code_request(
                phone_number,
                f"xhs-login-secondary-{getattr(env, 'id', 'env')}-{uuid.uuid4().hex}",
            )
            secondary_request_id = str(
                secondary_request.get("requestId") or secondary_request.get("request_id") or ""
            ).strip()
            if not secondary_request_id:
                raise RuntimeError("二维码二次验证接码订单未返回 requestId")
            secondary_status = str(secondary_request.get("status") or "").strip()
            if secondary_status not in {"waiting", "received"}:
                raise RuntimeError(f"二维码二次验证接码订单状态异常: {secondary_status or 'unknown'}")

            logger.info(
                "小红书二维码二次验证已预挂接码订单: env_id=%s request_id=%s elapsed_ms=%s",
                getattr(env, "id", None),
                secondary_request_id,
                round((time.monotonic() - qr_started_at) * 1000),
            )

            # Start listening to both SIMs before the phone opens the QR image.
            secondary_sms_wait_task = asyncio.create_task(
                self._wait_open_sms_code_request(
                    secondary_request_id,
                    initial_request=secondary_request,
                )
            )
            await asyncio.sleep(0)

            xhs_app_slot = self._infer_xhs_app_slot(env)
            task = await self._create_phone_cloud_xhs_qr_task(
                xhs_account,
                qr_image,
                xhs_account_id=xhs_account_id or None,
                xhs_app_slot=xhs_app_slot,
            )
            task_id = str(task.get("taskId") or task.get("task_id") or "").strip()
            if not task_id:
                raise RuntimeError("二维码扫码任务创建成功但未返回 taskId")
            logger.info(
                "小红书二维码手机任务已创建: env_id=%s request_id=%s task_id=%s elapsed_ms=%s",
                getattr(env, "id", None),
                secondary_request_id,
                task_id,
                round((time.monotonic() - qr_started_at) * 1000),
            )
            qr_task = await self._wait_phone_cloud_xhs_qr_task(task_id, str(task.get("_adminToken") or ""))
            logger.info(
                "小红书二维码手机任务执行成功: env_id=%s request_id=%s task_id=%s elapsed_ms=%s result=%s",
                getattr(env, "id", None),
                secondary_request_id,
                task_id,
                round((time.monotonic() - qr_started_at) * 1000),
                self._summarize_phone_cloud_qr_task(qr_task),
            )
            secondary_code_consumed = await self._complete_xhs_post_qr_verification(
                api_base,
                phone_number,
                secondary_request_id,
                initial_request=secondary_request,
                sms_wait_task=secondary_sms_wait_task,
            )
            logger.info(
                "小红书二维码登录后置验证完成: env_id=%s request_id=%s task_id=%s secondary_code_used=%s elapsed_ms=%s",
                getattr(env, "id", None),
                secondary_request_id,
                task_id,
                secondary_code_consumed,
                round((time.monotonic() - qr_started_at) * 1000),
            )
        finally:
            await self._stop_background_task(secondary_sms_wait_task)
            if secondary_request_id and not secondary_code_consumed:
                await self._cancel_open_sms_code_request(secondary_request_id)

    async def _complete_xhs_post_qr_verification(
        self,
        api_base: str,
        phone_number: str,
        request_id: str,
        *,
        initial_request: dict[str, Any] | None = None,
        sms_wait_task: asyncio.Task[dict[str, Any]] | None = None,
    ) -> bool:
        """Finish either direct QR login or the automatically sent second SMS."""
        deadline = asyncio.get_running_loop().time() + SMS_CODE_CENTER_ACTIVATION_TTL_SECONDS
        sms_request = initial_request
        last_sms_status = ""
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise RuntimeError("扫码后等待登录成功或二次验证码超时")

            if sms_wait_task is not None and not sms_wait_task.done():
                try:
                    login_status = await self._get_mcp_login_status(api_base)
                except Exception as exc:
                    logger.warning(
                        "扫码后二次验证登录态查询失败，双卡监听继续运行: request_id=%s error=%s",
                        request_id,
                        exc,
                    )
                    login_status = {}
                if bool(login_status.get("is_logged_in")):
                    logger.info("小红书扫码后直接登录成功，无需二次验证码: request_id=%s", request_id)
                    return False
                await asyncio.sleep(min(SMS_CODE_CENTER_OPEN_API_POLL_INTERVAL_SECONDS, remaining))
                continue
            if sms_wait_task is not None:
                sms_request = sms_wait_task.result()

            current_status = str((sms_request or {}).get("status") or "").strip()
            if sms_request is None or current_status == "waiting":
                login_result, sms_request = await asyncio.gather(
                    self._get_mcp_login_status(api_base),
                    self._get_open_sms_code_request(request_id),
                    return_exceptions=True,
                )
                if isinstance(sms_request, BaseException):
                    raise sms_request
                if isinstance(login_result, BaseException):
                    logger.warning(
                        "扫码后二次验证登录态查询失败，继续等待短信: request_id=%s error=%s",
                        request_id,
                        login_result,
                    )
                    login_status = {}
                else:
                    login_status = login_result
            else:
                try:
                    login_status = await self._get_mcp_login_status(api_base)
                except Exception as exc:
                    logger.warning(
                        "扫码后二次验证登录态查询失败，继续等待短信: request_id=%s error=%s",
                        request_id,
                        exc,
                    )
                    login_status = {}

            request_status = str(sms_request.get("status") or "").strip()
            if request_status != last_sms_status:
                logger.info(
                    "小红书扫码后二次接码订单状态变化: request_id=%s status=%s",
                    request_id,
                    request_status or "unknown",
                )
                last_sms_status = request_status

            if bool(login_status.get("is_logged_in")):
                if request_status == "received":
                    logger.info("小红书扫码已登录且二次短信已到达，无需再次提交: request_id=%s", request_id)
                    return True
                logger.info("小红书扫码后直接登录成功，无需二次验证码: request_id=%s", request_id)
                return False

            if request_status == "received":
                code = str(sms_request.get("code") or "").strip()
                if not code:
                    raise RuntimeError("二维码二次验证接码订单已收到短信但验证码为空")
                result = await self._submit_mcp_phone_code(api_base, phone_number, code)
                logger.info("小红书扫码后二次验证码已提交: request_id=%s", request_id)
                if bool(result.get("is_logged_in")):
                    return True
                await self._wait_for_mcp_login(api_base, timeout_seconds=min(30.0, remaining))
                return True
            if request_status in {"expired", "cancelled", "failed"}:
                raise RuntimeError(f"扫码后二次验证码请求未收到验证码: {request_status}")
            if request_status != "waiting":
                raise RuntimeError(f"扫码后二次验证码请求状态异常: {request_status or 'unknown'}")

            sms_request = None
            await asyncio.sleep(min(SMS_CODE_CENTER_OPEN_API_POLL_INTERVAL_SECONDS, remaining))

    async def _wait_for_mcp_login(self, api_base: str, *, timeout_seconds: float) -> None:
        deadline = asyncio.get_running_loop().time() + max(1.0, timeout_seconds)
        while True:
            status = await self._get_mcp_login_status(api_base)
            if bool(status.get("is_logged_in")):
                return
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise RuntimeError("二次验证码已提交，但小红书登录态确认失败")
            await asyncio.sleep(min(1.0, remaining))

    async def _get_mcp_login_qrcode(self, api_base: str) -> dict[str, Any]:
        async with httpx.AsyncClient(**self._httpx_client_kwargs(api_base, timeout=45.0)) as client:
            resp = await client.get(f"{api_base}/api/v1/login/qrcode")
        if resp.status_code != 200:
            raise RuntimeError(f"获取小红书二维码失败: HTTP {resp.status_code}")
        payload = resp.json() if resp.content else {}
        if not isinstance(payload, dict) or not (payload.get("success") or payload.get("code") == 0):
            raise RuntimeError(str(payload.get("message") or payload.get("error") or "获取小红书二维码失败"))
        data = payload.get("data") or {}
        return data if isinstance(data, dict) else {}

    async def _create_phone_cloud_xhs_qr_task(
        self,
        xhs_account: str,
        qr_image_data_url: str,
        *,
        xhs_account_id: str | None = None,
        xhs_app_slot: str | None = None,
    ) -> dict[str, Any]:
        admin_token = await self._get_phone_cloud_admin_token()
        target = await self._resolve_phone_cloud_xhs_target(
            xhs_account,
            admin_token,
            xhs_account_id=xhs_account_id,
            xhs_app_slot=xhs_app_slot,
        )
        payload = {
            "deviceId": target["deviceId"],
            "xhsAppSlot": target["xhsAppSlot"],
            "qrImageDataUrl": qr_image_data_url,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{SMS_CODE_CENTER_BASE_URL}/api/v1/xhs/qr-scan-tasks",
                headers={"Authorization": f"Bearer {admin_token}"},
                json=payload,
            )
        data = resp.json() if resp.content else {}
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"创建小红书二维码扫码任务失败: HTTP {resp.status_code} {str(data)[:300]}")
        task = data.get("task") if isinstance(data, dict) else None
        if not isinstance(task, dict):
            raise RuntimeError("二维码扫码任务响应结构异常")
        # The token is used only by this in-process polling call and is never
        # persisted with the task or exposed to API callers.
        task["_adminToken"] = admin_token
        return task

    @staticmethod
    def _infer_xhs_app_slot(env: XHSEnvironment | None) -> str | None:
        if env is None:
            return None
        candidates = " ".join(
            str(getattr(env, key, "") or "")
            for key in ("notes", "labels", "group_name", "account_name")
        ).lower()
        if any(marker in candidates for marker in ("app2", "app 2", "分身", "双开", "Ⅱ", "ii·", "ii ")):
            return "app2"
        if any(marker in candidates for marker in ("app1", "app 1", "主应用", "普通小红书")):
            return "app1"
        return None

    async def _wait_phone_cloud_xhs_qr_task(self, task_id: str, admin_token: str) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + SMS_CODE_CENTER_ACTIVATION_TTL_SECONDS
        started_at = time.monotonic()
        last_status = ""
        async with httpx.AsyncClient(timeout=20.0) as client:
            while True:
                if asyncio.get_running_loop().time() >= deadline:
                    raise RuntimeError("等待小红书二维码扫码确认超时")
                resp = await client.get(
                    f"{SMS_CODE_CENTER_BASE_URL}/api/v1/xhs/qr-scan-tasks/{task_id}",
                    headers={"Authorization": f"Bearer {admin_token}"},
                )
                data = resp.json() if resp.content else {}
                if resp.status_code != 200:
                    raise RuntimeError(f"查询二维码扫码任务失败: HTTP {resp.status_code} {str(data)[:300]}")
                task = data.get("task") if isinstance(data, dict) else None
                if not isinstance(task, dict):
                    raise RuntimeError("二维码扫码任务查询响应结构异常")
                status = str(task.get("status") or "").strip()
                if status != last_status:
                    logger.info(
                        "小红书二维码手机任务状态变化: task_id=%s status=%s elapsed_ms=%s",
                        task_id,
                        status or "unknown",
                        round((time.monotonic() - started_at) * 1000),
                    )
                    last_status = status
                if status == "succeeded":
                    return task
                if status in {"failed", "cancelled", "expired"}:
                    result = task.get("result") if isinstance(task.get("result"), dict) else {}
                    message = str(result.get("message") or result.get("error") or "").strip()
                    raise RuntimeError(f"小红书二维码扫码任务失败: {message or status}")
                await asyncio.sleep(2)

    @staticmethod
    def _summarize_phone_cloud_qr_task(task: dict[str, Any]) -> str:
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        runner = result.get("runner") if isinstance(result.get("runner"), dict) else {}
        summary = task.get("summary") if isinstance(task.get("summary"), dict) else {}
        values = [
            str(result.get("action") or "").strip(),
            str(result.get("message") or "").strip(),
            str(runner.get("action") or "").strip(),
            str(summary.get("latestEvent") or "").strip(),
        ]
        return " | ".join(value for value in values if value)[:500] or "succeeded"

    async def _get_phone_cloud_admin_token(self) -> str:
        if SMS_CODE_CENTER_ADMIN_API_TOKEN:
            return SMS_CODE_CENTER_ADMIN_API_TOKEN
        if not SMS_CODE_CENTER_ADMIN_USERNAME or not SMS_CODE_CENTER_ADMIN_PASSWORD:
            raise RuntimeError(
                "未配置手机云控管理员鉴权：请设置 SMS_CODE_CENTER_ADMIN_API_TOKEN，"
                "或设置 SMS_CODE_CENTER_ADMIN_USERNAME / SMS_CODE_CENTER_ADMIN_PASSWORD"
            )
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{SMS_CODE_CENTER_BASE_URL}/api/v1/auth/login",
                json={"username": SMS_CODE_CENTER_ADMIN_USERNAME, "password": SMS_CODE_CENTER_ADMIN_PASSWORD},
            )
        data = resp.json() if resp.content else {}
        session = data.get("session") if isinstance(data, dict) else None
        token = str(session.get("token") or "").strip() if isinstance(session, dict) else ""
        if resp.status_code != 200 or not token:
            raise RuntimeError(f"获取手机云控管理员会话失败: HTTP {resp.status_code} {str(data)[:300]}")
        return token

    async def _resolve_phone_cloud_xhs_target(
        self,
        xhs_account: str,
        admin_token: str,
        *,
        xhs_account_id: str | None = None,
        xhs_app_slot: str | None = None,
    ) -> dict[str, str]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{SMS_CODE_CENTER_BASE_URL}/api/v1/devices",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        data = resp.json() if resp.content else {}
        if resp.status_code != 200:
            raise RuntimeError(f"读取手机云控设备配置失败: HTTP {resp.status_code} {str(data)[:300]}")
        devices = data.get("devices") if isinstance(data, dict) else None
        if not isinstance(devices, list):
            raise RuntimeError("手机云控设备列表响应结构异常")

        normalized_account_id = str(xhs_account_id or "").strip()
        id_candidates: list[dict[str, str]] = []
        name_candidates: list[dict[str, str]] = []
        name_candidates_without_id: list[dict[str, str]] = []
        for device in devices:
            if not isinstance(device, dict):
                continue
            current_id = str(device.get("deviceId") or "").strip()
            if not current_id:
                continue
            accounts = device.get("xhsAccounts") if isinstance(device.get("xhsAccounts"), list) else []
            for account in accounts:
                if not isinstance(account, dict) or account.get("enabled") is False:
                    continue
                slot = str(account.get("appSlot") or "").strip()
                account_name = str(account.get("accountName") or "").strip()
                account_id = str(
                    account.get("xhsAccountId")
                    or account.get("accountId")
                    or account.get("xhs_account_id")
                    or ""
                ).strip()
                if xhs_app_slot in {"app1", "app2"} and slot != xhs_app_slot:
                    continue
                candidate = {"deviceId": current_id, "xhsAppSlot": slot}
                if normalized_account_id and account_id == normalized_account_id:
                    id_candidates.append(candidate)
                if account_name == xhs_account:
                    name_candidates.append(candidate)
                    if not account_id:
                        name_candidates_without_id.append(candidate)

        if normalized_account_id and id_candidates:
            candidates = id_candidates
            match_field = "小红书ID"
            match_value = normalized_account_id
        elif normalized_account_id:
            # Older phone-cloud records do not expose account IDs yet. Allow an
            # exact-name fallback only for those legacy records; never fall back
            # to a record carrying a different explicit ID.
            candidates = name_candidates_without_id
            match_field = "小红书账号名"
            match_value = xhs_account
        else:
            candidates = name_candidates
            match_field = "小红书账号名"
            match_value = xhs_account

        if not candidates:
            raise RuntimeError(
                f"所有扫码设备中均未配置{match_field}“{match_value}”对应的应用槽位，"
                "请先在手机云控配置 app1/app2 账号映射"
            )
        if len(candidates) > 1:
            raise RuntimeError(f"{match_field}“{match_value}”对应多个应用槽位，无法安全选择扫码手机")
        return candidates[0]

    @staticmethod
    def _normalize_cn_phone_number(value: str) -> str:
        digits = re.sub(r"\D+", "", str(value or ""))
        if len(digits) == 13 and digits.startswith("86"):
            return digits[2:]
        return digits

    def _extract_sms_activation_device_id(self, activation: dict[str, Any]) -> str:
        for key in ("deviceId", "device_id"):
            value = str(activation.get(key) or "").strip()
            if value:
                return value
        device = activation.get("device")
        if isinstance(device, dict):
            for key in ("deviceId", "device_id", "id"):
                value = str(device.get(key) or "").strip()
                if value:
                    return value
        return ""

    @staticmethod
    def _find_sms_command(payload: dict[str, Any] | None, command_id: str) -> dict[str, Any] | None:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return None
        target_id = str(command_id or "").strip()
        for item in items:
            if isinstance(item, dict) and str(item.get("command_id") or item.get("commandId") or "").strip() == target_id:
                return item
        return None

    def _parse_creator_stats_excel(self, content: bytes) -> list[dict[str, Any]]:
        try:
            import openpyxl
        except ImportError as exc:
            raise RuntimeError("缺少 openpyxl，无法解析创作中心导出文件") from exc

        try:
            workbook = openpyxl.load_workbook(filename=io.BytesIO(content), data_only=True, read_only=True)
        except Exception as exc:
            raise RuntimeError(f"创作中心导出文件解析失败: {exc}") from exc
        sheet = workbook.active
        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return []

        header_index = 0
        for idx, row in enumerate(rows[:5]):
            normalized_cells = [self._normalize_note_text(cell) or "" for cell in row]
            if any(cell in {"笔记标题", "标题"} for cell in normalized_cells):
                header_index = idx
                break
        headers = [self._normalize_note_text(cell) or "" for cell in rows[header_index]]
        header_map = {name: index for index, name in enumerate(headers) if name}

        def pick(row: tuple[Any, ...], *names: str) -> Any:
            for name in names:
                idx = header_map.get(name)
                if idx is not None and idx < len(row):
                    return row[idx]
            return None

        normalized: list[dict[str, Any]] = []
        for source_row_index, raw_row in enumerate(rows[header_index + 1:], start=header_index + 2):
            title = self._normalize_note_text(pick(raw_row, "笔记标题", "标题")) or ""
            if not title:
                continue
            published_at_value = pick(raw_row, "首次发布时间", "发布时间")
            note_id_value = self._normalize_note_text(
                pick(raw_row, "笔记ID", "笔记 ID", "笔记id", "笔记Id", "笔记链接", "笔记地址")
            ) or ""
            note_id_match = re.search(r"/explore/([a-zA-Z0-9_-]+)", note_id_value)
            note_id = note_id_match.group(1) if note_id_match else note_id_value
            metrics = {
                "exposure_count": self._safe_optional_int(pick(raw_row, "曝光", "曝光量")),
                "view_count": self._safe_optional_int(pick(raw_row, "观看", "观看量", "浏览", "浏览量")),
                "cover_click_rate": self._safe_optional_rate(pick(raw_row, "封面点击率")),
                "like_count": self._safe_optional_int(pick(raw_row, "点赞", "点赞量")),
                "comment_count": self._safe_optional_int(pick(raw_row, "评论", "评论量")),
                "collect_count": self._safe_optional_int(pick(raw_row, "收藏", "收藏量")),
                "share_count": self._safe_optional_int(pick(raw_row, "分享", "转发", "分享量", "转发量")),
            }
            normalized.append(
                {
                    "source_row_index": source_row_index,
                    "note_id": note_id,
                    "title": title,
                    "published_at_raw": self._normalize_note_text(published_at_value) or "",
                    "published_at": self._parse_creator_stats_published_at(published_at_value),
                    **metrics,
                    "raw_payload": {
                        "note_id": note_id,
                        "title": title,
                        "published_at_raw": self._normalize_note_text(published_at_value) or "",
                        **metrics,
                    },
                }
            )
        return normalized

    @staticmethod
    def _parse_creator_stats_published_at(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day)

        raw = str(value or "").strip()
        if not raw:
            return None
        raw = raw.replace("年", "-").replace("月", "-").replace("日", " ")
        raw = re.sub(r"\s+", " ", raw).strip()
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d",
            "%Y/%m/%d",
        ):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _safe_rate(value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            numeric = float(value)
            return round(numeric * 100.0, 4) if 0 < numeric <= 1 else round(numeric, 4)
        raw = str(value).strip().replace(",", "")
        if not raw:
            return 0.0
        is_percent = raw.endswith("%")
        if is_percent:
            raw = raw[:-1].strip()
        try:
            numeric = float(raw)
        except ValueError:
            return 0.0
        if not is_percent and 0 < numeric <= 1:
            numeric *= 100.0
        return round(numeric, 4)

    @classmethod
    def _safe_optional_int(cls, value: Any) -> int | None:
        if value is None or str(value).strip() in {"", "-", "--"}:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(round(float(value)))
        raw = str(value).replace(",", "").strip()
        try:
            return int(round(float(raw)))
        except ValueError:
            return None

    @classmethod
    def _safe_optional_rate(cls, value: Any) -> float | None:
        if value is None or str(value).strip() in {"", "-", "--"}:
            return None
        raw = str(value).strip().replace(",", "")
        is_percent = raw.endswith("%")
        if is_percent:
            raw = raw[:-1].strip()
        try:
            numeric = float(raw)
        except ValueError:
            return None
        if not is_percent and 0 < numeric <= 1:
            numeric *= 100.0
        return round(numeric, 4)

    @staticmethod
    def _match_creator_note_stats(note: XHSAccountNote, stats_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        target_feed_id = str(note.feed_id or "").strip()
        if target_feed_id:
            for row in stats_rows:
                if str(row.get("note_id") or "").strip() == target_feed_id:
                    return row

        target_title = (XHSService._normalize_note_text(note.title) or "").strip()
        if not target_title:
            return None
        title_matches = [
            row for row in stats_rows
            if (XHSService._normalize_note_text(row.get("title")) or "").strip() == target_title
        ]
        if len(title_matches) == 1:
            return title_matches[0]
        if len(title_matches) > 1 and note.published_at:
            note_published_at = note.published_at.replace(tzinfo=None)
            best_row: dict[str, Any] | None = None
            best_delta: float | None = None
            for row in title_matches:
                row_published_at = row.get("published_at")
                if not isinstance(row_published_at, datetime):
                    continue
                row_published_at = row_published_at.replace(tzinfo=None)
                # 创作者中心导出通常按北京时间展示，库里 published_at 是 UTC naive。
                deltas = [
                    abs((row_published_at - note_published_at).total_seconds()),
                    abs(((row_published_at - timedelta(hours=8)) - note_published_at).total_seconds()),
                    abs(((row_published_at + timedelta(hours=8)) - note_published_at).total_seconds()),
                ]
                row_delta = min(deltas)
                if best_delta is None or row_delta < best_delta:
                    best_delta = row_delta
                    best_row = row
            if best_row is not None and best_delta is not None and best_delta <= 180:
                return best_row
        return None

    async def _fetch_account_note_detail_metrics(
        self,
        feed_id: str,
        xsec_token: str | None,
        *,
        title: str | None = None,
        api_base: str | None = None,
        persona: SyncSessionPersona | None = None,
    ) -> dict[str, Any] | None:
        token = str(xsec_token or "").strip()
        if not feed_id or not token:
            return None

        resolved_api_base = self._resolve_active_mcp_api(api_base)
        max_attempts = 4
        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(**self._httpx_client_kwargs(resolved_api_base, timeout=30.0)) as client:
                    resp = await client.post(
                        f"{resolved_api_base}/api/v1/feeds/detail",
                        json={
                            "feed_id": feed_id,
                            "xsec_token": token,
                            "xsec_source": "pc_user",
                            "load_all_comments": False,
                        },
                    )
                if resp.status_code != 200:
                    body_preview = (resp.text or "").strip().replace("\n", " ")
                    if self._is_temporary_unavailable_message(body_preview) and attempt < max_attempts:
                        await self._sleep_sync_retry_backoff(persona)
                        continue
                    logger.warning("账号帖子详情拉取失败: feed_id=%s status=%s body=%s", feed_id, resp.status_code, body_preview[:300])
                    return None

                data = resp.json() if resp.content else {}
                if not isinstance(data, dict) or not (data.get("success") or data.get("code") == 0):
                    err_msg = str(data.get("message") or data.get("error") or data.get("msg") or "")
                    if self._is_temporary_unavailable_message(err_msg) and attempt < max_attempts:
                        await self._sleep_sync_retry_backoff(persona)
                        continue
                    logger.warning("账号帖子详情返回失败: feed_id=%s message=%s", feed_id, err_msg)
                    return None

                payload = data.get("data", {}) or {}
                if not isinstance(payload, dict):
                    logger.warning("账号帖子详情返回结构异常: feed_id=%s", feed_id)
                    return None
                nested_data = payload.get("data")
                if isinstance(nested_data, dict):
                    payload = {
                        **payload,
                        **nested_data,
                    }
                detail_data = self._extract_account_note_detail_data(payload, title=title)
                has_structured_detail = any(
                    detail_data.get(key)
                    for key in ("content", "cover_image_url", "image_urls", "published_at")
                )
                has_metric_detail = any(
                    isinstance(detail_data.get(key), int)
                    for key in ("liked_count", "comment_count", "collected_count", "share_count")
                )
                if has_structured_detail or has_metric_detail:
                    return detail_data
                logger.warning("账号帖子详情未返回可用详情: feed_id=%s", feed_id)
                return None
            except Exception as exc:
                if attempt < max_attempts:
                    await self._sleep_sync_retry_backoff(persona)
                    continue
                logger.warning("账号帖子详情同步异常: feed_id=%s error=%s", feed_id, exc)
                return None

    async def _mark_stale_publishing_posts_failed(self, minutes: int = 10) -> None:
        """兜底：将长时间卡在 publishing 的任务自动置为 failed。"""
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        stmt = (
            select(XHSPost)
            .where(
                XHSPost.status == "publishing",
                XHSPost.updated_at.is_not(None),
                XHSPost.updated_at < cutoff,
            )
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        if not rows:
            return
        for post in rows:
            post.status = "failed"
            post.updated_at = utc_now_naive()
        await self.db.commit()
        logger.warning("自动回收卡住发布任务: %s 条", len(rows))

    async def _save_post_to_copywriting(self, post: XHSPost) -> None:
        """发布成功后将帖子标题和内容写入文案库。"""
        title = (post.title or "").strip()
        content = (post.content or "").strip()
        if not title or not content:
            return
        try:
            service = CopywritingService(self.db)
            await service.create(title=title, content=content, user_id=post.user_id)
        except Exception:
            logger.exception("发布成功后写入文案库失败: post_id=%s", post.id)

    # ==================== 云登环境管理 ====================

    async def sync_environments_from_yundeng(self) -> int:
        """从云登 API 同步环境列表到本地数据库"""
        if self._should_delegate_browser_ops():
            return await self.trigger_worker_sync_environments()
        self._require_local_browser_ops("同步云登环境")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # 获取所有 shopId
                resp = await client.post(
                    f"{YUNDENG_API}/api/v2/userapi/user/shopseriallist",
                    json={"groupId": "", "accountName": ""},
                )
                data = resp.json()
                if data.get("code") != 0:
                    logger.error(f"获取云登环境列表失败: {data}")
                    return 0

                shop_ids = [item["shopId"] for item in data["data"]["list"] if item.get("shopId")]
                if not shop_ids:
                    return 0

                # 云登接口限制：shopdetaillist 一次最多查询 10 个
                detail_items: list[dict] = []
                batch_size = 10
                for i in range(0, len(shop_ids), batch_size):
                    batch_ids = shop_ids[i:i + batch_size]
                    resp = await client.post(
                        f"{YUNDENG_API}/api/v2/userapi/user/shopdetaillist",
                        json={"browserid": batch_ids},
                    )
                    batch_data = resp.json()
                    if batch_data.get("code") != 0:
                        logger.error(
                            "获取云登环境详情失败(批次 %s-%s): %s",
                            i + 1,
                            i + len(batch_ids),
                            batch_data,
                        )
                        continue
                    detail_items.extend(batch_data.get("data", {}).get("browser") or [])

                if not detail_items:
                    logger.error("获取云登环境详情失败: 所有批次都为空")
                    return 0

                remote_shop_ids = {
                    str(item.get("browserid") or item.get("serial") or "").strip()
                    for item in detail_items
                    if str(item.get("browserid") or item.get("serial") or "").strip()
                }
                if remote_shop_ids:
                    stale_result = await self.db.execute(
                        select(XHSEnvironment).where(XHSEnvironment.status == "active")
                    )
                    stale_envs = list(stale_result.scalars().all())
                    for stale_env in stale_envs:
                        if stale_env.shop_id not in remote_shop_ids:
                            stale_env.status = "inactive"

                count = 0
                for item in detail_items:
                    shop_id = item.get("browserid") or item.get("serial")
                    if not shop_id:
                        continue

                    proxy = item.get("proxy") or {}
                    proxy_info = proxy.get("name", "") or proxy.get("inlie", "")
                    if proxy_info and proxy.get("PublicIP"):
                        proxy_info += f" ({proxy['PublicIP']})"

                    accounts = item.get("accounts") or {}
                    group_name = accounts.get("groupName", "")

                    labels = item.get("label") or []
                    label_str = ", ".join(l.get("name", "") for l in labels if l.get("name"))

                    # 查询是否已存在
                    result = await self.db.execute(
                        select(XHSEnvironment).where(XHSEnvironment.shop_id == shop_id)
                    )
                    env = result.scalar_one_or_none()

                    if env:
                        env.account_name = item.get("name", "")
                        env.notes = item.get("notes", "") or ""
                        env.proxy_info = proxy_info or ""
                        env.group_name = group_name or ""
                        env.labels = label_str
                        env.status = "active"
                    else:
                        env = XHSEnvironment(
                            shop_id=shop_id,
                            account_name=item.get("name", ""),
                            notes=item.get("notes", "") or "",
                            proxy_info=proxy_info or "",
                            group_name=group_name or "",
                            labels=label_str,
                            status="active",
                        )
                        self.db.add(env)
                    count += 1

                await self.db.commit()
                logger.info(f"同步云登环境完成: {count} 条")
                return count

        except Exception as e:
            logger.error(f"同步云登环境失败: {e}")
            return 0

    async def list_environments(self, user: User, include_inactive: bool = False) -> list[XHSEnvironment]:
        """获取用户可用的环境列表"""
        status_condition = True if include_inactive else XHSEnvironment.status == "active"
        if has_role(user, ROLE_ADMIN):
            result = await self.db.execute(
                select(XHSEnvironment)
                .where(status_condition)
                .order_by(XHSEnvironment.account_name)
            )
            return list(result.scalars().all())

        viewer_roles = set(get_user_roles(user))
        visible_departments: set[str] = set()
        if ROLE_XHS_LEAD in viewer_roles:
            visible_departments.add("xhs")
        if ROLE_BRAND_LEAD in viewer_roles:
            visible_departments.add("brand")
        if visible_departments:
            result = await self.db.execute(
                select(XHSEnvironment)
                .where(and_(status_condition, XHSEnvironment.department.in_(visible_departments)))
                .order_by(XHSEnvironment.account_name)
            )
            return list(result.scalars().all())

        # 普通用户：只看分配给自己的
        result = await self.db.execute(
            select(XHSEnvironment)
            .join(UserXHSEnvironment)
            .where(
                and_(
                    UserXHSEnvironment.user_id == user.id,
                    status_condition,
                )
            )
            .order_by(XHSEnvironment.account_name)
        )
        return list(result.scalars().all())

    async def get_environment(self, env_id: int) -> Optional[XHSEnvironment]:
        result = await self.db.execute(
            select(XHSEnvironment).where(XHSEnvironment.id == env_id)
        )
        return result.scalar_one_or_none()

    async def get_environment_by_shop_id(self, shop_id: str) -> Optional[XHSEnvironment]:
        result = await self.db.execute(
            select(XHSEnvironment).where(XHSEnvironment.shop_id == shop_id)
        )
        return result.scalar_one_or_none()

    # ==================== 用户-环境关联 ====================

    async def assign_environment(self, user_id: int, env_id: int) -> bool:
        """设置运营归属：一个用户可负责多个环境，一个环境只保留一个负责人。"""
        result = await self.db.execute(
            select(UserXHSEnvironment.id).where(
                and_(
                    UserXHSEnvironment.user_id == user_id,
                    UserXHSEnvironment.environment_id == env_id,
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return True

        await self.db.execute(
            delete(UserXHSEnvironment).where(
                UserXHSEnvironment.environment_id == env_id
            )
        )
        mapping = UserXHSEnvironment(user_id=user_id, environment_id=env_id)
        self.db.add(mapping)
        await self.db.commit()
        return True

    async def remove_environment(self, user_id: int, env_id: int) -> bool:
        await self.db.execute(
            delete(UserXHSEnvironment).where(
                and_(
                    UserXHSEnvironment.user_id == user_id,
                    UserXHSEnvironment.environment_id == env_id,
                )
            )
        )
        await self.db.commit()
        return True

    # ==================== 发布流程 ====================

    async def publish(
        self,
        user: User,
        env: XHSEnvironment,
        title: str,
        content: str,
        image_paths: list[str],
        tags: list[str] | None = None,
        ai_origin_type: str = "manual",
        is_original: bool = False,
        visibility: str = "公开可见",
        scheduled_at: datetime | None = None,
    ) -> XHSPost:
        """发布入口：支持立即发布与定时发布。"""
        normalized_scheduled_at = self._normalize_to_utc_naive(scheduled_at)
        if normalized_scheduled_at is not None:
            if normalized_scheduled_at <= utc_now_naive() + timedelta(minutes=1):
                raise ValueError("定时发布时间必须晚于当前时间（至少 1 分钟）")
        if normalized_scheduled_at is not None:
            return await self.schedule_publish(
                user=user,
                env=env,
                title=title,
                content=content,
                image_paths=image_paths,
                tags=tags,
                ai_origin_type=ai_origin_type,
                is_original=is_original,
                visibility=visibility,
                scheduled_at=normalized_scheduled_at,
            )
        return await self.publish_now(
            user=user,
            env=env,
            title=title,
            content=content,
            image_paths=image_paths,
            tags=tags,
            ai_origin_type=ai_origin_type,
            is_original=is_original,
            visibility=visibility,
        )

    async def publish_now(
        self,
        user: User,
        env: XHSEnvironment,
        title: str,
        content: str,
        image_paths: list[str],
        tags: list[str] | None = None,
        ai_origin_type: str = "manual",
        is_original: bool = False,
        visibility: str = "公开可见",
        background: bool = True,
    ) -> XHSPost:
        """立即发布：创建记录后转入后台执行。"""
        post = XHSPost(
            user_id=user.id,
            environment_id=env.id,
            title=title,
            content=content,
            image_urls=image_paths or [],
            tags=tags or [],
            ai_origin_type=ai_origin_type,
            status="publishing",
        )
        self.db.add(post)
        await self.db.commit()
        await self.db.refresh(post)
        if self._should_delegate_browser_ops():
            await self.trigger_worker_publish(post.id)
            return post
        if not background:
            return await self._run_publish_with_guards(
                post=post,
                env=env,
                title=title,
                content=content,
                image_paths=image_paths,
                tags=tags,
                is_original=is_original,
                visibility=visibility,
                recover_identifiers_async=False,
            )
        self._schedule_background_publish(
            post_id=post.id,
            env_id=env.id,
            title=title,
            content=content,
            image_paths=image_paths,
            tags=tags or [],
            ai_origin_type=ai_origin_type,
            is_original=is_original,
            visibility=visibility,
        )
        return post

    async def schedule_publish(
        self,
        user: User,
        env: XHSEnvironment,
        title: str,
        content: str,
        image_paths: list[str],
        tags: list[str] | None = None,
        ai_origin_type: str = "manual",
        is_original: bool = False,
        visibility: str = "公开可见",
        scheduled_at: datetime | None = None,
    ) -> XHSPost:
        """定时发布：只落库，等待后台任务执行。"""
        post = XHSPost(
            user_id=user.id,
            environment_id=env.id,
            title=title,
            content=content,
            image_urls=image_paths or [],
            tags=tags or [],
            ai_origin_type=ai_origin_type,
            status="scheduled",
            scheduled_at=scheduled_at,
        )
        self.db.add(post)
        await self.db.commit()
        await self.db.refresh(post)
        return post

    async def _execute_publish(
        self,
        post: XHSPost,
        env: XHSEnvironment,
        title: str,
        content: str,
        image_paths: list[str],
        tags: list[str] | None = None,
        is_original: bool = False,
        visibility: str = "公开可见",
        recover_identifiers_async: bool = True,
    ) -> XHSPost:
        """完整发布流程：连接已在线云登 → 启动 xhs-mcp → 发布 → 获取 feed_id → 写库"""
        self._require_local_browser_ops("小红书发布")
        mcp_pid = None
        use_external_mcp = bool(XHS_MCP_EXTERNAL_API)
        mcp_port = None if use_external_mcp else await self._allocate_free_port()
        mcp_api = XHS_MCP_EXTERNAL_API if use_external_mcp else f"http://localhost:{mcp_port}"
        previous_mcp_api = getattr(self, "_active_mcp_api", None)
        try:
            self._active_mcp_api = mcp_api
            resolved_image_paths = await self._resolve_publish_image_paths(image_paths)
            # 1. 获取云登 WebSocket URL
            ws_url = await self._acquire_ready_browser_ws(env.shop_id)
            if not ws_url:
                post.status = "failed"
                await self.db.commit()
                raise RuntimeError(f"无法获取环境 {env.shop_id} 的浏览器连接")

            # 2. 连接发布服务
            # 优先使用外部 mcp 服务（Windows 常见场景），否则在容器内拉起临时实例。
            if use_external_mcp:
                if not await self._check_mcp_running(mcp_api):
                    raise RuntimeError("外部小红书发布服务不可用，请先启动 XHS MCP 服务")
            else:
                # 为本次发布单独启动 xhs-mcp 实例，避免不同账号互相抢占同一个端口
                mcp_pid = await self._start_mcp(ws_url, mcp_port or 0)
                if not mcp_pid:
                    raise RuntimeError("启动小红书发布服务失败，请稍后重试")
                await self._wait_mcp_ready()

            try:
                publish_content, publish_tags = self._prepare_publish_content_and_tags(
                    content=content,
                    tags=tags or [],
                )
                # 3. 发布内容
                feed_id, xsec_token, publish_ok = await self._call_publish_api(
                    title, publish_content, resolved_image_paths, publish_tags, is_original, visibility
                )

                # 4. 更新帖子记录
                post.feed_id = feed_id
                post.xsec_token = xsec_token
                post.post_url = self._build_post_url(feed_id, xsec_token)
                post.tags = publish_tags
                post.status = "success" if publish_ok else "failed"
                if publish_ok:
                    post.published_at = utc_now_naive()
                    post.scheduled_at = None
                await self.db.commit()
                await self.db.refresh(post)
                if publish_ok:
                    await self._save_post_to_copywriting(post)
                if publish_ok and (not post.xsec_token):
                    if recover_identifiers_async:
                        self._schedule_identifier_recovery(
                            post_id=post.id,
                            env_id=env.id,
                            expected_title=title,
                            expected_content=publish_content,
                        )
                    else:
                        recovered_feed_id, recovered_xsec_token = await self._recover_published_identifiers(
                            expected_title=title,
                            expected_content=publish_content,
                            current_feed_id=post.feed_id,
                            current_xsec_token=post.xsec_token,
                            mcp_api=mcp_api,
                        )
                        if recovered_feed_id:
                            post.feed_id = recovered_feed_id
                        if recovered_xsec_token:
                            post.xsec_token = recovered_xsec_token
                        post.post_url = self._build_post_url(post.feed_id, post.xsec_token)
                        await self.db.commit()
                        await self.db.refresh(post)

            finally:
                # 5. 关闭我们启动的临时 mcp（外部服务模式不关闭）
                if mcp_pid is not None:
                    await self._stop_mcp(mcp_pid)

        except Exception as e:
            logger.error(f"发布失败: {e}")
            post.status = "failed"
            await self.db.commit()
            raise
        finally:
            self._active_mcp_api = previous_mcp_api

        return post

    @classmethod
    async def _get_env_publish_lock(cls, env_id: int) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        loop_key = id(loop)
        with cls._env_publish_locks_guard:
            loop_locks = cls._env_publish_locks_by_loop.get(loop_key)
            if loop_locks is None:
                loop_locks = {}
                cls._env_publish_locks_by_loop[loop_key] = loop_locks
            lock = loop_locks.get(env_id)
            if lock is None:
                lock = asyncio.Lock()
                loop_locks[env_id] = lock
        return lock

    async def _run_publish_with_guards(
        self,
        post: XHSPost,
        env: XHSEnvironment,
        title: str,
        content: str,
        image_paths: list[str],
        tags: list[str] | None = None,
        is_original: bool = False,
        visibility: str = "公开可见",
        recover_identifiers_async: bool = True,
    ) -> XHSPost:
        """统一发布入口：先走全局队列，再做同环境互斥。"""

        async def _guarded_publish() -> XHSPost:
            env_lock = await self._get_env_publish_lock(env.id)
            async with env_lock:
                logger.info(
                    "小红书发布开始: post_id=%s, env_id=%s, user_id=%s",
                    post.id,
                    env.id,
                    post.user_id,
                )
                return await self._execute_publish(
                    post=post,
                    env=env,
                    title=title,
                    content=content,
                    image_paths=image_paths,
                    tags=tags,
                    is_original=is_original,
                    visibility=visibility,
                    recover_identifiers_async=recover_identifiers_async,
                )

        return await xhs_publish_queue.enqueue(_guarded_publish())

    def _schedule_background_publish(
        self,
        post_id: int,
        env_id: int,
        title: str,
        content: str,
        image_paths: list[str],
        tags: list[str],
        ai_origin_type: str,
        is_original: bool,
        visibility: str,
    ) -> None:
        async def _run() -> None:
            try:
                if self._should_delegate_browser_ops():
                    await self.trigger_worker_publish(post_id)
                    return
                async with async_session() as db:
                    service = XHSService(db)
                    post_result = await db.execute(select(XHSPost).where(XHSPost.id == post_id))
                    post = post_result.scalar_one_or_none()
                    if not post:
                        logger.warning("后台发布终止: post_id=%s 不存在", post_id)
                        return

                    env = await service.get_environment(env_id)
                    if not env:
                        post.status = "failed"
                        await db.commit()
                        logger.warning("后台发布终止: post_id=%s 对应环境不存在", post_id)
                        return

                    await service._run_publish_with_guards(
                        post=post,
                        env=env,
                        title=title,
                        content=content,
                        image_paths=image_paths,
                        tags=tags,
                        is_original=is_original,
                        visibility=visibility,
                    )
            except Exception as e:
                logger.error("后台发布失败: post_id=%s error=%s", post_id, e, exc_info=True)

        asyncio.create_task(_run())

    async def execute_due_scheduled_posts(self, max_count: int = 10) -> int:
        """执行到期的定时发布任务。"""
        self._require_local_browser_ops("执行定时发布")
        now = utc_now_naive()
        result = await self.db.execute(
            select(XHSPost)
            .where(
                and_(
                    XHSPost.status == "scheduled",
                    XHSPost.scheduled_at.is_not(None),
                    XHSPost.scheduled_at <= now,
                )
            )
            .order_by(XHSPost.scheduled_at.asc(), XHSPost.id.asc())
            .limit(max_count)
        )
        due_posts = list(result.scalars().all())
        if not due_posts:
            return 0

        done = 0
        for post in due_posts:
            env = await self.get_environment(post.environment_id)
            if not env:
                post.status = "failed"
                await self.db.commit()
                continue
            try:
                await self._run_publish_with_guards(
                    post=post,
                    env=env,
                    title=post.title,
                    content=post.content,
                    image_paths=post.image_urls or [],
                    tags=post.tags or [],
                    is_original=False,
                    visibility="公开可见",
                )
            except Exception as e:
                logger.error(f"执行定时发布失败: post_id={post.id}, error={e}")
            done += 1
            await asyncio.sleep(1)
        return done

    @classmethod
    def _now_browser_status_checked_at(cls) -> str:
        return datetime.now().isoformat(timespec="seconds")

    @classmethod
    def _cache_browser_status(cls, env_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        cached = dict(payload)
        with cls._browser_status_cache_guard:
            cls._browser_status_cache[int(env_id)] = cached
        return cached

    @classmethod
    def _get_cached_browser_status(cls, env_id: int) -> dict[str, Any] | None:
        with cls._browser_status_cache_guard:
            cached = cls._browser_status_cache.get(int(env_id))
        return dict(cached) if cached else None

    @staticmethod
    def _extract_browser_ws_from_payload(payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        queue: list[Any] = [payload]
        seen = 0
        while queue and seen < 80:
            seen += 1
            current = queue.pop(0)
            if isinstance(current, dict):
                for key, value in current.items():
                    normalized_key = str(key or "").lower()
                    if isinstance(value, str) and value.startswith("ws://"):
                        return value
                    if normalized_key in {"puppeteer", "ws", "wsurl", "ws_url", "websocket", "websocketurl", "debuggerurl", "cdpurl"}:
                        if isinstance(value, str) and value.startswith("ws://"):
                            return value
                    if isinstance(value, (dict, list)):
                        queue.append(value)
            elif isinstance(current, list):
                queue.extend(current[:20])
        return None

    @staticmethod
    def _extract_browser_online_hint(payload: Any) -> bool | None:
        if not isinstance(payload, (dict, list)):
            return None
        positive = {"1", "true", "active", "running", "online", "opened", "open", "started", "已启动", "运行中", "打开"}
        negative = {"0", "false", "inactive", "stopped", "offline", "closed", "close", "not_started", "未启动", "已停止", "关闭"}
        status_keys = ("status", "state", "running", "active", "open", "started", "launch", "browserstatus", "runstatus")
        queue: list[Any] = [payload]
        seen = 0
        while queue and seen < 100:
            seen += 1
            current = queue.pop(0)
            if isinstance(current, dict):
                for key, value in current.items():
                    normalized_key = str(key or "").replace("_", "").replace("-", "").lower()
                    key_matches = any(item in normalized_key for item in status_keys)
                    if key_matches:
                        if isinstance(value, bool):
                            return value
                        normalized_value = str(value).strip().lower()
                        if normalized_value in positive:
                            return True
                        if normalized_value in negative:
                            return False
                    if isinstance(value, (dict, list)):
                        queue.append(value)
            elif isinstance(current, list):
                queue.extend(current[:30])
        return None

    @staticmethod
    def _extract_browser_status_debug_value(payload: Any) -> str | None:
        if not isinstance(payload, (dict, list)):
            return None
        status_keys = ("status", "state", "running", "active", "open", "started", "launch", "browserstatus", "runstatus")
        queue: list[Any] = [payload]
        seen = 0
        while queue and seen < 100:
            seen += 1
            current = queue.pop(0)
            if isinstance(current, dict):
                for key, value in current.items():
                    normalized_key = str(key or "").replace("_", "").replace("-", "").lower()
                    if any(item in normalized_key for item in status_keys) and not isinstance(value, (dict, list)):
                        return f"{key}={value}"
                    if isinstance(value, (dict, list)):
                        queue.append(value)
            elif isinstance(current, list):
                queue.extend(current[:30])
        return None

    async def _read_browser_status_from_yundeng(self, env: XHSEnvironment) -> tuple[bool | None, str | None, str]:
        """Read whether a YunDeng environment is already running without intentionally stopping/restarting it."""
        self._require_local_browser_ops("读取云登浏览器在线状态")
        shop_id = str(env.shop_id or "").strip()
        if not shop_id:
            return False, None, "环境缺少 shop_id"

        probes: list[tuple[str, str, dict[str, Any] | None]] = [
            ("GET", f"/api/v2/browser/status?account_id={shop_id}", None),
            ("GET", f"/api/v2/browser/active?account_id={shop_id}", None),
            ("POST", "/api/v2/browser/status", {"account_id": shop_id}),
            ("POST", "/api/v2/browser/active", {"account_id": shop_id}),
            ("POST", "/api/v2/userapi/user/shopdetaillist", {"browserid": [shop_id]}),
        ]
        last_error = ""
        for method, path, body in probes:
            url = f"{YUNDENG_API}{path}"
            try:
                async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
                    if method == "GET":
                        resp = await client.get(url)
                    else:
                        resp = await client.post(url, json=body)
                if resp.status_code >= 400:
                    last_error = f"{path} HTTP {resp.status_code}"
                    continue
                payload = resp.json() if resp.content else {}
                if isinstance(payload, dict) and payload.get("code") not in (None, 0):
                    last_error = str(payload.get("message") or payload.get("msg") or payload)
                    continue
                ws_url = self._extract_browser_ws_from_payload(payload)
                online = self._extract_browser_online_hint(payload)
                if ws_url:
                    return True, self._normalize_browser_ws(ws_url), f"status_api:{method} {path}:ws"
                if online is not None:
                    debug_value = self._extract_browser_status_debug_value(payload)
                    source = f"status_api:{method} {path}"
                    if debug_value:
                        source = f"{source}:{debug_value}"
                    return online, None, source
            except Exception as exc:
                last_error = str(exc)
                continue
        return None, None, last_error or "云登状态接口未返回可识别状态"

    async def _request_browser_ws_for_online_environment(self, env: XHSEnvironment) -> Optional[str]:
        """
        Ask YunDeng to start or attach to the environment and return its
        debugging WebSocket. The caller should let YunDeng/MCP handle startup
        instead of blocking on a separate online-status probe.
        """
        self._require_local_browser_ops("启动云登浏览器并获取连接")
        await self._apply_sync_cloud_fingerprint_update(env)
        body = {"account_id": env.shop_id, "headless": "0"}
        body.update(self._parse_sync_browser_start_config(env))
        last_error = ""
        for attempt in range(1, XHS_BROWSER_START_RETRY_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
                    resp = await client.post(f"{YUNDENG_API}/api/v2/browser/start", json=body)
                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code}: {(resp.text or '')[:400]}"
                    logger.warning("启动云登浏览器失败: shop_id=%s attempt=%s error=%s", env.shop_id, attempt, last_error)
                else:
                    data = resp.json() if resp.content else {}
                    if data.get("code") != 0:
                        last_error = str(data)
                        logger.warning("启动云登浏览器失败: shop_id=%s attempt=%s response=%s", env.shop_id, attempt, data)
                    else:
                        raw_ws = self._extract_browser_ws_from_payload(data)
                        ws_url = self._normalize_browser_ws(raw_ws) if raw_ws else None
                        if ws_url and await self._probe_browser_ws(ws_url):
                            self._cache_browser_status(
                                int(env.id),
                                {
                                    "environment_id": int(env.id),
                                    "shop_id": env.shop_id,
                                    "account_name": env.account_name,
                                    "browser_status": "online",
                                    "is_online": True,
                                    "checked_at": self._now_browser_status_checked_at(),
                                    "source": "browser_start",
                                    "error": None,
                                    "ws_url": ws_url,
                                },
                            )
                            return ws_url
                        last_error = "云登已返回但浏览器调试端口不可连接"
                        logger.warning("云登浏览器连接不可用: shop_id=%s attempt=%s ws=%s", env.shop_id, attempt, ws_url)
            except Exception as e:
                last_error = str(e)
                logger.warning("启动云登浏览器异常: env=%s attempt=%s error=%s", env.shop_id, attempt, e)
            if attempt < XHS_BROWSER_START_RETRY_ATTEMPTS and XHS_BROWSER_START_RETRY_DELAY_SECONDS > 0:
                await asyncio.sleep(XHS_BROWSER_START_RETRY_DELAY_SECONDS)
        self._cache_browser_status(
            int(env.id),
            {
                "environment_id": int(env.id),
                "shop_id": env.shop_id,
                "account_name": env.account_name,
                "browser_status": "error",
                "is_online": False,
                "checked_at": self._now_browser_status_checked_at(),
                "source": "browser_start",
                "error": last_error or "启动云登浏览器失败",
            },
        )
        logger.error("启动云登浏览器并获取 WebSocket 失败: env=%s error=%s", env.shop_id, last_error)
        return None

    async def get_browser_environment_status(
        self,
        env: XHSEnvironment,
        *,
        refresh: bool = True,
        include_ws: bool = False,
    ) -> dict[str, Any]:
        cached = self._get_cached_browser_status(int(env.id))
        if cached and not refresh:
            if not include_ws:
                cached.pop("ws_url", None)
            return cached

        online_hint, ws_url, source_or_error = await self._read_browser_status_from_yundeng(env)
        error: str | None = None
        status = "unknown"
        if online_hint is True:
            status = "online"
        elif online_hint is False:
            status = "offline"
        else:
            error = source_or_error

        if ws_url and not await self._probe_browser_ws(ws_url):
            status = "error"
            error = "浏览器调试端口不可连接"

        payload = {
            "environment_id": int(env.id),
            "shop_id": env.shop_id,
            "account_name": env.account_name,
            "browser_status": status,
            "is_online": status == "online",
            "checked_at": self._now_browser_status_checked_at(),
            "source": source_or_error if status in {"online", "offline"} else "status_api",
            "error": error,
            "ws_url": ws_url if include_ws else None,
        }
        if not include_ws:
            payload.pop("ws_url", None)
        return self._cache_browser_status(int(env.id), payload)

    async def list_browser_environment_statuses(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(XHSEnvironment)
            .where(XHSEnvironment.status == "active")
            .order_by(XHSEnvironment.is_sync_runner.desc(), XHSEnvironment.account_name.asc())
        )
        envs = list(result.scalars().all())
        statuses: list[dict[str, Any]] = []
        for env in envs:
            cached = self._get_cached_browser_status(int(env.id))
            if cached and not refresh:
                cached.pop("ws_url", None)
                statuses.append(cached)
                continue
            if not refresh:
                statuses.append(
                    {
                        "environment_id": int(env.id),
                        "shop_id": env.shop_id,
                        "account_name": env.account_name,
                        "browser_status": "unknown",
                        "is_online": False,
                        "checked_at": None,
                        "source": "cache",
                        "error": None,
                    }
                )
                continue
            statuses.append(await self.get_browser_environment_status(env, refresh=True))
        return statuses

    async def refresh_browser_environment_status(self, env_id: int) -> dict[str, Any]:
        env = await self.get_environment(env_id)
        if not env or env.status != "active":
            raise RuntimeError("云登环境不存在或未启用")
        return await self.get_browser_environment_status(env, refresh=True)

    async def _apply_sync_cloud_fingerprint_update(self, scrape_env: XHSEnvironment) -> bool:
        """如已配置开放平台参数，则先更新实例指纹并触发云端会话重启。"""
        raw_config = str(getattr(scrape_env, "sync_cloud_update_config", "") or "").strip()
        session_id = str(getattr(scrape_env, "sync_cloud_session_id", "") or "").strip()
        api_key = str(getattr(scrape_env, "sync_cloud_api_key", "") or "").strip()
        has_partial_config = bool(raw_config or session_id or api_key)
        if not has_partial_config:
            return False
        if not YUNDENG_CLOUD_OPEN_TOKEN.strip():
            logger.warning("跳过开放平台指纹更新: env=%s, 原因=未配置 YUNDENG_CLOUD_OPEN_TOKEN", scrape_env.shop_id)
            return False
        if not raw_config or not session_id or not api_key:
            logger.warning("跳过开放平台指纹更新: env=%s, 原因=sessionId/apiKey/更新模板未配齐", scrape_env.shop_id)
            return False

        payload = self._parse_sync_cloud_update_config(scrape_env)
        payload.setdefault("sessionId", session_id)
        payload.setdefault("sessionName", scrape_env.account_name)
        headers = {"Authorization": YUNDENG_CLOUD_OPEN_TOKEN.strip()}
        try:
            async with httpx.AsyncClient(timeout=45.0, headers=headers) as client:
                update_resp = await client.post(
                    f"{YUNDENG_CLOUD_API}/v2/cloudbrowser/api/user/sessions/update",
                    json=payload,
                )
                update_data = update_resp.json() if update_resp.content else {}
                if update_resp.status_code != 200 or update_data.get("code") != 200:
                    logger.warning(
                        "开放平台指纹更新失败: env=%s session_id=%s status=%s response=%s payload=%s",
                        scrape_env.shop_id,
                        session_id,
                        update_resp.status_code,
                        update_data,
                        payload,
                    )
                    return False
                stop_resp = await client.post(
                    f"{YUNDENG_CLOUD_API}/v2/cloudbrowser/api/session/stop?apiKey={api_key}&sessionId={session_id}"
                )
                stop_data = stop_resp.json() if stop_resp.content else {}
                if stop_resp.status_code != 200 or stop_data.get("code") != 200:
                    logger.warning(
                        "开放平台停止会话失败: env=%s session_id=%s status=%s response=%s",
                        scrape_env.shop_id,
                        session_id,
                        stop_resp.status_code,
                        stop_data,
                    )
                start_resp = await client.post(
                    f"{YUNDENG_CLOUD_API}/v2/cloudbrowser/api/session/start?apiKey={api_key}&sessionId={session_id}"
                )
                start_data = start_resp.json() if start_resp.content else {}
                if start_resp.status_code != 200 or start_data.get("code") != 200:
                    logger.warning(
                        "开放平台启动会话失败: env=%s session_id=%s status=%s response=%s",
                        scrape_env.shop_id,
                        session_id,
                        start_resp.status_code,
                        start_data,
                    )
                    return False
            logger.info("开放平台指纹更新成功: env=%s session_id=%s", scrape_env.shop_id, session_id)
            return True
        except Exception as exc:
            logger.warning("开放平台指纹更新异常: env=%s session_id=%s error=%s", scrape_env.shop_id, session_id, exc)
            return False

    async def _probe_browser_ws(self, ws_url: str) -> bool:
        """探测浏览器调试端口是否真的可连，避免拿到失效 WS。"""
        try:
            parsed = urlparse(ws_url)
            host = parsed.hostname
            port = parsed.port
            if not host or not port:
                return False
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=XHS_BROWSER_WS_PROBE_TIMEOUT_SECONDS,
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True
        except Exception:
            return False

    async def _sleep_after_browser_stop(self) -> None:
        if XHS_BROWSER_STOP_COOLDOWN_SECONDS > 0:
            await asyncio.sleep(XHS_BROWSER_STOP_COOLDOWN_SECONDS)

    async def _acquire_ready_browser_ws(self, shop_id: str) -> Optional[str]:
        """Start or attach to a YunDeng environment and return a usable WebSocket."""
        env = await self.get_environment_by_shop_id(shop_id)
        if not env:
            logger.error("浏览器环境不存在: shop_id=%s", shop_id)
            return None
        return await self._request_browser_ws_for_online_environment(env)

    async def _acquire_ready_sync_browser_ws(self, scrape_env: XHSEnvironment) -> Optional[str]:
        """Start or attach to a sync runner and return a usable WebSocket."""
        return await self._request_browser_ws_for_online_environment(scrape_env)

    @staticmethod
    def _normalize_browser_ws(ws_url: str) -> str:
        """
        In dockerized backend, YunDeng may return ws://127.0.0.1:xxxxx/...
        which points to container loopback. Remap to host gateway.
        """
        try:
            if not RUNNING_IN_DOCKER:
                return ws_url
            parsed = urlparse(ws_url)
            host = (parsed.hostname or "").strip().lower()
            if host not in {"127.0.0.1", "localhost"}:
                return ws_url
            port = parsed.port
            if not port:
                return ws_url
            new_netloc = f"host.docker.internal:{port}"
            if parsed.username:
                auth = parsed.username
                if parsed.password:
                    auth = f"{auth}:{parsed.password}"
                new_netloc = f"{auth}@{new_netloc}"
            return parsed._replace(netloc=new_netloc).geturl()
        except Exception:
            return ws_url

    async def _stop_browser(self, shop_id: str):
        """停止云登浏览器"""
        self._require_local_browser_ops("停止云登浏览器")
        try:
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                resp = await client.get(f"{YUNDENG_API}/api/v2/browser/stop?account_id={shop_id}")
                if resp.status_code != 200:
                    logger.warning(
                        "停止云登浏览器返回异常: shop_id=%s status=%s body=%s",
                        shop_id,
                        resp.status_code,
                        (resp.text or "")[:400],
                    )
        except Exception as e:
            logger.warning(f"停止云登浏览器失败: {e}")

    def _resolve_active_mcp_api(self, api_base: str | None = None) -> str:
        return api_base or getattr(self, "_active_mcp_api", XHS_MCP_API)

    @staticmethod
    def _should_bypass_env_proxy(url: str | None) -> bool:
        if not url:
            return False
        try:
            host = (urlparse(url).hostname or "").strip().lower()
        except Exception:
            return False
        return host in {"localhost", "127.0.0.1", "::1"}

    @classmethod
    def _httpx_client_kwargs(cls, url: str | None, *, timeout: float, **kwargs) -> dict:
        params = {"timeout": timeout, **kwargs}
        if cls._should_bypass_env_proxy(url):
            params["trust_env"] = False
        return params

    async def _check_mcp_running(self, api_base: str | None = None) -> bool:
        try:
            resolved_api = self._resolve_active_mcp_api(api_base)
            async with httpx.AsyncClient(**self._httpx_client_kwargs(resolved_api, timeout=3.0)) as client:
                resp = await client.get(f"{resolved_api}/health")
            return resp.status_code == 200
        except Exception:
            return False

    async def _allocate_free_port(self) -> int:
        for _ in range(50):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", 0))
                port = int(s.getsockname()[1])
            with self._mcp_port_guard:
                stale_before = time.monotonic() - 600
                for stale_port, reserved_at in list(self._reserved_mcp_ports.items()):
                    if reserved_at < stale_before:
                        self._reserved_mcp_ports.pop(stale_port, None)
                if port in self._reserved_mcp_ports:
                    continue
                self._reserved_mcp_ports[port] = time.monotonic()
                return port
        raise RuntimeError("无法为小红书 MCP 分配独立端口")

    @classmethod
    def _release_reserved_mcp_port(cls, port: int | None) -> None:
        if not port:
            return
        with cls._mcp_port_guard:
            cls._reserved_mcp_ports.pop(int(port), None)

    async def _start_mcp(self, ws_url: str, port: int) -> Optional[int]:
        """启动 xhs-mcp 进程"""
        try:
            env = os.environ.copy()
            env["XHS_BROWSER_WS"] = ws_url
            browser_download_dir = XHS_MCP_BROWSER_DOWNLOAD_DIR
            container_download_dir = XHS_MCP_CONTAINER_DOWNLOAD_DIR
            if not browser_download_dir and XHS_HOST_UPLOAD_ROOT:
                browser_download_dir = _join_env_path(XHS_HOST_UPLOAD_ROOT, "mcp-downloads")
            if not container_download_dir and XHS_CONTAINER_UPLOAD_ROOT:
                container_download_dir = _join_env_path(XHS_CONTAINER_UPLOAD_ROOT, "mcp-downloads")
            if browser_download_dir and container_download_dir:
                env["XHS_MCP_BROWSER_DOWNLOAD_DIR"] = browser_download_dir
                env["XHS_MCP_CONTAINER_DOWNLOAD_DIR"] = container_download_dir

            proc = await asyncio.create_subprocess_exec(
                XHS_MCP_BIN,
                "-port", f":{port}",
                env=env,
            )
            with self._mcp_port_guard:
                self._mcp_ports_by_pid[int(proc.pid)] = int(port)
            return proc.pid
        except FileNotFoundError:
            self._release_reserved_mcp_port(port)
            logger.error(f"启动 xhs-mcp 失败: 未找到可执行文件 {XHS_MCP_BIN}，请配置 XHS_MCP_BIN_PATH")
            return None
        except Exception as e:
            self._release_reserved_mcp_port(port)
            logger.error(f"启动 xhs-mcp 失败: {e}")
            return None

    async def _wait_mcp_ready(self, api_base: str | None = None, timeout: int = 15):
        for i in range(timeout):
            if await self._check_mcp_running(api_base):
                return
            await asyncio.sleep(1)
        raise RuntimeError("xiaohongshu-mcp 启动超时")

    async def _stop_mcp(self, pid: int):
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception as e:
            logger.warning(f"停止 xhs-mcp 失败: {e}")
        finally:
            with self._mcp_port_guard:
                port = self._mcp_ports_by_pid.pop(int(pid), None)
            self._release_reserved_mcp_port(port)

    async def _call_publish_api(
        self, title, content, images, tags, is_original, visibility, api_base: str | None = None
    ) -> tuple[Optional[str], Optional[str], bool]:
        """调用 xhs-mcp HTTP API 发布内容。"""
        api_base = self._resolve_active_mcp_api(api_base)
        # MCP publish may take minutes (image upload + creator center interactions),
        # especially on Windows finger-browser setups.
        async with httpx.AsyncClient(**self._httpx_client_kwargs(api_base, timeout=420.0)) as client:
            resp = await client.post(
                f"{api_base}/api/v1/publish",
                json={
                    "title": title,
                    "content": content,
                    "images": images,
                    "tags": tags or [],
                    "is_original": is_original,
                    "visibility": visibility,
                },
            )
            payload = resp.json() if resp.content else {}

            feed_id, xsec_token = self._extract_publish_identifiers(payload)
            publish_ok = self._is_publish_response_success(resp.status_code, payload)
            if not publish_ok:
                detail = self._extract_publish_failure_message(payload, resp.status_code)
                raise RuntimeError(detail)

            if publish_ok and not (feed_id and xsec_token):
                logger.warning("发布接口返回成功，但缺少 feed_id 或 xsec_token，后续同步能力将受限")

            return feed_id, xsec_token, publish_ok

    def _schedule_identifier_recovery(
        self,
        post_id: int,
        env_id: int,
        expected_title: str,
        expected_content: str,
    ) -> None:
        async def _run() -> None:
            try:
                env_lock = await self._get_env_publish_lock(env_id)
                async with env_lock:
                    async with async_session() as db:
                        service = XHSService(db)
                        await service._recover_post_identifiers_in_background(
                            post_id=post_id,
                            expected_title=expected_title,
                            expected_content=expected_content,
                        )
            except Exception as e:
                logger.warning("后台回补帖子标识失败: post_id=%s, error=%s", post_id, e)

        asyncio.create_task(_run())

    async def _recover_post_identifiers_in_background(
        self,
        post_id: int,
        expected_title: str,
        expected_content: str,
    ) -> None:
        result = await self.db.execute(select(XHSPost).where(XHSPost.id == post_id))
        post = result.scalar_one_or_none()
        if not post or post.status != "success":
            return
        if post.feed_id and post.xsec_token:
            return

        env = await self.get_environment(post.environment_id)
        if not env:
            logger.warning("后台回补帖子标识失败: post_id=%s, 环境不存在", post_id)
            return

        mcp_pid = None
        use_external_mcp = bool(XHS_MCP_EXTERNAL_API)
        mcp_port = None if use_external_mcp else await self._allocate_free_port()
        mcp_api = XHS_MCP_EXTERNAL_API if use_external_mcp else f"http://localhost:{mcp_port}"
        previous_mcp_api = getattr(self, "_active_mcp_api", None)

        try:
            self._active_mcp_api = mcp_api
            ws_url = await self._acquire_ready_browser_ws(env.shop_id)
            if not ws_url:
                logger.warning("后台回补帖子标识失败: post_id=%s, 无法获取浏览器连接", post_id)
                return

            if use_external_mcp:
                if not await self._check_mcp_running(mcp_api):
                    logger.warning("后台回补帖子标识失败: post_id=%s, 外部 MCP 不可用", post_id)
                    return
            else:
                mcp_pid = await self._start_mcp(ws_url, mcp_port or 0)
                if not mcp_pid:
                    logger.warning("后台回补帖子标识失败: post_id=%s, 启动 MCP 失败", post_id)
                    return
                await self._wait_mcp_ready(mcp_api)

            recovered_feed_id, recovered_xsec_token = await self._recover_published_identifiers(
                expected_title=expected_title,
                expected_content=expected_content,
                current_feed_id=post.feed_id,
                current_xsec_token=post.xsec_token,
                mcp_api=mcp_api,
            )
            if recovered_feed_id:
                post.feed_id = recovered_feed_id
            if recovered_xsec_token:
                post.xsec_token = recovered_xsec_token
            post.post_url = self._build_post_url(post.feed_id, post.xsec_token)
            await self.db.commit()
        except Exception as e:
            logger.warning("后台回补帖子标识失败: post_id=%s, error=%s", post_id, e)
        finally:
            self._active_mcp_api = previous_mcp_api
            if mcp_pid is not None:
                await self._stop_mcp(mcp_pid)

    @staticmethod
    def _extract_publish_identifiers(payload: dict) -> tuple[Optional[str], Optional[str]]:
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            data = {}

        def _pick_str(source: dict, keys: tuple[str, ...]) -> Optional[str]:
            for key in keys:
                value = source.get(key)
                if value is None:
                    continue
                text = str(value).strip()
                if text:
                    return text
            return None

        feed_id = _pick_str(
            data,
            ("post_id", "feed_id", "note_id", "id", "postId", "feedId", "noteId"),
        ) or _pick_str(
            payload if isinstance(payload, dict) else {},
            ("post_id", "feed_id", "note_id", "id", "postId", "feedId", "noteId"),
        )

        xsec_token = _pick_str(
            data,
            ("xsec_token", "xsecToken", "x_sec_token", "token", "xSecToken"),
        ) or _pick_str(
            payload if isinstance(payload, dict) else {},
            ("xsec_token", "xsecToken", "x_sec_token", "token", "xSecToken"),
        )

        url_like = XHSService._pick_post_url_from_payload(payload)
        from_url_feed_id, from_url_xsec = XHSService._extract_identifiers_from_url(url_like)

        return feed_id or from_url_feed_id, xsec_token or from_url_xsec

    @staticmethod
    def _pick_post_url_from_payload(payload: dict) -> Optional[str]:
        if not isinstance(payload, dict):
            return None
        url_keys = (
            "post_url",
            "note_url",
            "feed_url",
            "url",
            "share_url",
            "jump_url",
            "link",
            "href",
        )
        stack = [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in url_keys and isinstance(value, str) and "/explore/" in value:
                        return value
                    if isinstance(value, (dict, list)):
                        stack.append(value)
            elif isinstance(node, list):
                for value in node:
                    if isinstance(value, (dict, list)):
                        stack.append(value)
                    elif isinstance(value, str) and "/explore/" in value:
                        return value
        return None

    @staticmethod
    def _extract_identifiers_from_url(url: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        if not url:
            return None, None
        try:
            parsed = urlparse(url)
            path = parsed.path or ""
            match = re.search(r"/explore/([0-9a-zA-Z]+)", path)
            feed_id = match.group(1) if match else None
            query = parse_qs(parsed.query or "")
            xsec_token = (query.get("xsec_token") or query.get("xsecToken") or [None])[0]
            if xsec_token:
                xsec_token = xsec_token.strip()
            return feed_id, xsec_token or None
        except Exception:
            return None, None

    @staticmethod
    def _build_post_url(feed_id: Optional[str], xsec_token: Optional[str]) -> Optional[str]:
        if not feed_id:
            return None
        if xsec_token:
            return f"https://www.xiaohongshu.com/explore/{feed_id}?xsec_token={xsec_token}"
        return f"https://www.xiaohongshu.com/explore/{feed_id}"

    @staticmethod
    def _build_account_note_url(feed_id: Optional[str], xsec_token: Optional[str]) -> Optional[str]:
        if not feed_id:
            return None
        if xsec_token:
            return f"https://www.xiaohongshu.com/explore/{feed_id}?xsec_token={xsec_token}&xsec_source=pc_user"
        return f"https://www.xiaohongshu.com/explore/{feed_id}"

    @staticmethod
    def _safe_int(value: object) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(round(float(value)))
        try:
            return int(str(value or "0").replace(",", "").strip() or 0)
        except Exception:
            return 0

    @classmethod
    def _merge_metric_count(cls, current: object, incoming: object) -> int:
        current_value = cls._safe_int(current)
        incoming_value = cls._safe_int(incoming)
        if current_value > 0 and incoming_value == 0:
            return current_value
        return incoming_value

    @classmethod
    def _extract_optional_count(cls, source: object, *keys: str) -> int | None:
        if not isinstance(source, dict):
            return None
        for key in keys:
            if key in source:
                return cls._safe_int(source.get(key))
        return None

    @staticmethod
    def _prepare_publish_content_and_tags(content: str, tags: list[str]) -> tuple[str, list[str]]:
        """
        发布前将正文中的 #话题 提取为 tags，正文只保留纯内容。
        优先使用 mcp 的 tags 参数写入话题，避免正文与话题混写。
        """
        content_tags = XHSService._extract_hashtags(content)
        merged_tags = list(content_tags) + list(tags or [])
        normalized = XHSService._normalize_tag_list(merged_tags)
        cleaned_content = XHSService._remove_hashtags_from_content(content)
        return cleaned_content, normalized

    @staticmethod
    def _normalize_tag_list(tags: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in tags or []:
            tag = str(raw or "").strip().lstrip("#")
            if not tag:
                continue
            lower = tag.lower()
            if lower in seen:
                continue
            seen.add(lower)
            normalized.append(tag)
        return normalized

    @staticmethod
    def _extract_hashtags(text: str) -> list[str]:
        pattern = re.compile(r"#([^\s#，。！？、,.!?:;；（）()【】\[\]<>《》]+)")
        return [m.group(1).strip() for m in pattern.finditer(text or "") if m.group(1).strip()]

    @staticmethod
    def _remove_hashtags_from_content(text: str) -> str:
        pattern = re.compile(r"#([^\s#，。！？、,.!?:;；（）()【】\[\]<>《》]+)")
        cleaned = pattern.sub("", text or "")
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"\n[ \t]+", "\n", cleaned)
        cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = cleaned.strip()
        # 如果正文只有话题，兜底保留原文本，避免发布空正文。
        if not cleaned:
            return (text or "").strip()
        return cleaned

    async def _recover_published_identifiers(
        self,
        expected_title: str,
        expected_content: str,
        current_feed_id: Optional[str],
        current_xsec_token: Optional[str],
        mcp_api: str | None = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        发布成功后从“我的主页”回补帖子标识。
        已知 current_feed_id 时，优先比对第 1 条；若不匹配则扫描最近 5 条。
        未知 current_feed_id 时，退化为直接取第 1 条。
        """
        mcp_api = self._resolve_active_mcp_api(mcp_api)
        if not await self._check_mcp_running(mcp_api):
            return current_feed_id, current_xsec_token

        for attempt in range(10):
            candidates = await self._fetch_my_profile_feeds(mcp_api, limit=5)
            if candidates:
                matched = self._match_profile_feed_by_feed_id(candidates, current_feed_id)
                if matched:
                    feed_id = matched.get("feed_id")
                    xsec_token = matched.get("xsec_token")
                    if feed_id and xsec_token:
                        return feed_id, xsec_token
                logger.info(
                    "发布后第 %s/%s 次从我的主页未命中目标 feed_id，继续重试: current_feed_id=%s, candidates=%s",
                    attempt + 1,
                    10,
                    current_feed_id,
                    [item.get("feed_id") for item in candidates],
                )
            else:
                logger.info("发布后第 %s/%s 次从我的主页获取最新帖子为空，继续重试", attempt + 1, 10)

            if attempt < 9:
                await asyncio.sleep(2)

        logger.warning(
            "发布后从我的主页重试 10 次仍未命中目标帖子: current_feed_id=%s, title=%s",
            current_feed_id,
            expected_title,
        )
        return current_feed_id, current_xsec_token

    async def _fetch_my_profile_feeds(self, api_base: str | None = None, limit: int = 5) -> list[dict]:
        try:
            api_base = self._resolve_active_mcp_api(api_base)
            async with httpx.AsyncClient(**self._httpx_client_kwargs(api_base, timeout=30.0)) as client:
                resp = await client.get(f"{api_base}/api/v1/user/me")
                if resp.status_code != 200:
                    return []
                payload = resp.json() if resp.content else {}
                if not isinstance(payload, dict):
                    return []
                if not (payload.get("success") or payload.get("code") == 0):
                    return []

                data = payload.get("data") or {}
                if isinstance(data, dict) and isinstance(data.get("data"), dict):
                    data = data.get("data") or {}
                if not isinstance(data, dict):
                    return []

                feeds = data.get("feeds")
                if not isinstance(feeds, list) or not feeds:
                    return []

                normalized: list[dict] = []
                for raw in feeds[: max(1, limit)]:
                    if not isinstance(raw, dict):
                        continue
                    feed_id = str(raw.get("id") or "").strip()
                    xsec_token = str(raw.get("xsecToken") or raw.get("xsec_token") or "").strip()
                    if not feed_id:
                        continue
                    normalized.append({
                        "feed_id": feed_id,
                        "xsec_token": xsec_token,
                    })
                return normalized
        except Exception:
            return []

    @staticmethod
    def _match_profile_feed_by_feed_id(feeds: list[dict], target_feed_id: Optional[str]) -> Optional[dict]:
        if not feeds:
            return None
        if not target_feed_id:
            first = feeds[0]
            return first if first.get("feed_id") and first.get("xsec_token") else None

        target = str(target_feed_id).strip()
        if not target:
            first = feeds[0]
            return first if first.get("feed_id") and first.get("xsec_token") else None

        first = feeds[0]
        if str(first.get("feed_id") or "").strip() == target and first.get("xsec_token"):
            return first

        for item in feeds[1:5]:
            if str(item.get("feed_id") or "").strip() == target and item.get("xsec_token"):
                return item
        return None

    async def _verify_published_note_content(
        self,
        feed_id: str,
        xsec_token: str,
        expected_title: str,
        expected_content: str,
        api_base: str | None = None,
    ) -> bool:
        try:
            api_base = self._resolve_active_mcp_api(api_base)
            async with httpx.AsyncClient(**self._httpx_client_kwargs(api_base, timeout=30.0)) as client:
                resp = await client.post(
                    f"{api_base}/api/v1/feeds/detail",
                    json={
                        "feed_id": feed_id,
                        "xsec_token": xsec_token,
                        "load_all_comments": False,
                    },
                )
                if resp.status_code != 200:
                    return False
                payload = resp.json() if resp.content else {}
                if not isinstance(payload, dict):
                    return False
                if not (payload.get("success") or payload.get("code") == 0):
                    return False
                data = payload.get("data") or {}
                if not isinstance(data, dict):
                    return False
                note_data = data.get("note")
                if isinstance(note_data, dict):
                    note = note_data
                else:
                    nested_data = data.get("data") if isinstance(data.get("data"), dict) else {}
                    note = nested_data.get("note") if isinstance(nested_data.get("note"), dict) else {}
                if not isinstance(note, dict):
                    return False
                actual_title = str(
                    note.get("title")
                    or note.get("displayTitle")
                    or ""
                ).strip()
                actual_content = str(
                    note.get("desc")
                    or note.get("content")
                    or note.get("description")
                    or ""
                ).strip()
                if (expected_title or "").strip() and actual_title and actual_title != expected_title.strip():
                    return False

                # 内容校验采用宽松策略：去除 #标签 后比对前缀，减少平台格式化/话题处理差异影响
                expected_plain = self._normalize_text(self._strip_hashtags(expected_content))
                actual_plain = self._normalize_text(self._strip_hashtags(actual_content))
                if actual_plain:
                    expected_prefix = expected_plain[:12]
                    if expected_prefix and expected_prefix not in actual_plain:
                        return False
                return True
        except Exception:
            return False

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", "", (text or "")).lower()

    @staticmethod
    def _strip_hashtags(text: str) -> str:
        return re.sub(r"#[^\s#，。！？、,.!?:;；（）()【】\[\]<>《》]+", "", text or "")

    @staticmethod
    def _is_publish_response_success(status_code: int, payload: dict) -> bool:
        if status_code < 200 or status_code >= 300:
            return False

        if not isinstance(payload, dict):
            return True

        code = payload.get("code")
        if code in (0, 200, True, "0", "200"):
            return True
        if isinstance(code, str) and code.lower() in {"ok", "success", "succeeded"}:
            return True

        message = str(payload.get("message") or payload.get("msg") or "").lower()
        if ("success" in message) or ("成功" in message):
            return True

        return False

    @staticmethod
    def _extract_publish_failure_message(payload: dict, status_code: int) -> str:
        if not isinstance(payload, dict):
            return f"小红书发布失败（HTTP {status_code}）"

        def _first_text(candidates) -> str:
            for value in candidates:
                if value is None:
                    continue
                text = str(value).strip()
                if text:
                    return text
            return ""

        top_msg = _first_text([payload.get("message"), payload.get("msg"), payload.get("error")])
        data = payload.get("data")
        data_msg = ""
        if isinstance(data, dict):
            data_msg = _first_text(
                [data.get("message"), data.get("msg"), data.get("error"), data.get("detail"), data.get("reason")]
            )

        preferred = data_msg or top_msg
        if preferred:
            return preferred

        code = payload.get("code")
        if code not in (None, ""):
            return f"小红书发布失败（code={code}, HTTP={status_code}）"
        return f"小红书发布失败（HTTP {status_code}）"

    # ==================== 帖子管理 ====================

    async def list_posts(
        self,
        user: User,
        page: int = 1,
        limit: int = 20,
        status: Optional[str] = None,
    ) -> tuple[list[XHSPost], int]:
        await self._mark_stale_publishing_posts_failed(minutes=10)

        conditions = []
        if user.role != "admin":
            conditions.append(XHSPost.user_id == user.id)
        if status:
            conditions.append(XHSPost.status == status)

        where_clause = and_(*conditions) if conditions else True

        count_stmt = select(func.count()).select_from(XHSPost).where(where_clause)
        total = (await self.db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(XHSPost, XHSEnvironment.account_name)
            .join(XHSEnvironment, XHSPost.environment_id == XHSEnvironment.id, isouter=True)
            .where(where_clause)
            .options(selectinload(XHSPost.environment))
            .order_by(XHSPost.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        rows = result.all()
        items = []
        for post, account_name in rows:
            post.account_name = account_name or getattr(post.environment, "account_name", None)
            items.append(post)
        return items, total

    async def get_post(self, post_id: int, user: User) -> Optional[XHSPost]:
        stmt = (
            select(XHSPost, XHSEnvironment.account_name)
            .join(XHSEnvironment, XHSPost.environment_id == XHSEnvironment.id, isouter=True)
            .where(XHSPost.id == post_id)
        )
        if user.role != "admin":
            stmt = stmt.where(XHSPost.user_id == user.id)
        result = await self.db.execute(stmt)
        row = result.first()
        if not row:
            return None
        post, account_name = row
        post.account_name = account_name or getattr(post.environment, "account_name", None)
        return post

    async def delete_post(self, post: XHSPost) -> bool:
        await self.db.delete(post)
        await self.db.commit()
        return True

    async def remote_edit_published_post(
        self,
        post: XHSPost,
        title: str,
        content: str,
        tags: list[str] | None = None,
    ) -> XHSPost:
        """编辑已发布帖子（远端小红书 + 本地回写）。"""
        if post.status != "success":
            raise ValueError("仅已发布帖子支持远端编辑")
        if not post.feed_id:
            raise ValueError("帖子缺少 feed_id，无法远端编辑")
        if self._should_delegate_browser_ops():
            await self.trigger_worker_remote_edit(
                post_id=post.id,
                title=title,
                content=content,
                tags=tags,
            )
            post.title = title
            post.content = content
            post.tags = tags or []
            await self.db.commit()
            await self.db.refresh(post)
            return post

        mcp_running = await self._check_mcp_running()
        mcp_pid: int | None = None
        try:
            if not mcp_running:
                env = await self.get_environment(post.environment_id)
                if not env:
                    raise ValueError("帖子对应发布环境不存在")
                ws_url = await self._acquire_ready_browser_ws(env.shop_id)
                if not ws_url:
                    raise ValueError("无法获取浏览器连接，暂时不能远端编辑")
                mcp_pid = await self._start_mcp(ws_url, XHS_MCP_PORT)
                if not mcp_pid:
                    raise ValueError("启动小红书服务失败，暂时不能远端编辑")
                await self._wait_mcp_ready(XHS_MCP_API)

            tools = await self._mcp_list_tools()
            tool = self._pick_mcp_tool(
                tools,
                candidates=("xhs_edit_note", "edit_note", "update_note", "edit_feed", "update_feed"),
            )
            if not tool:
                raise XHSRemoteOperationUnsupported(
                    "当前 xiaohongshu-mcp 未提供“已发布内容编辑”能力，请升级或切换支持该能力的版本。"
                )

            args = self._build_mcp_tool_args(
                tool=tool,
                mapping={
                    "feed_id": post.feed_id,
                    "note_id": post.feed_id,
                    "id": post.feed_id,
                    "xsec_token": post.xsec_token,
                    "title": title,
                    "content": content,
                    "desc": content,
                    "tags": tags or [],
                },
            )
            await self._mcp_call_tool(tool["name"], args)

            post.title = title
            post.content = content
            post.tags = tags or []
            await self.db.commit()
            await self.db.refresh(post)
            return post
        finally:
            if not mcp_running and mcp_pid is not None:
                await self._stop_mcp(mcp_pid)

    async def remote_delete_published_post(self, post: XHSPost) -> XHSPost:
        """删除已发布帖子（远端小红书 + 本地状态标记）。"""
        if post.status != "success":
            raise ValueError("仅已发布帖子支持远端删除")
        if not post.feed_id:
            raise ValueError("帖子缺少 feed_id，无法远端删除")
        if self._should_delegate_browser_ops():
            await self.trigger_worker_remote_delete(post_id=post.id)
            post.status = "deleted"
            post.last_synced_at = utc_now_naive()
            await self.db.commit()
            await self.db.refresh(post)
            return post

        mcp_running = await self._check_mcp_running()
        mcp_pid: int | None = None
        try:
            if not mcp_running:
                env = await self.get_environment(post.environment_id)
                if not env:
                    raise ValueError("帖子对应发布环境不存在")
                ws_url = await self._acquire_ready_browser_ws(env.shop_id)
                if not ws_url:
                    raise ValueError("无法获取浏览器连接，暂时不能远端删除")
                mcp_pid = await self._start_mcp(ws_url, XHS_MCP_PORT)
                if not mcp_pid:
                    raise ValueError("启动小红书服务失败，暂时不能远端删除")
                await self._wait_mcp_ready(XHS_MCP_API)

            tools = await self._mcp_list_tools()
            tool = self._pick_mcp_tool(
                tools,
                candidates=("xhs_delete_note", "delete_note", "remove_note", "delete_feed"),
            )
            if not tool:
                raise XHSRemoteOperationUnsupported(
                    "当前 xiaohongshu-mcp 未提供“已发布内容删除”能力，请升级或切换支持该能力的版本。"
                )

            args = self._build_mcp_tool_args(
                tool=tool,
                mapping={
                    "feed_id": post.feed_id,
                    "note_id": post.feed_id,
                    "id": post.feed_id,
                    "xsec_token": post.xsec_token,
                },
            )
            await self._mcp_call_tool(tool["name"], args)

            post.status = "deleted"
            post.last_synced_at = utc_now_naive()
            await self.db.commit()
            await self.db.refresh(post)
            return post
        finally:
            if not mcp_running and mcp_pid is not None:
                await self._stop_mcp(mcp_pid)

    async def update_post(
        self,
        post: XHSPost,
        title: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
        ai_origin_type: str | None = None,
        scheduled_at: datetime | None = None,
    ) -> XHSPost:
        """更新帖子本地管理信息。"""
        if post.status in {"deleted"}:
            raise ValueError("已删除帖子不允许编辑")

        if title is not None:
            v = title.strip()
            if not v:
                raise ValueError("标题不能为空")
            if len(v) > 20:
                raise ValueError("标题不能超过20字")
            post.title = v

        if content is not None:
            v = content.strip()
            if not v:
                raise ValueError("正文不能为空")
            if len(v) > 1000:
                raise ValueError("正文不能超过1000字")
            post.content = v

        if tags is not None:
            post.tags = tags

        if ai_origin_type is not None:
            post.ai_origin_type = ai_origin_type

        if scheduled_at is not None:
            if post.status != "scheduled":
                raise ValueError("仅待发布任务可修改发布时间")
            normalized = self._normalize_to_utc_naive(scheduled_at)
            if normalized is None or normalized <= utc_now_naive() + timedelta(minutes=1):
                raise ValueError("定时发布时间必须晚于当前时间（至少 1 分钟）")
            post.scheduled_at = normalized

        await self.db.commit()
        await self.db.refresh(post)
        return post

    async def _mcp_list_tools(self) -> list[dict]:
        """Read MCP tools via streamable HTTP /mcp."""
        async with httpx.AsyncClient(timeout=20.0) as client:
            init_resp = await client.post(
                f"{XHS_MCP_API}/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "ztqc-backend", "version": "1.0"},
                    },
                },
            )
            if init_resp.status_code != 200:
                logger.warning(f"MCP initialize failed: status={init_resp.status_code}")
                return []

            session_id = init_resp.headers.get("Mcp-Session-Id") or init_resp.headers.get("mcp-session-id")
            headers = {"Content-Type": "application/json"}
            if session_id:
                headers["Mcp-Session-Id"] = session_id

            await client.post(
                f"{XHS_MCP_API}/mcp",
                headers=headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            )
            list_resp = await client.post(
                f"{XHS_MCP_API}/mcp",
                headers=headers,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            )
            if list_resp.status_code != 200:
                logger.warning(f"MCP tools/list failed: status={list_resp.status_code}")
                return []
            payload = list_resp.json()
            return list((payload.get("result") or {}).get("tools") or [])

    async def _mcp_call_tool(self, tool_name: str, arguments: dict) -> dict:
        async with httpx.AsyncClient(timeout=60.0) as client:
            init_resp = await client.post(
                f"{XHS_MCP_API}/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "ztqc-backend", "version": "1.0"},
                    },
                },
            )
            if init_resp.status_code != 200:
                raise ValueError("小红书服务初始化失败，暂时无法执行远端操作")

            session_id = init_resp.headers.get("Mcp-Session-Id") or init_resp.headers.get("mcp-session-id")
            headers = {"Content-Type": "application/json"}
            if session_id:
                headers["Mcp-Session-Id"] = session_id

            await client.post(
                f"{XHS_MCP_API}/mcp",
                headers=headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            )
            call_resp = await client.post(
                f"{XHS_MCP_API}/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
            )
            if call_resp.status_code != 200:
                raise ValueError(f"远端操作失败（HTTP {call_resp.status_code}）")
            payload = call_resp.json()
            if payload.get("error"):
                msg = payload["error"].get("message") or "远端操作失败"
                raise ValueError(msg)
            return payload.get("result") or {}

    @staticmethod
    def _pick_mcp_tool(tools: list[dict], candidates: tuple[str, ...]) -> dict | None:
        by_name = {str(tool.get("name")): tool for tool in tools}
        for name in candidates:
            if name in by_name:
                return by_name[name]
        return None

    @staticmethod
    def _build_mcp_tool_args(tool: dict, mapping: dict) -> dict:
        schema = tool.get("inputSchema") or {}
        properties = schema.get("properties") or {}
        required = schema.get("required") or []

        args: dict = {}
        for key in properties.keys():
            if key in mapping and mapping[key] is not None:
                args[key] = mapping[key]

        missing = [field for field in required if field not in args]
        if missing:
            raise XHSRemoteOperationUnsupported(
                f"当前远端工具参数不匹配（缺少: {', '.join(missing)}），无法安全执行。"
            )
        return args

    async def cancel_scheduled_post(self, post: XHSPost) -> XHSPost:
        """取消待发布任务。"""
        if post.status != "scheduled":
            raise ValueError("仅待发布任务可取消")
        post.status = "cancelled"
        await self.db.commit()
        await self.db.refresh(post)
        return post

    async def execute_post_by_id_for_worker(self, post_id: int) -> XHSPost:
        """供 Windows Worker 使用：执行指定帖子发布。"""
        self._require_local_browser_ops("执行小红书发布任务")
        result = await self.db.execute(select(XHSPost).where(XHSPost.id == post_id))
        post = result.scalar_one_or_none()
        if not post:
            raise ValueError("帖子不存在")
        if post.status not in ("publishing", "scheduled"):
            raise ValueError("仅 publishing/scheduled 状态任务可执行")

        env = await self.get_environment(post.environment_id)
        if not env:
            post.status = "failed"
            await self.db.commit()
            raise ValueError("帖子对应发布环境不存在")

        if post.status == "scheduled":
            post.scheduled_at = None
            post.status = "publishing"
            await self.db.commit()

        return await self._run_publish_with_guards(
            post=post,
            env=env,
            title=post.title,
            content=post.content,
            image_paths=post.image_urls or [],
            tags=post.tags or [],
            is_original=False,
            visibility="公开可见",
        )

    async def run_scheduled_post_now(self, post: XHSPost) -> XHSPost:
        """立即执行待发布任务。"""
        if post.status != "scheduled":
            raise ValueError("仅待发布任务可立即执行")
        if self._should_delegate_browser_ops():
            post.scheduled_at = None
            post.status = "publishing"
            await self.db.commit()
            await self.trigger_worker_publish(post.id)
            await self.db.refresh(post)
            return post
        env = await self.get_environment(post.environment_id)
        if not env:
            post.status = "failed"
            await self.db.commit()
            raise ValueError("帖子对应发布环境不存在")

        post.scheduled_at = None
        await self.db.commit()
        return await self._run_publish_with_guards(
            post=post,
            env=env,
            title=post.title,
            content=post.content,
            image_paths=post.image_urls or [],
            tags=post.tags or [],
            is_original=False,
            visibility="公开可见",
        )

    # ==================== 数据同步 ====================

    async def sync_single_post(self, post: XHSPost) -> bool:
        """兼容旧调用，仅返回是否成功。"""
        result = await self.sync_single_post_verbose(post)
        return result.success

    async def sync_single_post_verbose(self, post: XHSPost) -> PostSyncResult:
        """同步单个帖子的数据（返回可读失败原因）"""
        if self._should_delegate_browser_ops():
            try:
                await self.trigger_worker_sync_single_post(post.id)
                await self.db.refresh(post)
                return PostSyncResult(success=True, reason="worker_delegated", message="已通过 Windows Worker 完成同步")
            except Exception as e:
                return PostSyncResult(
                    success=False,
                    reason="worker_sync_failed",
                    message=str(e),
                )
        if not post.feed_id or not post.xsec_token:
            recovered_feed_id, recovered_xsec = await self._recover_published_identifiers(
                expected_title=post.title,
                expected_content=post.content,
                current_feed_id=post.feed_id,
                current_xsec_token=post.xsec_token,
            )
            if recovered_feed_id and recovered_xsec:
                post.feed_id = recovered_feed_id
                post.xsec_token = recovered_xsec
                post.post_url = self._build_post_url(recovered_feed_id, recovered_xsec)
                await self.db.commit()
            else:
                missing_fields: list[str] = []
                if not (recovered_feed_id or post.feed_id):
                    missing_fields.append("feed_id")
                if not (recovered_xsec or post.xsec_token):
                    missing_fields.append("xsec_token")
                missing_text = "、".join(missing_fields) if missing_fields else "feed_id 或 xsec_token"
                return PostSyncResult(
                    success=False,
                    reason="missing_identifiers",
                    message=f"帖子缺少 {missing_text}，无法同步（缺少 feed_id 或 xsec_token）",
                )

        if not post.feed_id or not post.xsec_token:
            return PostSyncResult(
                success=False,
                reason="missing_identifiers",
                message="帖子缺少 feed_id 或 xsec_token，无法同步",
            )

        try:
            scrape_env = await self._resolve_account_scrape_environment()
            use_external_mcp = bool(XHS_MCP_EXTERNAL_API)
            if use_external_mcp:
                result = await self._fetch_and_update_stats(post, XHS_MCP_EXTERNAL_API)
                if result.success:
                    return result
                if self._should_retry_once(result, 0):
                    await asyncio.sleep(1)
                    return await self._fetch_and_update_stats(post, XHS_MCP_EXTERNAL_API)
                return result

            ws_url = await self._acquire_ready_browser_ws(scrape_env.shop_id)
            if not ws_url:
                return PostSyncResult(
                    success=False,
                    reason="browser_start_failed",
                    message="采集浏览器启动或连接失败，请检查云登环境配置",
                )

            last_result: PostSyncResult | None = None
            for attempt in range(2):
                mcp_port = await self._allocate_free_port()
                mcp_api = f"http://localhost:{mcp_port}"
                mcp_pid = await self._start_mcp(ws_url, mcp_port)
                if not mcp_pid:
                    return PostSyncResult(
                        success=False,
                        reason="mcp_start_failed",
                        message="启动小红书同步服务失败，请检查 xiaohongshu-mcp 是否可用",
                    )
                try:
                    try:
                        await self._wait_mcp_ready(mcp_api)
                    except Exception:
                        return PostSyncResult(
                            success=False,
                            reason="mcp_not_ready",
                            message="小红书同步服务启动超时，请稍后重试",
                        )
                    result = await self._fetch_and_update_stats(post, mcp_api)
                finally:
                    await self._stop_mcp(mcp_pid)

                if result.success:
                    return result
                last_result = result
                if not self._should_retry_once(result, attempt):
                    return result
                await asyncio.sleep(1)

            return last_result or PostSyncResult(success=False, reason="unknown", message="同步失败")

        except Exception as e:
            logger.error(f"同步帖子 {post.id} 数据失败: {e}")
            return PostSyncResult(
                success=False,
                reason="unexpected_error",
                message=f"同步过程中出现异常: {e}",
            )

    async def _fetch_and_update_stats(self, post: XHSPost, api_base: str | None = None) -> PostSyncResult:
        """调用 xhs-mcp 获取帖子详情并更新统计"""
        max_attempts = 10
        last_error_message = ""
        resolved_api_base = self._resolve_active_mcp_api(api_base)

        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(**self._httpx_client_kwargs(resolved_api_base, timeout=30.0)) as client:
                    resp = await client.post(
                        f"{resolved_api_base}/api/v1/feeds/detail",
                        json={
                            "feed_id": post.feed_id,
                            "xsec_token": post.xsec_token,
                            "load_all_comments": False,
                        },
                    )
                    if resp.status_code != 200:
                        body_preview = (resp.text or "").strip().replace("\n", " ")
                        if len(body_preview) > 300:
                            body_preview = body_preview[:300] + "..."
                        last_error_message = body_preview

                        if self._is_temporary_unavailable_message(body_preview):
                            logger.warning(
                                "帖子详情临时不可用，自动重试: post_id=%s, attempt=%s/%s, body=%s",
                                post.id,
                                attempt,
                                max_attempts,
                                body_preview,
                            )
                            if attempt < max_attempts:
                                await asyncio.sleep(1.2)
                                continue
                            return PostSyncResult(
                                success=False,
                                reason="feed_detail_temporarily_unavailable",
                                message=f"帖子详情临时不可用，已重试 {max_attempts} 次，请稍后再试",
                            )

                        deleted_msg = self._extract_deleted_message(body_preview)
                        if not deleted_msg:
                            deleted_msg = await self._probe_deleted_from_post_url(post)
                        if deleted_msg:
                            post.status = "deleted"
                            await self.db.commit()
                            return PostSyncResult(
                                success=False,
                                reason="post_deleted",
                                message="帖子已删除或不可见，无法同步",
                            )
                        logger.warning(
                            f"帖子详情接口异常: status={resp.status_code}, post_id={post.id}, body={body_preview}"
                        )
                        msg = f"帖子详情接口异常（HTTP {resp.status_code}）"
                        if body_preview:
                            msg = f"{msg}: {body_preview}"
                        return PostSyncResult(
                            success=False,
                            reason="feed_detail_http_error",
                            message=msg,
                        )

                    try:
                        data = resp.json()
                    except ValueError:
                        logger.warning(f"帖子详情接口返回非 JSON: post_id={post.id}")
                        return PostSyncResult(
                            success=False,
                            reason="feed_detail_invalid_json",
                            message="帖子详情接口返回了非法数据格式",
                        )

                    if data.get("success") or data.get("code") == 0:
                        payload = data.get("data", {}) or {}
                        note = payload.get("note") or payload.get("data", {}).get("note") or {}
                        interact = note.get("interactInfo", {})

                        post.like_count = int(interact.get("likedCount", 0) or 0)
                        post.comment_count = int(interact.get("commentCount", 0) or 0)
                        post.collect_count = int(interact.get("collectedCount", 0) or 0)
                        post.share_count = int(interact.get("sharedCount", 0) or 0)
                        post.last_synced_at = utc_now_naive()

                        await self.db.commit()
                        return PostSyncResult(success=True, reason="ok", message="同步成功")
                    else:
                        err_msg = str(
                            data.get("message")
                            or data.get("error")
                            or data.get("msg")
                            or ""
                        )
                        last_error_message = err_msg
                        err_msg_lower = err_msg.lower()

                        if self._is_temporary_unavailable_message(err_msg):
                            logger.warning(
                                "帖子详情返回临时不可用，自动重试: post_id=%s, attempt=%s/%s, message=%s",
                                post.id,
                                attempt,
                                max_attempts,
                                err_msg,
                            )
                            if attempt < max_attempts:
                                await asyncio.sleep(1.2)
                                continue
                            return PostSyncResult(
                                success=False,
                                reason="feed_detail_temporarily_unavailable",
                                message=f"帖子详情临时不可用，已重试 {max_attempts} 次，请稍后再试",
                            )

                        # 仅在明确“帖子不存在/已删除”时才改为 deleted，避免临时异常误判
                        if self._extract_deleted_message(err_msg_lower):
                            post.status = "deleted"
                            await self.db.commit()
                            return PostSyncResult(
                                success=False,
                                reason="post_deleted",
                                message="帖子已删除或不可见，无法同步",
                            )

                        logger.warning(f"帖子详情返回失败但不标记删除: post_id={post.id}, message={err_msg_lower}")
                        display_msg = err_msg_lower or "未知错误"
                        return PostSyncResult(
                            success=False,
                            reason="feed_detail_failed",
                            message=f"帖子详情接口返回失败: {display_msg}",
                        )
            except Exception as e:
                err_text = str(e)
                last_error_message = err_text
                if self._is_retryable_sync_exception(err_text) and attempt < max_attempts:
                    logger.warning(
                        "同步详情异常，自动重试: post_id=%s, attempt=%s/%s, error=%s",
                        post.id,
                        attempt,
                        max_attempts,
                        err_text,
                    )
                    await asyncio.sleep(1.2)
                    continue

                logger.error(f"获取帖子详情失败: {e}")
                return PostSyncResult(
                    success=False,
                    reason="feed_detail_exception",
                    message=f"拉取帖子详情失败: {e}",
                )

        return PostSyncResult(
            success=False,
            reason="feed_detail_temporarily_unavailable",
            message=f"帖子详情临时不可用，已重试 {max_attempts} 次，请稍后再试: {last_error_message}",
        )

    async def _probe_deleted_from_post_url(self, post: XHSPost) -> str | None:
        """兜底检测：当 mcp 详情接口异常时，直接探测帖子 URL 是否为“页面不见了”"""
        if not post.post_url:
            return None
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(post.post_url)
                text = (resp.text or "").lower()
                deleted_markers = [
                    "你访问的页面不见了",
                    "页面不见了",
                    "note not found",
                    "该笔记不存在",
                    "内容无法查看",
                    "deleted",
                ]
                for marker in deleted_markers:
                    if marker.lower() in text:
                        return marker
            return None
        except Exception as e:
            logger.info(f"探测帖子 URL 失败: post_id={post.id}, error={e}")
            return None

    @staticmethod
    def _to_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _should_retry_once(result: PostSyncResult, attempt: int) -> bool:
        if attempt >= 1:
            return False
        return result.reason in {"feed_detail_http_error", "feed_detail_temporarily_unavailable"}

    @staticmethod
    def _extract_deleted_message(text: str) -> str | None:
        value = (text or "").lower()
        # 临时可恢复错误（例如 noteDetailMap 未就绪）不应判定为删除
        if XHSService._is_temporary_unavailable_message(value):
            return None
        deleted_markers = [
            "该内容因违规已被删除",
            "该笔记已被删除",
            "该笔记不存在",
            "笔记不存在",
            "note has been deleted",
            "note not found",
            "\"error\":\"deleted\"",
        ]
        for marker in deleted_markers:
            if marker in value:
                return marker
        return None

    @staticmethod
    def _is_temporary_unavailable_message(text: str) -> bool:
        value = (text or "").lower()
        markers = [
            "sorry, this page isn't available right now",
            "sorry this page isn't available right now",
            "page isn't available right now",
            "not found in notedetailmap",
            "feed detail not found in notedetailmap",
            "execution context was destroyed",
            "请打开小红书app扫码查看",
            "当前笔记暂时无法浏览",
            "temporarily unavailable",
        ]
        return any(marker in value for marker in markers)

    @staticmethod
    def _is_retryable_sync_exception(text: str) -> bool:
        value = (text or "").lower()
        markers = [
            "timed out",
            "timeout",
            "connection refused",
            "connection reset",
            "temporary failure",
            "context was destroyed",
            "broken pipe",
            "network is unreachable",
        ]
        return any(marker in value for marker in markers)

    async def sync_all_posts(self) -> int:
        """同步所有成功状态的帖子"""
        if self._should_delegate_browser_ops():
            return await self.trigger_worker_sync_all_posts()
        self._require_local_browser_ops("同步小红书帖子")
        result = await self.db.execute(
            select(XHSPost).where(XHSPost.status == "success")
        )
        posts = list(result.scalars().all())

        success_count = 0
        for post in posts:
            if await self.sync_single_post(post):
                success_count += 1
            # 避免请求过快
            await asyncio.sleep(2)

        return success_count

    # ==================== 图片上传 ====================

    async def save_upload_image(self, file_content: bytes, filename: str) -> str:
        """保存图片并返回本地绝对路径"""
        ext = os.path.splitext(filename)[1] or ".jpg"
        safe_name = f"xhs_{uuid.uuid4().hex}{ext}"

        upload_dir = os.path.join(settings.storage_path, "xhs")
        os.makedirs(upload_dir, exist_ok=True)

        file_path = os.path.join(upload_dir, safe_name)
        with open(file_path, "wb") as f:
            f.write(file_content)

        return os.path.abspath(file_path)

    async def _persist_account_note_cover_image(
        self,
        cover_image_url: str | None,
        *,
        existing_url: str | None = None,
        feed_id: str | None = None,
    ) -> str | None:
        source_url = str(cover_image_url or "").strip()
        current_url = str(existing_url or "").strip()

        if self._is_existing_upload_url_available(current_url):
            return current_url

        if not source_url:
            return current_url or None

        if self._is_existing_upload_url_available(source_url):
            return source_url

        if not (source_url.startswith("http://") or source_url.startswith("https://")):
            return source_url

        try:
            return await self._download_account_note_cover_to_local(source_url, feed_id=feed_id)
        except Exception as e:
            logger.warning("账号帖子封面图下载到本地失败: feed_id=%s url=%s error=%s", feed_id or "-", source_url, e)
            return source_url

    def _prepare_account_note_cover_image(
        self,
        cover_image_url: str | None,
        *,
        existing_url: str | None = None,
    ) -> tuple[str | None, str | None]:
        source_url = str(cover_image_url or "").strip()
        current_url = str(existing_url or "").strip()

        if self._is_existing_upload_url_available(current_url):
            return current_url, None
        if not source_url:
            return current_url or None, None
        if self._is_existing_upload_url_available(source_url):
            return source_url, None
        if source_url.startswith("http://") or source_url.startswith("https://"):
            return source_url, source_url
        return source_url, None

    async def _apply_pending_account_note_cover_localizations(
        self,
        pending_cover_localizations: list[tuple[int, str, str | None, str]],
    ) -> None:
        if not pending_cover_localizations:
            return

        updated = False
        seen_pairs: set[tuple[int, str, str]] = set()
        for environment_id, feed_id, current_cover_url, source_url in pending_cover_localizations:
            normalized_feed_id = str(feed_id or "").strip()
            if environment_id <= 0 or not normalized_feed_id or not source_url:
                continue
            pair_key = (int(environment_id), normalized_feed_id, source_url)
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            localized_url = await self._persist_account_note_cover_image(
                source_url,
                existing_url=current_cover_url,
                feed_id=normalized_feed_id,
            )
            if not localized_url or localized_url == current_cover_url:
                continue
            stmt = select(XHSAccountNote).where(
                and_(
                    XHSAccountNote.environment_id == int(environment_id),
                    XHSAccountNote.feed_id == normalized_feed_id,
                )
            )
            note = (await self.db.execute(stmt)).scalar_one_or_none()
            if note is None or note.cover_image_url == localized_url:
                continue
            note.cover_image_url = localized_url
            updated = True

        if updated:
            await self.db.commit()

    async def _download_account_note_cover_to_local(self, source_url: str, *, feed_id: str | None = None) -> str:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.xiaohongshu.com/",
        }
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
            resp = await client.get(source_url)
            resp.raise_for_status()
        if not resp.content:
            raise ValueError("远程图片响应为空")

        ext = self._guess_remote_image_extension(
            source_url,
            content_type=resp.headers.get("content-type"),
        )
        safe_feed_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(feed_id or "cover")).strip("_") or "cover"
        filename = f"{safe_feed_id}_{hashlib.md5(source_url.encode('utf-8')).hexdigest()[:12]}{ext}"
        local_path = await self.save_upload_image(resp.content, filename)
        return self.local_upload_path_to_url(local_path)

    @staticmethod
    def _is_existing_upload_url_available(candidate_url: str | None) -> bool:
        value = str(candidate_url or "").strip()
        if not value.startswith("/uploads/"):
            return False
        try:
            return os.path.exists(XHSService._uploads_url_to_local_path(value))
        except Exception:
            return False

    @staticmethod
    def _guess_remote_image_extension(source_url: str, *, content_type: str | None = None) -> str:
        content_type_text = (content_type or "").lower()
        if "png" in content_type_text:
            return ".png"
        if "webp" in content_type_text:
            return ".webp"
        if "gif" in content_type_text:
            return ".gif"
        if "jpeg" in content_type_text or "jpg" in content_type_text:
            return ".jpg"

        path = urlparse(source_url).path or ""
        ext = os.path.splitext(path)[1].lower()
        if ext in {".jpg", ".jpeg"}:
            return ".jpg"
        if ext in {".png", ".webp", ".gif"}:
            return ext
        return ".jpg"

    @staticmethod
    def local_upload_path_to_url(local_path: str) -> str:
        storage_root = Path(settings.storage_path).resolve()
        candidate = Path(local_path).resolve()
        storage_root_text = str(storage_root)
        candidate_text = str(candidate)
        if candidate_text != storage_root_text and not candidate_text.startswith(storage_root_text + os.sep):
            raise ValueError("图片路径不在 uploads 目录内")
        rel = candidate.relative_to(storage_root).as_posix()
        return f"/uploads/{rel}"

    async def _resolve_publish_image_paths(self, image_paths: list[str]) -> list[str]:
        """
        将发布请求里的图片来源统一转换为可发布的本地绝对路径。
        支持：
        - 本地绝对路径
        - /uploads/... 内部图库 URL
        - http(s) 远程 URL（下载后保存）
        - data:image/...;base64,...（解码后保存）
        """
        resolved: list[str] = []
        for raw in image_paths or []:
            item = str(raw or "").strip()
            if not item:
                continue
            local = await self._resolve_single_publish_image(item)
            local = self._map_publish_path_for_external_browser(local)
            resolved.append(local)
        if not resolved:
            raise ValueError("请至少上传1张图片")
        return resolved

    @staticmethod
    def _map_publish_path_for_external_browser(local_path: str) -> str:
        """
        外部 Windows 浏览器无法访问容器内 /app/uploads 路径。
        当配置了宿主机 uploads 根目录时，将容器路径映射为宿主机可见路径。
        """
        if not local_path or not XHS_HOST_UPLOAD_ROOT:
            return local_path

        try:
            candidate = Path(local_path).resolve()
            storage_root = Path(settings.storage_path).resolve()
            candidate_text = str(candidate)
            storage_root_text = str(storage_root)
            if candidate_text != storage_root_text and not candidate_text.startswith(storage_root_text + os.sep):
                return local_path

            rel = candidate.relative_to(storage_root)
            mapped = Path(XHS_HOST_UPLOAD_ROOT) / rel
            mapped_text = str(mapped)
            logger.info("发布图片路径映射: container=%s -> host=%s", local_path, mapped_text)
            return mapped_text
        except Exception as e:
            logger.warning("发布图片路径映射失败，继续使用容器路径: path=%s error=%s", local_path, e)
            return local_path

    async def _resolve_single_publish_image(self, value: str) -> str:
        # 内部图库 URL（本地存储）
        # 注意：/uploads/... 在 Linux 下同时也是“绝对路径”形式，
        # 必须优先于 os.path.isabs 判断，否则会被误判为 /uploads 真实目录。
        if value.startswith("/uploads/"):
            local = self._uploads_url_to_local_path(value)
            if os.path.exists(local):
                return local
            public_base = self._uploads_public_base_url()
            if public_base:
                remote_url = f"{public_base}{value}"
                try:
                    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                        resp = await client.get(remote_url)
                        resp.raise_for_status()
                    filename = os.path.basename(urlparse(value).path or "") or f"shared_{uuid.uuid4().hex}.jpg"
                    return await self.save_upload_image(resp.content, filename)
                except Exception as e:
                    raise ValueError(f"共享图库图片回源下载失败: {e}") from e
            raise ValueError("图库图片文件不存在，请重新上传或配置 UPLOADS_PUBLIC_BASE_URL")

        # 已是本地绝对路径
        if os.path.isabs(value):
            abs_path = os.path.abspath(value)
            if os.path.exists(abs_path):
                return abs_path
            raise ValueError(f"图片文件不存在: {value}")

        # file:// 路径
        if value.startswith("file://"):
            parsed = urlparse(value)
            file_path = unquote(parsed.path or "")
            if file_path and os.path.exists(file_path):
                return os.path.abspath(file_path)
            raise ValueError("file:// 图片路径不存在")

        # data:image base64
        if value.startswith("data:image/"):
            decoded = self._decode_data_image_url(value)
            if not decoded:
                raise ValueError("图库图片数据格式无效")
            content, ext = decoded
            filename = f"gallery_{uuid.uuid4().hex}{ext}"
            return await self.save_upload_image(content, filename)

        # 远程 URL，下载后落本地
        if value.startswith("http://") or value.startswith("https://"):
            try:
                async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                    resp = await client.get(value)
                    resp.raise_for_status()
                content_type = (resp.headers.get("content-type") or "").lower()
                ext = ".jpg"
                if "png" in content_type:
                    ext = ".png"
                elif "webp" in content_type:
                    ext = ".webp"
                elif "gif" in content_type:
                    ext = ".gif"
                filename = f"remote_{uuid.uuid4().hex}{ext}"
                return await self.save_upload_image(resp.content, filename)
            except Exception as e:
                raise ValueError(f"下载图库远程图片失败: {e}") from e

        # 兜底：按相对路径处理
        candidate = os.path.abspath(value)
        if os.path.exists(candidate):
            return candidate
        raise ValueError(f"不支持的图片路径: {value}")

    @staticmethod
    def _uploads_url_to_local_path(url: str) -> str:
        """
        /uploads/... => <storage_path>/...
        并校验路径不逃逸 storage 根目录。
        """
        rel = url[len("/uploads/"):] if url.startswith("/uploads/") else url.lstrip("/")
        rel = rel.split("?", 1)[0].split("#", 1)[0]
        rel = unquote(rel)
        storage_root = Path(settings.storage_path).resolve()
        local = (storage_root / rel).resolve()
        storage_root_text = str(storage_root)
        local_text = str(local)
        if local_text != storage_root_text and not local_text.startswith(storage_root_text + os.sep):
            raise ValueError("非法图片路径")
        return local_text

    @staticmethod
    def _decode_data_image_url(data_url: str) -> tuple[bytes, str] | None:
        # 格式：data:image/png;base64,xxxx
        m = re.match(r"^data:image/([a-zA-Z0-9.+-]+);base64,(.+)$", data_url, re.DOTALL)
        if not m:
            return None
        subtype = (m.group(1) or "").lower()
        payload = m.group(2) or ""
        try:
            content = base64.b64decode(payload, validate=False)
        except Exception:
            return None
        ext_map = {
            "jpeg": ".jpg",
            "jpg": ".jpg",
            "png": ".png",
            "webp": ".webp",
            "gif": ".gif",
        }
        ext = ext_map.get(subtype, ".jpg")
        return content, ext

    @staticmethod
    def _normalize_to_utc_naive(value: datetime | None) -> datetime | None:
        return aware_or_cst_naive_to_utc_naive(value)
