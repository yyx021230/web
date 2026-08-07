"""add sync_browser_start_config to xhs_environments

Revision ID: a7d6c9e0f1ab
Revises: f6a7b8c9d0e1
Create Date: 2026-05-21 11:30:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a7d6c9e0f1ab"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("xhs_environments", sa.Column("sync_browser_start_config", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("xhs_environments", "sync_browser_start_config")
