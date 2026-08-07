"""create xhs account notes

Revision ID: f2b1c3d4e5f6
Revises: e8a1b2c3d4e5
Create Date: 2026-05-19 16:35:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f2b1c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "e8a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "xhs_account_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("account_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("profile_nickname", sa.String(length=200), nullable=True),
        sa.Column("red_id", sa.String(length=100), nullable=True),
        sa.Column("feed_id", sa.String(length=100), nullable=False),
        sa.Column("xsec_token", sa.String(length=255), nullable=True),
        sa.Column("post_url", sa.String(length=600), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("liked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("collected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sort_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.ForeignKeyConstraint(["environment_id"], ["xhs_environments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("environment_id", "feed_id", name="uq_xhs_account_notes_env_feed"),
    )
    op.create_index(op.f("ix_xhs_account_notes_id"), "xhs_account_notes", ["id"], unique=False)
    op.create_index(op.f("ix_xhs_account_notes_environment_id"), "xhs_account_notes", ["environment_id"], unique=False)
    op.create_index(op.f("ix_xhs_account_notes_feed_id"), "xhs_account_notes", ["feed_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_xhs_account_notes_feed_id"), table_name="xhs_account_notes")
    op.drop_index(op.f("ix_xhs_account_notes_environment_id"), table_name="xhs_account_notes")
    op.drop_index(op.f("ix_xhs_account_notes_id"), table_name="xhs_account_notes")
    op.drop_table("xhs_account_notes")
