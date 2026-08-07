"""add account note runner assignment and browse events

Revision ID: bb7c8d9e0f1a
Revises: fa9b7c6d5e4f
Create Date: 2026-05-27 18:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "bb7c8d9e0f1a"
down_revision = "fa9b7c6d5e4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect_name = bind.dialect.name

    note_columns = {column["name"] for column in inspector.get_columns("xhs_account_notes")}
    note_indexes = {index["name"] for index in inspector.get_indexes("xhs_account_notes")}
    with op.batch_alter_table("xhs_account_notes") as batch_op:
        if "assigned_runner_environment_id" not in note_columns:
            batch_op.add_column(sa.Column("assigned_runner_environment_id", sa.Integer(), nullable=True))
        if "assignment_updated_at" not in note_columns:
            batch_op.add_column(sa.Column("assignment_updated_at", sa.DateTime(), nullable=True))
        if "ix_xhs_account_notes_assigned_runner_environment_id" not in note_indexes:
            batch_op.create_index(
                "ix_xhs_account_notes_assigned_runner_environment_id",
                ["assigned_runner_environment_id"],
                unique=False,
            )
        if dialect_name != "sqlite":
            batch_op.create_foreign_key(
                "fk_xhs_account_notes_assigned_runner_environment_id",
                "xhs_environments",
                ["assigned_runner_environment_id"],
                ["id"],
            )

    existing_tables = set(inspector.get_table_names())
    if "xhs_account_note_browse_events" not in existing_tables:
        op.create_table(
            "xhs_account_note_browse_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("note_id", sa.Integer(), nullable=False),
            sa.Column("runner_environment_id", sa.Integer(), nullable=False),
            sa.Column("browse_source", sa.String(length=40), nullable=False),
            sa.Column("job_id", sa.String(length=64), nullable=True),
            sa.Column("note_feed_id", sa.String(length=100), nullable=True),
            sa.Column("note_title", sa.String(length=255), nullable=True),
            sa.Column("note_post_url", sa.String(length=600), nullable=True),
            sa.Column("source_environment_id", sa.Integer(), nullable=True),
            sa.Column("source_account_name", sa.String(length=200), nullable=True),
            sa.Column("runner_account_name", sa.String(length=200), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(["note_id"], ["xhs_account_notes.id"]),
            sa.ForeignKeyConstraint(["runner_environment_id"], ["xhs_environments.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    event_indexes = {index["name"] for index in inspector.get_indexes("xhs_account_note_browse_events")} if "xhs_account_note_browse_events" in set(sa.inspect(bind).get_table_names()) else set()
    if "ix_xhs_account_note_browse_events_note_id" not in event_indexes:
        op.create_index("ix_xhs_account_note_browse_events_note_id", "xhs_account_note_browse_events", ["note_id"], unique=False)
    if "ix_xhs_account_note_browse_events_runner_environment_id" not in event_indexes:
        op.create_index("ix_xhs_account_note_browse_events_runner_environment_id", "xhs_account_note_browse_events", ["runner_environment_id"], unique=False)
    if "ix_xhs_account_note_browse_events_browse_source" not in event_indexes:
        op.create_index("ix_xhs_account_note_browse_events_browse_source", "xhs_account_note_browse_events", ["browse_source"], unique=False)
    if "ix_xhs_account_note_browse_events_job_id" not in event_indexes:
        op.create_index("ix_xhs_account_note_browse_events_job_id", "xhs_account_note_browse_events", ["job_id"], unique=False)
    if "ix_xhs_account_note_browse_events_note_feed_id" not in event_indexes:
        op.create_index("ix_xhs_account_note_browse_events_note_feed_id", "xhs_account_note_browse_events", ["note_feed_id"], unique=False)
    if "ix_xhs_account_note_browse_events_source_environment_id" not in event_indexes:
        op.create_index("ix_xhs_account_note_browse_events_source_environment_id", "xhs_account_note_browse_events", ["source_environment_id"], unique=False)
    if "ix_xhs_account_note_browse_events_created_at" not in event_indexes:
        op.create_index("ix_xhs_account_note_browse_events_created_at", "xhs_account_note_browse_events", ["created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "xhs_account_note_browse_events" in inspector.get_table_names():
        for index_name in [
            "ix_xhs_account_note_browse_events_created_at",
            "ix_xhs_account_note_browse_events_source_environment_id",
            "ix_xhs_account_note_browse_events_note_feed_id",
            "ix_xhs_account_note_browse_events_job_id",
            "ix_xhs_account_note_browse_events_browse_source",
            "ix_xhs_account_note_browse_events_runner_environment_id",
            "ix_xhs_account_note_browse_events_note_id",
        ]:
            existing_indexes = {index["name"] for index in inspector.get_indexes("xhs_account_note_browse_events")}
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name="xhs_account_note_browse_events")
        op.drop_table("xhs_account_note_browse_events")

    note_columns = {column["name"] for column in inspector.get_columns("xhs_account_notes")}
    note_indexes = {index["name"] for index in inspector.get_indexes("xhs_account_notes")}
    with op.batch_alter_table("xhs_account_notes") as batch_op:
        if "ix_xhs_account_notes_assigned_runner_environment_id" in note_indexes:
            batch_op.drop_index("ix_xhs_account_notes_assigned_runner_environment_id")
        if "assignment_updated_at" in note_columns:
            batch_op.drop_column("assignment_updated_at")
        if "assigned_runner_environment_id" in note_columns:
            batch_op.drop_column("assigned_runner_environment_id")
