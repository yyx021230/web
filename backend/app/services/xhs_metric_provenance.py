"""Field-level ownership without changing existing numeric storage contracts."""
from __future__ import annotations

from datetime import datetime

from app.models.xhs_account_note import XHSAccountNote


def may_enrich_metric(note: XHSAccountNote, field: str) -> bool:
    sources = getattr(note, "metric_sources", None)
    if sources is None:
        return note.creator_synced_at is None
    return (sources.get(field) or {}).get("source") not in {"phone_cloud", "creator_export"}


def record_metric(note: XHSAccountNote, field: str, source: str, at: datetime, *, precision: str = "exact") -> None:
    sources = dict(note.metric_sources or {})
    if note.metric_sources is None and note.creator_synced_at is not None and getattr(note, "id", None) is not None:
        # Retain the legacy whole-note protection when an export only supplies some fields.
        sources = {key: {"source": "creator_export", "captured_at": note.creator_synced_at.isoformat(),
                         "precision": "legacy"}
                   for key in ("view_count", "liked_count", "comment_count", "collected_count",
                               "share_count", "exposure_count", "cover_click_rate")}
    sources[field] = {"source": source, "captured_at": at.isoformat(), "precision": precision}
    note.metric_sources = sources
