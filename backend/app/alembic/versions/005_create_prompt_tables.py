"""create prompt tables

Revision ID: 005
Revises: 6ac6769ce0b2
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "6ac6769ce0b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_categories",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("start_intro", sa.Text, nullable=True),
        sa.Column("sort_order", sa.Integer, server_default=sa.text("0")),
        sa.Column("deleted_at", sa.DateTime, nullable=True, index=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "prompt_examples",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("prompt_categories.id"), nullable=False, index=True),
        sa.Column("param_type", sa.String(100), nullable=False, index=True),
        sa.Column("image_num", sa.Integer, server_default=sa.text("0")),
        sa.Column("image_url", sa.String(500), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("chinese_example", sa.Text, nullable=False),
        sa.Column("english_example", sa.Text, nullable=False),
        sa.Column("ul_list", sa.JSON, server_default=sa.text("'[]'")),
        sa.Column("sort_order", sa.Integer, server_default=sa.text("0")),
        sa.Column("deleted_at", sa.DateTime, nullable=True, index=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("prompt_examples")
    op.drop_table("prompt_categories")
