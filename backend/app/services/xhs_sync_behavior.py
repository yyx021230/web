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
class CreatorSyncBehaviorOccurrence:
    """One independently sampled behavior occurrence in a sync session."""

    mode: CreatorSyncBehaviorMode
    pace: CreatorSyncPace
    entry_pause_seconds: float
    list_dwell_seconds: float
    detail_dwell_seconds: float
    context_switch_seconds: float
    final_transition_seconds: float
    note_limit: int
    profile_scroll_rounds: int
    profile_max_feeds: int
    profile_stagnant_rounds: int
    occasional_long_pause_seconds: float
    minimum_prelude_seconds: float

    @property
    def label(self) -> str:
        return _MODE_LABELS[self.mode]

    def progress_parameters(self) -> dict[str, object]:
        return {
            "mode": int(self.mode),
            "label": self.label,
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
            "minimum_prelude_seconds": round(self.minimum_prelude_seconds, 2),
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
    minimum_prelude_seconds: float = 0.0
    occurrences: tuple[CreatorSyncBehaviorOccurrence, ...] = ()

    @property
    def label(self) -> str:
        return _MODE_LABELS[self.mode]

    @property
    def is_direct(self) -> bool:
        return self.mode is CreatorSyncBehaviorMode.DIRECT

    def progress_parameters(self) -> dict[str, object]:
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
            "minimum_prelude_seconds": round(self.minimum_prelude_seconds, 2),
            "behavior_sequence": [int(item.mode) for item in self.occurrences],
            "behavior_occurrences": [item.progress_parameters() for item in self.occurrences],
            "occurrence_probabilities": {
                str(int(mode)): probability
                for mode, probability in _BEHAVIOR_OCCURRENCE_PROBABILITIES.items()
            },
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

_BEHAVIOR_OCCURRENCE_PROBABILITIES: dict[CreatorSyncBehaviorMode, int] = {
    CreatorSyncBehaviorMode.DIRECT: 18,
    CreatorSyncBehaviorMode.CURRENT_HOME: 62,
    CreatorSyncBehaviorMode.CURRENT_NOTE_DETAIL: 48,
    CreatorSyncBehaviorMode.PROFILE_HOME: 42,
    CreatorSyncBehaviorMode.PROFILE_NOTE_DETAIL: 32,
    CreatorSyncBehaviorMode.MIXED_HOME_AND_PROFILE: 24,
}

_BEHAVIOR_REPEAT_PROBABILITIES: dict[CreatorSyncBehaviorMode, int] = {
    CreatorSyncBehaviorMode.DIRECT: 8,
    CreatorSyncBehaviorMode.CURRENT_HOME: 15,
    CreatorSyncBehaviorMode.CURRENT_NOTE_DETAIL: 12,
    CreatorSyncBehaviorMode.PROFILE_HOME: 12,
    CreatorSyncBehaviorMode.PROFILE_NOTE_DETAIL: 10,
    CreatorSyncBehaviorMode.MIXED_HOME_AND_PROFILE: 8,
}

_MAX_BEHAVIOR_OCCURRENCES = 6


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
        entry=(1.5, 3.0),
        list_dwell=(5.0, 9.0),
        detail_dwell=(8.0, 14.0),
        context_switch=(3.0, 5.0),
        final_transition=(2.5, 5.0),
        note_limit=(3, 5),
        scroll_rounds=(1, 2),
        max_feeds=(8, 14),
        stagnant_rounds=(1, 1),
        long_pause_probability=8,
        long_pause=(8.0, 14.0),
    ),
    CreatorSyncPace.BALANCED: _PaceRanges(
        entry=(2.5, 5.0),
        list_dwell=(8.0, 16.0),
        detail_dwell=(12.0, 24.0),
        context_switch=(5.0, 9.0),
        final_transition=(4.0, 8.0),
        note_limit=(3, 8),
        scroll_rounds=(1, 3),
        max_feeds=(8, 24),
        stagnant_rounds=(1, 2),
        long_pause_probability=14,
        long_pause=(15.0, 25.0),
    ),
    CreatorSyncPace.SLOW: _PaceRanges(
        entry=(4.0, 8.0),
        list_dwell=(15.0, 28.0),
        detail_dwell=(22.0, 40.0),
        context_switch=(8.0, 15.0),
        final_transition=(7.0, 14.0),
        note_limit=(5, 8),
        scroll_rounds=(2, 4),
        max_feeds=(16, 30),
        stagnant_rounds=(1, 2),
        long_pause_probability=22,
        long_pause=(25.0, 45.0),
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
    if roll <= 20:
        return CreatorSyncPace.QUICK
    if roll <= 75:
        return CreatorSyncPace.BALANCED
    return CreatorSyncPace.SLOW


def _shuffle_modes(
    rng: BehaviorRandom,
    modes: list[CreatorSyncBehaviorMode],
) -> list[CreatorSyncBehaviorMode]:
    shuffled = list(modes)
    for index in range(len(shuffled) - 1, 0, -1):
        swap_index = rng.randint(0, index)
        shuffled[index], shuffled[swap_index] = shuffled[swap_index], shuffled[index]
    return shuffled


def _select_behavior_modes(
    rng: BehaviorRandom,
    *,
    forced_mode: int = 0,
) -> tuple[CreatorSyncBehaviorMode, ...]:
    try:
        return (CreatorSyncBehaviorMode(int(forced_mode)),)
    except (TypeError, ValueError):
        pass

    selected = [
        mode
        for mode, probability in _BEHAVIOR_OCCURRENCE_PROBABILITIES.items()
        if rng.randint(1, 100) <= probability
    ]
    if not selected:
        selected.append(_pick_weighted_mode(rng, _WEIGHTED_MODES))

    selected = _shuffle_modes(rng, selected)
    repeated = [
        mode
        for mode in selected
        if rng.randint(1, 100) <= _BEHAVIOR_REPEAT_PROBABILITIES[mode]
    ]
    repeat_slots = max(0, _MAX_BEHAVIOR_OCCURRENCES - len(selected))
    combined = selected + repeated[:repeat_slots]
    return tuple(_shuffle_modes(rng, combined))


_MINIMUM_PRELUDE_RANGES: dict[
    CreatorSyncPace,
    dict[CreatorSyncBehaviorMode, tuple[float, float]],
] = {
    CreatorSyncPace.QUICK: {
        CreatorSyncBehaviorMode.DIRECT: (8.0, 15.0),
        CreatorSyncBehaviorMode.CURRENT_HOME: (18.0, 30.0),
        CreatorSyncBehaviorMode.CURRENT_NOTE_DETAIL: (28.0, 45.0),
        CreatorSyncBehaviorMode.PROFILE_HOME: (25.0, 40.0),
        CreatorSyncBehaviorMode.PROFILE_NOTE_DETAIL: (40.0, 60.0),
        CreatorSyncBehaviorMode.MIXED_HOME_AND_PROFILE: (45.0, 70.0),
    },
    CreatorSyncPace.BALANCED: {
        CreatorSyncBehaviorMode.DIRECT: (12.0, 20.0),
        CreatorSyncBehaviorMode.CURRENT_HOME: (30.0, 45.0),
        CreatorSyncBehaviorMode.CURRENT_NOTE_DETAIL: (45.0, 70.0),
        CreatorSyncBehaviorMode.PROFILE_HOME: (40.0, 60.0),
        CreatorSyncBehaviorMode.PROFILE_NOTE_DETAIL: (60.0, 90.0),
        CreatorSyncBehaviorMode.MIXED_HOME_AND_PROFILE: (70.0, 105.0),
    },
    CreatorSyncPace.SLOW: {
        CreatorSyncBehaviorMode.DIRECT: (18.0, 28.0),
        CreatorSyncBehaviorMode.CURRENT_HOME: (45.0, 65.0),
        CreatorSyncBehaviorMode.CURRENT_NOTE_DETAIL: (70.0, 105.0),
        CreatorSyncBehaviorMode.PROFILE_HOME: (60.0, 85.0),
        CreatorSyncBehaviorMode.PROFILE_NOTE_DETAIL: (90.0, 135.0),
        CreatorSyncBehaviorMode.MIXED_HOME_AND_PROFILE: (105.0, 160.0),
    },
}


def _build_behavior_occurrence(
    rng: BehaviorRandom,
    mode: CreatorSyncBehaviorMode,
) -> CreatorSyncBehaviorOccurrence:
    pace = _pick_pace(rng)
    ranges = _PACE_RANGES[pace]
    occasional_long_pause_seconds = (
        rng.uniform(*ranges.long_pause)
        if rng.randint(1, 100) <= ranges.long_pause_probability
        else 0.0
    )
    return CreatorSyncBehaviorOccurrence(
        mode=mode,
        pace=pace,
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
        minimum_prelude_seconds=rng.uniform(*_MINIMUM_PRELUDE_RANGES[pace][mode]),
    )


def build_creator_sync_behavior_plan(
    rng: BehaviorRandom,
    *,
    forced_mode: int = 0,
    profile_available: bool = True,
) -> CreatorSyncBehaviorPlan:
    """Build a stable sequence of independently sampled read-only behaviors.

    ``forced_mode`` keeps one numbered behavior for debugging. Auto mode gives
    all six behaviors their own occurrence and repeat probabilities, so one
    session can contain a shuffled subset and occasional repeated behavior.
    ``profile_available`` remains accepted for compatibility; profile behavior
    can resolve the current account profile dynamically when no URL is saved.
    """

    del profile_available
    modes = _select_behavior_modes(rng, forced_mode=forced_mode)
    occurrences = tuple(_build_behavior_occurrence(rng, mode) for mode in modes)
    first = occurrences[0]
    selected_modes = {item.mode for item in occurrences}

    return CreatorSyncBehaviorPlan(
        mode=first.mode,
        pace=first.pace,
        visit_current_home=bool(selected_modes & {
            CreatorSyncBehaviorMode.CURRENT_HOME,
            CreatorSyncBehaviorMode.CURRENT_NOTE_DETAIL,
            CreatorSyncBehaviorMode.MIXED_HOME_AND_PROFILE,
        }),
        open_current_note_detail=CreatorSyncBehaviorMode.CURRENT_NOTE_DETAIL in selected_modes,
        visit_profile_home=bool(selected_modes & {
            CreatorSyncBehaviorMode.PROFILE_HOME,
            CreatorSyncBehaviorMode.PROFILE_NOTE_DETAIL,
            CreatorSyncBehaviorMode.MIXED_HOME_AND_PROFILE,
        }),
        open_profile_note_detail=CreatorSyncBehaviorMode.PROFILE_NOTE_DETAIL in selected_modes,
        entry_pause_seconds=first.entry_pause_seconds,
        list_dwell_seconds=first.list_dwell_seconds,
        detail_dwell_seconds=first.detail_dwell_seconds,
        context_switch_seconds=first.context_switch_seconds,
        final_transition_seconds=first.final_transition_seconds,
        note_limit=first.note_limit,
        profile_scroll_rounds=first.profile_scroll_rounds,
        profile_max_feeds=first.profile_max_feeds,
        profile_stagnant_rounds=first.profile_stagnant_rounds,
        occasional_long_pause_seconds=first.occasional_long_pause_seconds,
        minimum_prelude_seconds=min(
            240.0,
            sum(item.minimum_prelude_seconds for item in occurrences),
        ),
        occurrences=occurrences,
    )
