"""add xhs report daily dashboard indexes

Revision ID: f9a8b7c6d5e4
Revises: fa9b7c6d5e4f
Create Date: 2026-06-22
"""

from alembic import op


revision = "f9a8b7c6d5e4"
down_revision = "fa9b7c6d5e4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_xhs_report_daily_type_date_account",
        "xhs_report_daily",
        ["report_type", "report_date", "account_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_xhs_report_daily_type_date",
        "xhs_report_daily",
        ["report_type", "report_date"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_xhs_report_daily_type_date", table_name="xhs_report_daily", if_exists=True)
    op.drop_index("ix_xhs_report_daily_type_date_account", table_name="xhs_report_daily", if_exists=True)
