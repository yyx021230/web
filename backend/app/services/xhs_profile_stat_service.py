from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from datetime import date, datetime, time as dt_time, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    load_roles_for_users,
    normalize_roles,
)
from app.db.session import async_session
from app.models.user import User
from app.models.user_xhs_env import UserXHSEnvironment
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_environment import XHSEnvironment
from app.models.xhs_report import XHSProfileStatDaily

logger = logging.getLogger(__name__)


XHS_ACCOUNT_PREFIX = "【小红书】"
YOUJU_ACCOUNT_ID_FIELD = "account_id_with_id"
YOUJU_PROFILE_ID_PATTERN = re.compile(r"[（(]\s*([0-9a-zA-Z_-]+)\s*[）)]\s*$")
XHS_PROFILE_URL_ID_PATTERN = re.compile(r"/user/profile/([0-9a-zA-Z_-]+)", re.IGNORECASE)
PROFILE_OWNER_ROLE_PRIORITY = [
    ROLE_XHS_LEAD,
    ROLE_BRAND_LEAD,
    ROLE_XHS_OPS,
    ROLE_BRAND_OPS,
    ROLE_ADMIN,
    ROLE_BUYER,
    ROLE_VIEWER,
]
REPORTABLE_PROFILE_OWNER_ROLES = {
    ROLE_XHS_LEAD,
    ROLE_BRAND_LEAD,
    ROLE_XHS_OPS,
    ROLE_BRAND_OPS,
    ROLE_ADMIN,
}


def normalize_profile_account_name(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^【小红书】", "", text).strip()
    text = re.sub(r"\s+", "", text)
    return text.lower()


def display_profile_account_name(value: object) -> str:
    text = str(value or "").strip()
    return re.sub(r"^【小红书】", "", text).strip()


def normalize_profile_account_id(value: object) -> str:
    """Return a stable lowercase key for a Xiaohongshu profile id."""
    return str(value or "").strip().lower()


def get_youju_account_identifier(payload: object) -> str:
    """Read Youju's current account field, with a legacy response fallback."""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get(YOUJU_ACCOUNT_ID_FIELD) or payload.get("wx_app_id") or "").strip()


def extract_youju_profile_id(account_identifier: object) -> str:
    """Extract the profile id appended by Youju in ``account_id_with_id``.

    New Youju rows use a display label such as
    ``【小红书】账号昵称(6a02...)``.  The label is mutable and must not be
    used for ownership matching; the final parenthesised id is the stable key.
    """
    match = YOUJU_PROFILE_ID_PATTERN.search(str(account_identifier or "").strip())
    return normalize_profile_account_id(match.group(1)) if match else ""


def extract_profile_url_id(profile_url: object) -> str:
    """Extract the profile id from an account's configured Xiaohongshu URL."""
    try:
        path = urlparse(str(profile_url or "").strip()).path
    except ValueError:
        return ""
    match = XHS_PROFILE_URL_ID_PATTERN.search(path or "")
    return normalize_profile_account_id(match.group(1)) if match else ""


def _profile_owner_role(roles: list[str]) -> str:
    normalized = normalize_roles(roles, fallback=ROLE_VIEWER)
    for role in PROFILE_OWNER_ROLE_PRIORITY:
        if role in normalized:
            return role
    return get_primary_role(normalized)


def _to_int(value: object) -> int:
    try:
        raw = str(value if value is not None else "").strip().replace(",", "")
        if raw.endswith("%"):
            raw = raw[:-1]
        if not raw:
            return 0
        return int(round(float(raw)))
    except Exception:
        return 0


def _to_rate(value: object) -> float:
    try:
        raw = str(value if value is not None else "").strip()
        if not raw:
            return 0.0
        if raw.endswith("%"):
            return round(float(raw[:-1]) / 100, 6)
        parsed = float(raw)
        return round(parsed / 100, 6) if parsed > 1 else round(parsed, 6)
    except Exception:
        return 0.0


