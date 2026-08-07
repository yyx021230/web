"""create xhs schedule run logs

Revision ID: a6b7c8d9e0f1
Revises: d4e5f6a7b8c9
Create Date: 2026-06-29 13:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "xhs_schedule_run_logs" in tables:
        return

    op.create_table(
        "xhs_schedule_run_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_key", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), server_default="schedule", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="running", nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_xhs_schedule_run_logs_id"), "xhs_schedule_run_logs", ["id"], unique=False)
    op.create_index(op.f("ix_xhs_schedule_run_logs_task_key"), "xhs_schedule_run_logs", ["task_key"], unique=False)
    op.create_index(op.f("ix_xhs_schedule_run_logs_status"), "xhs_schedule_run_logs", ["status"], unique=False)
    op.create_index(op.f("ix_xhs_schedule_run_logs_started_at"), "xhs_schedule_run_logs", ["started_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "xhs_schedule_run_logs" not in tables:
        return

    op.drop_index(op.f("ix_xhs_schedule_run_logs_started_at"), table_name="xhs_schedule_run_logs")
    op.drop_index(op.f("ix_xhs_schedule_run_logs_status"), table_name="xhs_schedule_run_logs")
    op.drop_index(op.f("ix_xhs_schedule_run_logs_task_key"), table_name="xhs_schedule_run_logs")
    op.drop_index(op.f("ix_xhs_schedule_run_logs_id"), table_name="xhs_schedule_run_logs")
    op.drop_table("xhs_schedule_run_logs")
