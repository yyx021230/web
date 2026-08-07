"""add sync cloud update fields to xhs environments

Revision ID: c9e8b7a6d5f4
Revises: a7d6c9e0f1ab
Create Date: 2026-05-22 10:12:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c9e8b7a6d5f4"
down_revision = "a7d6c9e0f1ab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("xhs_environments", sa.Column("sync_cloud_session_id", sa.String(length=100), nullable=True))
    op.add_column("xhs_environments", sa.Column("sync_cloud_api_key", sa.String(length=255), nullable=True))
    op.add_column("xhs_environments", sa.Column("sync_cloud_update_config", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("xhs_environments", "sync_cloud_update_config")
    op.drop_column("xhs_environments", "sync_cloud_api_key")
    op.drop_column("xhs_environments", "sync_cloud_session_id")
