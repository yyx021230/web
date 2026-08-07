"""add promoted fields to xhs account notes

Revision ID: fa8c7d6e5f4b
Revises: f9a8b7c6d5e4
Create Date: 2026-06-22
"""

import sqlalchemy as sa
from alembic import op


revision = "fa8c7d6e5f4b"
down_revision = "f9a8b7c6d5e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("xhs_account_notes") as batch_op:
        batch_op.add_column(sa.Column("is_promoted", sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column("promoted_first_seen_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("promoted_last_seen_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("promoted_source", sa.String(length=64), nullable=True))
    op.create_index("ix_xhs_account_notes_is_promoted", "xhs_account_notes", ["is_promoted"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_xhs_account_notes_is_promoted", table_name="xhs_account_notes")
    with op.batch_alter_table("xhs_account_notes") as batch_op:
        batch_op.drop_column("promoted_source")
        batch_op.drop_column("promoted_last_seen_at")
        batch_op.drop_column("promoted_first_seen_at")
        batch_op.drop_column("is_promoted")
