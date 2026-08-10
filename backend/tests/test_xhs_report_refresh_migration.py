from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "5e6f7a8b9c0d"
CURRENT_REVISION = "6f7a8b9c0d1e"


def _database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def _run_alembic(path: Path, *args: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = _database_url(path)
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
            PRAGMA foreign_keys = ON;
            CREATE TABLE users (id INTEGER PRIMARY KEY);
            CREATE TABLE xhs_schedule_run_logs (id INTEGER PRIMARY KEY);
            CREATE TABLE alembic_version (
                version_num VARCHAR(32) NOT NULL PRIMARY KEY
            );
            INSERT INTO alembic_version (version_num)
            VALUES ('{PREVIOUS_REVISION}');
            INSERT INTO users (id) VALUES (1);
            INSERT INTO xhs_schedule_run_logs (id) VALUES (10);
            """
        )


def _current_revision(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        value = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
    assert value is not None
    return str(value[0])


def _has_table(path: Path, table_name: str) -> bool:
    with sqlite3.connect(path) as connection:
        value = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
    return value is not None


def test_report_refresh_migration_upgrade_downgrade_and_constraints(tmp_path):
    database_path = tmp_path / "report-refresh-migration.db"
    _prepare_previous_revision(database_path)

    _run_alembic(database_path, "upgrade", CURRENT_REVISION)
    assert _current_revision(database_path) == CURRENT_REVISION
    assert _has_table(database_path, "xhs_report_refresh_runs")

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        index_names = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list('xhs_report_refresh_runs')"
            ).fetchall()
        }
        assert "ix_xhs_report_refresh_runs_status_finished" in index_names

        connection.execute(
            """
            INSERT INTO xhs_report_refresh_runs (
                job_id, source, status, requested_by_user_id,
                schedule_run_id, request_config
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("migration-job", "manual", "queued", 1, 10, "{}"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO xhs_report_refresh_runs (
                    job_id, source, status, request_config
                ) VALUES (?, ?, ?, ?)
                """,
                ("migration-job", "manual", "queued", "{}"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO xhs_report_refresh_runs (
                    job_id, source, status, request_config
                ) VALUES (?, ?, ?, ?)
                """,
                ("bad-status", "manual", "unknown", "{}"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO xhs_report_refresh_runs (
                    job_id, source, status, requested_by_user_id, request_config
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("bad-user", "manual", "queued", 999, "{}"),
            )

        connection.execute("DELETE FROM users WHERE id = 1")
        connection.execute("DELETE FROM xhs_schedule_run_logs WHERE id = 10")
        foreign_keys = connection.execute(
            """
            SELECT requested_by_user_id, schedule_run_id
            FROM xhs_report_refresh_runs
            WHERE job_id = 'migration-job'
            """
        ).fetchone()
        assert foreign_keys == (None, None)

    _run_alembic(database_path, "downgrade", PREVIOUS_REVISION)
    assert _current_revision(database_path) == PREVIOUS_REVISION
    assert not _has_table(database_path, "xhs_report_refresh_runs")

    _run_alembic(database_path, "upgrade", CURRENT_REVISION)
    assert _current_revision(database_path) == CURRENT_REVISION
    assert _has_table(database_path, "xhs_report_refresh_runs")
