from __future__ import annotations

from typing import Any


REFERENCE_PAYLOAD_KEYS = ("image_data", "image_url", "images_data")


def compact_terminal_task_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Drop large input images once a task can no longer be retried by the worker."""

    compacted = dict(params or {})
    reference_count = 0
    if compacted.get("image_data"):
        reference_count += 1
    if compacted.get("image_url"):
        reference_count += 1
    images_data = compacted.get("images_data")
    if isinstance(images_data, list):
        reference_count += len([item for item in images_data if item])

    removed = False
    for key in REFERENCE_PAYLOAD_KEYS:
        if key in compacted:
            compacted.pop(key, None)
            removed = True
    compacted.pop("_processing_started_at", None)

    if removed:
        compacted["_input_reference_payload_removed"] = True
        compacted["_input_reference_count"] = reference_count
    return compacted
