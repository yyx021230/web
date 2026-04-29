"""create copywritings table

Revision ID: 003
Revises: 002
Create Date: 2026-04-24
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "copywritings",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("title", sa.String(255), nullable=False, index=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("tags", sa.JSON, default=[]),
        sa.Column("category", sa.String(100), nullable=True, index=True),
        sa.Column("created_by", sa.Integer, nullable=True, index=True),
        sa.Column("deleted_at", sa.DateTime, nullable=True, index=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("copywritings")
