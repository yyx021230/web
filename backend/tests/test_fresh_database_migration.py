from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import app.models  # noqa: F401 - register every ORM table on Base.metadata
from app.db.base import Base


BACKEND_DIR = Path(__file__).resolve().parents[1]
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


def _revision(connection: sqlite3.Connection) -> str:
    row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert row is not None
    return str(row[0])


def _columns(connection: sqlite3.Connection, table_name: str) -> dict[str, str]:
    return {
        str(row[1]): str(row[2]).upper()
        for row in connection.execute(f"PRAGMA table_info('{table_name}')")
    }


def _indexes(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA index_list('{table_name}')")
    }


def _assert_migrated_schema_covers_orm_metadata(
    connection: sqlite3.Connection,
) -> None:
    migrated_tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
        if not str(row[0]).startswith("sqlite_")
    }
    expected_tables = set(Base.metadata.tables)
    missing_tables = expected_tables - migrated_tables
    assert not missing_tables, f"ORM tables missing from migrations: {missing_tables}"

    missing_columns: dict[str, set[str]] = {}
    for table_name, table in Base.metadata.tables.items():
        migrated_columns = set(_columns(connection, table_name))
        absent = set(table.columns.keys()) - migrated_columns
        if absent:
            missing_columns[table_name] = absent
    assert not missing_columns, f"ORM columns missing from migrations: {missing_columns}"


def test_empty_database_full_upgrade_downgrade_and_reupgrade(tmp_path):
    database_path = tmp_path / "fresh-database-migration.db"

    _run_alembic(database_path, "upgrade", "head")

    with sqlite3.connect(database_path) as connection:
        assert _revision(connection) == CURRENT_REVISION
        _assert_migrated_schema_covers_orm_metadata(connection)
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "dify_tasks",
            "dify_workflows",
            "jobs",
            "job_items",
            "job_attempts",
            "job_events",
            "scheduler_leases",
            "xhs_report_refresh_runs",
        }.issubset(tables)

        task_columns = _columns(connection, "dify_tasks")
        assert task_columns["task_id"] == "VARCHAR(100)"
        assert task_columns["progress"] == "VARCHAR(255)"
        assert {
            "ix_dify_tasks_id",
            "ix_dify_tasks_user_id",
            "ix_dify_tasks_workflow_id",
        }.issubset(_indexes(connection, "dify_tasks"))
        assert "ix_dify_tasks_status" not in _indexes(connection, "dify_tasks")

        workflow_columns = _columns(connection, "dify_workflows")
        assert {"api_key", "base_url", "created_by"}.issubset(workflow_columns)
        assert "instance_id" not in workflow_columns
        assert "app_id" not in workflow_columns
        assert {
            "ix_dify_workflows_id",
            "ix_dify_workflows_created_by",
        }.issubset(_indexes(connection, "dify_workflows"))

        material_columns = _columns(connection, "materials")
        assert {"design_json", "ai_meta", "file_size"}.issubset(material_columns)
        material_info = {
            str(row[1]): row
            for row in connection.execute("PRAGMA table_info('materials')")
        }
        assert material_info["url"][3] == 0

    _run_alembic(database_path, "downgrade", "base")
    with sqlite3.connect(database_path) as connection:
        remaining_tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
            if not str(row[0]).startswith("sqlite_")
        }
        assert remaining_tables == {"alembic_version"}

    _run_alembic(database_path, "upgrade", "head")
    with sqlite3.connect(database_path) as connection:
        assert _revision(connection) == CURRENT_REVISION
        assert "ix_dify_tasks_workflow_id" in _indexes(connection, "dify_tasks")
