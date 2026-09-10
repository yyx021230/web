"""Hermes tools for one assigned mother copy and objective validation."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


OPERATOR_ROOT = Path(__file__).resolve().parents[3]
if str(OPERATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(OPERATOR_ROOT))

from core import sanitize_copy, validate_copy  # noqa: E402
from vehicle_knowledge import knowledge_for_case  # noqa: E402


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _read_json_env(name: str, fallback: Path | None = None) -> Any:
    configured = str(os.environ.get(name) or "").strip()
    path = Path(configured) if configured else fallback
    if path is None or not path.exists():
        raise RuntimeError(f"{name} does not point to a readable JSON file")
    return json.loads(path.read_text(encoding="utf-8"))


def _cases() -> dict[str, Any]:
    fallback = OPERATOR_ROOT / "config" / "cases.json"
    value = _read_json_env("XHS_CASES_PATH", fallback)
    if not isinstance(value, dict):
        raise RuntimeError("cases JSON must be an object")
    return value


def _mothers() -> dict[int, dict[str, Any]]:
    value = _read_json_env("XHS_ASSIGNED_MOTHERS_PATH")
    rows = value.get("mothers") if isinstance(value, dict) else value
    if not isinstance(rows, list):
        raise RuntimeError("assigned mothers JSON must contain a mothers list")
    return {
        int(row.get("id") or 0): row
        for row in rows
        if isinstance(row, dict) and int(row.get("id") or 0) > 0
    }


def _handle_get_case(params: dict[str, Any], **_: Any) -> str:
    try:
        case_id = str(params.get("case_id") or "").strip()
        mother_id = int(params.get("mother_id") or 0)
        case = _cases().get(case_id)
        mother = _mothers().get(mother_id)
        if not isinstance(case, dict):
            raise KeyError(f"unknown case_id: {case_id}")
        if not isinstance(mother, dict):
            raise KeyError(f"mother_id is not assigned to this run: {mother_id}")
        production_case = {key: value for key, value in case.items() if key != "display_quote_rows"}
        return _json({
            "success": True,
            "case_id": case_id,
            **production_case,
            "assigned_mother": mother,
            "product_knowledge": knowledge_for_case(case, mother),
        })
    except Exception as exc:
        return _json({"success": False, "error": f"{type(exc).__name__}: {exc}"})


def _handle_sanitize(params: dict[str, Any], **_: Any) -> str:
    try:
        title, content, changes = sanitize_copy(
            str(params.get("title") or ""),
            str(params.get("content") or ""),
        )
        return _json({
            "success": True,
            "title": title,
            "content": content,
            "changes": changes,
        })
    except Exception as exc:
        return _json({"success": False, "error": f"{type(exc).__name__}: {exc}"})


def _handle_validate(params: dict[str, Any], **_: Any) -> str:
    try:
        case_id = str(params.get("case_id") or "").strip()
        mother_id = int(params.get("selected_mother_id") or 0)
        case = _cases().get(case_id)
        mother = _mothers().get(mother_id)
        if not isinstance(case, dict):
            raise KeyError(f"unknown case_id: {case_id}")
        if not isinstance(mother, dict):
            raise KeyError(f"mother_id is not assigned to this run: {mother_id}")
        result = validate_copy(
            title=str(params.get("title") or ""),
            content=str(params.get("content") or ""),
            mother=mother,
            case=case,
        )
        return _json({"success": True, "case_id": case_id, **result})
    except Exception as exc:
        return _json({
            "success": False,
            "pass": False,
            "hard_errors": [f"validator_error: {type(exc).__name__}: {exc}"],
            "warnings": [],
            "blocking_rule": "hard_errors_only",
        })


GET_CASE_SCHEMA = {
    "name": "xhs_get_copy_case",
    "description": "Load the exact mother copy and current policy assigned by the batch planner.",
    "parameters": {
        "type": "object",
        "properties": {
            "case_id": {"type": "string"},
            "mother_id": {"type": "integer"},
        },
        "required": ["case_id", "mother_id"],
    },
}

SANITIZE_SCHEMA = {
    "name": "xhs_sanitize_copy",
    "description": "Replace only explicit banned dictionary terms with approved neutral text or symbols.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["title", "content"],
    },
}

VALIDATE_SCHEMA = {
    "name": "xhs_validate_copy",
    "description": "Validate complete copy; only objective hard_errors block delivery.",
    "parameters": {
        "type": "object",
        "properties": {
            "case_id": {"type": "string"},
            "selected_mother_id": {"type": "integer"},
            "title": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["case_id", "selected_mother_id", "title", "content"],
    },
}


def register(ctx: Any) -> None:
    ctx.register_tool(
        name="xhs_get_copy_case",
        toolset="xhs_copy",
        schema=GET_CASE_SCHEMA,
        handler=_handle_get_case,
    )
    ctx.register_tool(
        name="xhs_sanitize_copy",
        toolset="xhs_copy",
        schema=SANITIZE_SCHEMA,
        handler=_handle_sanitize,
    )
    ctx.register_tool(
        name="xhs_validate_copy",
        toolset="xhs_copy",
        schema=VALIDATE_SCHEMA,
        handler=_handle_validate,
    )
    ctx.register_skill("xhs-copy", Path(__file__).resolve().parent / "skills" / "xhs-copy" / "SKILL.md")
