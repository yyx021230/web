"""add is_sync_runner to xhs_environments

Revision ID: fa9b7c6d5e4f
Revises: c9e8b7a6d5f4
Create Date: 2026-05-27 16:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "fa9b7c6d5e4f"
down_revision = "c9e8b7a6d5f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "xhs_environments",
        sa.Column("is_sync_runner", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("xhs_environments", "is_sync_runner")
