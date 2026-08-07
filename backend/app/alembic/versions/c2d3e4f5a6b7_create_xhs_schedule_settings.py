"""create xhs schedule settings

Revision ID: c2d3e4f5a6b7
Revises: ab7d9e2c4f10, fb7a2d9c1e30
Create Date: 2026-06-26 18:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, Sequence[str], None] = ("ab7d9e2c4f10", "fb7a2d9c1e30")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "xhs_schedule_settings" in tables:
        return

    op.create_table(
        "xhs_schedule_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("run_time", sa.String(length=5), server_default="00:00", nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=32), nullable=True),
        sa.Column("last_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_key"),
    )
    op.create_index(op.f("ix_xhs_schedule_settings_id"), "xhs_schedule_settings", ["id"], unique=False)
    op.create_index(op.f("ix_xhs_schedule_settings_task_key"), "xhs_schedule_settings", ["task_key"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "xhs_schedule_settings" not in tables:
        return

    op.drop_index(op.f("ix_xhs_schedule_settings_task_key"), table_name="xhs_schedule_settings")
    op.drop_index(op.f("ix_xhs_schedule_settings_id"), table_name="xhs_schedule_settings")
    op.drop_table("xhs_schedule_settings")
