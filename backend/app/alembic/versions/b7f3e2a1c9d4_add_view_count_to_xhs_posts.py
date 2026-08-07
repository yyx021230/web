"""add_view_count_to_xhs_posts

Revision ID: b7f3e2a1c9d4
Revises: 6bd3612abcc9
Create Date: 2026-04-30 18:02:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7f3e2a1c9d4"
down_revision: Union[str, None] = "6bd3612abcc9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("xhs_posts")}
    if "view_count" not in columns:
        op.add_column(
            "xhs_posts",
            sa.Column("view_count", sa.Integer(), nullable=True, server_default="0", comment="浏览量"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("xhs_posts")}
    if "view_count" in columns:
        with op.batch_alter_table("xhs_posts", schema=None) as batch_op:
            batch_op.drop_column("view_count")
