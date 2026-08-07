"""add ai origin to xhs account notes

Revision ID: f5e6f7a8b9c0
Revises: f4d5e6f7a8b9
Create Date: 2026-05-19 18:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "f4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("xhs_account_notes", sa.Column("ai_origin_type", sa.String(length=20), nullable=False, server_default="manual"))


def downgrade() -> None:
    op.drop_column("xhs_account_notes", "ai_origin_type")
