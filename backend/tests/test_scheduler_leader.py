from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.dialects import postgresql, sqlite

from app.config import settings
from app.db.session import async_session
from app.main import app, lifespan
from app.models.scheduler_lease import SchedulerLease
from app.models.user import User
from app.services.scheduler_leader import (
    SCHEDULER_LEASE_KEY,
    SchedulerLeaderCoordinator,
    SchedulerLeaseService,
    SchedulerLoopSpec,
    build_scheduler_loop_specs,
    normalized_scheduler_lease_settings,
    _lease_upsert_statement,
)
from tests.conftest import make_auth_headers


async def _wait_until(predicate, *, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition was not met before timeout")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_scheduler_lease_acquire_renew_expire_takeover_and_release(client):
    started = datetime(2026, 8, 10, 12, 0, 0)
    async with async_session() as db:
        service = SchedulerLeaseService(db)
        assert await service.try_acquire_or_renew(
            lease_key=SCHEDULER_LEASE_KEY,
            owner_id="instance-a",
            lease_seconds=30,
            now=started,
        )
        await db.commit()

        assert not await service.try_acquire_or_renew(
            lease_key=SCHEDULER_LEASE_KEY,
            owner_id="instance-b",
            lease_seconds=30,
            now=started + timedelta(seconds=10),
        )
        await db.commit()

        assert await service.try_acquire_or_renew(
            lease_key=SCHEDULER_LEASE_KEY,
            owner_id="instance-a",
            lease_seconds=30,
            now=started + timedelta(seconds=20),
        )
        await db.commit()
        lease = await service.get(SCHEDULER_LEASE_KEY)
        assert lease is not None
        assert lease.owner_id == "instance-a"
        assert lease.acquired_at == started
        assert lease.heartbeat_at == started + timedelta(seconds=20)
        assert lease.lease_expires_at == started + timedelta(seconds=50)

        assert await service.try_acquire_or_renew(
            lease_key=SCHEDULER_LEASE_KEY,
            owner_id="instance-b",
            lease_seconds=30,
            now=started + timedelta(seconds=51),
        )
        await db.commit()
        await db.refresh(lease)
        assert lease.owner_id == "instance-b"
        assert lease.acquired_at == started + timedelta(seconds=51)
        assert not await service.release(
            lease_key=SCHEDULER_LEASE_KEY,
            owner_id="instance-a",
        )
        assert await service.release(
            lease_key=SCHEDULER_LEASE_KEY,
            owner_id="instance-b",
        )
        await db.commit()
        await db.refresh(lease)
        assert lease.owner_id is None
        assert lease.lease_expires_at is None


@pytest.mark.asyncio
async def test_scheduler_lease_concurrent_acquire_has_one_winner(client):
    now = datetime(2026, 8, 10, 12, 0, 0)

    async def attempt(owner_id: str) -> bool:
        async with async_session() as db:
            acquired = await SchedulerLeaseService(db).try_acquire_or_renew(
                lease_key=SCHEDULER_LEASE_KEY,
                owner_id=owner_id,
                lease_seconds=30,
                now=now,
            )
            await db.commit()
            return acquired

    results = await asyncio.gather(*(attempt(f"instance-{index}") for index in range(8)))
    assert sum(results) == 1
    async with async_session() as db:
        lease = await SchedulerLeaseService(db).get(SCHEDULER_LEASE_KEY)
        assert lease is not None
        assert lease.owner_id == f"instance-{results.index(True)}"


@pytest.mark.asyncio
async def test_scheduler_lease_respects_caller_rollback_and_validates(client):
    async with async_session() as db:
        service = SchedulerLeaseService(db)
        with pytest.raises(ValueError, match="lease_key"):
            await service.try_acquire_or_renew(
                lease_key="",
                owner_id="instance-a",
                lease_seconds=30,
            )
        with pytest.raises(ValueError, match="lease_seconds"):
            await service.try_acquire_or_renew(
                lease_key=SCHEDULER_LEASE_KEY,
                owner_id="instance-a",
                lease_seconds=0,
            )
        await service.try_acquire_or_renew(
            lease_key=SCHEDULER_LEASE_KEY,
            owner_id="instance-a",
            lease_seconds=30,
        )
        await db.rollback()

    async with async_session() as db:
        assert await SchedulerLeaseService(db).get(SCHEDULER_LEASE_KEY) is None


@pytest.mark.asyncio
async def test_two_coordinators_run_one_child_and_take_over_after_shutdown(client):
    active = 0
    max_active = 0
    starts: list[str] = []
    stops: list[str] = []

    async def child(owner_id: str) -> None:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        starts.append(owner_id)
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1
            stops.append(owner_id)

    first = SchedulerLeaderCoordinator(
        async_session,
        [SchedulerLoopSpec("test-loop", lambda: child("instance-a"))],
        owner_id="instance-a",
        lease_seconds=0.3,
        heartbeat_seconds=0.05,
    )
    second = SchedulerLeaderCoordinator(
        async_session,
        [SchedulerLoopSpec("test-loop", lambda: child("instance-b"))],
        owner_id="instance-b",
        lease_seconds=0.3,
        heartbeat_seconds=0.05,
    )
    first_task = asyncio.create_task(first.run())
    second_task = asyncio.create_task(second.run())
    try:
        await _wait_until(lambda: len(starts) == 1)
        await asyncio.sleep(0.12)
        assert max_active == 1
        assert first.is_leader != second.is_leader

        leader_task = first_task if first.is_leader else second_task
        follower = second if first.is_leader else first
        leader_task.cancel()
        await asyncio.gather(leader_task, return_exceptions=True)
        await _wait_until(lambda: len(starts) == 2)
        assert follower.is_leader is True
        assert max_active == 1
    finally:
        for task in (first_task, second_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(first_task, second_task, return_exceptions=True)

    assert len(stops) == 2
    assert active == 0
    async with async_session() as db:
        lease = await SchedulerLeaseService(db).get(SCHEDULER_LEASE_KEY)
        assert lease is not None
        assert lease.owner_id is None


@pytest.mark.asyncio
async def test_coordinator_stops_children_immediately_after_lease_loss(client):
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def child() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    coordinator = SchedulerLeaderCoordinator(
        async_session,
        [SchedulerLoopSpec("test-loop", child)],
        owner_id="instance-a",
        lease_seconds=1,
        heartbeat_seconds=0.05,
    )
    task = asyncio.create_task(coordinator.run())
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        async with async_session() as db:
            await db.execute(
                update(SchedulerLease)
                .where(SchedulerLease.lease_key == SCHEDULER_LEASE_KEY)
                .values(
                    owner_id="instance-b",
                    lease_expires_at=datetime(2099, 1, 1),
                )
            )
            await db.commit()
        await asyncio.wait_for(stopped.wait(), timeout=1)
        await _wait_until(lambda: coordinator.is_leader is False)
        assert coordinator.running_loop_names == ()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_coordinator_restarts_failed_child_without_losing_lease(client):
    starts = 0
    running = asyncio.Event()

    async def child() -> None:
        nonlocal starts
        starts += 1
        if starts == 1:
            raise RuntimeError("simulated child failure")
        running.set()
        await asyncio.Event().wait()

    coordinator = SchedulerLeaderCoordinator(
        async_session,
        [SchedulerLoopSpec("test-loop", child)],
        owner_id="instance-a",
        lease_seconds=0.3,
        heartbeat_seconds=0.05,
    )
    task = asyncio.create_task(coordinator.run())
    try:
        await asyncio.wait_for(running.wait(), timeout=1)
        assert starts == 2
        assert coordinator.is_leader is True
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_coordinator_fails_closed_when_lease_database_errors(client, monkeypatch):
    started = asyncio.Event()
    stopped = asyncio.Event()
    renew_calls = 0

    async def child() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    original_renew = SchedulerLeaseService.try_acquire_or_renew

    async def fail_after_first_renew(self, **kwargs):
        nonlocal renew_calls
        renew_calls += 1
        if renew_calls > 1:
            raise RuntimeError("simulated database outage")
        return await original_renew(self, **kwargs)

    monkeypatch.setattr(
        SchedulerLeaseService,
        "try_acquire_or_renew",
        fail_after_first_renew,
    )
    coordinator = SchedulerLeaderCoordinator(
        async_session,
        [SchedulerLoopSpec("test-loop", child)],
        owner_id="instance-a",
        lease_seconds=0.3,
        heartbeat_seconds=0.05,
    )
    task = asyncio.create_task(coordinator.run())
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        await asyncio.wait_for(stopped.wait(), timeout=1)
        await _wait_until(lambda: coordinator.is_leader is False)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_release_error_does_not_block_coordinator_shutdown(client, monkeypatch):
    async def fail_release(_self, **_kwargs):
        raise RuntimeError("simulated release failure")

    monkeypatch.setattr(SchedulerLeaseService, "release", fail_release)
    coordinator = SchedulerLeaderCoordinator(
        async_session,
        [],
        owner_id="instance-a",
        lease_seconds=0.3,
        heartbeat_seconds=0.05,
    )
    task = asyncio.create_task(coordinator.run())
    await _wait_until(lambda: coordinator.is_leader)
    task.cancel()
    results = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(results[0], asyncio.CancelledError)


def test_scheduler_loop_specs_and_setting_normalization(monkeypatch):
    monkeypatch.setattr(settings, "xhs_enable_sync_task_loop", True)
    monkeypatch.setattr(settings, "xhs_enable_scheduled_publish_loop", True)
    monkeypatch.setattr(settings, "xhs_enable_profile_stat_sync_loop", True)
    names = [spec.name for spec in build_scheduler_loop_specs(async_session)]
    assert names == [
        "xhs-configured-tasks",
        "hermes-content-production",
        "legacy-post-sync",
        "scheduled-publish",
        "profile-stat-sync",
    ]

    monkeypatch.setattr(settings, "scheduler_leader_lease_seconds", 5)
    monkeypatch.setattr(settings, "scheduler_leader_heartbeat_seconds", 99)
    assert normalized_scheduler_lease_settings() == (10, 3)

    with pytest.raises(ValueError, match="lease_seconds"):
        SchedulerLeaderCoordinator(async_session, [], lease_seconds=0)
    with pytest.raises(ValueError, match="heartbeat_seconds"):
        SchedulerLeaderCoordinator(
            async_session,
            [],
            lease_seconds=10,
            heartbeat_seconds=10,
        )


def test_scheduler_lease_upsert_compiles_for_postgresql_and_sqlite():
    now = datetime(2026, 8, 10, 12, 0, 0)
    values = {
        "lease_key": SCHEDULER_LEASE_KEY,
        "owner_id": "instance-a",
        "acquired_at": now,
        "heartbeat_at": now,
        "lease_expires_at": now + timedelta(seconds=30),
        "updated_at": now,
    }
    postgres_sql = str(
        _lease_upsert_statement(
            dialect_name="postgresql",
            values=values,
            owner_id="instance-a",
            acquired_at=now,
        ).compile(dialect=postgresql.dialect())
    )
    sqlite_sql = str(
        _lease_upsert_statement(
            dialect_name="sqlite",
            values=values,
            owner_id="instance-a",
            acquired_at=now,
        ).compile(dialect=sqlite.dialect())
    )
    assert "ON CONFLICT (lease_key) DO UPDATE" in postgres_sql
    assert "scheduler_leases.lease_expires_at <=" in postgres_sql
    assert "ON CONFLICT (lease_key) DO UPDATE" in sqlite_sql
    with pytest.raises(RuntimeError, match="Unsupported"):
        _lease_upsert_statement(
            dialect_name="mysql",
            values=values,
            owner_id="instance-a",
            acquired_at=now,
        )


@pytest.mark.asyncio
async def test_scheduler_lease_row_can_be_inspected(client):
    async with async_session() as db:
        await SchedulerLeaseService(db).try_acquire_or_renew(
            lease_key="inspectable-lease",
            owner_id="instance-a",
            lease_seconds=30,
        )
        await db.commit()
        row = (
            await db.execute(
                select(SchedulerLease).where(
                    SchedulerLease.lease_key == "inspectable-lease"
                )
            )
        ).scalar_one()
        assert row.owner_id == "instance-a"
        assert row.heartbeat_at is not None
        assert row.lease_expires_at is not None


@pytest.mark.asyncio
async def test_scheduler_leader_status_endpoint_is_admin_only(client):
    async with async_session() as db:
        db.add_all(
            [
                User(
                    id=1,
                    username="scheduler-admin",
                    email="scheduler-admin@example.com",
                    hashed_password="x",
                    role="admin",
                ),
                User(
                    id=2,
                    username="scheduler-viewer",
                    email="scheduler-viewer@example.com",
                    hashed_password="x",
                    role="viewer",
                ),
            ]
        )
        await SchedulerLeaseService(db).try_acquire_or_renew(
            lease_key=SCHEDULER_LEASE_KEY,
            owner_id="instance-a",
            lease_seconds=30,
        )
        await db.commit()

    denied = await client.get(
        "/api/v1/admin/reliability/scheduler-leader",
        headers=make_auth_headers(2),
    )
    response = await client.get(
        "/api/v1/admin/reliability/scheduler-leader",
        headers=make_auth_headers(1),
    )
    assert denied.status_code == 403
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["enabled"] is True
    assert payload["owner_id"] == "instance-a"
    assert payload["is_healthy"] is True
    assert payload["heartbeat_at"].endswith("Z")


@pytest.mark.asyncio
async def test_application_lifespan_starts_leader_coordinator(client, monkeypatch):
    import app.services.ai_image_provider_service as provider_module
    import app.services.scheduler_leader as leader_module
    import app.services.xhs_ad_dashboard_service as dashboard_module

    coordinator_started = asyncio.Event()
    coordinator_stopped = asyncio.Event()
    direct_loop_started = asyncio.Event()

    async def direct_loop() -> None:
        direct_loop_started.set()
        await asyncio.Event().wait()

    async def fake_coordinator_run(_self) -> None:
        coordinator_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            coordinator_stopped.set()

    async def fake_cache_warm() -> None:
        await asyncio.Event().wait()

    async def fake_provider_seed(_self) -> int:
        return 0

    monkeypatch.setattr(settings, "scheduler_leader_enabled", True)
    monkeypatch.setattr(
        leader_module,
        "build_scheduler_loop_specs",
        lambda _factory: [SchedulerLoopSpec("direct-loop", direct_loop)],
    )
    monkeypatch.setattr(
        leader_module.SchedulerLeaderCoordinator,
        "run",
        fake_coordinator_run,
    )
    monkeypatch.setattr(
        provider_module.AIImageProviderService,
        "ensure_default_providers",
        fake_provider_seed,
    )
    monkeypatch.setattr(
        dashboard_module,
        "warm_default_ad_dashboard_cache",
        fake_cache_warm,
    )

    async with lifespan(app):
        await asyncio.wait_for(coordinator_started.wait(), timeout=1)
        assert direct_loop_started.is_set() is False
    assert coordinator_stopped.is_set() is True


@pytest.mark.asyncio
async def test_application_lifespan_legacy_fallback_is_explicit(client, monkeypatch):
    import app.services.ai_image_provider_service as provider_module
    import app.services.scheduler_leader as leader_module
    import app.services.xhs_ad_dashboard_service as dashboard_module

    direct_loop_started = asyncio.Event()
    direct_loop_stopped = asyncio.Event()

    async def direct_loop() -> None:
        direct_loop_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            direct_loop_stopped.set()

    async def fake_cache_warm() -> None:
        await asyncio.Event().wait()

    async def fake_provider_seed(_self) -> int:
        return 0

    monkeypatch.setattr(settings, "scheduler_leader_enabled", False)
    monkeypatch.setattr(
        leader_module,
        "build_scheduler_loop_specs",
        lambda _factory: [SchedulerLoopSpec("direct-loop", direct_loop)],
    )
    monkeypatch.setattr(
        provider_module.AIImageProviderService,
        "ensure_default_providers",
        fake_provider_seed,
    )
    monkeypatch.setattr(
        dashboard_module,
        "warm_default_ad_dashboard_cache",
        fake_cache_warm,
    )

    async with lifespan(app):
        await asyncio.wait_for(direct_loop_started.wait(), timeout=1)
    assert direct_loop_stopped.is_set() is True
