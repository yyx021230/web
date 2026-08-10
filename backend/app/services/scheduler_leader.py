from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.models.scheduler_lease import SchedulerLease
from app.utils.timezone import utc_now_naive


logger = logging.getLogger(__name__)

SCHEDULER_LEASE_KEY = "background-scheduler"
LoopFactory = Callable[[], Coroutine[object, object, None]]


@dataclass(frozen=True)
class SchedulerLoopSpec:
    name: str
    factory: LoopFactory


class SchedulerLeaseService:
    """Atomically acquire, renew, and release one database-backed lease."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def try_acquire_or_renew(
        self,
        *,
        lease_key: str,
        owner_id: str,
        lease_seconds: float,
        now: datetime | None = None,
    ) -> bool:
        normalized_key = _required_bounded_text(lease_key, field="lease_key", limit=128)
        normalized_owner = _required_bounded_text(owner_id, field="owner_id", limit=160)
        normalized_seconds = float(lease_seconds)
        if normalized_seconds <= 0:
            raise ValueError("lease_seconds must be greater than zero")

        acquired_at = now or utc_now_naive()
        expires_at = acquired_at + timedelta(seconds=normalized_seconds)
        values = {
            "lease_key": normalized_key,
            "owner_id": normalized_owner,
            "acquired_at": acquired_at,
            "heartbeat_at": acquired_at,
            "lease_expires_at": expires_at,
            "updated_at": acquired_at,
        }
        statement = _lease_upsert_statement(
            dialect_name=self.db.get_bind().dialect.name,
            values=values,
            owner_id=normalized_owner,
            acquired_at=acquired_at,
        )
        acquired_owner = (await self.db.execute(statement)).scalar_one_or_none()
        return acquired_owner == normalized_owner

    async def release(self, *, lease_key: str, owner_id: str) -> bool:
        normalized_key = _required_bounded_text(lease_key, field="lease_key", limit=128)
        normalized_owner = _required_bounded_text(owner_id, field="owner_id", limit=160)
        now = utc_now_naive()
        released_key = (
            await self.db.execute(
                update(SchedulerLease)
                .where(
                    SchedulerLease.lease_key == normalized_key,
                    SchedulerLease.owner_id == normalized_owner,
                )
                .values(
                    owner_id=None,
                    heartbeat_at=now,
                    lease_expires_at=None,
                    updated_at=now,
                )
                .returning(SchedulerLease.lease_key)
            )
        ).scalar_one_or_none()
        return released_key == normalized_key

    async def get(self, lease_key: str) -> SchedulerLease | None:
        normalized_key = _required_bounded_text(lease_key, field="lease_key", limit=128)
        return (
            await self.db.execute(
                select(SchedulerLease).where(
                    SchedulerLease.lease_key == normalized_key
                )
            )
        ).scalar_one_or_none()


class SchedulerLeaderCoordinator:
    """Run background scheduler loops only while this instance owns the lease."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        loop_specs: list[SchedulerLoopSpec],
        *,
        owner_id: str | None = None,
        lease_key: str = SCHEDULER_LEASE_KEY,
        lease_seconds: float = 30,
        heartbeat_seconds: float = 10,
    ):
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be greater than zero")
        if heartbeat_seconds <= 0 or heartbeat_seconds >= lease_seconds:
            raise ValueError("heartbeat_seconds must be positive and below lease_seconds")
        self.session_factory = session_factory
        self.loop_specs = list(loop_specs)
        self.owner_id = owner_id or _default_owner_id()
        self.lease_key = lease_key
        self.lease_seconds = float(lease_seconds)
        self.heartbeat_seconds = float(heartbeat_seconds)
        self._child_tasks: dict[str, asyncio.Task[None]] = {}
        self._is_leader = False

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    @property
    def running_loop_names(self) -> tuple[str, ...]:
        return tuple(
            name for name, task in self._child_tasks.items() if not task.done()
        )

    async def run(self) -> None:
        try:
            while True:
                owns_lease = await self._renew_safely()
                if owns_lease:
                    if not self._is_leader:
                        logger.info(
                            "Scheduler leadership acquired: owner_id=%s",
                            self.owner_id,
                        )
                    self._is_leader = True
                    self._ensure_child_loops()
                else:
                    if self._is_leader:
                        logger.warning(
                            "Scheduler leadership lost: owner_id=%s",
                            self.owner_id,
                        )
                    self._is_leader = False
                    await self._stop_child_loops()
                await asyncio.sleep(self.heartbeat_seconds)
        except asyncio.CancelledError:
            raise
        finally:
            self._is_leader = False
            await self._stop_child_loops()
            await self._release_safely()

    async def _renew_safely(self) -> bool:
        try:
            async with self.session_factory() as db:
                acquired = await SchedulerLeaseService(db).try_acquire_or_renew(
                    lease_key=self.lease_key,
                    owner_id=self.owner_id,
                    lease_seconds=self.lease_seconds,
                )
                await db.commit()
                return acquired
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Scheduler lease renewal failed; stopping local scheduler loops: owner_id=%s",
                self.owner_id,
            )
            return False

    async def _release_safely(self) -> None:
        try:
            async with self.session_factory() as db:
                released = await SchedulerLeaseService(db).release(
                    lease_key=self.lease_key,
                    owner_id=self.owner_id,
                )
                await db.commit()
            if released:
                logger.info(
                    "Scheduler leadership released: owner_id=%s",
                    self.owner_id,
                )
        except Exception:
            logger.exception(
                "Scheduler lease release failed; lease will expire: owner_id=%s",
                self.owner_id,
            )

    def _ensure_child_loops(self) -> None:
        for spec in self.loop_specs:
            existing = self._child_tasks.get(spec.name)
            if existing is not None and not existing.done():
                continue
            if existing is not None:
                try:
                    error = existing.exception()
                except asyncio.CancelledError:
                    error = None
                if error is not None:
                    logger.error(
                        "Scheduler child loop stopped unexpectedly and will restart: loop=%s error=%s",
                        spec.name,
                        error,
                    )
            self._child_tasks[spec.name] = asyncio.create_task(
                spec.factory(),
                name=f"scheduler:{spec.name}",
            )

    async def _stop_child_loops(self) -> None:
        tasks = list(self._child_tasks.values())
        self._child_tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def build_scheduler_loop_specs(
    session_factory: async_sessionmaker,
) -> list[SchedulerLoopSpec]:
    from app.services.scheduler import (
        scheduled_publish_loop,
        sync_task_loop,
        xhs_configured_task_loop,
    )
    from app.services.xhs_profile_stat_service import profile_stat_daily_sync_loop

    specs = [
        SchedulerLoopSpec(
            "xhs-configured-tasks",
            lambda: xhs_configured_task_loop(session_factory),
        )
    ]
    if settings.xhs_enable_sync_task_loop:
        specs.append(
            SchedulerLoopSpec(
                "legacy-post-sync",
                lambda: sync_task_loop(session_factory),
            )
        )
    if settings.xhs_enable_scheduled_publish_loop:
        specs.append(
            SchedulerLoopSpec(
                "scheduled-publish",
                lambda: scheduled_publish_loop(session_factory),
            )
        )
    if settings.xhs_enable_profile_stat_sync_loop:
        specs.append(
            SchedulerLoopSpec(
                "profile-stat-sync",
                lambda: profile_stat_daily_sync_loop(session_factory),
            )
        )
    return specs


