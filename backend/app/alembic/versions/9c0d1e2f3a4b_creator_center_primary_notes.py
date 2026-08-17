"""make creator center the primary account-note source

Revision ID: 9c0d1e2f3a4b
Revises: 8b9c0d1e2f3a
Create Date: 2026-08-14 15:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "9c0d1e2f3a4b"
down_revision: Union[str, Sequence[str], None] = "8b9c0d1e2f3a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NOTE_COLUMNS = (
    sa.Column("identity_status", sa.String(length=32), nullable=False, server_default="resolved"),
    sa.Column("creator_identity_key", sa.String(length=64), nullable=True),
    sa.Column("identity_match_method", sa.String(length=40), nullable=True),
    sa.Column("identity_match_confidence", sa.Float(), nullable=True),
    sa.Column("creator_published_at_raw", sa.String(length=100), nullable=True),
    sa.Column("creator_first_seen_at", sa.DateTime(), nullable=True),
    sa.Column("creator_last_seen_at", sa.DateTime(), nullable=True),
    sa.Column("creator_synced_at", sa.DateTime(), nullable=True),
    sa.Column("homepage_synced_at", sa.DateTime(), nullable=True),
    sa.Column("source_post_id", sa.Integer(), nullable=True),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("xhs_account_notes")}
    with op.batch_alter_table("xhs_account_notes") as batch_op:
        batch_op.alter_column("feed_id", existing_type=sa.String(length=100), nullable=True)
        for column in NOTE_COLUMNS:
            if column.name not in existing_columns:
                batch_op.add_column(column)
        if "source_post_id" not in existing_columns:
            batch_op.create_foreign_key(
                "fk_xhs_account_notes_source_post_id",
                "xhs_posts",
                ["source_post_id"],
                ["id"],
            )

    op.execute(
        sa.text(
            "UPDATE xhs_account_notes "
            "SET identity_status = 'resolved', identity_match_method = 'feed_id', "
            "identity_match_confidence = 1.0, homepage_synced_at = last_seen_at "
            "WHERE feed_id IS NOT NULL AND TRIM(feed_id) <> ''"
        )
    )
    op.execute(
        sa.text(
            "UPDATE xhs_account_notes SET source_post_id = ("
            "SELECT p.id FROM xhs_posts p "
            "WHERE p.environment_id = xhs_account_notes.environment_id "
            "AND p.feed_id = xhs_account_notes.feed_id "
            "AND p.status = 'success' ORDER BY p.id DESC LIMIT 1"
            ") WHERE feed_id IS NOT NULL AND TRIM(feed_id) <> ''"
        )
    )

    inspector = inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("xhs_account_notes")}
    index_specs = (
        ("ix_xhs_account_notes_identity_status", ["identity_status"], False),
        ("ix_xhs_account_notes_creator_identity_key", ["creator_identity_key"], False),
        ("ix_xhs_account_notes_creator_synced_at", ["creator_synced_at"], False),
        ("ix_xhs_account_notes_homepage_synced_at", ["homepage_synced_at"], False),
        ("ix_xhs_account_notes_source_post_id", ["source_post_id"], False),
        ("uq_xhs_account_notes_env_creator_key", ["environment_id", "creator_identity_key"], True),
    )
    for name, columns, unique in index_specs:
        if name not in indexes:
            op.create_index(name, "xhs_account_notes", columns, unique=unique)

    if "xhs_creator_sync_rows" not in inspector.get_table_names():
        op.create_table(
            "xhs_creator_sync_rows",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("sync_run_id", sa.Integer(), nullable=True),
            sa.Column("environment_id", sa.Integer(), nullable=False),
            sa.Column("matched_note_id", sa.Integer(), nullable=True),
            sa.Column("source_row_index", sa.Integer(), nullable=False),
            sa.Column("source_key", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.Column("published_at_raw", sa.String(length=100), nullable=True),
            sa.Column("metrics", sa.JSON(), nullable=False),
            sa.Column("raw_payload", sa.JSON(), nullable=False),
            sa.Column("match_status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("match_method", sa.String(length=40), nullable=True),
            sa.Column("match_confidence", sa.Float(), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["sync_run_id"], ["xhs_account_sync_runs.id"]),
            sa.ForeignKeyConstraint(["environment_id"], ["xhs_environments.id"]),
            sa.ForeignKeyConstraint(["matched_note_id"], ["xhs_account_notes.id"]),
            sa.UniqueConstraint("sync_run_id", "environment_id", "source_row_index", name="uq_xhs_creator_sync_run_row"),
        )
        op.create_index("ix_xhs_creator_sync_rows_sync_run_id", "xhs_creator_sync_rows", ["sync_run_id"])
        op.create_index("ix_xhs_creator_sync_rows_environment_id", "xhs_creator_sync_rows", ["environment_id"])
        op.create_index("ix_xhs_creator_sync_rows_matched_note_id", "xhs_creator_sync_rows", ["matched_note_id"])
        op.create_index("ix_xhs_creator_sync_rows_source_key", "xhs_creator_sync_rows", ["source_key"])
        op.create_index("ix_xhs_creator_sync_rows_published_at", "xhs_creator_sync_rows", ["published_at"])
        op.create_index("ix_xhs_creator_sync_rows_match_status", "xhs_creator_sync_rows", ["match_status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "xhs_creator_sync_rows" in inspector.get_table_names():
        op.drop_table("xhs_creator_sync_rows")

    indexes = {index["name"] for index in inspect(bind).get_indexes("xhs_account_notes")}
    for name in (
        "uq_xhs_account_notes_env_creator_key",
        "ix_xhs_account_notes_source_post_id",
        "ix_xhs_account_notes_homepage_synced_at",
        "ix_xhs_account_notes_creator_synced_at",
        "ix_xhs_account_notes_creator_identity_key",
        "ix_xhs_account_notes_identity_status",
    ):
        if name in indexes:
            op.drop_index(name, table_name="xhs_account_notes")

    op.execute(sa.text("DELETE FROM xhs_account_notes WHERE feed_id IS NULL OR TRIM(feed_id) = ''"))
    existing_columns = {column["name"] for column in inspect(bind).get_columns("xhs_account_notes")}
    with op.batch_alter_table("xhs_account_notes") as batch_op:
        if "source_post_id" in existing_columns:
            batch_op.drop_constraint("fk_xhs_account_notes_source_post_id", type_="foreignkey")
        for column in reversed(NOTE_COLUMNS):
            if column.name in existing_columns:
                batch_op.drop_column(column.name)
        batch_op.alter_column("feed_id", existing_type=sa.String(length=100), nullable=False)
