from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.scripts import hermes_api


@pytest.mark.asyncio
async def test_sidecar_starts_only_hermes_with_an_independent_lease(monkeypatch):
    observed = {}
    started = asyncio.Event()
    stopped = asyncio.Event()

    class Coordinator:
        def __init__(self, session, specs, **kwargs):
            observed.update(session=session, specs=specs, **kwargs)

        async def run(self):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

    monkeypatch.setattr(hermes_api, "SchedulerLeaderCoordinator", Coordinator)
    async with hermes_api.hermes_lifespan(None):
        await asyncio.wait_for(started.wait(), timeout=1)
        assert observed["lease_key"] == "hermes-content-scheduler"
        assert [spec.name for spec in observed["specs"]] == ["hermes-content-production"]
    assert stopped.is_set()


def test_factory_preserves_existing_app_and_authentication(monkeypatch):
    import app.main as main

    original = main.app.router.lifespan_context
    monkeypatch.setattr(main.app, "router", SimpleNamespace(lifespan_context=original))
    assert hermes_api.create_app() is main.app
    assert main.app.router.lifespan_context is hermes_api.hermes_lifespan
