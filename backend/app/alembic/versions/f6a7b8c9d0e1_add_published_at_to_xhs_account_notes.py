"""add published_at to xhs_account_notes

Revision ID: f6a7b8c9d0e1
Revises: f5e6f7a8b9c0
Create Date: 2026-05-20 16:50:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f6a7b8c9d0e1"
down_revision = "f5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("xhs_account_notes", sa.Column("published_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("xhs_account_notes", "published_at")
