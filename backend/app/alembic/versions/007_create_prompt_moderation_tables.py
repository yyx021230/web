"""create prompt moderation tables

Revision ID: 007
Revises: 006
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_reports",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("prompt_id", sa.Integer, sa.ForeignKey("prompt_examples.id"), nullable=False, index=True),
        sa.Column("reporter_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("reason", sa.String(100), nullable=False, server_default=sa.text("'其他'")),
        sa.Column("details", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("resolved_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True, index=True),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
        sa.Column("resolution_note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "prompt_audit_logs",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("prompt_id", sa.Integer, sa.ForeignKey("prompt_examples.id"), nullable=False, index=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("operator_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True, index=True),
        sa.Column("details", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("prompt_audit_logs")
    op.drop_table("prompt_reports")
