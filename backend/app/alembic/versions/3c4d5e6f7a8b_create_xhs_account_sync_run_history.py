"""create durable xhs account sync run history

Revision ID: 3c4d5e6f7a8b
Revises: 2b7c9d1e4f63, a6b7c8d9e0f1, f0a1b2c3d4e5
Create Date: 2026-07-23 15:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3c4d5e6f7a8b"
down_revision: Union[str, Sequence[str], None] = ("2b7c9d1e4f63", "a6b7c8d9e0f1", "f0a1b2c3d4e5")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "xhs_account_sync_runs" not in tables:
        op.create_table(
            "xhs_account_sync_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.String(length=64), nullable=False),
            sa.Column("sync_kind", sa.String(length=48), nullable=False),
            sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
            sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
            sa.Column("parent_run_id", sa.Integer(), nullable=True),
            sa.Column("request_config", sa.JSON(), nullable=False),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["parent_run_id"], ["xhs_account_sync_runs.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("job_id"),
        )
        op.create_index("ix_xhs_account_sync_runs_job_id", "xhs_account_sync_runs", ["job_id"], unique=True)
        op.create_index("ix_xhs_account_sync_runs_sync_kind", "xhs_account_sync_runs", ["sync_kind"], unique=False)
        op.create_index("ix_xhs_account_sync_runs_status", "xhs_account_sync_runs", ["status"], unique=False)
        op.create_index("ix_xhs_account_sync_runs_requested_by_user_id", "xhs_account_sync_runs", ["requested_by_user_id"], unique=False)
        op.create_index("ix_xhs_account_sync_runs_parent_run_id", "xhs_account_sync_runs", ["parent_run_id"], unique=False)

    if "xhs_account_sync_run_items" not in tables:
        op.create_table(
            "xhs_account_sync_run_items",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("environment_id", sa.Integer(), nullable=True),
            sa.Column("account_name", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("result", sa.JSON(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(["run_id"], ["xhs_account_sync_runs.id"]),
            sa.ForeignKeyConstraint(["environment_id"], ["xhs_environments.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_xhs_account_sync_run_items_run_id", "xhs_account_sync_run_items", ["run_id"], unique=False)
        op.create_index("ix_xhs_account_sync_run_items_environment_id", "xhs_account_sync_run_items", ["environment_id"], unique=False)
        op.create_index("ix_xhs_account_sync_run_items_status", "xhs_account_sync_run_items", ["status"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "xhs_account_sync_run_items" in inspector.get_table_names():
        for name in ("ix_xhs_account_sync_run_items_status", "ix_xhs_account_sync_run_items_environment_id", "ix_xhs_account_sync_run_items_run_id"):
            op.drop_index(name, table_name="xhs_account_sync_run_items")
        op.drop_table("xhs_account_sync_run_items")
    if "xhs_account_sync_runs" in inspector.get_table_names():
        for name in ("ix_xhs_account_sync_runs_parent_run_id", "ix_xhs_account_sync_runs_requested_by_user_id", "ix_xhs_account_sync_runs_status", "ix_xhs_account_sync_runs_sync_kind", "ix_xhs_account_sync_runs_job_id"):
            op.drop_index(name, table_name="xhs_account_sync_runs")
        op.drop_table("xhs_account_sync_runs")
