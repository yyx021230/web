"""add status to xhs_account_notes

Revision ID: d7e8f9a0b1c2
Revises: a1b2c3d4e5f7
Create Date: 2026-06-05 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("xhs_account_notes")}
    if "status" not in columns:
        with op.batch_alter_table("xhs_account_notes") as batch_op:
            batch_op.add_column(
                sa.Column("status", sa.String(length=20), nullable=False, server_default="active", comment="账号帖子状态 active/offline")
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("xhs_account_notes")}
    if "status" in columns:
        with op.batch_alter_table("xhs_account_notes") as batch_op:
            batch_op.drop_column("status")
