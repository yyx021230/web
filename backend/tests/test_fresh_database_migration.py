from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import pytest

import app.models  # noqa: F401 - register every ORM table on Base.metadata
from app.db.base import Base


BACKEND_DIR = Path(__file__).resolve().parents[1]
CURRENT_REVISION = "e61113b0b002"


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
            "xhs_creator_sync_rows",
            "hermes_workflow_schedules",
            "hermes_workflow_runs",
            "hermes_workflow_posts",
            "hermes_worker_states",
            "hermes_publish_jobs",
            "hermes_publish_attempts",
            "auth_sessions",
        }.issubset(tables)

        account_note_columns = _columns(connection, "xhs_account_notes")
        assert {
            "identity_status",
            "creator_identity_key",
            "creator_synced_at",
            "homepage_synced_at",
            "source_post_id",
        }.issubset(account_note_columns)
        account_note_info = {
            str(row[1]): row
            for row in connection.execute("PRAGMA table_info('xhs_account_notes')")
        }
        assert account_note_info["feed_id"][3] == 0
        assert "uq_xhs_account_notes_env_creator_key" in _indexes(connection, "xhs_account_notes")

        assert "history_hidden_at" in _columns(connection, "ai_tasks")
        assert "ix_ai_tasks_history_hidden_at" in _indexes(connection, "ai_tasks")

        creator_sync_columns = _columns(connection, "xhs_creator_sync_rows")
        assert {
            "sync_run_id",
            "environment_id",
            "matched_note_id",
            "source_key",
            "metrics",
            "raw_payload",
            "match_status",
        }.issubset(creator_sync_columns)

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

        assert connection.execute("SELECT COUNT(*) FROM hermes_publish_jobs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM hermes_publish_attempts").fetchone()[0] == 0

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


def test_current_database_additive_publish_upgrade_and_rollback(tmp_path):
    path = tmp_path / "publish-upgrade.db"
    _run_alembic(path, "upgrade", "c47f2a6d9b10")
    with sqlite3.connect(path) as connection:
        existing_tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        before = {
            table.name: connection.execute(f'SELECT COUNT(*) FROM "{table.name}"').fetchone()[0]
            for table in Base.metadata.tables.values()
            if table.name in existing_tables and not table.name.startswith("hermes_publish_")
        }
    _run_alembic(path, "upgrade", "head")
    with sqlite3.connect(path) as connection:
        assert _revision(connection) == CURRENT_REVISION
        _assert_migrated_schema_covers_orm_metadata(connection)
        for name, count in before.items():
            assert connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] == count
        assert connection.execute("SELECT COUNT(*) FROM hermes_publish_jobs").fetchone()[0] == 0
    # Only the new empty tables are downgraded in this isolated database.
    _run_alembic(path, "downgrade", "c47f2a6d9b10")
    with sqlite3.connect(path) as connection:
        assert _revision(connection) == "c47f2a6d9b10"
        for name, count in before.items():
            assert connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] == count


def test_cloud_schema_downgrade_refuses_to_delete_saved_observations(tmp_path):
    path = tmp_path / "cloud-retention.db"
    _run_alembic(path, "upgrade", "head")
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO xhs_environments (id,shop_id,account_name,status) VALUES (1,'test-shop','Test','active')")
        connection.execute("INSERT INTO xhs_cloud_imports (client_id,run_id,item_id,environment_id,payload_hash,payload,status) "
                           "VALUES ('test-client',?, '0',1,?, '{}','applied')", ('a' * 64, 'b' * 64))
        connection.commit()
    with pytest.raises(subprocess.CalledProcessError):
        _run_alembic(path, "downgrade", "e61010a0b001")
    with sqlite3.connect(path) as connection:
        assert _revision(connection) == "e61112a0b001"
        assert connection.execute("SELECT COUNT(*) FROM xhs_cloud_imports").fetchone()[0] == 1


def test_master_cutover_preserves_existing_creator_history_and_blocks_lossy_downgrade(tmp_path):
    path=tmp_path / "master-cutover-retention.db"
    _run_alembic(path,"upgrade","e61113a0b001")
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO xhs_environments (id,shop_id,account_name,status) VALUES (1,'fixture','Snapshot','active')")
        connection.execute("INSERT INTO xhs_account_sync_runs (id,job_id,sync_kind,source,status,request_config) VALUES (1,'fixture-run','engagement','manual','succeeded','{}')")
        connection.execute("INSERT INTO xhs_creator_sync_rows (sync_run_id,environment_id,source_row_index,source_key,title,metrics,raw_payload) VALUES (1,1,1,'fixture-key','Keep original','{}','{}')")
        connection.commit()
    _run_alembic(path,"upgrade","head")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT environment_id,account_id,title FROM xhs_creator_sync_rows").fetchone()==(1,None,"Keep original")
        connection.execute("INSERT INTO xhs_accounts (id,xhs_account_id,account_name,department,account_type,status,owner_label,sim_device_label,login_device_label,source_row,source_hash,revision) VALUES (1,'10000001','Canonical','xhs','personal','active','','','',1,'fixture',1)")
        connection.execute("INSERT INTO xhs_creator_sync_rows (sync_run_id,account_id,source_row_index,source_key,title,metrics,raw_payload) VALUES (1,1,1,'native-key','Keep native','{}','{}')")
        connection.commit()
    with pytest.raises(subprocess.CalledProcessError):
        _run_alembic(path,"downgrade","e61113a0b001")
    with sqlite3.connect(path) as connection:
        assert _revision(connection)==CURRENT_REVISION
        assert connection.execute("SELECT COUNT(*) FROM xhs_creator_sync_rows").fetchone()[0]==2
