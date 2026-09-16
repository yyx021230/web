from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.xhs_service import SyncJobCancelled, SyncSessionPersona, XHSService
from app.services.xhs_sync_behavior import (
    CreatorSyncBehaviorMode,
    build_creator_sync_behavior_plan,
)


class FixedRoll:
    def __init__(self, value: int):
        self.value = value

    def randint(self, _a: int, _b: int) -> int:
        return self.value


def _persona() -> SyncSessionPersona:
    return SyncSessionPersona(
        profile_prep_range=(0.0, 0.0),
        account_pause_range=(0.0, 0.0),
        account_long_pause_range=(0.0, 0.0),
        detail_pause_range=(0.0, 0.0),
        detail_long_pause_range=(0.0, 0.0),
        retry_backoff_range=(0.0, 0.0),
        context_switch_range=(0.0, 0.0),
        inter_batch_pause_range=(0.0, 0.0),
        env_order_window=(2, 2),
        detail_order_window=(2, 2),
        warmup_rounds=1,
        warmup_note_limit=4,
        use_profile_peek=False,
        warmup_detail_peek_probability=0.0,
        extra_long_pause_probability=0.0,
    )


@pytest.mark.parametrize(
    ("roll", "expected"),
    [
        (1, CreatorSyncBehaviorMode.DIRECT),
        (20, CreatorSyncBehaviorMode.DIRECT),
        (21, CreatorSyncBehaviorMode.CURRENT_HOME),
        (45, CreatorSyncBehaviorMode.CURRENT_HOME),
        (46, CreatorSyncBehaviorMode.CURRENT_NOTE_DETAIL),
        (65, CreatorSyncBehaviorMode.CURRENT_NOTE_DETAIL),
        (66, CreatorSyncBehaviorMode.PROFILE_HOME),
        (80, CreatorSyncBehaviorMode.PROFILE_HOME),
        (81, CreatorSyncBehaviorMode.PROFILE_NOTE_DETAIL),
        (90, CreatorSyncBehaviorMode.PROFILE_NOTE_DETAIL),
        (91, CreatorSyncBehaviorMode.MIXED_HOME_AND_PROFILE),
        (100, CreatorSyncBehaviorMode.MIXED_HOME_AND_PROFILE),
    ],
)
def test_creator_behavior_weight_boundaries(roll: int, expected: CreatorSyncBehaviorMode):
    plan = build_creator_sync_behavior_plan(FixedRoll(roll))

    assert plan.mode is expected


@pytest.mark.parametrize("forced_mode", range(1, 7))
def test_creator_behavior_can_force_each_numbered_route(forced_mode: int):
    plan = build_creator_sync_behavior_plan(FixedRoll(1), forced_mode=forced_mode)

    assert int(plan.mode) == forced_mode


@pytest.mark.asyncio
async def test_creator_behavior_current_note_route_is_ordered_and_read_only(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]
    plan = build_creator_sync_behavior_plan(
        FixedRoll(1),
        forced_mode=int(CreatorSyncBehaviorMode.CURRENT_NOTE_DETAIL),
    )
    env = SimpleNamespace(id=17, account_name="行为账号", profile_url="")
    events: list[str] = []
    progress: list[dict] = []

    async def fake_profile_prep(self, persona):
        events.append("profile_prep")

    async def fake_fetch_current(self, *, api_base=None, limit=60):
        events.append(f"current:{api_base}:{limit}")
        return {"feeds": [{"feed_id": "feed-1", "xsec_token": "token-1"}]}

    async def fake_detail(self, payload, *, api_base, persona):
        events.append(f"detail:{payload['feeds'][0]['feed_id']}")
        return True

    async def fake_context_switch(self, persona):
        events.append("context_switch")

    async def capture_progress(payload: dict):
        progress.append(dict(payload))

    monkeypatch.setattr(XHSService, "_sleep_sync_profile_prep", fake_profile_prep)
    monkeypatch.setattr(XHSService, "_fetch_current_account_notes", fake_fetch_current)
    monkeypatch.setattr(XHSService, "_run_warmup_detail_peek", fake_detail)
    monkeypatch.setattr(XHSService, "_sleep_between_account_note_context_switch", fake_context_switch)

    await service._run_creator_sync_behavior_prelude(
        api_base="http://mcp.test",
        env=env,
        persona=_persona(),
        plan=plan,
        progress_callback=capture_progress,
    )

    assert events == [
        "profile_prep",
        "current:http://mcp.test:4",
        "detail:feed-1",
        "context_switch",
    ]
    assert [item["phase"] for item in progress] == [
        "creator_behavior_planned",
        "creator_behavior_completed",
    ]
    assert progress[-1]["behavior_actions"] == ["current_home", "current_note_detail"]


@pytest.mark.asyncio
async def test_creator_profile_detail_route_falls_back_when_profile_url_is_missing(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]
    plan = build_creator_sync_behavior_plan(
        FixedRoll(1),
        forced_mode=int(CreatorSyncBehaviorMode.PROFILE_NOTE_DETAIL),
    )
    env = SimpleNamespace(id=18, account_name="无主页账号", profile_url=None)
    events: list[str] = []
    completed: list[dict] = []

    async def no_wait(*_args, **_kwargs):
        return None

    async def fake_fetch_current(self, *, api_base=None, limit=60):
        events.append("current_fallback")
        return {"feeds": [{"feed_id": "feed-fallback", "xsec_token": "token-fallback"}]}

    async def fake_detail(self, payload, *, api_base, persona):
        events.append("detail_fallback")
        return True

    async def capture_progress(payload: dict):
        completed.append(dict(payload))

    monkeypatch.setattr(XHSService, "_sleep_sync_profile_prep", no_wait)
    monkeypatch.setattr(XHSService, "_sleep_between_account_note_context_switch", no_wait)
    monkeypatch.setattr(XHSService, "_fetch_current_account_notes", fake_fetch_current)
    monkeypatch.setattr(XHSService, "_run_warmup_detail_peek", fake_detail)

    await service._run_creator_sync_behavior_prelude(
        api_base="http://mcp.test",
        env=env,
        persona=_persona(),
        plan=plan,
        progress_callback=capture_progress,
    )

    assert events == ["current_fallback", "detail_fallback"]
    assert completed[-1]["behavior_actions"] == [
        "current_home_fallback",
        "current_note_detail_fallback",
    ]


@pytest.mark.asyncio
async def test_creator_behavior_does_not_swallow_cancellation():
    service = XHSService(None)  # type: ignore[arg-type]
    plan = build_creator_sync_behavior_plan(FixedRoll(1), forced_mode=1)
    env = SimpleNamespace(id=19, account_name="取消账号", profile_url=None)

    with pytest.raises(SyncJobCancelled):
        await service._run_creator_sync_behavior_prelude(
            api_base="http://mcp.test",
            env=env,
            persona=_persona(),
            plan=plan,
            cancel_check=lambda: True,
        )
