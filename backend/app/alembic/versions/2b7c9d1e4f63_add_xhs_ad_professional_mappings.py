"""add xhs ad professional mappings

Revision ID: 2b7c9d1e4f63
Revises: 0f1e2d3c4b5a
Create Date: 2026-07-01 10:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "2b7c9d1e4f63"
down_revision: Union[str, Sequence[str], None] = "0f1e2d3c4b5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "xhs_ad_account_professional_mappings" in tables:
        return

    op.create_table(
        "xhs_ad_account_professional_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("account_name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("xhs_account_id", sa.String(length=64), nullable=False),
        sa.Column("xhs_account_name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("xhs_owner_name", sa.String(length=100), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", name="uq_xhs_ad_account_professional_account"),
    )
    op.create_index(
        op.f("ix_xhs_ad_account_professional_mappings_id"),
        "xhs_ad_account_professional_mappings",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_xhs_ad_account_professional_mappings_account_id"),
        "xhs_ad_account_professional_mappings",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_xhs_ad_account_professional_mappings_xhs_account_id"),
        "xhs_ad_account_professional_mappings",
        ["xhs_account_id"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "xhs_ad_account_professional_mappings" not in tables:
        return
    op.drop_index(op.f("ix_xhs_ad_account_professional_mappings_xhs_account_id"), table_name="xhs_ad_account_professional_mappings")
    op.drop_index(op.f("ix_xhs_ad_account_professional_mappings_account_id"), table_name="xhs_ad_account_professional_mappings")
    op.drop_index(op.f("ix_xhs_ad_account_professional_mappings_id"), table_name="xhs_ad_account_professional_mappings")
    op.drop_table("xhs_ad_account_professional_mappings")
