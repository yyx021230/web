from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "6f7a8b9c0d1e"
CURRENT_REVISION = "7a8b9c0d1e2f"


def _run_alembic(path: Path, *args: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{path.as_posix()}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _prepare_previous_revision(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            f"""
            CREATE TABLE alembic_version (
                version_num VARCHAR(32) NOT NULL PRIMARY KEY
            );
            INSERT INTO alembic_version (version_num)
            VALUES ('{PREVIOUS_REVISION}');
            """
        )


def _revision(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
    assert row is not None
    return str(row[0])


def _has_table(path: Path, table_name: str) -> bool:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
    return row is not None


def test_scheduler_lease_migration_upgrade_downgrade_and_reupgrade(tmp_path):
    database_path = tmp_path / "scheduler-lease-migration.db"
    _prepare_previous_revision(database_path)

    _run_alembic(database_path, "upgrade", CURRENT_REVISION)
    assert _revision(database_path) == CURRENT_REVISION
    assert _has_table(database_path, "scheduler_leases")
    with sqlite3.connect(database_path) as connection:
        indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list('scheduler_leases')"
            ).fetchall()
        }
        assert "ix_scheduler_leases_owner_id" in indexes
        assert "ix_scheduler_leases_lease_expires_at" in indexes
        connection.execute(
            """
            INSERT INTO scheduler_leases (
                lease_key, owner_id, acquired_at, heartbeat_at, lease_expires_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "background-scheduler",
                "instance-a",
                "2026-08-10 12:00:00",
                "2026-08-10 12:00:00",
                "2026-08-10 12:00:30",
            ),
        )
        try:
            connection.execute(
                "INSERT INTO scheduler_leases (lease_key) VALUES (?)",
                ("background-scheduler",),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("duplicate lease_key must be rejected")

    _run_alembic(database_path, "downgrade", PREVIOUS_REVISION)
    assert _revision(database_path) == PREVIOUS_REVISION
    assert not _has_table(database_path, "scheduler_leases")

    _run_alembic(database_path, "upgrade", CURRENT_REVISION)
    assert _revision(database_path) == CURRENT_REVISION
    assert _has_table(database_path, "scheduler_leases")
