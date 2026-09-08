"""Explicit UI type preferences constrain source selection, not copy structure.

Default modes keep the original full eligible pool. Specific modes use source
text cues (not an LLM guarantee). Empty selections are reported before generation;
we never silently switch a requested type to unrelated templates.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path
from typing import Any

path = Path(__file__).resolve().parents[2] / 'backend/app/services/hermes_reference_types.py'
spec = importlib.util.spec_from_file_location('hermes_reference_types', path)
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)
APPROVED_SOURCE_SHA256 = catalog.APPROVED_NOTE_SHA256


def copy_type_pool(rows: list[dict[str, Any]], requested: str | None) -> list[dict[str, Any]]:
    return catalog.matching_pool(rows, 'copy', requested)


def required_prompt_count(rows: list[dict[str, Any]], *, requested: str | None,
                          total_tasks: int, case_tasks: int) -> int:
    """A precise single may retry its sole mother within existing attempt limits.

    Never weaken batch uniqueness or borrow an unrelated type for a reserve.
    Preserve the previously approved standalone-section exception for one post.
    """
    # Matching has already validated aliases. Defaults do not mean precise.
    precise = bool(requested and requested not in {'跟随母文结构', '跟随母图结构', 'auto'})
    if total_tasks == case_tasks == 1 and len(rows) == 1 and (
        precise or rows[0].get('source_section_title')
    ):
        return 1
    return case_tasks * 2


def image_type_pool(rows: list[dict[str, Any]], requested: str | None, classifier) -> list[dict[str, Any]]:
    if requested in {'note_poster', '手账便签风'}:
        rows = [approved_note_section(row, classifier) for row in rows]
    return catalog.matching_pool(rows, 'image', requested, classifier)


def approved_note_section(row: dict[str, Any], classifier) -> dict[str, Any]:
    """User-approved section of #324; preserve the online original and its ID.

    This is an in-memory source view, not a write to the online prompt library.
    If its boundaries change, don't silently guess a different source.
    """
    derived = catalog.approved_image_section(row, expected_sha=APPROVED_SOURCE_SHA256)
    if derived is row:
        return row
    derived['template_type'] = classifier(derived)
    return derived
