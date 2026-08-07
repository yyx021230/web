"""add_share_count_to_xhs_posts

Revision ID: c4a8f1e2d7b9
Revises: b7f3e2a1c9d4
Create Date: 2026-04-30 18:12:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4a8f1e2d7b9"
down_revision: Union[str, None] = "b7f3e2a1c9d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("xhs_posts")}
    if "share_count" not in columns:
        op.add_column(
            "xhs_posts",
            sa.Column("share_count", sa.Integer(), nullable=True, server_default="0", comment="转发量"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("xhs_posts")}
    if "share_count" in columns:
        with op.batch_alter_table("xhs_posts", schema=None) as batch_op:
            batch_op.drop_column("share_count")
