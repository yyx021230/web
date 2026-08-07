"""add campaign id to xhs report daily

Revision ID: e8a1b2c3d4e5
Revises: a9c3e1f7b2d4
Create Date: 2026-05-19 00:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "e8a1b2c3d4e5"
down_revision: Union[str, None] = "a9c3e1f7b2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("xhs_report_daily")}
    indexes = {index["name"] for index in inspector.get_indexes("xhs_report_daily")}
    unique_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("xhs_report_daily")}

    def backfill_legacy_campaign_ids() -> None:
        bind.execute(
            sa.text(
                """
                UPDATE xhs_report_daily
                SET campaign_id = 'legacy-' || id
                WHERE campaign_id IS NULL OR campaign_id = ''
                """
            )
        )

    if bind.dialect.name == "sqlite":
        if "campaign_id" not in columns:
            with op.batch_alter_table("xhs_report_daily") as batch_op:
                batch_op.add_column(
                    sa.Column("campaign_id", sa.String(length=128), server_default="", nullable=False),
                )
            columns.add("campaign_id")
        backfill_legacy_campaign_ids()
        with op.batch_alter_table("xhs_report_daily") as batch_op:
            if "uq_xhs_report_daily_key" in unique_constraints:
                batch_op.drop_constraint("uq_xhs_report_daily_key", type_="unique")
            batch_op.create_unique_constraint(
                "uq_xhs_report_daily_key",
                ["report_type", "account_id", "report_date", "campaign_id"],
            )
        if op.f("ix_xhs_report_daily_campaign_id") not in indexes:
            op.create_index(op.f("ix_xhs_report_daily_campaign_id"), "xhs_report_daily", ["campaign_id"], unique=False)
        return

    if "campaign_id" not in columns:
        op.add_column(
            "xhs_report_daily",
            sa.Column("campaign_id", sa.String(length=128), server_default="", nullable=False),
        )
    backfill_legacy_campaign_ids()
    if op.f("ix_xhs_report_daily_campaign_id") not in indexes:
        op.create_index(op.f("ix_xhs_report_daily_campaign_id"), "xhs_report_daily", ["campaign_id"], unique=False)
    if "uq_xhs_report_daily_key" in unique_constraints:
        op.drop_constraint("uq_xhs_report_daily_key", "xhs_report_daily", type_="unique")
    op.create_unique_constraint(
        "uq_xhs_report_daily_key",
        "xhs_report_daily",
        ["report_type", "account_id", "report_date", "campaign_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("xhs_report_daily")}
    unique_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("xhs_report_daily")}

    if bind.dialect.name == "sqlite":
        if op.f("ix_xhs_report_daily_campaign_id") in indexes:
            op.drop_index(op.f("ix_xhs_report_daily_campaign_id"), table_name="xhs_report_daily")
        with op.batch_alter_table("xhs_report_daily") as batch_op:
            if "uq_xhs_report_daily_key" in unique_constraints:
                batch_op.drop_constraint("uq_xhs_report_daily_key", type_="unique")
            batch_op.create_unique_constraint(
                "uq_xhs_report_daily_key",
                ["report_type", "account_id", "report_date"],
            )
            batch_op.drop_column("campaign_id")
        return

    if "uq_xhs_report_daily_key" in unique_constraints:
        op.drop_constraint("uq_xhs_report_daily_key", "xhs_report_daily", type_="unique")
    op.create_unique_constraint(
        "uq_xhs_report_daily_key",
        "xhs_report_daily",
        ["report_type", "account_id", "report_date"],
    )
    if op.f("ix_xhs_report_daily_campaign_id") in indexes:
        op.drop_index(op.f("ix_xhs_report_daily_campaign_id"), table_name="xhs_report_daily")
    op.drop_column("xhs_report_daily", "campaign_id")
