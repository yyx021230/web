"""add cover image url to xhs account notes

Revision ID: e1f2a3b4c5d6
Revises: c9e8b7a6d5f4
Create Date: 2026-05-22 18:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "c9e8b7a6d5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "xhs_account_notes",
        sa.Column("cover_image_url", sa.String(length=1000), nullable=True, comment="帖子封面图"),
    )


def downgrade() -> None:
    op.drop_column("xhs_account_notes", "cover_image_url")
