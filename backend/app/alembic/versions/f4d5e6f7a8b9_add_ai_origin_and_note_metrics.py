"""add ai origin and note metrics

Revision ID: f4d5e6f7a8b9
Revises: f3c4d5e6f7a8
Create Date: 2026-05-19 18:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "f3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("xhs_posts", sa.Column("ai_origin_type", sa.String(length=20), nullable=False, server_default="manual"))
    op.add_column("xhs_account_notes", sa.Column("comment_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("xhs_account_notes", sa.Column("share_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("xhs_account_notes", "share_count")
    op.drop_column("xhs_account_notes", "comment_count")
    op.drop_column("xhs_posts", "ai_origin_type")
