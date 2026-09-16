from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from app.services.xhs_service import SyncJobCancelled, SyncSessionPersona, XHSService
from app.services.xhs_sync_behavior import (
    CreatorSyncBehaviorMode,
    CreatorSyncPace,
    build_creator_sync_behavior_plan,
)


class FixedRoll:
    def __init__(self, value: int):
        self.value = value

    def randint(self, a: int, b: int) -> int:
        return min(max(self.value, a), b)

    def uniform(self, a: float, b: float) -> float:
        return (a + b) / 2


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


def test_creator_behavior_auto_mode_can_combine_all_six_behaviors():
    plan = build_creator_sync_behavior_plan(FixedRoll(1))

    assert {item.mode for item in plan.occurrences} == set(CreatorSyncBehaviorMode)
    assert len(plan.occurrences) == 6


def test_creator_behavior_auto_mode_has_independent_probability_and_repetition():
    rng = random.Random(20260916)
    plans = [build_creator_sync_behavior_plan(rng) for _ in range(1200)]
    sequences = [tuple(item.mode for item in plan.occurrences) for plan in plans]

    for mode in CreatorSyncBehaviorMode:
        assert any(mode in sequence for sequence in sequences)
    assert any(len(sequence) > 1 for sequence in sequences)
    assert any(len(set(sequence)) < len(sequence) for sequence in sequences)
    assert len(set(sequences)) > 100


@pytest.mark.parametrize("forced_mode", range(1, 7))
def test_creator_behavior_can_force_each_numbered_route(forced_mode: int):
    plan = build_creator_sync_behavior_plan(FixedRoll(1), forced_mode=forced_mode)

    assert int(plan.mode) == forced_mode
    assert 1.5 <= plan.entry_pause_seconds <= 8.0
    assert 5.0 <= plan.list_dwell_seconds <= 28.0
    assert 8.0 <= plan.detail_dwell_seconds <= 40.0
    assert 1 <= plan.profile_scroll_rounds <= 4
    assert 8 <= plan.profile_max_feeds <= 30
    assert 8.0 <= plan.minimum_prelude_seconds <= 160.0


@pytest.mark.parametrize(
    ("roll", "expected"),
    [
        (1, CreatorSyncPace.QUICK),
        (20, CreatorSyncPace.QUICK),
        (21, CreatorSyncPace.BALANCED),
        (75, CreatorSyncPace.BALANCED),
        (76, CreatorSyncPace.SLOW),
        (100, CreatorSyncPace.SLOW),
    ],
)
def test_creator_behavior_selects_stable_session_pace(roll: int, expected: CreatorSyncPace):
    plan = build_creator_sync_behavior_plan(FixedRoll(roll), forced_mode=1)

    assert plan.pace is expected


def test_creator_behavior_does_not_remove_profile_probabilities_when_url_is_missing():
    with_profile = build_creator_sync_behavior_plan(FixedRoll(1), profile_available=True)
    without_profile = build_creator_sync_behavior_plan(FixedRoll(1), profile_available=False)

    assert [item.mode for item in without_profile.occurrences] == [
        item.mode for item in with_profile.occurrences
    ]
    assert CreatorSyncBehaviorMode.PROFILE_HOME in {
        item.mode for item in without_profile.occurrences
    }
    assert CreatorSyncBehaviorMode.PROFILE_NOTE_DETAIL in {
        item.mode for item in without_profile.occurrences
    }


@pytest.mark.asyncio
async def test_creator_direct_route_keeps_random_stabilization_delays(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]
    plan = build_creator_sync_behavior_plan(FixedRoll(1), forced_mode=1)
    env = SimpleNamespace(id=16, account_name="直接路线账号", profile_url=None)
    delays: list[float] = []
    progress: list[dict] = []

    async def fake_delay(self, seconds, cancel_check=None):
        delays.append(round(float(seconds), 2))

    async def capture_progress(payload: dict):
        progress.append(dict(payload))

    monkeypatch.setattr(XHSService, "_sleep_creator_behavior_delay", fake_delay)

    await service._run_creator_sync_behavior_prelude(
        api_base="http://mcp.test",
        env=env,
        persona=_persona(),
        plan=plan,
        progress_callback=capture_progress,
    )

    occurrence = plan.occurrences[0]
    assert delays[0] == round(occurrence.entry_pause_seconds, 2)
    assert round(occurrence.final_transition_seconds, 2) in delays
    assert delays[-1] == pytest.approx(occurrence.minimum_prelude_seconds, abs=0.01)
    assert progress[-1]["phase"] == "creator_behavior_completed"
    assert progress[-1]["behavior_actions"] == ["direct_pause"]


