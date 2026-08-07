"""add xhs profile stat daily

Revision ID: fd2a8c3e1b90
Revises: b8c9d0e1f2a3
Create Date: 2026-06-23 16:10:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "fd2a8c3e1b90"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "xhs_profile_stat_daily" not in tables:
        op.create_table(
            "xhs_profile_stat_daily",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("stat_date", sa.Date(), nullable=False),
            sa.Column("channel_account_name", sa.String(length=255), nullable=False),
            sa.Column("channel_account_key", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("total_visits", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("leads", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("natural_source_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ad_paid_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("natural_openings", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ad_openings", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("natural_leads", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("special_natural_leads", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ad_leads", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("direct_private_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("private_leads", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("comment_users", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("comment_leads", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("xhs_ad_leads", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("natural_opening_conversion_rate", sa.Float(), nullable=False, server_default="0"),
            sa.Column("ad_opening_conversion_rate", sa.Float(), nullable=False, server_default="0"),
            sa.Column("comment_lead_rate", sa.Float(), nullable=False, server_default="0"),
            sa.Column("private_lead_rate", sa.Float(), nullable=False, server_default="0"),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("stat_date", "channel_account_name", name="uq_xhs_profile_stat_daily_account_date"),
        )

    existing_indexes = {index["name"] for index in inspector.get_indexes("xhs_profile_stat_daily")}
    if op.f("ix_xhs_profile_stat_daily_id") not in existing_indexes:
        op.create_index(op.f("ix_xhs_profile_stat_daily_id"), "xhs_profile_stat_daily", ["id"], unique=False)
    if op.f("ix_xhs_profile_stat_daily_stat_date") not in existing_indexes:
        op.create_index(op.f("ix_xhs_profile_stat_daily_stat_date"), "xhs_profile_stat_daily", ["stat_date"], unique=False)
    if op.f("ix_xhs_profile_stat_daily_channel_account_name") not in existing_indexes:
        op.create_index(op.f("ix_xhs_profile_stat_daily_channel_account_name"), "xhs_profile_stat_daily", ["channel_account_name"], unique=False)
    if op.f("ix_xhs_profile_stat_daily_channel_account_key") not in existing_indexes:
        op.create_index(op.f("ix_xhs_profile_stat_daily_channel_account_key"), "xhs_profile_stat_daily", ["channel_account_key"], unique=False)
    if "ix_xhs_profile_stat_daily_date_account" not in existing_indexes:
        op.create_index(
            "ix_xhs_profile_stat_daily_date_account",
            "xhs_profile_stat_daily",
            ["stat_date", "channel_account_key"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("ix_xhs_profile_stat_daily_date_account", table_name="xhs_profile_stat_daily")
    op.drop_index(op.f("ix_xhs_profile_stat_daily_channel_account_key"), table_name="xhs_profile_stat_daily")
    op.drop_index(op.f("ix_xhs_profile_stat_daily_channel_account_name"), table_name="xhs_profile_stat_daily")
    op.drop_index(op.f("ix_xhs_profile_stat_daily_stat_date"), table_name="xhs_profile_stat_daily")
    op.drop_index(op.f("ix_xhs_profile_stat_daily_id"), table_name="xhs_profile_stat_daily")
    op.drop_table("xhs_profile_stat_daily")
