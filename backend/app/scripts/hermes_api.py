"""Hermes-only lifecycle for coexistence with an unchanged legacy Web API.

Run with uvicorn app.scripts.hermes_api:create_app --factory. The frontend
routes only Hermes endpoints here; all other business requests stay on the
existing backend. Do not run the monolithic new API alongside this service.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from app.db.session import async_session
from app.services.scheduler import hermes_workflow_schedule_loop
from app.services.scheduler_leader import (
    SchedulerLeaderCoordinator,
    SchedulerLoopSpec,
    normalized_scheduler_lease_settings,
)


@asynccontextmanager
async def hermes_lifespan(app):
    lease_seconds, heartbeat_seconds = normalized_scheduler_lease_settings()
    coordinator = SchedulerLeaderCoordinator(
        async_session,
        [SchedulerLoopSpec(
            "hermes-content-production",
            lambda: hermes_workflow_schedule_loop(async_session),
        )],
        lease_key="hermes-content-scheduler",
        lease_seconds=lease_seconds,
        heartbeat_seconds=heartbeat_seconds,
    )
    task = asyncio.create_task(coordinator.run(), name="hermes-scheduler-coordinator")
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def create_app():
    # Reuse authentication, exceptions, middleware and routes without starting
    # legacy publishing/sync loops or warming the large ad dashboard cache.
    from app.main import app

    app.router.lifespan_context = hermes_lifespan
    return app
