"""add xhs account id to environments

Revision ID: 8b9c0d1e2f3a
Revises: 7a8b9c0d1e2f
Create Date: 2026-08-14 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "8b9c0d1e2f3a"
down_revision: Union[str, Sequence[str], None] = "7a8b9c0d1e2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("xhs_environments")}
    if "xhs_account_id" not in columns:
        with op.batch_alter_table("xhs_environments") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "xhs_account_id",
                    sa.String(length=100),
                    nullable=True,
                    comment="小红书账号ID",
                )
            )

    inspector = inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("xhs_environments")}
    if "ix_xhs_environments_xhs_account_id" not in indexes:
        op.create_index(
            "ix_xhs_environments_xhs_account_id",
            "xhs_environments",
            ["xhs_account_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("xhs_environments")}
    if "ix_xhs_environments_xhs_account_id" in indexes:
        op.drop_index("ix_xhs_environments_xhs_account_id", table_name="xhs_environments")

    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("xhs_environments")}
    if "xhs_account_id" in columns:
        with op.batch_alter_table("xhs_environments") as batch_op:
            batch_op.drop_column("xhs_account_id")