@pytest.mark.asyncio
async def test_creator_post_behavior_uses_distinct_progress_stage(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]
    plan = build_creator_sync_behavior_plan(FixedRoll(1), forced_mode=1)
    env = SimpleNamespace(id=22, account_name="后置路线账号", profile_url=None)
    progress: list[dict] = []

    async def no_wait(*_args, **_kwargs):
        return None

    async def capture_progress(payload: dict):
        progress.append(dict(payload))

    monkeypatch.setattr(XHSService, "_sleep_creator_behavior_delay", no_wait)

    await service._run_creator_sync_behavior_prelude(
        api_base="http://mcp.test",
        env=env,
        persona=_persona(),
        plan=plan,
        behavior_stage="after_creator",
        progress_callback=capture_progress,
    )

    assert [item["phase"] for item in progress] == [
        "creator_post_behavior_planned",
        "creator_post_behavior_completed",
    ]
    assert progress[-1]["behavior_stage"] == "after_creator"
    assert progress[-1]["behavior_actions"] == ["direct_pause"]


@pytest.mark.asyncio
async def test_creator_behavior_current_note_route_is_ordered_and_read_only(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]
    plan = build_creator_sync_behavior_plan(
        FixedRoll(50),
        forced_mode=int(CreatorSyncBehaviorMode.CURRENT_NOTE_DETAIL),
    )
    env = SimpleNamespace(id=17, account_name="行为账号", profile_url="")
    events: list[str] = []
    progress: list[dict] = []

    async def fake_delay(self, seconds, cancel_check=None):
        events.append(f"delay:{seconds:.2f}")

    async def fake_fetch_current(self, *, api_base=None, limit=60):
        events.append(f"current:{api_base}:{limit}")
        return {"feeds": [{"feed_id": "feed-1", "xsec_token": "token-1"}]}

    async def fake_detail(self, payload, *, api_base, persona):
        events.append(f"detail:{payload['feeds'][0]['feed_id']}")
        return True

    async def capture_progress(payload: dict):
        progress.append(dict(payload))

    monkeypatch.setattr(XHSService, "_sleep_creator_behavior_delay", fake_delay)
    monkeypatch.setattr(XHSService, "_fetch_current_account_notes", fake_fetch_current)
    monkeypatch.setattr(XHSService, "_run_warmup_detail_peek", fake_detail)

    await service._run_creator_sync_behavior_prelude(
        api_base="http://mcp.test",
        env=env,
        persona=_persona(),
        plan=plan,
        progress_callback=capture_progress,
    )

    assert events == [
        "delay:3.75",
        "current:http://mcp.test:8",
        "delay:12.00",
        "detail:feed-1",
        "delay:18.00",
        "delay:6.00",
        "delay:57.50",
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
        events.append("current_resolution")
        return {
            "user_id": "profileuser",
            "feeds": [{"feed_id": "feed-fallback", "xsec_token": "token-fallback"}],
        }

    async def fake_fetch_profile(self, profile_url, api_base=None, limit=120, **kwargs):
        events.append(f"profile:{profile_url}")
        return {"feeds": [{"feed_id": "feed-profile", "xsec_token": "token-profile"}]}

    async def fake_detail(self, payload, *, api_base, persona):
        events.append("detail_fallback")
        return True

    async def capture_progress(payload: dict):
        completed.append(dict(payload))

    monkeypatch.setattr(XHSService, "_sleep_creator_behavior_delay", no_wait)
    monkeypatch.setattr(XHSService, "_fetch_current_account_notes", fake_fetch_current)
    monkeypatch.setattr(XHSService, "_fetch_profile_account_notes", fake_fetch_profile)
    monkeypatch.setattr(XHSService, "_run_warmup_detail_peek", fake_detail)

    await service._run_creator_sync_behavior_prelude(
        api_base="http://mcp.test",
        env=env,
        persona=_persona(),
        plan=plan,
        progress_callback=capture_progress,
    )

    assert events == [
        "current_resolution",
        "profile:https://www.xiaohongshu.com/user/profile/profileuser",
        "detail_fallback",
    ]
    assert completed[-1]["behavior_actions"] == [
        "current_home_profile_resolution",
        "profile_home",
        "profile_note_detail",
    ]


@pytest.mark.asyncio
async def test_creator_mixed_route_randomizes_dwell_and_profile_scroll(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]
    plan = build_creator_sync_behavior_plan(
        FixedRoll(50),
        forced_mode=int(CreatorSyncBehaviorMode.MIXED_HOME_AND_PROFILE),
    )
    env = SimpleNamespace(
        id=20,
        account_name="混合路线账号",
        profile_url="https://www.xiaohongshu.com/user/profile/abc?xsec_token=xyz",
    )
    delays: list[float] = []
    profile_calls: list[dict] = []
    progress: list[dict] = []

    async def fake_delay(self, seconds, cancel_check=None):
        delays.append(round(float(seconds), 2))

    async def fake_fetch_current(self, *, api_base=None, limit=60):
        return {"feeds": []}

    async def fake_fetch_profile(self, profile_url, api_base=None, limit=120, **kwargs):
        profile_calls.append({"profile_url": profile_url, "limit": limit, **kwargs})
        return {"feeds": []}

    async def capture_progress(payload: dict):
        progress.append(dict(payload))

    monkeypatch.setattr(XHSService, "_sleep_creator_behavior_delay", fake_delay)
    monkeypatch.setattr(XHSService, "_fetch_current_account_notes", fake_fetch_current)
    monkeypatch.setattr(XHSService, "_fetch_profile_account_notes", fake_fetch_profile)

    await service._run_creator_sync_behavior_prelude(
        api_base="http://mcp.test",
        env=env,
        persona=_persona(),
        plan=plan,
        progress_callback=capture_progress,
    )

    assert delays[:5] == [3.75, 12.0, 7.0, 12.0, 6.0]
    assert delays[5] == pytest.approx(plan.minimum_prelude_seconds, abs=0.01)
    assert profile_calls == [
        {
            "profile_url": env.profile_url,
            "limit": 8,
            "scroll_mode": "input",
            "max_feeds": 24,
            "max_scroll_rounds": 3,
            "max_stagnant_rounds": 2,
        }
    ]
    assert progress[-1]["behavior_actions"] == ["current_home", "profile_home"]
    assert progress[-1]["behavior_parameters"]["profile_scroll_rounds"] == 3


@pytest.mark.asyncio
async def test_creator_mixed_route_continues_after_one_read_only_action_fails(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]
    plan = build_creator_sync_behavior_plan(
        FixedRoll(50),
        forced_mode=int(CreatorSyncBehaviorMode.MIXED_HOME_AND_PROFILE),
    )
    env = SimpleNamespace(
        id=21,
        account_name="降级路线账号",
        profile_url="https://www.xiaohongshu.com/user/profile/abc?xsec_token=xyz",
    )
    actions: list[str] = []
    progress: list[dict] = []

    async def no_wait(*_args, **_kwargs):
        return None

    async def broken_current(self, *, api_base=None, limit=60):
        raise RuntimeError("current home unavailable")

    async def working_profile(self, profile_url, api_base=None, limit=120, **kwargs):
        actions.append("profile_home")
        return {"feeds": []}

    async def capture_progress(payload: dict):
        progress.append(dict(payload))

    monkeypatch.setattr(XHSService, "_sleep_creator_behavior_delay", no_wait)
    monkeypatch.setattr(XHSService, "_fetch_current_account_notes", broken_current)
    monkeypatch.setattr(XHSService, "_fetch_profile_account_notes", working_profile)

    await service._run_creator_sync_behavior_prelude(
        api_base="http://mcp.test",
        env=env,
        persona=_persona(),
        plan=plan,
        progress_callback=capture_progress,
    )

    assert actions == ["profile_home"]
    assert progress[-1]["phase"] == "creator_behavior_completed"
    assert progress[-1]["behavior_actions"] == ["profile_home"]
    assert progress[-1]["behavior_failed_actions"] == [
        {
            "occurrence": 1,
            "mode": 6,
            "action": "current_home",
            "error": "current home unavailable",
        }
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
