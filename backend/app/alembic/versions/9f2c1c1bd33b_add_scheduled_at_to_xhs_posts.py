"""add_scheduled_at_to_xhs_posts

Revision ID: 9f2c1c1bd33b
Revises: c4a8f1e2d7b9
Create Date: 2026-05-04 22:05:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9f2c1c1bd33b"
down_revision: Union[str, None] = "c4a8f1e2d7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("xhs_posts")}
    if "scheduled_at" not in columns:
        op.add_column("xhs_posts", sa.Column("scheduled_at", sa.DateTime(), nullable=True, comment="定时发布时间"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("xhs_posts")}
    if "scheduled_at" in columns:
        with op.batch_alter_table("xhs_posts", schema=None) as batch_op:
            batch_op.drop_column("scheduled_at")
