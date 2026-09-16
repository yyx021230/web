from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Protocol


class CreatorSyncBehaviorMode(IntEnum):
    """Read-only navigation routes used before creator-center synchronization."""

    DIRECT = 1
    CURRENT_HOME = 2
    CURRENT_NOTE_DETAIL = 3
    PROFILE_HOME = 4
    PROFILE_NOTE_DETAIL = 5
    MIXED_HOME_AND_PROFILE = 6


class CreatorSyncPace(str, Enum):
    QUICK = "quick"
    BALANCED = "balanced"
    SLOW = "slow"


_MODE_LABELS: dict[CreatorSyncBehaviorMode, str] = {
    CreatorSyncBehaviorMode.DIRECT: "直接同步",
    CreatorSyncBehaviorMode.CURRENT_HOME: "当前账号主页",
    CreatorSyncBehaviorMode.CURRENT_NOTE_DETAIL: "当前主页加笔记详情",
    CreatorSyncBehaviorMode.PROFILE_HOME: "账号个人主页",
    CreatorSyncBehaviorMode.PROFILE_NOTE_DETAIL: "个人主页加笔记详情",
    CreatorSyncBehaviorMode.MIXED_HOME_AND_PROFILE: "当前主页加个人主页",
}


@dataclass(frozen=True)
class CreatorSyncBehaviorPlan:
    mode: CreatorSyncBehaviorMode
    pace: CreatorSyncPace = CreatorSyncPace.BALANCED
    visit_current_home: bool = False
    open_current_note_detail: bool = False
    visit_profile_home: bool = False
    open_profile_note_detail: bool = False
    entry_pause_seconds: float = 0.0
    list_dwell_seconds: float = 0.0
    detail_dwell_seconds: float = 0.0
    context_switch_seconds: float = 0.0
    final_transition_seconds: float = 0.0
    note_limit: int = 4
    profile_scroll_rounds: int = 1
    profile_max_feeds: int = 8
    profile_stagnant_rounds: int = 1
    occasional_long_pause_seconds: float = 0.0

    @property
    def label(self) -> str:
        return _MODE_LABELS[self.mode]

    @property
    def is_direct(self) -> bool:
        return self.mode is CreatorSyncBehaviorMode.DIRECT

    def progress_parameters(self) -> dict[str, int | float | str]:
        return {
            "pace": self.pace.value,
            "entry_pause_seconds": round(self.entry_pause_seconds, 2),
            "list_dwell_seconds": round(self.list_dwell_seconds, 2),
            "detail_dwell_seconds": round(self.detail_dwell_seconds, 2),
            "context_switch_seconds": round(self.context_switch_seconds, 2),
            "final_transition_seconds": round(self.final_transition_seconds, 2),
            "note_limit": self.note_limit,
            "profile_scroll_rounds": self.profile_scroll_rounds,
            "profile_max_feeds": self.profile_max_feeds,
            "profile_stagnant_rounds": self.profile_stagnant_rounds,
            "occasional_long_pause_seconds": round(self.occasional_long_pause_seconds, 2),
        }


class BehaviorRandom(Protocol):
    def randint(self, a: int, b: int) -> int: ...

    def uniform(self, a: float, b: float) -> float: ...


_WEIGHTED_MODES: tuple[tuple[CreatorSyncBehaviorMode, int], ...] = (
    (CreatorSyncBehaviorMode.DIRECT, 20),
    (CreatorSyncBehaviorMode.CURRENT_HOME, 25),
    (CreatorSyncBehaviorMode.CURRENT_NOTE_DETAIL, 20),
    (CreatorSyncBehaviorMode.PROFILE_HOME, 15),
    (CreatorSyncBehaviorMode.PROFILE_NOTE_DETAIL, 10),
    (CreatorSyncBehaviorMode.MIXED_HOME_AND_PROFILE, 10),
)

_WEIGHTED_MODES_WITHOUT_PROFILE: tuple[tuple[CreatorSyncBehaviorMode, int], ...] = (
    (CreatorSyncBehaviorMode.DIRECT, 25),
    (CreatorSyncBehaviorMode.CURRENT_HOME, 45),
    (CreatorSyncBehaviorMode.CURRENT_NOTE_DETAIL, 30),
)


@dataclass(frozen=True)
class _PaceRanges:
    entry: tuple[float, float]
    list_dwell: tuple[float, float]
    detail_dwell: tuple[float, float]
    context_switch: tuple[float, float]
    final_transition: tuple[float, float]
    note_limit: tuple[int, int]
    scroll_rounds: tuple[int, int]
    max_feeds: tuple[int, int]
    stagnant_rounds: tuple[int, int]
    long_pause_probability: int
    long_pause: tuple[float, float]


