"""create Hermes content workflow tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-04 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())

    if "hermes_workflow_schedules" not in tables:
        schedule_table = op.create_table(
            "hermes_workflow_schedules",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("run_time", sa.String(length=5), server_default="09:00", nullable=False),
            sa.Column("timezone", sa.String(length=64), server_default="Asia/Shanghai", nullable=False),
            sa.Column("posts_per_account", sa.Integer(), server_default="5", nullable=False),
            sa.Column("accounts", sa.JSON(), nullable=False),
            sa.Column("instruction", sa.Text(), nullable=True),
            sa.Column("last_enqueued_for", sa.Date(), nullable=True),
            sa.Column("last_run_id", sa.Integer(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
        op.create_index("ix_hermes_workflow_schedules_id", "hermes_workflow_schedules", ["id"])
        op.create_index("ix_hermes_workflow_schedules_enabled", "hermes_workflow_schedules", ["enabled"])
        op.create_index("ix_hermes_workflow_schedules_last_enqueued_for", "hermes_workflow_schedules", ["last_enqueued_for"])
        op.bulk_insert(schedule_table, [{
            "name": "Hermes 每日 8×5",
            "enabled": False,
            "run_time": "09:00",
            "timezone": "Asia/Shanghai",
            "posts_per_account": 5,
            "accounts": [],
        }])

    if "hermes_workflow_runs" not in tables:
        op.create_table(
            "hermes_workflow_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("run_key", sa.String(length=64), nullable=False),
            sa.Column("source", sa.String(length=24), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("requested_by", sa.Integer(), nullable=True),
            sa.Column("schedule_id", sa.Integer(), nullable=True),
            sa.Column("scheduled_for", sa.Date(), nullable=True),
            sa.Column("parameters", sa.JSON(), nullable=False),
            sa.Column("total_posts", sa.Integer(), server_default="0", nullable=False),
            sa.Column("generated_posts", sa.Integer(), server_default="0", nullable=False),
            sa.Column("approved_posts", sa.Integer(), server_default="0", nullable=False),
            sa.Column("rejected_posts", sa.Integer(), server_default="0", nullable=False),
            sa.Column("worker_id", sa.String(length=160), nullable=True),
            sa.Column("output_manifest", sa.JSON(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("publish_requested_at", sa.DateTime(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["schedule_id"], ["hermes_workflow_schedules.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_key"),
        )
        for column in ("id", "run_key", "source", "status", "requested_by", "schedule_id", "scheduled_for", "worker_id", "created_at"):
            op.create_index(f"ix_hermes_workflow_runs_{column}", "hermes_workflow_runs", [column])

    if "hermes_workflow_posts" not in tables:
        op.create_table(
            "hermes_workflow_posts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("environment_id", sa.Integer(), nullable=False),
            sa.Column("owner_user_id", sa.Integer(), nullable=True),
            sa.Column("slot", sa.Integer(), nullable=False),
            sa.Column("account_name", sa.String(length=200), nullable=False),
            sa.Column("vehicle_model", sa.String(length=160), nullable=False),
            sa.Column("case_id", sa.String(length=120), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("title", sa.String(length=80), nullable=True),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("image_url", sa.String(length=1200), nullable=True),
            sa.Column("hard_pass", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("source_detail", sa.JSON(), nullable=True),
            sa.Column("review_comment", sa.Text(), nullable=True),
            sa.Column("reviewed_by", sa.Integer(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("publish_status", sa.String(length=32), server_default="not_requested", nullable=False),
            sa.Column("publish_external_id", sa.String(length=200), nullable=True),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(["environment_id"], ["xhs_environments.id"]),
            sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["hermes_workflow_runs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_id", "environment_id", "slot", name="uq_hermes_run_environment_slot"),
        )
        for column in ("id", "run_id", "environment_id", "owner_user_id", "status", "reviewed_by", "publish_status"):
            op.create_index(f"ix_hermes_workflow_posts_{column}", "hermes_workflow_posts", [column])

    if "hermes_worker_states" not in tables:
        op.create_table(
            "hermes_worker_states",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("worker_id", sa.String(length=160), nullable=False),
            sa.Column("status", sa.String(length=32), server_default="idle", nullable=False),
            sa.Column("current_run_id", sa.Integer(), nullable=True),
            sa.Column("capabilities", sa.JSON(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(["current_run_id"], ["hermes_workflow_runs.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("worker_id"),
        )
        for column in ("id", "worker_id", "status", "current_run_id", "last_seen_at"):
            op.create_index(f"ix_hermes_worker_states_{column}", "hermes_worker_states", [column])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    for table in ("hermes_worker_states", "hermes_workflow_posts", "hermes_workflow_runs", "hermes_workflow_schedules"):
        if table in tables:
            op.drop_table(table)
