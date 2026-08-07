"""add department to xhs environments

Revision ID: 4d5e6f7a8b9c
Revises: 3c4d5e6f7a8b
Create Date: 2026-07-24 14:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4d5e6f7a8b9c"
down_revision: Union[str, Sequence[str], None] = "3c4d5e6f7a8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("xhs_environments")}
    if "department" not in columns:
        op.add_column(
            "xhs_environments",
            sa.Column("department", sa.String(length=20), nullable=False, server_default="xhs"),
        )
        op.create_index("ix_xhs_environments_department", "xhs_environments", ["department"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("xhs_environments")}
    if "department" in columns:
        op.drop_index("ix_xhs_environments_department", table_name="xhs_environments")
        op.drop_column("xhs_environments", "department")
