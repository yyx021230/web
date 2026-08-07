"""add content fields to xhs_account_notes

Revision ID: b1c2d3e4f5a6
Revises: e1f2a3b4c5d6
Create Date: 2026-05-27 15:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "xhs_account_notes",
        sa.Column("content", sa.Text(), nullable=True, comment="帖子正文"),
    )
    op.add_column(
        "xhs_account_notes",
        sa.Column("image_urls", sa.JSON(), nullable=True, comment="帖子图片列表"),
    )
    op.add_column(
        "xhs_account_notes",
        sa.Column("content_status", sa.String(length=40), nullable=True, comment="正文同步状态"),
    )
    op.add_column(
        "xhs_account_notes",
        sa.Column("content_missing_reason", sa.String(length=255), nullable=True, comment="正文缺失原因"),
    )
    op.add_column(
        "xhs_account_notes",
        sa.Column("detail_synced_at", sa.DateTime(), nullable=True, comment="最近一次详情同步时间"),
    )


def downgrade() -> None:
    op.drop_column("xhs_account_notes", "detail_synced_at")
    op.drop_column("xhs_account_notes", "content_missing_reason")
    op.drop_column("xhs_account_notes", "content_status")
    op.drop_column("xhs_account_notes", "image_urls")
    op.drop_column("xhs_account_notes", "content")
