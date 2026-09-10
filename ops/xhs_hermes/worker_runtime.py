"""Portable paths, environment loading and deployment-only concurrency ceilings."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def hermes_repo() -> Path:
    return Path(os.environ.get("HERMES_REPO") or ROOT.parents[2] / "hermes-xhs-lab").expanduser().resolve()


def hermes_python() -> Path:
    relative = Path("Scripts/python.exe") if sys.platform == "win32" else Path("bin/python")
    return Path(os.environ.get("HERMES_PYTHON") or hermes_repo() / ".venv" / relative).expanduser().absolute()


def runner_command() -> list[str]:
    # No shell expansion, zsh syntax, executable-bit assumptions or Mac paths.
    return [sys.executable, str(ROOT / "run_daily_8x5.py")]


def apply_worker_limits(config: dict[str, Any]) -> dict[str, Any]:
    result = dict(config)
    for variable, fields in (
        ("HERMES_MAX_TEXT_WORKERS", ("copy_workers", "image_plan_workers", "text_workers")),
        ("HERMES_MAX_IMAGE_WORKERS", ("image_workers",)),
    ):
        raw = os.environ.get(variable)
        if raw is None:
            continue
        ceiling = int(raw)
        if not 1 <= ceiling <= 16:
            raise ValueError(f"{variable} must be between 1 and 16")
        for field in fields:
            current = int(result.get(field) or ceiling)
            if current < 1:
                raise ValueError(f"{field} must be positive")
            result[field] = min(current, ceiling)
    return result
