from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol


class CreatorSyncBehaviorMode(IntEnum):
    """Read-only navigation routes used before creator-center synchronization."""

    DIRECT = 1
    CURRENT_HOME = 2
    CURRENT_NOTE_DETAIL = 3
    PROFILE_HOME = 4
    PROFILE_NOTE_DETAIL = 5
    MIXED_HOME_AND_PROFILE = 6


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

    @property
    def label(self) -> str:
        return _MODE_LABELS[self.mode]

    @property
    def is_direct(self) -> bool:
        return self.mode is CreatorSyncBehaviorMode.DIRECT

    def progress_parameters(self) -> dict[str, int | float]:
        return {
            "entry_pause_seconds": round(self.entry_pause_seconds, 2),
            "list_dwell_seconds": round(self.list_dwell_seconds, 2),
            "detail_dwell_seconds": round(self.detail_dwell_seconds, 2),
            "context_switch_seconds": round(self.context_switch_seconds, 2),
            "final_transition_seconds": round(self.final_transition_seconds, 2),
            "note_limit": self.note_limit,
            "profile_scroll_rounds": self.profile_scroll_rounds,
            "profile_max_feeds": self.profile_max_feeds,
            "profile_stagnant_rounds": self.profile_stagnant_rounds,
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


def build_creator_sync_behavior_plan(
    rng: BehaviorRandom,
    *,
    forced_mode: int = 0,
) -> CreatorSyncBehaviorPlan:
    """Build one stable behavior plan for a complete account sync session.

    ``forced_mode`` accepts 1-6. Any other value selects a weighted route.
    All routes are read-only; none performs likes, comments, follows, or other
    state-changing engagement.
    """

    try:
        mode = CreatorSyncBehaviorMode(int(forced_mode))
    except (TypeError, ValueError):
        roll = rng.randint(1, 100)
        cumulative = 0
        mode = CreatorSyncBehaviorMode.DIRECT
        for candidate, weight in _WEIGHTED_MODES:
            cumulative += weight
            if roll <= cumulative:
                mode = candidate
                break

    return CreatorSyncBehaviorPlan(
        mode=mode,
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
        entry_pause_seconds=rng.uniform(0.7, 2.4),
        list_dwell_seconds=rng.uniform(1.4, 4.8),
        detail_dwell_seconds=rng.uniform(2.5, 7.5),
        context_switch_seconds=rng.uniform(1.5, 4.5),
        final_transition_seconds=rng.uniform(1.2, 3.8),
        note_limit=rng.randint(3, 8),
        profile_scroll_rounds=rng.randint(1, 3),
        profile_max_feeds=rng.randint(8, 24),
        profile_stagnant_rounds=rng.randint(1, 2),
    )
