from __future__ import annotations

import asyncio
import copy
import logging
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Iterable

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.xhs_ad_account_assignment import XHSAdAccountBuyerAssignment, XHSAdAccountProfessionalMapping
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_report import (
    XHSAdStatsDailyAccount,
    XHSAdStatsDailyBrand,
    XHSAdStatsDailyContentTag,
    XHSAdStatsDailyNote,
    XHSReportDaily,
    XHSReportToken,
)
from app.core.roles import ROLE_BUYER, load_roles_for_users, normalize_roles
from app.db.session import async_session
from app.services.dashboard_snapshot_service import DashboardSnapshotService
from app.services.vehicle_catalog_service import VehicleCatalogService
from app.services.xhs_service import XHSService


BASE_REPORT_TYPES = ("simple", "standard")
NOTE_REPORT_TYPES = ("simple_note", "standard_note")
REPORT_TYPE_LABELS = {
    "simple": "简单投",
    "standard": "标准投",
    "creative": "创意报表",
    "simple_note": "简单投笔记报表",
    "standard_note": "标准投笔记报表",
}
_AD_DASHBOARD_CACHE_TTL_SECONDS = 300
_AD_CONTENT_TAG_CACHE_TTL_SECONDS = 900
_AD_ROW_CACHE_TTL_SECONDS = 900
_AD_DASHBOARD_CACHE_MAX_ENTRIES = 24
_AD_ROW_CACHE_MAX_ENTRIES = 16
_AD_DASHBOARD_SNAPSHOT_TTL_SECONDS = 21600
_AD_CONTENT_TAG_SNAPSHOT_TTL_SECONDS = 21600
_AD_DASHBOARD_NAMESPACE = "xhs_ad_dashboard"
_AD_CONTENT_TAG_NAMESPACE = "xhs_ad_content_tags"
_AD_CONTENT_TAG_COMPUTE_CONCURRENCY = 1
_ad_dashboard_cache: dict[tuple, tuple[float, dict]] = {}
_ad_content_tag_cache: dict[tuple, tuple[float, dict]] = {}
_ad_row_cache: dict[tuple, tuple[float, list[dict]]] = {}
_ad_content_tag_compute_semaphore: asyncio.Semaphore | None = None
_ad_content_tag_compute_loop: asyncio.AbstractEventLoop | None = None
_FALLBACK_BRANDS = (
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
_BRAND_ALIASES = {
    "奥迪AUDI": "奥迪",
    "上汽奥迪": "奥迪",
    "小鹏汽车": "小鹏",
    "岚图": "岚图汽车",
    "深蓝": "深蓝汽车",
    "零跑": "零跑汽车",
}
logger = logging.getLogger(__name__)


def _content_tag_compute_semaphore() -> asyncio.Semaphore:
    global _ad_content_tag_compute_loop, _ad_content_tag_compute_semaphore
    loop = asyncio.get_running_loop()
    if _ad_content_tag_compute_semaphore is None or _ad_content_tag_compute_loop is not loop:
        _ad_content_tag_compute_loop = loop
        _ad_content_tag_compute_semaphore = asyncio.Semaphore(_AD_CONTENT_TAG_COMPUTE_CONCURRENCY)
    return _ad_content_tag_compute_semaphore


def invalidate_ad_dashboard_caches() -> None:
    _ad_dashboard_cache.clear()
    _ad_content_tag_cache.clear()
    _ad_row_cache.clear()


def _to_float(value: object) -> float:
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


def _to_int(value: object) -> int:
    return int(round(_to_float(value)))


def _ratio(num: float, den: float) -> float:
    return float(num) / float(den) if den else 0.0


def _percent(num: float, den: float) -> float:
    return round(_ratio(num, den) * 100, 2)


def _round(value: float, digits: int = 2) -> float:
    return round(float(value or 0.0), digits)


def _get(row: dict, *keys: str) -> object:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _sum(row: dict, *keys: str) -> float:
    return sum(_to_float(row.get(key)) for key in keys)


def _metric(row: dict, *keys: str) -> float:
    value = _get(row, *keys)
    return _to_float(value)


def _row_time(row: dict, fallback: date | None = None) -> str:
    value = str(_get(row, "time", "report_date") or "").strip()
    return value or (fallback.isoformat() if fallback else "")


def _report_type_label(report_type: object) -> str:
    key = str(report_type or "").strip()
    return REPORT_TYPE_LABELS.get(key, key)


def _strip_brand_noise(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[🔴🟢🟡🟣🔵⭐️★☆]+", "", text)
    text = re.sub(r"^\s*(?:\d{1,2}[./月-]\d{1,2}(?:日)?|复投|新投|加投|续投|测试|素材|计划|推广)\s*", "", text)
    text = re.sub(r"\s+", "", text)
    return text.strip(" -_/#｜|·")


def _normalize_brand_candidate(value: object, brand_catalog: tuple[str, ...]) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    candidates = [raw]
    candidates.extend(part.strip() for part in re.split(r"[#＃/｜|,，;；\s]+", raw) if part.strip())
    for candidate in candidates:
        cleaned = _strip_brand_noise(candidate)
        if not cleaned:
            continue
        for alias, brand in _BRAND_ALIASES.items():
            if alias in cleaned:
                return brand
        for brand in brand_catalog:
            # Single-character catalog entries (for example the truck brand
            # "曼") must not match arbitrary account names such as "云特曼".
            if brand and (cleaned == brand or (len(brand) > 1 and brand in cleaned)):
                return brand
    return ""


def _interaction(row: dict) -> float:
    direct = _metric(row, "interaction")
    if direct:
        return direct
    return _sum(row, "like", "collect", "comment", "share", "follow")


def _conversion(row: dict) -> float:
    return _metric(row, "msg_leads_num", "valid_leads", "leads", "conversion", "conversions")


def _openings(row: dict) -> float:
    return _metric(row, "initiative_message", "msg_chat_user_cnt")


def _brand(row: dict, brand_catalog: tuple[str, ...]) -> str:
    for key in ("brand", "brand_name", "car_brand", "series_name", "sub_brand", "brandName"):
        value = _normalize_brand_candidate(row.get(key), brand_catalog)
        if value:
            return value
    text = str(_get(row, "campaign_name", "unit_name", "creativity_name", "note_title") or "")
    value = _normalize_brand_candidate(text, brand_catalog)
    if value:
        return value
    return "未知"


def _creative_tag(row: dict) -> str:
    ai_origin = str(row.get("ai_origin_type") or "").strip()
    if ai_origin:
        return {
            "manual": "人工素材",
            "text_ai": "文生图",
            "image_ai": "图生图",
            "all_ai": "全 AI",
        }.get(ai_origin, ai_origin)
    for key in ("creative_tag", "tag", "tag_name", "creative_type", "creative_style"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    name = str(_get(row, "creativity_name", "creative_name", "campaign_name", "unit_name") or "").strip()
    if "#" in name:
        parts = [part.strip() for part in name.split("#") if part.strip()]
        if parts:
            return parts[0]
    return "未标记"


def _note_id(row: dict) -> str:
    return str(_get(row, "note_id", "creative_id", "note_material", "feed_id", "material_id", "item_id") or "").strip()


def _note_title(row: dict) -> str:
    return str(_get(row, "note_title", "note_name", "creative_name", "creativity_name", "note_material") or "").strip() or "未命名笔记"


def _note_owner_name_from_values(profile_nickname: object, account_name: object) -> str:
    return (
        str(profile_nickname or "").strip()
        or str(account_name or "").strip()
        or "未知"
    )


def _clean_content_tag(tag: object) -> str:
    value = str(tag or "").strip().strip("#").strip()
    value = re.sub(r"[\[【(（]\s*话题\s*[\]】)）]?$", "", value).strip()
    value = re.sub(r"[#\s]*话题\s*[\]】)）]?$", "", value).strip()
    value = value.rstrip("#").strip()
    return value


def _valid_content_tag(tag: str) -> bool:
    value = _clean_content_tag(tag)
    if not value:
        return False
    if value.isdigit():
        return False
    return True


def _row_note_content_tag(
    row: dict,
    note_tag_map: dict[str, dict[str, str]],
    *,
    level: str = "primary",
    primary_tag: str | None = None,
) -> list[str]:
    nid = _note_id(row)
    note_tags = note_tag_map.get(nid) if nid else None
    if not note_tags:
        return []

    primary = _clean_content_tag(note_tags.get("primary") or "")
    secondary = _clean_content_tag(note_tags.get("secondary") or "")
    if primary_tag and primary != primary_tag:
        return []
    if level == "secondary":
        return [secondary or "未打二级标签"]
    return [primary] if primary else []


def _date_range(start_date: str | None, end_date: str | None, days: int = 30) -> tuple[date, date]:
    if end_date:
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    else:
        end = date.today() - timedelta(days=1)
    if start_date:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
    else:
        start = end - timedelta(days=max(1, days) - 1)
    if start > end:
        start, end = end, start
    return start, end


def _previous_range(start: date, end: date) -> tuple[date, date]:
    days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return prev_start, prev_end


def _snapshot_account_ids(account_ids: list[str] | None) -> list[str]:
    return sorted(str(item).strip() for item in (account_ids or []) if str(item).strip())


class XHSAdDashboardService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _load_snapshot(self, namespace: str, params: dict) -> dict | None:
        try:
            return await DashboardSnapshotService(self.db).get_payload(namespace, params)
        except Exception as exc:
            await self.db.rollback()
            logger.warning("Dashboard snapshot read skipped: namespace=%s error=%s", namespace, exc)
            return None

    async def _save_snapshot(self, namespace: str, params: dict, payload: dict, *, ttl_seconds: int) -> None:
        try:
            await DashboardSnapshotService(self.db).save_payload(namespace, params, payload, ttl_seconds=ttl_seconds)
        except Exception as exc:
            await self.db.rollback()
            logger.warning("Dashboard snapshot save skipped: namespace=%s error=%s", namespace, exc)

    async def _car_brand_catalog(self) -> tuple[str, ...]:
        brands = set(_FALLBACK_BRANDS)
        try:
            brands.update(await VehicleCatalogService(self.db).brands())
        except Exception:
            pass
        return tuple(sorted(brands, key=len, reverse=True))

    async def _report_revision(
        self,
        report_types: Iterable[str],
        start: date,
        end: date,
        account_ids: list[str] | None = None,
    ) -> dict:
        conditions = [
            XHSReportDaily.report_type.in_(list(report_types)),
            XHSReportDaily.report_date >= start,
            XHSReportDaily.report_date <= end,
        ]
        if account_ids:
            conditions.append(XHSReportDaily.account_id.in_(account_ids))
        try:
            row_count, max_updated_at = (
                await self.db.execute(
                    select(func.count(XHSReportDaily.id), func.max(XHSReportDaily.updated_at)).where(and_(*conditions))
                )
            ).one()
            return {
                "row_count": int(row_count or 0),
                "max_updated_at": max_updated_at.isoformat() if max_updated_at else "",
            }
        except Exception as exc:
            await self.db.rollback()
            logger.warning("Report revision fallback used: %s", exc)
            return {"row_count": 0, "max_updated_at": ""}

    async def _assignment_revision(self) -> dict[str, object]:
        try:
            row_count, max_assignment_updated_at, max_user_updated_at = (
                await self.db.execute(
                    select(
                        func.count(XHSAdAccountBuyerAssignment.id),
                        func.max(XHSAdAccountBuyerAssignment.updated_at),
                        func.max(User.updated_at),
                    ).select_from(XHSAdAccountBuyerAssignment).join(User, User.id == XHSAdAccountBuyerAssignment.user_id)
                )
            ).one()
            mapping_count, max_professional_mapping_updated_at = (
                await self.db.execute(
                    select(
                        func.count(XHSAdAccountProfessionalMapping.id),
                        func.max(XHSAdAccountProfessionalMapping.updated_at),
                    )
                )
            ).one()
            return {
                "row_count": int(row_count or 0),
                "max_assignment_updated_at": max_assignment_updated_at.isoformat() if max_assignment_updated_at else "",
                "max_user_updated_at": max_user_updated_at.isoformat() if max_user_updated_at else "",
                "professional_mapping_count": int(mapping_count or 0),
                "max_professional_mapping_updated_at": max_professional_mapping_updated_at.isoformat() if max_professional_mapping_updated_at else "",
            }
        except Exception as exc:
            await self.db.rollback()
            logger.warning("Assignment revision fallback used: %s", exc)
            return {
                "row_count": 0,
                "max_assignment_updated_at": "",
                "max_user_updated_at": "",
                "professional_mapping_count": 0,
                "max_professional_mapping_updated_at": "",
            }

    async def _assignments(self) -> dict[str, dict]:
        stmt = (
            select(
                XHSAdAccountBuyerAssignment.account_id,
                XHSAdAccountBuyerAssignment.account_name,
                User.id,
                User.username,
                User.display_name,
                User.email,
                User.role,
            )
            .join(User, User.id == XHSAdAccountBuyerAssignment.user_id)
        )
        result = await self.db.execute(stmt)
        rows = result.all()
        roles_by_user = await load_roles_for_users(self.db, [int(user_id) for _, _, user_id, _, _, _, _ in rows])
        return {
            str(account_id): {
                "account_id": str(account_id),
                "account_name": account_name,
                "buyer_user_id": user_id,
                "buyer_username": username,
                "buyer_display_name": display_name or username,
                "buyer_email": email,
            }
            for account_id, account_name, user_id, username, display_name, email, role in rows
            if ROLE_BUYER in (roles_by_user.get(int(user_id)) or normalize_roles([role], fallback=None))
        }

    async def _professional_mappings(self) -> dict[str, dict]:
        result = await self.db.execute(
            select(
                XHSAdAccountProfessionalMapping.account_id,
                XHSAdAccountProfessionalMapping.account_name,
                XHSAdAccountProfessionalMapping.xhs_account_id,
                XHSAdAccountProfessionalMapping.xhs_account_name,
                XHSAdAccountProfessionalMapping.xhs_owner_name,
            )
        )
        return {
            str(account_id): {
                "account_id": str(account_id),
                "account_name": account_name,
                "xhs_account_id": str(xhs_account_id or ""),
                "xhs_account_name": str(xhs_account_name or ""),
                "xhs_owner_name": str(xhs_owner_name or ""),
            }
            for account_id, account_name, xhs_account_id, xhs_account_name, xhs_owner_name in result.all()
            if str(account_id or "").strip() and str(xhs_account_id or "").strip()
        }

    async def _professional_options(self, allowed_account_ids: list[str] | None = None) -> list[dict]:
        mappings = await self._professional_mappings()
        allowed = {str(item) for item in allowed_account_ids} if allowed_account_ids is not None else None
        by_xhs: dict[str, dict] = {}
        for account_id, item in mappings.items():
            if allowed is not None and account_id not in allowed:
                continue
            xhs_account_id = str(item.get("xhs_account_id") or "")
            if not xhs_account_id:
                continue
            bucket = by_xhs.setdefault(xhs_account_id, {
                "xhs_account_id": xhs_account_id,
                "xhs_account_name": item.get("xhs_account_name") or xhs_account_id,
                "xhs_owner_name": item.get("xhs_owner_name") or "",
                "account_ids": [],
                "account_count": 0,
            })
            bucket["account_ids"].append(account_id)
            bucket["account_count"] += 1
        for bucket in by_xhs.values():
            bucket["account_ids"] = sorted(set(bucket["account_ids"]))
        return sorted(
            by_xhs.values(),
            key=lambda row: (str(row.get("xhs_owner_name") or ""), str(row.get("xhs_account_name") or "")),
        )

    @staticmethod
    def _filter_accounts_by_professionals(
        selected_account_ids: list[str],
        mappings: dict[str, dict],
        xhs_account_ids: list[str] | None,
    ) -> list[str]:
        selected_xhs_ids = {str(item).strip() for item in (xhs_account_ids or []) if str(item).strip()}
        if not selected_xhs_ids:
            return selected_account_ids
        professional_accounts = {
            account_id
            for account_id, item in mappings.items()
            if str(item.get("xhs_account_id") or "").strip() in selected_xhs_ids
        }
        if selected_account_ids:
            return sorted(set(selected_account_ids) & professional_accounts)
        return sorted(professional_accounts)

    async def account_options(self) -> list[dict]:
        return await self._account_options_for_buyer(None)

    async def _account_options_for_buyer(self, buyer_user_id: int | None = None) -> list[dict]:
        token_rows = (await self.db.execute(select(XHSReportToken))).scalars().all()
        assignments = await self._assignments()
        professional_mappings = await self._professional_mappings()
        accounts: dict[str, dict] = {}
        for row in token_rows:
            account_id = str(row.account_id)
            assignment = assignments.get(account_id) or {}
            professional = professional_mappings.get(account_id) or {}
            if buyer_user_id and int(assignment.get("buyer_user_id") or 0) != int(buyer_user_id):
                continue
            accounts[account_id] = {
                "account_id": row.account_id,
                "account_name": row.account_name,
                "token_status": row.token_status,
                "has_token": bool(row.token),
                "buyer_user_id": assignment.get("buyer_user_id"),
                "buyer_username": assignment.get("buyer_username"),
                "buyer_display_name": assignment.get("buyer_display_name"),
                "xhs_account_id": professional.get("xhs_account_id"),
                "xhs_account_name": professional.get("xhs_account_name"),
                "xhs_owner_name": professional.get("xhs_owner_name"),
            }
        if not accounts:
            daily_rows = await self.db.execute(
                select(XHSReportDaily.account_id, XHSReportDaily.account_name)
                .group_by(XHSReportDaily.account_id, XHSReportDaily.account_name)
            )
            for account_id, account_name in daily_rows.all():
                assignment = assignments.get(str(account_id)) or {}
                professional = professional_mappings.get(str(account_id)) or {}
                if buyer_user_id and int(assignment.get("buyer_user_id") or 0) != int(buyer_user_id):
                    continue
                accounts.setdefault(str(account_id), {
                    "account_id": str(account_id),
                    "account_name": account_name or str(account_id),
                    "token_status": None,
                    "has_token": False,
                    "buyer_user_id": assignment.get("buyer_user_id"),
                    "buyer_username": assignment.get("buyer_username"),
                    "buyer_display_name": assignment.get("buyer_display_name"),
                    "xhs_account_id": professional.get("xhs_account_id"),
                    "xhs_account_name": professional.get("xhs_account_name"),
                    "xhs_owner_name": professional.get("xhs_owner_name"),
                })
        return sorted(accounts.values(), key=lambda row: str(row["account_name"]))

    async def buyer_options(self) -> list[dict]:
        assignments = await self._assignments()
        by_user: dict[int, dict] = {}
        for item in assignments.values():
            user_id = int(item["buyer_user_id"])
            by_user.setdefault(user_id, {
                "user_id": user_id,
                "username": item["buyer_username"],
                "display_name": item.get("buyer_display_name") or item.get("buyer_username"),
                "email": item["buyer_email"],
                "account_count": 0,
            })
            by_user[user_id]["account_count"] += 1
        return sorted(by_user.values(), key=lambda item: str(item.get("display_name") or item.get("username") or ""))

    async def _rows(
        self,
        report_types: Iterable[str],
        start: date,
        end: date,
        account_ids: list[str] | None = None,
        attach_ai_origin: bool = True,
        limit: int | None = None,
    ) -> list[dict]:
        conditions = [
            XHSReportDaily.report_type.in_(list(report_types)),
            XHSReportDaily.report_date >= start,
            XHSReportDaily.report_date <= end,
        ]
        if account_ids:
            conditions.append(XHSReportDaily.account_id.in_(account_ids))
        stmt = select(
            XHSReportDaily.report_type,
            XHSReportDaily.payload,
            XHSReportDaily.report_date,
            XHSReportDaily.account_id,
            XHSReportDaily.account_name,
        ).where(and_(*conditions))
        if limit:
            stmt = stmt.order_by(XHSReportDaily.report_date.desc()).limit(limit)
        rows = (await self.db.execute(stmt)).all()
        result: list[dict] = []
        for report_type, payload, report_date, account_id, account_name in rows:
            normalized = XHSService._normalize_jg_report_row(
                report_type,
                payload or {},
                account_id=account_id,
                account_name=account_name,
            )
            normalized["report_type"] = report_type
            normalized["report_date"] = report_date.isoformat()
            normalized["account_id"] = account_id
            normalized["account_name"] = account_name
            result.append(normalized)
        if attach_ai_origin and "creative" in set(report_types):
            result = await XHSService(self.db)._attach_account_note_ai_origin_to_report_rows(result)
        return result

    @staticmethod
    async def _rows_new_session(
        report_types: Iterable[str],
        start: date,
        end: date,
        account_ids: list[str] | None = None,
        attach_ai_origin: bool = True,
        limit: int | None = None,
    ) -> list[dict]:
        cache_key = (
            "rows-v1",
            tuple(sorted(str(item) for item in report_types)),
            start.isoformat(),
            end.isoformat(),
            tuple(sorted(str(item).strip() for item in (account_ids or []) if str(item).strip())),
            bool(attach_ai_origin),
            int(limit or 0),
        )
        now = time.monotonic()
        cached = _ad_row_cache.get(cache_key)
        if cached and now - cached[0] <= _AD_ROW_CACHE_TTL_SECONDS:
            return copy.deepcopy(cached[1])

        async with async_session() as db:
            rows = await XHSAdDashboardService(db)._rows(
                report_types,
                start,
                end,
                account_ids,
                attach_ai_origin=attach_ai_origin,
                limit=limit,
            )
        if len(_ad_row_cache) >= _AD_ROW_CACHE_MAX_ENTRIES:
            oldest_key = min(_ad_row_cache, key=lambda key: _ad_row_cache[key][0])
            _ad_row_cache.pop(oldest_key, None)
        _ad_row_cache[cache_key] = (now, copy.deepcopy(rows))
        return rows

    async def _aggregate_account_rows(
        self,
        report_types: Iterable[str],
        start: date,
        end: date,
        account_ids: list[str] | None = None,
    ) -> list[dict]:
        conditions = [
            XHSAdStatsDailyAccount.report_type.in_(list(report_types)),
            XHSAdStatsDailyAccount.stat_date >= start,
            XHSAdStatsDailyAccount.stat_date <= end,
        ]
        if account_ids:
            conditions.append(XHSAdStatsDailyAccount.account_id.in_(account_ids))
        rows = (
            await self.db.execute(
                select(XHSAdStatsDailyAccount).where(and_(*conditions))
            )
        ).scalars().all()
        return [self._aggregate_account_row_to_metric(row) for row in rows]

    @staticmethod
    def _aggregate_account_row_to_metric(row: XHSAdStatsDailyAccount) -> dict:
        return {
            "report_type": row.report_type,
            "report_date": row.stat_date.isoformat(),
            "time": row.stat_date.isoformat(),
            "account_id": row.account_id,
            "account_name": row.account_name,
            "fee": row.fee,
            "impression": row.impression,
            "click": row.click,
            "message_consult": row.message_consult,
            "initiative_message": row.openings,
            "msg_chat_user_cnt": row.openings,
            "msg_leads_num": row.conversion,
            "interaction": row.interaction,
            "comment": row.comment,
            "special_natural_leads": row.special_natural_leads,
        }

    async def _aggregate_brand_rows(
        self,
        report_types: Iterable[str],
        start: date,
        end: date,
        account_ids: list[str] | None = None,
    ) -> list[dict]:
        conditions = [
            XHSAdStatsDailyBrand.report_type.in_(list(report_types)),
            XHSAdStatsDailyBrand.stat_date >= start,
            XHSAdStatsDailyBrand.stat_date <= end,
        ]
        if account_ids:
            conditions.append(XHSAdStatsDailyBrand.account_id.in_(account_ids))
        rows = (
            await self.db.execute(
                select(XHSAdStatsDailyBrand).where(and_(*conditions))
            )
        ).scalars().all()
        buckets: dict[str, dict] = {}
        for row in rows:
            bucket = buckets.setdefault(row.brand, {
                "brand": row.brand,
                "fee": 0.0,
                "impression": 0.0,
                "click": 0.0,
                "conversion": 0.0,
                "interaction": 0.0,
            })
            bucket["fee"] += float(row.fee or 0)
            bucket["impression"] += float(row.impression or 0)
            bucket["click"] += float(row.click or 0)
            bucket["conversion"] += float(row.conversion or 0)
            bucket["interaction"] += float(row.interaction or 0)
        return [
            {
                "brand": bucket["brand"],
                "fee": _round(bucket["fee"]),
                "impression": int(bucket["impression"]),
                "click": int(bucket["click"]),
                "ctr": _percent(bucket["click"], bucket["impression"]),
                "avg_click_cost": _round(_ratio(bucket["fee"], bucket["click"])),
                "conversion": int(bucket["conversion"]),
                "conversion_cost": _round(_ratio(bucket["fee"], bucket["conversion"])),
                "interaction": int(bucket["interaction"]),
            }
            for bucket in sorted(buckets.values(), key=lambda item: item["fee"], reverse=True)
        ]

    async def _aggregate_note_rows(
        self,
        report_types: Iterable[str],
        start: date,
        end: date,
        account_ids: list[str] | None = None,
    ) -> list[dict]:
        conditions = [
            XHSAdStatsDailyNote.report_type.in_(list(report_types)),
            XHSAdStatsDailyNote.stat_date >= start,
            XHSAdStatsDailyNote.stat_date <= end,
        ]
        if account_ids:
            conditions.append(XHSAdStatsDailyNote.account_id.in_(account_ids))
        rows = (
            await self.db.execute(
                select(XHSAdStatsDailyNote).where(and_(*conditions))
            )
        ).scalars().all()
        return [
            {
                "report_type": row.report_type,
                "report_date": row.stat_date.isoformat(),
                "time": row.stat_date.isoformat(),
                "account_id": row.account_id,
                "account_name": row.account_name,
                "note_id": row.note_id,
                "note_title": row.note_title,
                "note_name": row.note_title,
                "xhs_account_name": row.xhs_account_name,
                "primary_content_tag": row.primary_content_tag,
                "secondary_content_tag": row.secondary_content_tag,
                "fee": row.fee,
                "impression": row.impression,
                "click": row.click,
                "message_consult": row.message_consult,
                "initiative_message": row.openings,
                "msg_chat_user_cnt": row.openings,
                "msg_leads_num": row.conversion,
                "interaction": row.interaction,
            }
            for row in rows
        ]

    async def _aggregate_content_tag_rows(
        self,
        report_types: Iterable[str],
        start: date,
        end: date,
        account_ids: list[str] | None = None,
    ) -> list[dict]:
        conditions = [
            XHSAdStatsDailyContentTag.report_type.in_(list(report_types)),
            XHSAdStatsDailyContentTag.stat_date >= start,
            XHSAdStatsDailyContentTag.stat_date <= end,
        ]
        if account_ids:
            conditions.append(XHSAdStatsDailyContentTag.account_id.in_(account_ids))
        rows = (
            await self.db.execute(
                select(XHSAdStatsDailyContentTag).where(and_(*conditions))
            )
        ).scalars().all()
        return [
            {
                "report_type": row.report_type,
                "report_date": row.stat_date.isoformat(),
                "time": row.stat_date.isoformat(),
                "account_id": row.account_id,
                "account_name": row.account_name,
                "primary_content_tag": row.primary_content_tag,
                "secondary_content_tag": row.secondary_content_tag,
                "fee": row.fee,
                "conversion": row.conversion,
                "click": row.click,
                "interaction": row.interaction,
                "row_count": row.row_count,
            }
            for row in rows
        ]

    def _totals(self, rows: list[dict]) -> dict:
        fee = sum(_metric(row, "fee", "cost", "spend") for row in rows)
        impressions = sum(_metric(row, "impression", "show", "exposure") for row in rows)
        clicks = sum(_metric(row, "click") for row in rows)
        comments = sum(_metric(row, "comment") for row in rows)
        interactions = sum(_interaction(row) for row in rows)
        message_consult = sum(_metric(row, "message_consult") for row in rows)
        openings = sum(_openings(row) for row in rows)
        conversions = sum(_conversion(row) for row in rows)
        return {
            "fee": _round(fee),
            "impression": int(impressions),
            "click": int(clicks),
            "ctr": _percent(clicks, impressions),
            "avg_click_cost": _round(_ratio(fee, clicks)),
            "message_consult": int(message_consult),
            "openings": int(openings),
            "interaction": int(interactions),
            "interaction_rate": _percent(interactions, clicks),
            "opening_cost": _round(_ratio(fee, openings)),
            "conversion": int(conversions),
            "conversion_rate": _percent(conversions, clicks),
            "conversion_cost": _round(_ratio(fee, conversions)),
            "comment": int(comments),
        }

    def _kpis(self, current: dict, previous: dict) -> list[dict]:
        specs = [
            ("total_spend", "总消耗", "fee", "currency"),
            ("total_impression", "总曝光", "impression", "integer"),
            ("total_click", "总点击", "click", "integer"),
            ("ctr", "点击率", "ctr", "percent"),
            ("avg_click_cost", "平均点击成本", "avg_click_cost", "currency"),
            ("openings", "开口数", "openings", "integer"),
            ("interaction", "总互动量", "interaction", "integer"),
            ("interaction_rate", "互动率", "interaction_rate", "percent"),
            ("opening_cost", "开口成本", "opening_cost", "currency"),
            ("conversion", "总转化数", "conversion", "integer"),
            ("conversion_rate", "转化率", "conversion_rate", "percent"),
            ("conversion_cost", "平均转化成本", "conversion_cost", "currency"),
        ]
        items = []
        for key, label, metric_key, value_type in specs:
            value = current.get(metric_key, 0)
            prev = previous.get(metric_key, 0)
            delta = _round(float(value or 0) - float(prev or 0), 2)
            items.append({
                "key": key,
                "label": label,
                "value": value,
                "previous_value": prev,
                "delta": delta,
                "delta_rate": _percent(delta, float(prev or 0)) if prev else 0,
                "value_type": value_type,
            })
        return items

    def _buyer_label(self, account_id: str, assignments: dict[str, dict]) -> tuple[str, str]:
        assignment = assignments.get(str(account_id))
        if not assignment:
            return "unassigned", "未分配"
        label = assignment.get("buyer_display_name") or assignment.get("buyer_username") or "未命名投手"
        return f"user:{assignment['buyer_user_id']}", str(label)

    def _owner_rows(self, rows: list[dict], assignments: dict[str, dict]) -> list[dict]:
        buckets: dict[str, dict] = {}
        account_sets: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            account_id = str(row.get("account_id") or "")
            owner_key, owner_name = self._buyer_label(account_id, assignments)
            bucket = buckets.setdefault(owner_key, {
                "owner_key": owner_key,
                "owner_name": owner_name,
                "account_count": 0,
                "fee": 0.0,
                "conversion": 0.0,
                "impression": 0.0,
                "click": 0.0,
                "openings": 0.0,
                "comment": 0.0,
                "interaction": 0.0,
                "ad_leads": 0.0,
                "special_natural_leads": 0.0,
            })
            account_sets[owner_key].add(account_id)
            bucket["fee"] += _metric(row, "fee")
            conversion = _conversion(row)
            bucket["conversion"] += conversion
            bucket["impression"] += _metric(row, "impression")
            bucket["click"] += _metric(row, "click")
            bucket["openings"] += _openings(row)
            bucket["comment"] += _metric(row, "comment")
            bucket["interaction"] += _interaction(row)
            bucket["ad_leads"] += _metric(row, "msg_leads_num", "valid_leads")
            bucket["special_natural_leads"] += _metric(row, "special_natural_leads", "natural_leads", "organic_leads")
        result = []
        for owner_key, bucket in buckets.items():
            conversion = bucket["conversion"]
            item = {
                **bucket,
                "entity_type": "owner",
                "account_count": len(account_sets[owner_key]),
                "fee": _round(bucket["fee"]),
                "conversion": int(conversion),
                "conversion_cost": _round(_ratio(bucket["fee"], conversion)),
                "impression": int(bucket["impression"]),
                "click": int(bucket["click"]),
                "openings": int(bucket["openings"]),
                "opening_rate": _percent(bucket["openings"], bucket["click"]),
                "opening_conversion_rate": _percent(bucket["conversion"], bucket["openings"]),
                "opening_cost": _round(_ratio(bucket["fee"], bucket["openings"])),
                "comment": int(bucket["comment"]),
                "interaction": int(bucket["interaction"]),
                "ad_leads": int(bucket["ad_leads"]),
                "special_natural_leads": int(bucket["special_natural_leads"]),
            }
            result.append(item)
        return sorted(result, key=lambda item: item["fee"], reverse=True)

    def _account_rows(self, rows: list[dict], assignments: dict[str, dict]) -> list[dict]:
        buckets: dict[str, dict] = {}
        for row in rows:
            account_id = str(row.get("account_id") or "")
            assignment = assignments.get(account_id) or {}
            account_name = str(
                row.get("account_name")
                or assignment.get("account_name")
                or account_id
                or "未命名账户"
            )
            bucket = buckets.setdefault(account_id or account_name, {
                "owner_key": f"account:{account_id or account_name}",
                "owner_name": account_name,
                "account_id": account_id,
                "account_count": 1,
                "fee": 0.0,
                "conversion": 0.0,
                "impression": 0.0,
                "click": 0.0,
                "openings": 0.0,
                "comment": 0.0,
                "interaction": 0.0,
                "ad_leads": 0.0,
                "special_natural_leads": 0.0,
            })
            bucket["fee"] += _metric(row, "fee")
            conversion = _conversion(row)
            bucket["conversion"] += conversion
            bucket["impression"] += _metric(row, "impression")
            bucket["click"] += _metric(row, "click")
            bucket["openings"] += _openings(row)
            bucket["comment"] += _metric(row, "comment")
            bucket["interaction"] += _interaction(row)
            bucket["ad_leads"] += _metric(row, "msg_leads_num", "valid_leads")
            bucket["special_natural_leads"] += _metric(row, "special_natural_leads", "natural_leads", "organic_leads")
        result = []
        for bucket in buckets.values():
            conversion = bucket["conversion"]
            item = {
                **bucket,
                "entity_type": "account",
                "fee": _round(bucket["fee"]),
                "conversion": int(conversion),
                "conversion_cost": _round(_ratio(bucket["fee"], conversion)),
                "impression": int(bucket["impression"]),
                "click": int(bucket["click"]),
                "openings": int(bucket["openings"]),
                "opening_rate": _percent(bucket["openings"], bucket["click"]),
                "opening_conversion_rate": _percent(bucket["conversion"], bucket["openings"]),
                "opening_cost": _round(_ratio(bucket["fee"], bucket["openings"])),
                "comment": int(bucket["comment"]),
                "interaction": int(bucket["interaction"]),
                "ad_leads": int(bucket["ad_leads"]),
                "special_natural_leads": int(bucket["special_natural_leads"]),
            }
            result.append(item)
        return sorted(result, key=lambda item: item["fee"], reverse=True)

    async def _note_metadata_map(self, rows: list[dict]) -> dict[str, dict[str, str]]:
        note_ids = {_note_id(row) for row in rows if _note_id(row)}
        if not note_ids:
            return {}

        note_map: dict[str, dict[str, str]] = {}
        note_stmt = select(
            XHSAccountNote.feed_id,
            XHSAccountNote.primary_content_tag,
            XHSAccountNote.secondary_content_tag,
            XHSAccountNote.profile_nickname,
            XHSAccountNote.account_name,
        ).where(XHSAccountNote.feed_id.in_(note_ids))
        note_rows = (await self.db.execute(note_stmt)).all()
        for feed_id, primary_tag, secondary_tag, profile_nickname, account_name in note_rows:
            key = str(feed_id or "").strip()
            if not key:
                continue
            primary = _clean_content_tag(primary_tag)
            secondary = _clean_content_tag(secondary_tag)
            note_map[key] = {
                "primary": primary,
                "secondary": secondary,
                "owner_name": _note_owner_name_from_values(profile_nickname, account_name),
            }
        return note_map

    @staticmethod
    def _content_tag_map_from_metadata(note_map: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        return {
            key: {"primary": value.get("primary", ""), "secondary": value.get("secondary", "")}
            for key, value in note_map.items()
            if value.get("primary") or value.get("secondary")
        }

    @staticmethod
    def _note_owner_map_from_metadata(note_map: dict[str, dict[str, str]]) -> dict[str, str]:
        return {
            key: str(value.get("owner_name") or "未知")
            for key, value in note_map.items()
            if key
        }

    def _quadrant(
        self,
        rows: list[dict],
        note_tag_map: dict[str, dict[str, str]],
        *,
        level: str = "primary",
        primary_tag: str | None = None,
    ) -> dict:
        buckets = self._content_tag_buckets(rows, note_tag_map, level=level, primary_tag=primary_tag)
        points = self._content_tag_points(buckets)
        avg_x = _round(sum(item["x"] for item in points) / len(points)) if points else 0
        avg_y = _round(sum(item["y"] for item in points) / len(points)) if points else 0
        return {"avg_x": avg_x, "avg_y": avg_y, "points": sorted(points, key=lambda item: item["size"], reverse=True)}

    def _content_tag_buckets(
        self,
        rows: list[dict],
        note_tag_map: dict[str, dict[str, str]],
        *,
        level: str = "primary",
        primary_tag: str | None = None,
    ) -> dict[str, dict]:
        buckets: dict[str, dict] = {}
        for row in rows:
            tags = _row_note_content_tag(row, note_tag_map, level=level, primary_tag=primary_tag)
            for tag in tags:
                bucket = buckets.setdefault(tag, {"tag": tag, "fee": 0.0, "conversion": 0.0, "click": 0.0, "interaction": 0.0, "rows": 0})
                bucket["fee"] += _metric(row, "fee")
                bucket["conversion"] += _conversion(row)
                bucket["click"] += _metric(row, "click")
                bucket["interaction"] += _interaction(row)
                bucket["rows"] += 1
        return buckets

    @staticmethod
    def _add_content_tag_bucket_metric(bucket: dict, row_metrics: dict[str, float]) -> None:
        bucket["fee"] += row_metrics["fee"]
        bucket["conversion"] += row_metrics["conversion"]
        bucket["click"] += row_metrics["click"]
        bucket["interaction"] += row_metrics["interaction"]
        bucket["rows"] += 1

    @staticmethod
    def _content_tag_row_metrics(row: dict) -> dict[str, float]:
        return {
            "fee": _metric(row, "fee"),
            "conversion": _conversion(row),
            "click": _metric(row, "click"),
            "interaction": _interaction(row),
        }

    @staticmethod
    def _new_content_tag_bucket(tag: str) -> dict:
        return {"tag": tag, "fee": 0.0, "conversion": 0.0, "click": 0.0, "interaction": 0.0, "rows": 0}

    def _content_tag_points(self, buckets: dict[str, dict]) -> list[dict]:
        points: list[dict] = []
        for bucket in buckets.values():
            conversion = bucket["conversion"]
            if conversion <= 0:
                continue
            points.append({
                "tag": bucket["tag"],
                "x": _round(_ratio(bucket["fee"], conversion)),
                "y": int(conversion),
                "size": _round(bucket["fee"]),
                "click": int(bucket["click"]),
                "interaction": int(bucket["interaction"]),
                "row_count": bucket["rows"],
            })
        return points

    def _content_tag_payload(
        self,
        rows: list[dict],
        note_tag_map: dict[str, dict[str, str]],
        *,
        level: str = "primary",
        primary_tag: str | None = None,
    ) -> tuple[dict, list[dict]]:
        buckets = self._content_tag_buckets(rows, note_tag_map, level=level, primary_tag=primary_tag)
        return self._content_tag_payload_from_buckets(buckets)

    def _content_tag_payload_from_buckets(self, buckets: dict[str, dict]) -> tuple[dict, list[dict]]:
        points = sorted(self._content_tag_points(buckets), key=lambda item: item["size"], reverse=True)
        avg_x = _round(sum(item["x"] for item in points) / len(points)) if points else 0
        avg_y = _round(sum(item["y"] for item in points) / len(points)) if points else 0
        creative_tags = [
            {
                "tag": bucket["tag"],
                "fee": _round(bucket["fee"]),
                "conversion": int(bucket["conversion"]),
                "conversion_cost": _round(_ratio(bucket["fee"], bucket["conversion"])),
                "click": int(bucket["click"]),
                "interaction": int(bucket["interaction"]),
            }
            for bucket in sorted((item for item in buckets.values() if item["conversion"] > 0), key=lambda item: item["conversion"], reverse=True)[:20]
        ]
        return {"avg_x": avg_x, "avg_y": avg_y, "points": points}, creative_tags

    def _content_tag_tree_payload(
        self,
        rows: list[dict],
        note_tag_map: dict[str, dict[str, str]],
    ) -> tuple[dict, list[dict], dict[str, dict]]:
        primary_buckets: dict[str, dict] = {}
        child_buckets: dict[str, dict[str, dict]] = defaultdict(dict)
        for row in rows:
            nid = _note_id(row)
            note_tags = note_tag_map.get(nid) if nid else None
            if not note_tags:
                continue
            primary_tag = _clean_content_tag(note_tags.get("primary") or "")
            if not primary_tag:
                continue
            secondary_tag = _clean_content_tag(note_tags.get("secondary") or "") or "未打二级标签"
            row_metrics = self._content_tag_row_metrics(row)
            primary_bucket = primary_buckets.setdefault(primary_tag, self._new_content_tag_bucket(primary_tag))
            self._add_content_tag_bucket_metric(primary_bucket, row_metrics)
            secondary_buckets = child_buckets.setdefault(primary_tag, {})
            secondary_bucket = secondary_buckets.setdefault(secondary_tag, self._new_content_tag_bucket(secondary_tag))
            self._add_content_tag_bucket_metric(secondary_bucket, row_metrics)

        quadrant, creative_tags = self._content_tag_payload_from_buckets(primary_buckets)
        children: dict[str, dict] = {}
        for primary_tag, buckets in child_buckets.items():
            child_quadrant, child_creative_tags = self._content_tag_payload_from_buckets(buckets)
            children[primary_tag] = {
                "quadrant": child_quadrant,
                "creative_tags": child_creative_tags,
                "content_tag_level": "secondary",
                "content_tag_primary": primary_tag,
            }
        return quadrant, creative_tags, children

    def _content_tag_tree_payload_from_aggregate_rows(
        self,
        rows: list[dict],
    ) -> tuple[dict, list[dict], dict[str, dict]]:
        primary_buckets: dict[str, dict] = {}
        child_buckets: dict[str, dict[str, dict]] = defaultdict(dict)
        for row in rows:
            primary_tag = _clean_content_tag(row.get("primary_content_tag") or "")
            if not primary_tag:
                continue
            secondary_tag = _clean_content_tag(row.get("secondary_content_tag") or "") or "未打二级标签"
            row_metrics = {
                "fee": _metric(row, "fee"),
                "conversion": _conversion(row),
                "click": _metric(row, "click"),
                "interaction": _interaction(row),
            }
            primary_bucket = primary_buckets.setdefault(primary_tag, self._new_content_tag_bucket(primary_tag))
            self._add_content_tag_bucket_metric(primary_bucket, row_metrics)
            primary_bucket["rows"] += max(0, int(_metric(row, "row_count") or 0)) - 1

            secondary_buckets = child_buckets.setdefault(primary_tag, {})
            secondary_bucket = secondary_buckets.setdefault(secondary_tag, self._new_content_tag_bucket(secondary_tag))
            self._add_content_tag_bucket_metric(secondary_bucket, row_metrics)
            secondary_bucket["rows"] += max(0, int(_metric(row, "row_count") or 0)) - 1

        quadrant, creative_tags = self._content_tag_payload_from_buckets(primary_buckets)
        children: dict[str, dict] = {}
        for primary_tag, buckets in child_buckets.items():
            child_quadrant, child_creative_tags = self._content_tag_payload_from_buckets(buckets)
            children[primary_tag] = {
                "quadrant": child_quadrant,
                "creative_tags": child_creative_tags,
                "content_tag_level": "secondary",
                "content_tag_primary": primary_tag,
            }
        return quadrant, creative_tags, children

    def _content_tag_payload_from_aggregate_rows(
        self,
        rows: list[dict],
        *,
        level: str = "primary",
        primary_tag: str | None = None,
    ) -> tuple[dict, list[dict]]:
        buckets: dict[str, dict] = {}
        selected_primary = _clean_content_tag(primary_tag)
        for row in rows:
            primary = _clean_content_tag(row.get("primary_content_tag") or "")
            if selected_primary and primary != selected_primary:
                continue
            tag = _clean_content_tag(row.get("secondary_content_tag") or "") if level == "secondary" else primary
            tag = tag or ("未打二级标签" if level == "secondary" else "")
            if not tag:
                continue
            bucket = buckets.setdefault(tag, self._new_content_tag_bucket(tag))
            self._add_content_tag_bucket_metric(bucket, {
                "fee": _metric(row, "fee"),
                "conversion": _conversion(row),
                "click": _metric(row, "click"),
                "interaction": _interaction(row),
            })
            bucket["rows"] += max(0, int(_metric(row, "row_count") or 0)) - 1
        return self._content_tag_payload_from_buckets(buckets)

    def _funnel(self, rows: list[dict]) -> list[dict]:
        totals = self._totals(rows)
        values = [
            ("曝光", totals["impression"]),
            ("点击", totals["click"]),
            ("咨询", totals["message_consult"]),
            ("开口", totals["openings"]),
            ("转化", totals["conversion"]),
        ]
        first = float(values[0][1] or 0)
        prev = first
        result = []
        for label, value in values:
            result.append({
                "label": label,
                "value": int(value),
                "overall_rate": _percent(float(value), first),
                "step_rate": _percent(float(value), prev),
            })
            prev = float(value or 0)
        return result

    def _creative_tags(self, rows: list[dict], note_tag_map: dict[str, dict[str, str]]) -> list[dict]:
        buckets = self._content_tag_buckets(rows, note_tag_map)
        return [
            {
                "tag": bucket["tag"],
                "fee": _round(bucket["fee"]),
                "conversion": int(bucket["conversion"]),
                "conversion_cost": _round(_ratio(bucket["fee"], bucket["conversion"])),
                "click": int(bucket["click"]),
                "interaction": int(bucket["interaction"]),
            }
            for bucket in sorted(buckets.values(), key=lambda item: item["conversion"], reverse=True)[:20]
        ]

    def _top_notes(self, rows: list[dict], note_owner_map: dict[str, str] | None = None) -> dict:
        note_owner_map = note_owner_map or {}
        buckets: dict[str, dict] = {}
        for row in rows:
            nid = _note_id(row)
            if not nid:
                continue
            bucket = buckets.setdefault(nid, {
                "note_id": nid,
                "note_title": _note_title(row),
                "creative_tag": _creative_tag(row),
                "account_name": str(row.get("account_name") or ""),
                "xhs_account_name": note_owner_map.get(nid, "未知"),
                "fee": 0.0,
                "impression": 0.0,
                "click": 0.0,
                "conversion": 0.0,
                "message_consult": 0.0,
                "openings": 0.0,
                "interaction": 0.0,
            })
            bucket["fee"] += _metric(row, "fee")
            bucket["impression"] += _metric(row, "impression")
            bucket["click"] += _metric(row, "click")
            bucket["conversion"] += _conversion(row)
            bucket["message_consult"] += _metric(row, "message_consult")
            bucket["openings"] += _openings(row)
            bucket["interaction"] += _interaction(row)

        normalized = []
        for bucket in buckets.values():
            normalized.append({
                **bucket,
                "fee": _round(bucket["fee"]),
                "impression": int(bucket["impression"]),
                "click": int(bucket["click"]),
                "conversion": int(bucket["conversion"]),
                "conversion_rate": _percent(bucket["conversion"], bucket["click"]),
                "conversion_cost": _round(_ratio(bucket["fee"], bucket["conversion"])),
                "message_consult": int(bucket["message_consult"]),
                "openings": int(bucket["openings"]),
                "initiative_message": int(bucket["openings"]),
                "interaction": int(bucket["interaction"]),
            })
        if not normalized:
            return {}
        score_keys = ("conversion", "conversion_rate", "impression", "message_consult", "initiative_message")
        max_by_key = {key: max(float(item.get(key) or 0) for item in normalized) for key in score_keys}
        for item in normalized:
            scores = [
                _ratio(float(item.get(key) or 0), max_by_key[key]) * 100
                for key in score_keys
                if max_by_key[key] > 0
            ]
            item["score"] = _round(sum(scores) / len(scores)) if scores else 0.0
        return {
            "conversion": max(normalized, key=lambda item: item["conversion"]),
            "conversion_rate": max(normalized, key=lambda item: item["conversion_rate"]),
            "impression": max(normalized, key=lambda item: item["impression"]),
            "message_consult": max(normalized, key=lambda item: item["message_consult"]),
            "initiative_message": max(normalized, key=lambda item: item["initiative_message"]),
        }

    def _comparison_rows(
        self,
        current_rows: list[dict],
        previous_rows: list[dict],
        assignments: dict[str, dict],
        *,
        dimension: str = "owner",
    ) -> list[dict]:
        row_builder = self._account_rows if dimension == "account" else self._owner_rows
        current = {row["owner_key"]: row for row in row_builder(current_rows, assignments)}
        previous = {row["owner_key"]: row for row in row_builder(previous_rows, assignments)}
        keys = set(current) | set(previous)
        result = []
        for key in keys:
            if key == "unassigned":
                continue
            cur = current.get(key, {})
            prev = previous.get(key, {})
            owner_name = cur.get("owner_name") or prev.get("owner_name") or key
            if str(owner_name).startswith("user:"):
                continue
            current_opening_rate = _percent(float(cur.get("openings") or 0), float(cur.get("click") or 0))
            previous_opening_rate = _percent(float(prev.get("openings") or 0), float(prev.get("click") or 0))
            current_opening_cost = _round(_ratio(float(cur.get("fee") or 0), float(cur.get("openings") or 0)))
            previous_opening_cost = _round(_ratio(float(prev.get("fee") or 0), float(prev.get("openings") or 0)))
            def diff(metric: str) -> float:
                return _round(float(cur.get(metric) or 0) - float(prev.get(metric) or 0), 2)
            result.append({
                "owner_key": key,
                "owner_name": owner_name,
                "entity_type": cur.get("entity_type") or prev.get("entity_type") or ("account" if dimension == "account" else "owner"),
                "fee_current": _round(float(cur.get("fee") or 0)),
                "fee_previous": _round(float(prev.get("fee") or 0)),
                "fee_delta": diff("fee"),
                "conversion_current": int(float(cur.get("conversion") or 0)),
                "conversion_previous": int(float(prev.get("conversion") or 0)),
                "conversion_delta": diff("conversion"),
                "conversion_cost_current": _round(float(cur.get("conversion_cost") or 0)),
                "conversion_cost_previous": _round(float(prev.get("conversion_cost") or 0)),
                "conversion_cost_delta": diff("conversion_cost"),
                "opening_rate_current": current_opening_rate,
                "opening_rate_previous": previous_opening_rate,
                "opening_rate_delta": _round(current_opening_rate - previous_opening_rate),
                "opening_cost_current": current_opening_cost,
                "opening_cost_previous": previous_opening_cost,
                "opening_cost_delta": _round(current_opening_cost - previous_opening_cost),
            })
        return sorted(result, key=lambda item: abs(item["fee_delta"]), reverse=True)

    def _trend(self, rows: list[dict], start: date, end: date) -> list[dict]:
        buckets: dict[str, dict] = {}
        cursor = start
        while cursor <= end:
            key = cursor.isoformat()
            buckets[key] = {
                "date": key,
                "fee": 0.0,
                "conversion": 0.0,
                "click": 0.0,
                "impression": 0.0,
                "interaction": 0.0,
                "openings": 0.0,
            }
            cursor += timedelta(days=1)
        for row in rows:
            key = _row_time(row)[:10]
            if key not in buckets:
                continue
            buckets[key]["fee"] += _metric(row, "fee")
            buckets[key]["conversion"] += _conversion(row)
            buckets[key]["click"] += _metric(row, "click")
            buckets[key]["impression"] += _metric(row, "impression")
            buckets[key]["interaction"] += _interaction(row)
            buckets[key]["openings"] += _openings(row)
        return [
            {
                "date": item["date"],
                "fee": _round(item["fee"]),
                "conversion": int(item["conversion"]),
                "click": int(item["click"]),
                "impression": int(item["impression"]),
                "interaction": int(item["interaction"]),
                "openings": int(item["openings"]),
            }
            for item in buckets.values()
        ]

    def _brand_rows(self, rows: list[dict], brand_catalog: tuple[str, ...]) -> list[dict]:
        buckets: dict[str, dict] = {}
        for row in rows:
            brand = _brand(row, brand_catalog)
            bucket = buckets.setdefault(brand, {"brand": brand, "fee": 0.0, "impression": 0.0, "click": 0.0, "conversion": 0.0, "interaction": 0.0})
            bucket["fee"] += _metric(row, "fee")
            bucket["impression"] += _metric(row, "impression")
            bucket["click"] += _metric(row, "click")
            bucket["conversion"] += _conversion(row)
            bucket["interaction"] += _interaction(row)
        return [
            {
                "brand": bucket["brand"],
                "fee": _round(bucket["fee"]),
                "impression": int(bucket["impression"]),
                "click": int(bucket["click"]),
                "ctr": _percent(bucket["click"], bucket["impression"]),
                "avg_click_cost": _round(_ratio(bucket["fee"], bucket["click"])),
                "conversion": int(bucket["conversion"]),
                "conversion_cost": _round(_ratio(bucket["fee"], bucket["conversion"])),
                "interaction": int(bucket["interaction"]),
            }
            for bucket in sorted(buckets.values(), key=lambda item: item["fee"], reverse=True)
        ]

    def _note_rows(self, rows: list[dict], note_owner_map: dict[str, str] | None = None) -> list[dict]:
        note_owner_map = note_owner_map or {}
        buckets: dict[str, dict] = {}
        for row in rows:
            nid = _note_id(row)
            if not nid:
                continue
            bucket = buckets.setdefault(nid, {
                "note_id": nid,
                "note_title": _note_title(row),
                "account_name": str(row.get("account_name") or ""),
                "report_types": set(),
                "fee": 0.0,
                "impression": 0.0,
                "click": 0.0,
                "openings": 0.0,
                "conversion": 0.0,
                "interaction": 0.0,
            })
            bucket["report_types"].add(row.get("report_type"))
            bucket["fee"] += _metric(row, "fee")
            bucket["impression"] += _metric(row, "impression")
            bucket["click"] += _metric(row, "click")
            bucket["openings"] += _openings(row)
            bucket["conversion"] += _conversion(row)
            bucket["interaction"] += _interaction(row)
        items = []
        for bucket in buckets.values():
            report_types = sorted(str(x) for x in bucket["report_types"] if x)
            items.append({
                "note_id": bucket["note_id"],
                "note_title": bucket["note_title"],
                "account_name": bucket["account_name"],
                "xhs_account_name": note_owner_map.get(bucket["note_id"], "未知"),
                "report_types": [_report_type_label(report_type) for report_type in report_types],
                "fee": _round(bucket["fee"]),
                "impression": int(bucket["impression"]),
                "click": int(bucket["click"]),
                "ctr": _percent(bucket["click"], bucket["impression"]),
                "avg_click_cost": _round(_ratio(bucket["fee"], bucket["click"])),
                "openings": int(bucket["openings"]),
                "conversion": int(bucket["conversion"]),
                "conversion_cost": _round(_ratio(bucket["fee"], bucket["conversion"])),
                "opening_conversion_rate": _percent(bucket["conversion"], bucket["openings"]),
                "interaction": int(bucket["interaction"]),
            })
        return sorted(items, key=lambda item: item["fee"], reverse=True)

    def _ai_summary(self, totals: dict, owner_rows: list[dict], brand_rows: list[dict]) -> dict:
        top_owner = owner_rows[0]["owner_name"] if owner_rows else "暂无负责人"
        top_brand = brand_rows[0]["brand"] if brand_rows else "暂无品牌"
        return {
            "title": "投流数据摘要",
            "summary": f"本周期总消耗 {totals['fee']}，产生 {totals['conversion']} 个转化，平均转化成本 {totals['conversion_cost']}。消耗最高负责人为 {top_owner}，品牌侧贡献最高为 {top_brand}。",
            "actions": [
                "优先复盘高消耗低转化计划，确认素材承接和私信入口是否一致。",
                "保留低 CPA 且转化量高的计划作为放量池，避免频繁重置学习期。",
                "未分配账户建议先完成投手归属，后续负责人表才能稳定追责。",
            ],
        }

    async def dashboard(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        days: int = 30,
        account_ids: list[str] | None = None,
        xhs_account_ids: list[str] | None = None,
        report_type: str = "all",
        buyer_user_id: int | None = None,
        include_content_tags: bool = True,
        force_refresh: bool = False,
        viewer_scope: str = "all",
    ) -> dict:
        start, end = _date_range(start_date, end_date, days)
        prev_start, prev_end = _previous_range(start, end)
        assignments = await self._assignments()
        professional_mappings = await self._professional_mappings()
        selected_account_ids = [str(x).strip() for x in account_ids or [] if str(x).strip()]
        selected_xhs_account_ids = [str(x).strip() for x in xhs_account_ids or [] if str(x).strip()]
        if buyer_user_id:
            buyer_accounts = [account_id for account_id, item in assignments.items() if int(item.get("buyer_user_id") or 0) == buyer_user_id]
            selected_account_ids = sorted(set(selected_account_ids) & set(buyer_accounts)) if selected_account_ids else buyer_accounts
        selected_account_ids = self._filter_accounts_by_professionals(selected_account_ids, professional_mappings, selected_xhs_account_ids)
        row_account_ids = selected_account_ids if selected_account_ids or not (buyer_user_id or selected_xhs_account_ids) else ["__no_matched_filter_account__"]
        assignment_revision = await self._assignment_revision()

        base_types = BASE_REPORT_TYPES if report_type == "all" else (report_type,)
        base_types = tuple(item for item in base_types if item in BASE_REPORT_TYPES)
        if not base_types:
            base_types = BASE_REPORT_TYPES

        cache_key = (
            "content-tag-tree-v3",
            start.isoformat(),
            end.isoformat(),
            tuple(sorted(selected_account_ids)),
            tuple(sorted(selected_xhs_account_ids)),
            tuple(base_types),
            report_type,
            int(buyer_user_id or 0),
            str(viewer_scope or "all"),
            bool(include_content_tags),
            tuple(sorted(assignment_revision.items())),
        )
        now = time.monotonic()
        cached = _ad_dashboard_cache.get(cache_key)
        if not force_refresh and cached and now - cached[0] <= _AD_DASHBOARD_CACHE_TTL_SECONDS:
            return copy.deepcopy(cached[1])

        snapshot_params = {
            "version": "ad-dashboard-v2-aggregate",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "previous_start_date": prev_start.isoformat(),
            "previous_end_date": prev_end.isoformat(),
            "account_ids": _snapshot_account_ids(selected_account_ids),
            "xhs_account_ids": _snapshot_account_ids(selected_xhs_account_ids),
            "row_account_ids": _snapshot_account_ids(row_account_ids),
            "report_type": report_type,
            "base_types": list(base_types),
            "buyer_user_id": int(buyer_user_id or 0),
            "viewer_scope": str(viewer_scope or "all"),
            "include_content_tags": bool(include_content_tags),
            "report_revision": await self._report_revision(base_types, prev_start, end, row_account_ids),
            "assignment_revision": assignment_revision,
        }
        snapshot_payload = None if force_refresh else await self._load_snapshot(_AD_DASHBOARD_NAMESPACE, snapshot_params)
        if not force_refresh and snapshot_payload:
            _ad_dashboard_cache[cache_key] = (now, copy.deepcopy(snapshot_payload))
            return snapshot_payload

        current_rows, previous_rows = await asyncio.gather(
            self._aggregate_account_rows(base_types, start, end, row_account_ids),
            self._aggregate_account_rows(base_types, prev_start, prev_end, row_account_ids),
        )
        used_aggregates = bool(current_rows or previous_rows)
        if not used_aggregates:
            current_rows, previous_rows = await asyncio.gather(
                self._rows_new_session(base_types, start, end, row_account_ids),
                self._rows_new_session(base_types, prev_start, prev_end, row_account_ids),
            )
        totals = self._totals(current_rows)
        previous_totals = self._totals(previous_rows)
        entity_dimension = "account" if buyer_user_id else "owner"
        owner_rows = self._account_rows(current_rows, assignments) if buyer_user_id else self._owner_rows(current_rows, assignments)
        brand_rows = await self._aggregate_brand_rows(base_types, start, end, row_account_ids) if used_aggregates else self._brand_rows(current_rows, await self._car_brand_catalog())
        content_payload = await self.content_tag_modules(
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            account_ids=row_account_ids,
            xhs_account_ids=None,
            report_type=report_type,
            buyer_user_id=buyer_user_id,
            force_refresh=force_refresh,
            viewer_scope=viewer_scope,
        ) if include_content_tags else {
            "quadrant": {"avg_x": 0, "avg_y": 0, "points": []},
            "creative_tags": [],
            "top_notes": {},
            "note_rows": [],
        }
        filter_account_options = await self._account_options_for_buyer(
            buyer_user_id if str(viewer_scope or "").startswith("buyer:self:") else None
        )
        xhs_professional_options = await self._professional_options(
            [item["account_id"] for item in filter_account_options]
        )

        payload = {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "previous_start_date": prev_start.isoformat(),
            "previous_end_date": prev_end.isoformat(),
            "filters": {
                "account_ids": selected_account_ids,
                "xhs_account_ids": selected_xhs_account_ids,
                "report_type": report_type,
                "buyer_user_id": buyer_user_id,
                "viewer_scope": str(viewer_scope or "all"),
                "accounts": filter_account_options,
                "buyers": await self.buyer_options(),
                "xhs_accounts": xhs_professional_options,
            },
            "summary": totals,
            "kpis": self._kpis(totals, previous_totals),
            "owner_rows": owner_rows,
            "quadrant": content_payload["quadrant"],
            "funnel": self._funnel(current_rows),
            "creative_tags": content_payload["creative_tags"],
            "top_notes": content_payload["top_notes"],
            "comparison_rows": self._comparison_rows(current_rows, previous_rows, assignments, dimension=entity_dimension),
            "trend": self._trend(current_rows, start, end),
            "brand_rows": brand_rows,
            "note_rows": content_payload["note_rows"],
            "ai_summary": self._ai_summary(totals, owner_rows, brand_rows),
            "data_source": "aggregate" if used_aggregates else "raw",
        }
        if len(_ad_dashboard_cache) >= _AD_DASHBOARD_CACHE_MAX_ENTRIES:
            oldest_key = min(_ad_dashboard_cache, key=lambda key: _ad_dashboard_cache[key][0])
            _ad_dashboard_cache.pop(oldest_key, None)
        _ad_dashboard_cache[cache_key] = (now, copy.deepcopy(payload))
        await self._save_snapshot(
            _AD_DASHBOARD_NAMESPACE,
            snapshot_params,
            payload,
            ttl_seconds=_AD_DASHBOARD_SNAPSHOT_TTL_SECONDS,
        )
        return payload

    async def content_tag_modules(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        days: int = 30,
        account_ids: list[str] | None = None,
        xhs_account_ids: list[str] | None = None,
        report_type: str = "all",
        buyer_user_id: int | None = None,
        level: str = "primary",
        primary_tag: str | None = None,
        force_refresh: bool = False,
        viewer_scope: str = "all",
    ) -> dict:
        start, end = _date_range(start_date, end_date, days)
        assignments = await self._assignments()
        professional_mappings = await self._professional_mappings()
        selected_account_ids = [str(x).strip() for x in account_ids or [] if str(x).strip()]
        selected_xhs_account_ids = [str(x).strip() for x in xhs_account_ids or [] if str(x).strip()]
        if buyer_user_id:
            buyer_accounts = [account_id for account_id, item in assignments.items() if int(item.get("buyer_user_id") or 0) == buyer_user_id]
            selected_account_ids = sorted(set(selected_account_ids) & set(buyer_accounts)) if selected_account_ids else buyer_accounts
        selected_account_ids = self._filter_accounts_by_professionals(selected_account_ids, professional_mappings, selected_xhs_account_ids)
        row_account_ids = selected_account_ids if selected_account_ids or not (buyer_user_id or selected_xhs_account_ids) else ["__no_matched_filter_account__"]
        assignment_revision = await self._assignment_revision()

        note_types = NOTE_REPORT_TYPES
        if report_type == "simple":
            note_types = ("simple_note",)
        elif report_type == "standard":
            note_types = ("standard_note",)
        tag_level = "secondary" if level == "secondary" else "primary"
        selected_primary_tag = _clean_content_tag(primary_tag)
        if selected_primary_tag:
            tag_level = "secondary"

        cache_key = (
            start.isoformat(),
            end.isoformat(),
            tuple(sorted(selected_account_ids)),
            tuple(sorted(selected_xhs_account_ids)),
            tuple(note_types),
            report_type,
            int(buyer_user_id or 0),
            str(viewer_scope or "all"),
            tag_level,
            selected_primary_tag,
            "note-owner-v1",
            tuple(sorted(assignment_revision.items())),
        )
        now = time.monotonic()
        cached = _ad_content_tag_cache.get(cache_key)
        if not force_refresh and cached and now - cached[0] <= _AD_CONTENT_TAG_CACHE_TTL_SECONDS:
            return copy.deepcopy(cached[1])

        snapshot_params = {
            "version": "ad-content-tags-v2-aggregate",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "account_ids": _snapshot_account_ids(selected_account_ids),
            "xhs_account_ids": _snapshot_account_ids(selected_xhs_account_ids),
            "row_account_ids": _snapshot_account_ids(row_account_ids),
            "report_type": report_type,
            "note_types": list(note_types),
            "buyer_user_id": int(buyer_user_id or 0),
            "viewer_scope": str(viewer_scope or "all"),
            "level": tag_level,
            "primary_tag": selected_primary_tag or "",
            "assignment_revision": assignment_revision,
            "report_revision": await self._report_revision(
                tuple(list(note_types) + (["creative"] if report_type == "all" else [])),
                start,
                end,
                row_account_ids,
            ),
        }
        snapshot_payload = None if force_refresh else await self._load_snapshot(_AD_CONTENT_TAG_NAMESPACE, snapshot_params)
        if not force_refresh and snapshot_payload:
            _ad_content_tag_cache[cache_key] = (now, copy.deepcopy(snapshot_payload))
            return snapshot_payload

        async with _content_tag_compute_semaphore():
            now = time.monotonic()
            cached = _ad_content_tag_cache.get(cache_key)
            if not force_refresh and cached and now - cached[0] <= _AD_CONTENT_TAG_CACHE_TTL_SECONDS:
                return copy.deepcopy(cached[1])

            snapshot_payload = None if force_refresh else await self._load_snapshot(_AD_CONTENT_TAG_NAMESPACE, snapshot_params)
            if not force_refresh and snapshot_payload:
                _ad_content_tag_cache[cache_key] = (now, copy.deepcopy(snapshot_payload))
                return snapshot_payload

            compute_started_at = time.monotonic()
            content_report_types = tuple(list(note_types) + (["creative"] if report_type == "all" else []))
            aggregate_tag_rows, aggregate_note_rows, aggregate_all_note_rows = await asyncio.gather(
                self._aggregate_content_tag_rows(content_report_types, start, end, row_account_ids),
                self._aggregate_note_rows(note_types, start, end, row_account_ids),
                self._aggregate_note_rows(content_report_types, start, end, row_account_ids),
            )
            used_aggregates = bool(aggregate_tag_rows or aggregate_note_rows or aggregate_all_note_rows)
            if used_aggregates:
                note_rows = aggregate_note_rows
                content_tag_rows = aggregate_all_note_rows
                note_owner_map = {
                    str(row.get("note_id") or ""): str(row.get("xhs_account_name") or "未知")
                    for row in aggregate_all_note_rows
                    if str(row.get("note_id") or "").strip()
                }
                if tag_level == "primary":
                    quadrant, creative_tags, content_tag_children = self._content_tag_tree_payload_from_aggregate_rows(
                        aggregate_tag_rows,
                    )
                else:
                    quadrant, creative_tags = self._content_tag_payload_from_aggregate_rows(
                        aggregate_tag_rows,
                        level=tag_level,
                        primary_tag=selected_primary_tag or None,
                    )
                    content_tag_children = {}
            else:
                creative_rows: list[dict] = []
                if report_type == "all":
                    creative_rows, note_rows = await asyncio.gather(
                        self._rows_new_session(("creative",), start, end, row_account_ids, attach_ai_origin=False),
                        self._rows_new_session(note_types, start, end, row_account_ids),
                    )
                else:
                    note_rows = await self._rows_new_session(note_types, start, end, row_account_ids)
                content_tag_rows = note_rows + creative_rows
                note_metadata_map = await self._note_metadata_map(content_tag_rows)
                content_tag_map = self._content_tag_map_from_metadata(note_metadata_map)
                note_owner_map = self._note_owner_map_from_metadata(note_metadata_map)
                if tag_level == "primary":
                    quadrant, creative_tags, content_tag_children = self._content_tag_tree_payload(
                        content_tag_rows,
                        content_tag_map,
                    )
                else:
                    quadrant, creative_tags = self._content_tag_payload(
                        content_tag_rows,
                        content_tag_map,
                        level=tag_level,
                        primary_tag=selected_primary_tag or None,
                    )
                    content_tag_children = {}
            payload = {
                "quadrant": quadrant,
                "creative_tags": creative_tags,
                "top_notes": self._top_notes(content_tag_rows, note_owner_map),
                "note_rows": self._note_rows(note_rows, note_owner_map),
                "content_tag_level": tag_level,
                "content_tag_primary": selected_primary_tag or None,
                "content_tag_children": content_tag_children,
                "data_source": "aggregate" if used_aggregates else "raw",
            }
            if len(_ad_content_tag_cache) >= _AD_DASHBOARD_CACHE_MAX_ENTRIES:
                oldest_key = min(_ad_content_tag_cache, key=lambda key: _ad_content_tag_cache[key][0])
                _ad_content_tag_cache.pop(oldest_key, None)
            _ad_content_tag_cache[cache_key] = (now, copy.deepcopy(payload))
            await self._save_snapshot(
                _AD_CONTENT_TAG_NAMESPACE,
                snapshot_params,
                payload,
                ttl_seconds=_AD_CONTENT_TAG_SNAPSHOT_TTL_SECONDS,
            )
            elapsed = time.monotonic() - compute_started_at
            if elapsed >= 3:
                logger.warning(
                    "XHS ad content tags cold compute took %.2fs buyer=%s accounts=%s report_type=%s rows=%s notes=%s points=%s",
                    elapsed,
                    buyer_user_id or "all",
                    len(row_account_ids or []),
                    report_type,
                    len(content_tag_rows),
                    len(payload["note_rows"]),
                    len(payload["quadrant"].get("points", [])),
                )
            return payload


async def warm_default_ad_dashboard_cache() -> None:
    try:
        async with async_session() as db:
            service = XHSAdDashboardService(db)
            await service.dashboard(report_type="all", include_content_tags=False)
            await service.content_tag_modules(report_type="all")
        logger.info("Warmed default ad dashboard caches")
    except Exception as exc:
        logger.warning("Warm ad dashboard cache skipped: %s", exc)
