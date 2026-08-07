"""create xhs ad daily aggregate tables

Revision ID: 0f1e2d3c4b5a
Revises: f9a8b7c6d5e4
Create Date: 2026-06-29 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "0f1e2d3c4b5a"
down_revision: Union[str, Sequence[str], None] = "f9a8b7c6d5e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


METRIC_COLUMNS = [
    sa.Column("fee", sa.Float(), nullable=False, server_default="0"),
    sa.Column("impression", sa.Float(), nullable=False, server_default="0"),
    sa.Column("click", sa.Float(), nullable=False, server_default="0"),
    sa.Column("message_consult", sa.Float(), nullable=False, server_default="0"),
    sa.Column("openings", sa.Float(), nullable=False, server_default="0"),
    sa.Column("conversion", sa.Float(), nullable=False, server_default="0"),
    sa.Column("interaction", sa.Float(), nullable=False, server_default="0"),
    sa.Column("comment", sa.Float(), nullable=False, server_default="0"),
    sa.Column("special_natural_leads", sa.Float(), nullable=False, server_default="0"),
    sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    ]


def _base_columns(include_account: bool = True) -> list[sa.Column]:
    columns = [
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("report_type", sa.String(length=16), nullable=False),
    ]
    if include_account:
        columns.extend([
            sa.Column("account_id", sa.String(length=64), nullable=False),
            sa.Column("account_name", sa.String(length=255), server_default="", nullable=False),
        ])
    columns.extend([
        sa.Column("buyer_user_id", sa.Integer(), nullable=True),
        sa.Column("buyer_name", sa.String(length=255), server_default="", nullable=False),
    ])
    return columns


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "xhs_ad_stats_daily_account" not in tables:
        op.create_table(
            "xhs_ad_stats_daily_account",
            *_base_columns(include_account=True),
            *METRIC_COLUMNS,
            *_timestamps(),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("stat_date", "report_type", "account_id", name="uq_xhs_ad_stats_daily_account_key"),
        )
        op.create_index("ix_xhs_ad_stats_daily_account_id", "xhs_ad_stats_daily_account", ["id"])
        op.create_index("ix_xhs_ad_stats_daily_account_stat_date", "xhs_ad_stats_daily_account", ["stat_date"])
        op.create_index("ix_xhs_ad_stats_daily_account_report_type", "xhs_ad_stats_daily_account", ["report_type"])
        op.create_index("ix_xhs_ad_stats_daily_account_account_id", "xhs_ad_stats_daily_account", ["account_id"])
        op.create_index("ix_xhs_ad_stats_daily_account_buyer_user_id", "xhs_ad_stats_daily_account", ["buyer_user_id"])
        op.create_index("ix_xhs_ad_stats_daily_account_date_type", "xhs_ad_stats_daily_account", ["stat_date", "report_type"])
        op.create_index("ix_xhs_ad_stats_daily_account_buyer_date", "xhs_ad_stats_daily_account", ["buyer_user_id", "stat_date"])

    if "xhs_ad_stats_daily_buyer" not in tables:
        op.create_table(
            "xhs_ad_stats_daily_buyer",
            *_base_columns(include_account=False),
            sa.Column("account_count", sa.Integer(), nullable=False, server_default="0"),
            *METRIC_COLUMNS,
            *_timestamps(),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("stat_date", "report_type", "buyer_user_id", name="uq_xhs_ad_stats_daily_buyer_key"),
        )
        op.create_index("ix_xhs_ad_stats_daily_buyer_id", "xhs_ad_stats_daily_buyer", ["id"])
        op.create_index("ix_xhs_ad_stats_daily_buyer_stat_date", "xhs_ad_stats_daily_buyer", ["stat_date"])
        op.create_index("ix_xhs_ad_stats_daily_buyer_report_type", "xhs_ad_stats_daily_buyer", ["report_type"])
        op.create_index("ix_xhs_ad_stats_daily_buyer_buyer_user_id", "xhs_ad_stats_daily_buyer", ["buyer_user_id"])
        op.create_index("ix_xhs_ad_stats_daily_buyer_date_type", "xhs_ad_stats_daily_buyer", ["stat_date", "report_type"])

    if "xhs_ad_stats_daily_brand" not in tables:
        op.create_table(
            "xhs_ad_stats_daily_brand",
            *_base_columns(include_account=True),
            sa.Column("brand", sa.String(length=120), nullable=False),
            sa.Column("fee", sa.Float(), nullable=False, server_default="0"),
            sa.Column("impression", sa.Float(), nullable=False, server_default="0"),
            sa.Column("click", sa.Float(), nullable=False, server_default="0"),
            sa.Column("conversion", sa.Float(), nullable=False, server_default="0"),
            sa.Column("interaction", sa.Float(), nullable=False, server_default="0"),
            sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
            *_timestamps(),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("stat_date", "report_type", "account_id", "brand", name="uq_xhs_ad_stats_daily_brand_key"),
        )
        op.create_index("ix_xhs_ad_stats_daily_brand_id", "xhs_ad_stats_daily_brand", ["id"])
        op.create_index("ix_xhs_ad_stats_daily_brand_stat_date", "xhs_ad_stats_daily_brand", ["stat_date"])
        op.create_index("ix_xhs_ad_stats_daily_brand_report_type", "xhs_ad_stats_daily_brand", ["report_type"])
        op.create_index("ix_xhs_ad_stats_daily_brand_account_id", "xhs_ad_stats_daily_brand", ["account_id"])
        op.create_index("ix_xhs_ad_stats_daily_brand_buyer_user_id", "xhs_ad_stats_daily_brand", ["buyer_user_id"])
        op.create_index("ix_xhs_ad_stats_daily_brand_brand", "xhs_ad_stats_daily_brand", ["brand"])
        op.create_index("ix_xhs_ad_stats_daily_brand_date_type", "xhs_ad_stats_daily_brand", ["stat_date", "report_type"])
        op.create_index("ix_xhs_ad_stats_daily_brand_buyer_date", "xhs_ad_stats_daily_brand", ["buyer_user_id", "stat_date"])

    if "xhs_ad_stats_daily_note" not in tables:
        op.create_table(
            "xhs_ad_stats_daily_note",
            *_base_columns(include_account=True),
            sa.Column("note_id", sa.String(length=128), nullable=False),
            sa.Column("note_title", sa.String(length=500), server_default="", nullable=False),
            sa.Column("xhs_account_name", sa.String(length=255), server_default="", nullable=False),
            sa.Column("primary_content_tag", sa.String(length=80), server_default="", nullable=False),
            sa.Column("secondary_content_tag", sa.String(length=120), server_default="", nullable=False),
            sa.Column("fee", sa.Float(), nullable=False, server_default="0"),
            sa.Column("impression", sa.Float(), nullable=False, server_default="0"),
            sa.Column("click", sa.Float(), nullable=False, server_default="0"),
            sa.Column("message_consult", sa.Float(), nullable=False, server_default="0"),
            sa.Column("openings", sa.Float(), nullable=False, server_default="0"),
            sa.Column("conversion", sa.Float(), nullable=False, server_default="0"),
            sa.Column("interaction", sa.Float(), nullable=False, server_default="0"),
            sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
            *_timestamps(),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("stat_date", "report_type", "account_id", "note_id", name="uq_xhs_ad_stats_daily_note_key"),
        )
        op.create_index("ix_xhs_ad_stats_daily_note_id", "xhs_ad_stats_daily_note", ["id"])
        op.create_index("ix_xhs_ad_stats_daily_note_stat_date", "xhs_ad_stats_daily_note", ["stat_date"])
        op.create_index("ix_xhs_ad_stats_daily_note_report_type", "xhs_ad_stats_daily_note", ["report_type"])
        op.create_index("ix_xhs_ad_stats_daily_note_account_id", "xhs_ad_stats_daily_note", ["account_id"])
        op.create_index("ix_xhs_ad_stats_daily_note_buyer_user_id", "xhs_ad_stats_daily_note", ["buyer_user_id"])
        op.create_index("ix_xhs_ad_stats_daily_note_note_id", "xhs_ad_stats_daily_note", ["note_id"])
        op.create_index("ix_xhs_ad_stats_daily_note_date_type", "xhs_ad_stats_daily_note", ["stat_date", "report_type"])
        op.create_index("ix_xhs_ad_stats_daily_note_buyer_date", "xhs_ad_stats_daily_note", ["buyer_user_id", "stat_date"])
        op.create_index("ix_xhs_ad_stats_daily_note_tag", "xhs_ad_stats_daily_note", ["primary_content_tag", "secondary_content_tag"])

    if "xhs_ad_stats_daily_content_tag" not in tables:
        op.create_table(
            "xhs_ad_stats_daily_content_tag",
            *_base_columns(include_account=True),
            sa.Column("primary_content_tag", sa.String(length=80), server_default="", nullable=False),
            sa.Column("secondary_content_tag", sa.String(length=120), server_default="", nullable=False),
            sa.Column("fee", sa.Float(), nullable=False, server_default="0"),
            sa.Column("conversion", sa.Float(), nullable=False, server_default="0"),
            sa.Column("click", sa.Float(), nullable=False, server_default="0"),
            sa.Column("interaction", sa.Float(), nullable=False, server_default="0"),
            sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
            *_timestamps(),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("stat_date", "report_type", "account_id", "primary_content_tag", "secondary_content_tag", name="uq_xhs_ad_stats_daily_content_tag_key"),
        )
        op.create_index("ix_xhs_ad_stats_daily_content_tag_id", "xhs_ad_stats_daily_content_tag", ["id"])
        op.create_index("ix_xhs_ad_stats_daily_content_tag_stat_date", "xhs_ad_stats_daily_content_tag", ["stat_date"])
        op.create_index("ix_xhs_ad_stats_daily_content_tag_report_type", "xhs_ad_stats_daily_content_tag", ["report_type"])
        op.create_index("ix_xhs_ad_stats_daily_content_tag_account_id", "xhs_ad_stats_daily_content_tag", ["account_id"])
        op.create_index("ix_xhs_ad_stats_daily_content_tag_buyer_user_id", "xhs_ad_stats_daily_content_tag", ["buyer_user_id"])
        op.create_index("ix_xhs_ad_stats_daily_content_tag_date_type", "xhs_ad_stats_daily_content_tag", ["stat_date", "report_type"])
        op.create_index("ix_xhs_ad_stats_daily_content_tag_buyer_date", "xhs_ad_stats_daily_content_tag", ["buyer_user_id", "stat_date"])
        op.create_index("ix_xhs_ad_stats_daily_content_tag_tags", "xhs_ad_stats_daily_content_tag", ["primary_content_tag", "secondary_content_tag"])


def downgrade() -> None:
    for table in (
        "xhs_ad_stats_daily_content_tag",
        "xhs_ad_stats_daily_note",
        "xhs_ad_stats_daily_brand",
        "xhs_ad_stats_daily_buyer",
        "xhs_ad_stats_daily_account",
    ):
        op.drop_table(table, if_exists=True)
