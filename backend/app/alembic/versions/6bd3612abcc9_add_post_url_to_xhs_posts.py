"""add_post_url_to_xhs_posts

Revision ID: 6bd3612abcc9
Revises: 0aa83ceebeb5
Create Date: 2026-04-30 17:09:44.852585
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6bd3612abcc9'
down_revision: Union[str, None] = '0aa83ceebeb5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('xhs_posts', sa.Column('post_url', sa.String(500), nullable=True, comment="小红书帖子链接"))


def downgrade() -> None:
    op.drop_column('xhs_posts', 'post_url')
