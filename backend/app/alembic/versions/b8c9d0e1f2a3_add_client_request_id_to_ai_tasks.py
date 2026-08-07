"""add client request id to ai tasks

Revision ID: b8c9d0e1f2a3
Revises: 1f2e3d4c5b6a, fa8c7d6e5f4b
Create Date: 2026-06-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = ("1f2e3d4c5b6a", "fa8c7d6e5f4b")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_tasks", sa.Column("client_request_id", sa.String(length=64), nullable=True))
    op.create_index("ix_ai_tasks_client_request_id", "ai_tasks", ["client_request_id"])
    op.create_index(
        "uq_ai_tasks_user_client_request",
        "ai_tasks",
        ["user_id", "client_request_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_ai_tasks_user_client_request", table_name="ai_tasks")
    op.drop_index("ix_ai_tasks_client_request_id", table_name="ai_tasks")
    op.drop_column("ai_tasks", "client_request_id")
