from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


_BACKEND_SNAPSHOT = Path(__file__).resolve().parents[1] / "data" / "hermes_policy_cases.json"
_REPO_CASES = Path(__file__).resolve().parents[3] / "ops" / "xhs_hermes" / "config" / "cases.json"
_BACKEND_DISPLAY = _BACKEND_SNAPSHOT.with_name("hermes_policy_display.json")
_REPO_DISPLAY = _REPO_CASES.with_name("policy_display.json")


def _cases_path() -> Path | None:
    configured = str(os.environ.get("HERMES_POLICY_CASES_PATH") or "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.extend([_REPO_CASES, _BACKEND_SNAPSHOT])
    return next((path for path in candidates if path.exists() and path.is_file()), None)


def load_policy_cases() -> dict[str, dict[str, Any]]:
    path = _cases_path()
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(case_id): row
        for case_id, row in value.items()
        if isinstance(row, dict) and str(row.get("vehicle_model") or "").strip()
    }


def load_policy_display_rows() -> dict[str, list[dict[str, Any]]]:
    configured = str(os.environ.get("HERMES_POLICY_DISPLAY_PATH") or "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.extend([_REPO_DISPLAY, _BACKEND_DISPLAY])
    path = next((candidate for candidate in candidates if candidate.exists() and candidate.is_file()), None)
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(case_id): [row for row in rows if isinstance(row, dict)]
        for case_id, rows in value.items()
        if isinstance(rows, list)
    } if isinstance(value, dict) else {}


def policy_summaries() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    display_rows = load_policy_display_rows()
    for case_id, case in load_policy_cases().items():
        rows.append({
            "case_id": case_id,
            "brand": str(case.get("brand") or ""),
            "vehicle_model": str(case.get("vehicle_model") or ""),
            "policy_source": str(case.get("policy_source") or ""),
            "policy_source_title": str(case.get("policy_source_title") or ""),
            "policy_source_url": str(case.get("policy_source_url") or ""),
            "policy_deadline": case.get("policy_deadline"),
            "public_deadline": case.get("public_deadline"),
            "allow_multi_config_quote": bool(case.get("allow_multi_config_quote")),
            # 运营政策弹窗单独读取原表的国补、省补两列；生产 case 中不保存省补金额。
            "quote_rows": list(display_rows.get(case_id) or case.get("quote_rows") or []),
            "policy_text": str(case.get("policy_text") or ""),
        })
    return sorted(rows, key=lambda row: str(row["vehicle_model"]))