def normalized_scheduler_lease_settings() -> tuple[int, int]:
    lease_seconds = max(10, int(settings.scheduler_leader_lease_seconds or 30))
    heartbeat_seconds = max(
        1,
        min(
            int(settings.scheduler_leader_heartbeat_seconds or 10),
            max(1, lease_seconds // 3),
        ),
    )
    return lease_seconds, heartbeat_seconds


def _required_bounded_text(value: object, *, field: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    if len(text) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return text


def _lease_upsert_statement(
    *,
    dialect_name: str,
    values: dict[str, Any],
    owner_id: str,
    acquired_at: datetime,
):
    if dialect_name == "postgresql":
        statement = postgresql_insert(SchedulerLease).values(**values)
    elif dialect_name == "sqlite":
        statement = sqlite_insert(SchedulerLease).values(**values)
    else:
        raise RuntimeError(f"Unsupported scheduler lease dialect: {dialect_name}")
    return statement.on_conflict_do_update(
        index_elements=[SchedulerLease.lease_key],
        set_={
            "owner_id": owner_id,
            "acquired_at": case(
                (
                    SchedulerLease.owner_id == owner_id,
                    SchedulerLease.acquired_at,
                ),
                else_=acquired_at,
            ),
            "heartbeat_at": acquired_at,
            "lease_expires_at": values["lease_expires_at"],
            "updated_at": acquired_at,
        },
        where=or_(
            SchedulerLease.owner_id == owner_id,
            SchedulerLease.owner_id.is_(None),
            SchedulerLease.lease_expires_at.is_(None),
            SchedulerLease.lease_expires_at <= acquired_at,
        ),
    ).returning(SchedulerLease.owner_id)


def _default_owner_id() -> str:
    host = socket.gethostname().strip() or "unknown-host"
    return f"{host}:{os.getpid()}:{uuid.uuid4().hex[:12]}"[:160]