def _date_range(start_date: str | None, end_date: str | None, days: int = 30) -> tuple[date, date]:
    if end_date:
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    else:
        end = date.today()
    if start_date:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
    else:
        start = end - timedelta(days=max(1, days) - 1)
    if start > end:
        start, end = end, start
    return start, end


def _date_iter(start: date, end: date):
    cursor = start
    while cursor <= end:
        yield cursor
        cursor += timedelta(days=1)


class XHSProfileStatService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _current_assignment_context(
        self,
        *,
        allowed_owner_roles: set[str] | None = None,
        allowed_owner_ids: set[int] | None = None,
    ) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict], dict[str, int]]:
        """Resolve all ownership from the current user/environment assignments.

        New Youju rows are matched by the immutable profile id in
        ``account_id_with_id``
        against the id in an environment's ``profile_url``. Historical rows
        without that id can use account-name aliases as a compatibility fallback.
        The displayed owner and account list always come from the latest
        assignment.
        """
        assignment_stmt = (
            select(
                XHSEnvironment.id,
                XHSEnvironment.account_name,
                XHSEnvironment.profile_url,
                XHSEnvironment.status,
                User.id,
                User.username,
                User.display_name,
                User.role,
            )
            .join(UserXHSEnvironment, UserXHSEnvironment.environment_id == XHSEnvironment.id)
            .join(User, User.id == UserXHSEnvironment.user_id)
        )
        assignment_rows = (await self.db.execute(assignment_stmt)).all()
        roles_by_user = await load_roles_for_users(self.db, [int(row[4]) for row in assignment_rows])
        legacy_name_mapping: dict[str, dict] = {}
        profile_id_mapping: dict[str, dict] = {}
        owners: dict[str, dict] = {}
        owner_by_environment: dict[int, dict] = {}
        active_environment_ids: set[int] = set()
        for environment_id, env_account_name, profile_url, status, user_id, username, display_name, fallback_role in assignment_rows:
            normalized_roles = normalize_roles(roles_by_user.get(int(user_id), []), fallback=fallback_role or "viewer")
            if not set(normalized_roles).intersection(REPORTABLE_PROFILE_OWNER_ROLES):
                continue
            if allowed_owner_roles and not set(normalized_roles).intersection(allowed_owner_roles):
                continue
            if allowed_owner_ids and int(user_id) not in allowed_owner_ids:
                continue
            owner = {
                "owner_id": str(user_id),
                "owner_name": display_name or username or "未命名运营",
                "owner_role": _profile_owner_role(normalized_roles),
            }
            owner_by_environment[int(environment_id)] = owner
            owner_item = owners.setdefault(str(user_id), {**owner, "account_names": set()})
            display_name_value = display_profile_account_name(env_account_name)
            if display_name_value:
                owner_item["account_names"].add(display_name_value)
                legacy_name_mapping[normalize_profile_account_name(env_account_name)] = owner
            profile_id = extract_profile_url_id(profile_url)
            if profile_id:
                profile_id_mapping[profile_id] = owner
            if str(status or "").lower() == "active":
                active_environment_ids.add(int(environment_id))

        if owner_by_environment:
            alias_stmt = select(
                XHSAccountNote.environment_id,
                XHSAccountNote.account_name,
                XHSAccountNote.profile_nickname,
            ).where(XHSAccountNote.environment_id.in_(owner_by_environment))
            for environment_id, account_name, profile_nickname in (await self.db.execute(alias_stmt)).all():
                owner = owner_by_environment.get(int(environment_id))
                if not owner:
                    continue
                for candidate in (account_name, profile_nickname):
                    key = normalize_profile_account_name(candidate)
                    if key:
                        legacy_name_mapping[key] = owner

        return profile_id_mapping, legacy_name_mapping, owners, {
            "assigned_owner_count": len(owners),
            "assigned_account_count": sum(len(item["account_names"]) for item in owners.values()),
            "assigned_active_account_count": len(active_environment_ids),
        }

    @staticmethod
    def _owner_for_account(account_name: str, owner_map: dict[str, dict]) -> dict:
        key = normalize_profile_account_name(account_name)
        owner = owner_map.get(key)
        if owner:
            return owner
        return {"owner_id": "unassigned", "owner_name": "未分配", "owner_role": "unassigned"}

    @classmethod
    def _owner_for_stat_row(
        cls,
        row: XHSProfileStatDaily,
        *,
        profile_id_map: dict[str, dict],
        legacy_name_map: dict[str, dict],
    ) -> dict:
        profile_id = extract_youju_profile_id(get_youju_account_identifier(row.payload))
        if profile_id:
            # An id-bearing row must never fall back to its mutable nickname.
            return profile_id_map.get(profile_id) or {
                "owner_id": "unassigned",
                "owner_name": "未分配",
                "owner_role": "unassigned",
            }
        return cls._owner_for_account(row.channel_account_name, legacy_name_map)

    @staticmethod
    def _row_from_payload(stat_date: date, payload: dict[str, Any]) -> dict[str, Any]:
        raw_account_name = get_youju_account_identifier(payload)
        account_name = display_profile_account_name(raw_account_name)
        return {
            "stat_date": stat_date,
            "channel_account_name": account_name,
            "channel_account_key": normalize_profile_account_name(raw_account_name),
            "total_visits": _to_int(payload.get("subscribe")),
            "leads": _to_int(payload.get("info")),
            "natural_source_count": _to_int(payload.get("user_info.ad_info.advertiser_id=null")),
            "ad_paid_count": _to_int(payload.get("user_info.ad_info.advertiser_id")),
            "natural_openings": _to_int(payload.get("chat+user_info.ad_info.advertiser_id=null")),
            "ad_openings": _to_int(payload.get("{小红书广告总开口}-{特殊自然来源数}")),
            "natural_leads": _to_int(payload.get("phone+user_info.ad_info.advertiser_id=null")),
            "special_natural_leads": _to_int(payload.get("user_info.ad_info.campaign_id=-1+phone")),
            "ad_leads": _to_int(payload.get("{小红书广告}-{特殊自然来源数}")),
            "direct_private_count": _to_int(payload.get("{总访问数}-{评论用户数}")),
            "private_leads": _to_int(payload.get("{客资数}-{评论留资数}")),
            "comment_users": _to_int(payload.get("tag_小红书评论")),
            "comment_leads": _to_int(payload.get("tag_小红书评论+phone")),
            "xhs_ad_leads": _to_int(payload.get("user_info.ad_info.advertiser_id+phone")),
            "natural_opening_conversion_rate": _to_rate(payload.get("({自然来源客资数}+{特殊自然来源数})/{自然来源开口数}")),
            "ad_opening_conversion_rate": _to_rate(payload.get("({小红书广告}-{特殊自然来源数})/{广告开口数}")),
            "comment_lead_rate": _to_rate(payload.get("{评论留资数}/{评论用户数}")),
            "private_lead_rate": _to_rate(payload.get("({客资数}-{评论留资数})/({总访问数}-{评论用户数})")),
            "payload": payload,
        }

    async def fetch_day(self, target_date: date) -> list[dict[str, Any]]:
        if not settings.xhs_profile_stat_app_id or not settings.xhs_profile_stat_secret:
            raise RuntimeError("XHS profileStat app_id/secret 未配置")
        start_time = f"{target_date.isoformat()} 00:00:00"
        end_time = f"{target_date.isoformat()} 23:59:59"
        params = {
            "script": settings.xhs_profile_stat_script,
            "app_id": settings.xhs_profile_stat_app_id,
            "secret": settings.xhs_profile_stat_secret,
            "config_id": settings.xhs_profile_stat_config_id,
            "module": settings.xhs_profile_stat_module,
            "start_time": start_time,
            "end_time": end_time,
        }
        url = f"{settings.xhs_profile_stat_api_base_url.rstrip('/')}/publicApi/profileStat"
        async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
            response = await client.get(url, params=params)
        if response.status_code >= 400:
            raise RuntimeError(f"profileStat HTTP {response.status_code}: {response.text[:500]}")
        body = response.json()
        if str(body.get("msg")) != "success" or not isinstance(body.get("data"), dict):
            raise RuntimeError(str(body.get("msg") or "profileStat 返回异常"))
        rows = body["data"].get("data") or []
        return [
            self._row_from_payload(target_date, row)
            for row in rows
            if get_youju_account_identifier(row).startswith(XHS_ACCOUNT_PREFIX)
        ]

    async def upsert_rows(self, rows: list[dict[str, Any]]) -> int:
        updated = 0
        for row in rows:
            existing = (
                await self.db.execute(
                    select(XHSProfileStatDaily).where(
                        XHSProfileStatDaily.stat_date == row["stat_date"],
                        XHSProfileStatDaily.channel_account_name == row["channel_account_name"],
                    )
                )
            ).scalar_one_or_none()
            if existing:
                for key, value in row.items():
                    setattr(existing, key, value)
            else:
                self.db.add(XHSProfileStatDaily(**row))
            updated += 1
        await self.db.commit()
        return updated

    async def sync_day(self, target_date: date) -> dict:
        rows = await self.fetch_day(target_date)
        updated = await self.upsert_rows(rows)
        return {"date": target_date.isoformat(), "rows": len(rows), "updated": updated}

    async def backfill(
        self,
        *,
        start_date: date,
        end_date: date,
        delay_seconds: float = 65.0,
        skip_existing: bool = True,
        limit_days: int | None = None,
        max_retries: int = 2,
    ) -> dict:
        results: list[dict] = []
        errors: list[dict] = []
        days = list(_date_iter(start_date, end_date))
        if limit_days:
            days = days[: max(0, limit_days)]
        for index, day in enumerate(days):
            if skip_existing:
                exists = (
                    await self.db.execute(
                        select(func.count(XHSProfileStatDaily.id)).where(XHSProfileStatDaily.stat_date == day)
                    )
                ).scalar_one()
                if int(exists or 0) > 0:
                    results.append({"date": day.isoformat(), "skipped": True, "rows": int(exists or 0)})
                    continue
            last_error: Exception | None = None
            for attempt in range(max(1, max_retries + 1)):
                try:
                    results.append(await self.sync_day(day))
                    last_error = None
                    break
                except Exception as exc:
                    await self.db.rollback()
                    last_error = exc
                    logger.warning("profileStat sync failed: date=%s attempt=%s error=%s", day, attempt + 1, exc)
                    if attempt < max_retries and delay_seconds > 0:
                        await asyncio.sleep(delay_seconds)
            if last_error is not None:
                errors.append({"date": day.isoformat(), "error": str(last_error)})
            if index < len(days) - 1 and delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days": len(days),
            "updated_days": len([item for item in results if not item.get("skipped")]),
            "results": results,
            "errors": errors,
        }

    async def owner_rows(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        days: int = 30,
        allowed_owner_roles: set[str] | None = None,
        allowed_owner_ids: set[int] | None = None,
    ) -> dict:
        start, end = _date_range(start_date, end_date, days)
        rows = (
            await self.db.execute(
                select(XHSProfileStatDaily).where(
                    and_(
                        XHSProfileStatDaily.stat_date >= start,
                        XHSProfileStatDaily.stat_date <= end,
                    )
                )
            )
        ).scalars().all()
        profile_id_map, legacy_name_map, assigned_owners, assignment_summary = await self._current_assignment_context(
            allowed_owner_roles=allowed_owner_roles,
            allowed_owner_ids=allowed_owner_ids,
        )
        buckets: dict[str, dict] = {
            owner_id: {
                "owner_id": owner_id,
                "owner_name": owner["owner_name"],
                "owner_role": owner["owner_role"],
                **self._empty_metrics(),
            }
            for owner_id, owner in assigned_owners.items()
        }
        account_sets: dict[str, set[str]] = defaultdict(set, {
            owner_id: set(owner["account_names"])
            for owner_id, owner in assigned_owners.items()
        })
        daily_sets: dict[str, set[str]] = defaultdict(set)
        total = self._empty_metrics()
        unmatched_accounts: set[str] = set()
        covered_owner_ids: set[str] = set()
        covered_account_keys: set[str] = set()
        for row in rows:
            owner = self._owner_for_stat_row(
                row,
                profile_id_map=profile_id_map,
                legacy_name_map=legacy_name_map,
            )
            if owner["owner_id"] == "unassigned":
                unmatched_accounts.add(display_profile_account_name(row.channel_account_name))
                continue
            owner_id = owner["owner_id"]
            bucket = buckets.setdefault(owner_id, {
                "owner_id": owner_id,
                "owner_name": owner["owner_name"],
                "owner_role": owner["owner_role"],
                **self._empty_metrics(),
            })
            covered_owner_ids.add(owner_id)
            covered_account_keys.add(
                extract_youju_profile_id(get_youju_account_identifier(row.payload))
                or normalize_profile_account_name(row.channel_account_name)
            )
            daily_sets[owner_id].add(row.stat_date.isoformat())
            for key in self._metric_keys():
                value = int(getattr(row, key) or 0)
                bucket[key] += value
                total[key] += value
        owner_rows = []
        for owner_id, bucket in buckets.items():
            account_names = sorted(account_sets[owner_id])
            item = {
                **bucket,
                "account_names": account_names,
                "account_count": len(account_names),
                "days": len(daily_sets[owner_id]),
            }
            item.update(self._derived_rates(item))
            owner_rows.append(item)
        total.update(self._derived_rates(total))
        return {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "owner_rows": sorted(owner_rows, key=lambda item: item["leads"], reverse=True),
            "total": total,
            "unmatched_accounts": sorted(unmatched_accounts),
            "assignment_summary": {
                **assignment_summary,
                "covered_owner_count": len(covered_owner_ids),
                "covered_account_count": len(covered_account_keys),
                "unmatched_profile_account_count": len(unmatched_accounts),
            },
        }

    @staticmethod
    def _metric_keys() -> list[str]:
        return [
            "total_visits",
            "leads",
            "natural_source_count",
            "ad_paid_count",
            "natural_openings",
            "ad_openings",
            "natural_leads",
            "special_natural_leads",
            "ad_leads",
            "direct_private_count",
            "private_leads",
            "comment_users",
            "comment_leads",
            "xhs_ad_leads",
        ]

    @classmethod
    def _empty_metrics(cls) -> dict[str, int]:
        return {key: 0 for key in cls._metric_keys()}

    @staticmethod
    def _derived_rates(item: dict) -> dict[str, float]:
        def ratio(num: int, den: int) -> float:
            return round(float(num or 0) / float(den or 1), 6) if den else 0.0

        return {
            "natural_opening_conversion_rate": ratio(
                int(item.get("natural_leads", 0)) + int(item.get("special_natural_leads", 0)),
                int(item.get("natural_openings", 0)),
            ),
            "ad_opening_conversion_rate": ratio(int(item.get("ad_leads", 0)), int(item.get("ad_openings", 0))),
            "comment_lead_rate": ratio(int(item.get("comment_leads", 0)), int(item.get("comment_users", 0))),
            "private_lead_rate": ratio(int(item.get("private_leads", 0)), int(item.get("direct_private_count", 0))),
        }


async def profile_stat_daily_sync_loop(session_factory=async_session) -> None:
    while True:
        now = datetime.now()
        target = datetime.combine(now.date(), dt_time(hour=max(0, min(23, settings.xhs_profile_stat_daily_update_hour))))
        if now >= target:
            target = target + timedelta(days=1)
        await asyncio.sleep(max(60, (target - now).total_seconds()))
        try:
            async with session_factory() as db:
                service = XHSProfileStatService(db)
                await service.sync_day(date.today() - timedelta(days=1))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("profileStat daily sync loop failed: %s", exc)
