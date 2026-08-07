#!/usr/bin/env python3
"""Fail CI when the Alembic graph has zero or multiple heads."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[1]
config = Config(str(ROOT / "backend" / "alembic.ini"))
config.set_main_option("script_location", str(ROOT / "backend" / "app" / "alembic"))
heads = ScriptDirectory.from_config(config).get_heads()

if len(heads) != 1:
    raise SystemExit(f"Expected exactly one Alembic head, found {len(heads)}: {heads}")

print(f"Alembic head: {heads[0]}")