_PACE_RANGES: dict[CreatorSyncPace, _PaceRanges] = {
    CreatorSyncPace.QUICK: _PaceRanges(
        entry=(0.4, 1.2),
        list_dwell=(1.0, 2.8),
        detail_dwell=(2.0, 4.8),
        context_switch=(0.8, 2.4),
        final_transition=(0.8, 2.0),
        note_limit=(3, 5),
        scroll_rounds=(1, 2),
        max_feeds=(8, 14),
        stagnant_rounds=(1, 1),
        long_pause_probability=6,
        long_pause=(4.0, 7.0),
    ),
    CreatorSyncPace.BALANCED: _PaceRanges(
        entry=(0.7, 2.4),
        list_dwell=(1.4, 4.8),
        detail_dwell=(2.5, 7.5),
        context_switch=(1.5, 4.5),
        final_transition=(1.2, 3.8),
        note_limit=(3, 8),
        scroll_rounds=(1, 3),
        max_feeds=(8, 24),
        stagnant_rounds=(1, 2),
        long_pause_probability=12,
        long_pause=(6.0, 11.0),
    ),
    CreatorSyncPace.SLOW: _PaceRanges(
        entry=(1.5, 3.5),
        list_dwell=(3.8, 8.0),
        detail_dwell=(6.0, 12.0),
        context_switch=(3.0, 6.0),
        final_transition=(2.5, 6.0),
        note_limit=(5, 8),
        scroll_rounds=(2, 4),
        max_feeds=(16, 30),
        stagnant_rounds=(1, 2),
        long_pause_probability=18,
        long_pause=(9.0, 16.0),
    ),
}


def _pick_weighted_mode(
    rng: BehaviorRandom,
    weighted_modes: tuple[tuple[CreatorSyncBehaviorMode, int], ...],
) -> CreatorSyncBehaviorMode:
    roll = rng.randint(1, 100)
    cumulative = 0
    for candidate, weight in weighted_modes:
        cumulative += weight
        if roll <= cumulative:
            return candidate
    return weighted_modes[-1][0]


def _pick_pace(rng: BehaviorRandom) -> CreatorSyncPace:
    roll = rng.randint(1, 100)
    if roll <= 30:
        return CreatorSyncPace.QUICK
    if roll <= 80:
        return CreatorSyncPace.BALANCED
    return CreatorSyncPace.SLOW


def build_creator_sync_behavior_plan(
    rng: BehaviorRandom,
    *,
    forced_mode: int = 0,
    profile_available: bool = True,
) -> CreatorSyncBehaviorPlan:
    """Build one stable behavior plan for a complete account sync session.

    ``forced_mode`` accepts 1-6. Any other value selects a weighted route.
    All routes are read-only; none performs likes, comments, follows, or other
    state-changing engagement.
    """

    try:
        mode = CreatorSyncBehaviorMode(int(forced_mode))
    except (TypeError, ValueError):
        mode = _pick_weighted_mode(
            rng,
            _WEIGHTED_MODES if profile_available else _WEIGHTED_MODES_WITHOUT_PROFILE,
        )

    pace = _pick_pace(rng)
    ranges = _PACE_RANGES[pace]
    occasional_long_pause_seconds = (
        rng.uniform(*ranges.long_pause)
        if rng.randint(1, 100) <= ranges.long_pause_probability
        else 0.0
    )

    return CreatorSyncBehaviorPlan(
        mode=mode,
        pace=pace,
        visit_current_home=mode in {
            CreatorSyncBehaviorMode.CURRENT_HOME,
            CreatorSyncBehaviorMode.CURRENT_NOTE_DETAIL,
            CreatorSyncBehaviorMode.MIXED_HOME_AND_PROFILE,
        },
        open_current_note_detail=mode is CreatorSyncBehaviorMode.CURRENT_NOTE_DETAIL,
        visit_profile_home=mode in {
            CreatorSyncBehaviorMode.PROFILE_HOME,
            CreatorSyncBehaviorMode.PROFILE_NOTE_DETAIL,
            CreatorSyncBehaviorMode.MIXED_HOME_AND_PROFILE,
        },
        open_profile_note_detail=mode is CreatorSyncBehaviorMode.PROFILE_NOTE_DETAIL,
        entry_pause_seconds=rng.uniform(*ranges.entry),
        list_dwell_seconds=rng.uniform(*ranges.list_dwell),
        detail_dwell_seconds=rng.uniform(*ranges.detail_dwell),
        context_switch_seconds=rng.uniform(*ranges.context_switch),
        final_transition_seconds=rng.uniform(*ranges.final_transition),
        note_limit=rng.randint(*ranges.note_limit),
        profile_scroll_rounds=rng.randint(*ranges.scroll_rounds),
        profile_max_feeds=rng.randint(*ranges.max_feeds),
        profile_stagnant_rounds=rng.randint(*ranges.stagnant_rounds),
        occasional_long_pause_seconds=occasional_long_pause_seconds,
    )
