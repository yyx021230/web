"""add xhs account type

Revision ID: a1b2c3d4e5f6
Revises: 9c0d1e2f3a4b
Create Date: 2026-08-19 18:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "9c0d1e2f3a4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("xhs_environments")}
    indexes = {index["name"] for index in inspector.get_indexes("xhs_environments")}

    if "xhs_account_type" not in columns:
        with op.batch_alter_table("xhs_environments") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "xhs_account_type",
                    sa.String(length=40),
                    nullable=False,
                    server_default="enterprise_professional",
                )
            )
    if "ix_xhs_environments_xhs_account_type" not in indexes:
        op.create_index(
            "ix_xhs_environments_xhs_account_type",
            "xhs_environments",
            ["xhs_account_type"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("xhs_environments")}
    indexes = {index["name"] for index in inspector.get_indexes("xhs_environments")}

    if "ix_xhs_environments_xhs_account_type" in indexes:
        op.drop_index("ix_xhs_environments_xhs_account_type", table_name="xhs_environments")
    if "xhs_account_type" in columns:
        with op.batch_alter_table("xhs_environments") as batch_op:
            batch_op.drop_column("xhs_account_type")
