"""add content tags to xhs account notes

Revision ID: fb7a2d9c1e30
Revises: fa8c7d6e5f4b
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa


revision = "fb7a2d9c1e30"
down_revision = "fa8c7d6e5f4b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("xhs_account_notes")}
    with op.batch_alter_table("xhs_account_notes") as batch_op:
        if "primary_content_tag" not in columns:
            batch_op.add_column(sa.Column("primary_content_tag", sa.String(length=80), nullable=True))
        if "secondary_content_tag" not in columns:
            batch_op.add_column(sa.Column("secondary_content_tag", sa.String(length=120), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("xhs_account_notes")}
    with op.batch_alter_table("xhs_account_notes") as batch_op:
        if "secondary_content_tag" in columns:
            batch_op.drop_column("secondary_content_tag")
        if "primary_content_tag" in columns:
            batch_op.drop_column("primary_content_tag")
