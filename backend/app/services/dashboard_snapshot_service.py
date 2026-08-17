from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dashboard_snapshot import DashboardSnapshot


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def stable_dashboard_cache_key(params: dict[str, Any]) -> str:
    raw = json.dumps(params, ensure_ascii=False, sort_keys=True, default=_json_default, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DashboardSnapshotService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_payload(self, namespace: str, params: dict[str, Any]) -> dict | None:
        cache_key = stable_dashboard_cache_key(params)
        now = datetime.utcnow()
        row = (
            await self.db.execute(
                select(DashboardSnapshot).where(
                    DashboardSnapshot.namespace == namespace,
                    DashboardSnapshot.cache_key == cache_key,
                )
            )
        ).scalar_one_or_none()
        if not row:
            return None
        if row.expires_at and row.expires_at <= now:
            return None
        payload = copy.deepcopy(row.payload or {})
        if isinstance(payload, dict):
            payload.setdefault("_snapshot", {})
            payload["_snapshot"].update({
                "hit": True,
                "namespace": namespace,
                "generated_at": row.generated_at.isoformat() if row.generated_at else None,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            })
        return payload if isinstance(payload, dict) else None

    async def save_payload(
        self,
        namespace: str,
        params: dict[str, Any],
        payload: dict,
        *,
        ttl_seconds: int = 1800,
    ) -> None:
        cache_key = stable_dashboard_cache_key(params)
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=max(60, int(ttl_seconds or 1800)))
        payload_to_store = copy.deepcopy(payload)
        if isinstance(payload_to_store, dict):
            payload_to_store.pop("_snapshot", None)
        raw = json.dumps(payload_to_store, ensure_ascii=False, default=_json_default, separators=(",", ":"))
        values = {
            "namespace": namespace,
            "cache_key": cache_key,
            "params": copy.deepcopy(params),
            "payload": payload_to_store,
            "payload_bytes": len(raw.encode("utf-8")),
            "generated_at": now,
            "expires_at": expires_at,
            "updated_at": now,
        }
        bind = self.db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        await self.db.execute(
            delete(DashboardSnapshot).where(
                DashboardSnapshot.expires_at.is_not(None),
                DashboardSnapshot.expires_at < now - timedelta(days=1),
            )
        )
        if dialect_name == "postgresql":
            stmt = pg_insert(DashboardSnapshot).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["namespace", "cache_key"],
                set_={
                    "params": stmt.excluded.params,
                    "payload": stmt.excluded.payload,
                    "payload_bytes": stmt.excluded.payload_bytes,
                    "generated_at": stmt.excluded.generated_at,
                    "expires_at": stmt.excluded.expires_at,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            await self.db.execute(stmt)
        else:
            existing = (
                await self.db.execute(
                    select(DashboardSnapshot).where(
                        DashboardSnapshot.namespace == namespace,
                        DashboardSnapshot.cache_key == cache_key,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                for key, value in values.items():
                    setattr(existing, key, value)
            else:
                self.db.add(DashboardSnapshot(**values))
        await self.db.commit()
