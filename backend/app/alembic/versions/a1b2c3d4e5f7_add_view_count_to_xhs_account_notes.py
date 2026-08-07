"""add view_count to xhs_account_notes

Revision ID: a1b2c3d4e5f7
Revises: c1d2e3f4a5b6
Create Date: 2026-06-02 20:15:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("xhs_account_notes")}
    if "view_count" not in columns:
        with op.batch_alter_table("xhs_account_notes") as batch_op:
            batch_op.add_column(
                sa.Column("view_count", sa.Integer(), nullable=False, server_default="0", comment="浏览量")
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("xhs_account_notes")}
    if "view_count" in columns:
        with op.batch_alter_table("xhs_account_notes") as batch_op:
            batch_op.drop_column("view_count")
