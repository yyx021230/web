from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

UTC = timezone.utc

try:
    CST: tzinfo = ZoneInfo("Asia/Shanghai")
except Exception:
    CST = timezone(timedelta(hours=8))


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def cst_now_naive() -> datetime:
    return datetime.now(CST).replace(tzinfo=None)


def utc_naive_to_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC)


def utc_naive_to_aware_iso(value: datetime | None) -> str | None:
    aware = utc_naive_to_aware(value)
    if aware is None:
        return None
    return aware.isoformat().replace("+00:00", "Z")


def utc_naive_to_cst_naive(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC).astimezone(CST).replace(tzinfo=None)


def cst_naive_to_utc_naive(value: datetime) -> datetime:
    return value.replace(tzinfo=CST).astimezone(UTC).replace(tzinfo=None)


def aware_or_cst_naive_to_utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return cst_naive_to_utc_naive(value)
    return value.astimezone(UTC).replace(tzinfo=None)
