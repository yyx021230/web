"""add ai task history visibility

Revision ID: c47f2a6d9b10
Revises: b36e8d1f4a2c
"""

from alembic import op
import sqlalchemy as sa


revision = "c47f2a6d9b10"
down_revision = "b36e8d1f4a2c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_tasks", sa.Column("history_hidden_at", sa.DateTime(), nullable=True))
    op.create_index("ix_ai_tasks_history_hidden_at", "ai_tasks", ["history_hidden_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_tasks_history_hidden_at", table_name="ai_tasks")
    op.drop_column("ai_tasks", "history_hidden_at")
