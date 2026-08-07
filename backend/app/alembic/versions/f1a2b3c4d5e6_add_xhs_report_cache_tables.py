"""add_xhs_report_cache_tables

Revision ID: f1a2b3c4d5e6
Revises: c4a8f1e2d7b9
Create Date: 2026-05-13 15:10:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "c4a8f1e2d7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "xhs_report_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("account_name", sa.String(length=255), nullable=False),
        sa.Column("token", sa.String(length=1024), nullable=True),
        sa.Column("token_status", sa.String(length=32), nullable=True),
        sa.Column("token_message", sa.String(length=1024), nullable=True),
        sa.Column("token_timestamp", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id"),
    )
    op.create_index(op.f("ix_xhs_report_tokens_id"), "xhs_report_tokens", ["id"], unique=False)
    op.create_index(op.f("ix_xhs_report_tokens_account_id"), "xhs_report_tokens", ["account_id"], unique=True)
    op.create_index(op.f("ix_xhs_report_tokens_account_name"), "xhs_report_tokens", ["account_name"], unique=False)

    op.create_table(
        "xhs_report_daily",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_type", sa.String(length=16), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("account_name", sa.String(length=255), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_type", "account_id", "report_date", name="uq_xhs_report_daily_key"),
    )
    op.create_index(op.f("ix_xhs_report_daily_id"), "xhs_report_daily", ["id"], unique=False)
    op.create_index(op.f("ix_xhs_report_daily_report_type"), "xhs_report_daily", ["report_type"], unique=False)
    op.create_index(op.f("ix_xhs_report_daily_account_id"), "xhs_report_daily", ["account_id"], unique=False)
    op.create_index(op.f("ix_xhs_report_daily_account_name"), "xhs_report_daily", ["account_name"], unique=False)
    op.create_index(op.f("ix_xhs_report_daily_report_date"), "xhs_report_daily", ["report_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_xhs_report_daily_report_date"), table_name="xhs_report_daily")
    op.drop_index(op.f("ix_xhs_report_daily_account_name"), table_name="xhs_report_daily")
    op.drop_index(op.f("ix_xhs_report_daily_account_id"), table_name="xhs_report_daily")
    op.drop_index(op.f("ix_xhs_report_daily_report_type"), table_name="xhs_report_daily")
    op.drop_index(op.f("ix_xhs_report_daily_id"), table_name="xhs_report_daily")
    op.drop_table("xhs_report_daily")

    op.drop_index(op.f("ix_xhs_report_tokens_account_name"), table_name="xhs_report_tokens")
    op.drop_index(op.f("ix_xhs_report_tokens_account_id"), table_name="xhs_report_tokens")
    op.drop_index(op.f("ix_xhs_report_tokens_id"), table_name="xhs_report_tokens")
    op.drop_table("xhs_report_tokens")
