from __future__ import annotations

import importlib
import io
import re

from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_postgres_publish_migration_uses_same_bounded_name_for_create_and_drop():
    migration = importlib.import_module(
        "app.alembic.versions.c3d4e5f6a7b8_add_hermes_publish_schedule"
    )
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    created = re.findall(r"ADD CONSTRAINT (\w+) FOREIGN KEY", sql)
    dropped = re.findall(r"DROP CONSTRAINT (\w+)", sql)
    assert len(created) == 1
    assert created == dropped
    assert len(created[0].encode("utf-8")) <= 63
    assert "REFERENCES xhs_environments (id)" in sql
    assert "FOREIGN KEY(publish_target_environment_id)" in sql


def test_sqlite_keeps_existing_full_constraint_name():
    from sqlalchemy import Column, ForeignKeyConstraint, Integer, MetaData, Table
    from sqlalchemy.dialects.sqlite import dialect
    from sqlalchemy.schema import CreateTable

    name = "fk_hermes_workflow_posts_publish_target_environment_id_xhs_environments"
    metadata = MetaData()
    Table("xhs_environments", metadata, Column("id", Integer, primary_key=True))
    with Operations.context(MigrationContext.configure(dialect_name="sqlite")) as operations:
        table = Table(
            "hermes_workflow_posts", metadata,
            Column("publish_target_environment_id", Integer),
            ForeignKeyConstraint(["publish_target_environment_id"], ["xhs_environments.id"], name=operations.f(name)),
        )
    assert f"CONSTRAINT {name}" in str(CreateTable(table).compile(dialect=dialect()))
