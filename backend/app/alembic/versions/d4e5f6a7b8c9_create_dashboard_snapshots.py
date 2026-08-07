"""create dashboard snapshots

Revision ID: d4e5f6a7b8c9
Revises: c2d3e4f5a6b7
Create Date: 2026-06-27 10:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "dashboard_snapshots" in tables:
        return

    op.create_table(
        "dashboard_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("namespace", sa.String(length=80), nullable=False),
        sa.Column("cache_key", sa.String(length=128), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_bytes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("namespace", "cache_key", name="uq_dashboard_snapshots_namespace_key"),
    )
    op.create_index(op.f("ix_dashboard_snapshots_id"), "dashboard_snapshots", ["id"], unique=False)
    op.create_index(op.f("ix_dashboard_snapshots_namespace"), "dashboard_snapshots", ["namespace"], unique=False)
    op.create_index(op.f("ix_dashboard_snapshots_cache_key"), "dashboard_snapshots", ["cache_key"], unique=False)
    op.create_index(op.f("ix_dashboard_snapshots_expires_at"), "dashboard_snapshots", ["expires_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "dashboard_snapshots" not in tables:
        return

    op.drop_index(op.f("ix_dashboard_snapshots_expires_at"), table_name="dashboard_snapshots")
    op.drop_index(op.f("ix_dashboard_snapshots_cache_key"), table_name="dashboard_snapshots")
    op.drop_index(op.f("ix_dashboard_snapshots_namespace"), table_name="dashboard_snapshots")
    op.drop_index(op.f("ix_dashboard_snapshots_id"), table_name="dashboard_snapshots")
    op.drop_table("dashboard_snapshots")
