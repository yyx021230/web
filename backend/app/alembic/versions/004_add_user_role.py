"""add role column to users table

Revision ID: 004
Revises: 003
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("role", sa.String(20), nullable=False, server_default="viewer"))
    # 将现有用户设为 admin
    op.execute("UPDATE users SET role = 'admin' WHERE username = 'yuxuan'")


def downgrade() -> None:
    op.drop_column("users", "role")
