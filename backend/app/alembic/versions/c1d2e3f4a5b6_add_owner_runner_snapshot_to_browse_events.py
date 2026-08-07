"""add owner runner snapshot to browse events

Revision ID: c1d2e3f4a5b6
Revises: bb7c8d9e0f1a
Create Date: 2026-05-28 11:55:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c1d2e3f4a5b6"
down_revision = "bb7c8d9e0f1a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect_name = bind.dialect.name

    event_columns = {column["name"] for column in inspector.get_columns("xhs_account_note_browse_events")}
    event_indexes = {index["name"] for index in inspector.get_indexes("xhs_account_note_browse_events")}
    with op.batch_alter_table("xhs_account_note_browse_events") as batch_op:
        if "owner_runner_environment_id" not in event_columns:
            batch_op.add_column(sa.Column("owner_runner_environment_id", sa.Integer(), nullable=True))
        if "owner_runner_account_name" not in event_columns:
            batch_op.add_column(sa.Column("owner_runner_account_name", sa.String(length=200), nullable=True))
        if "ix_xhs_account_note_browse_events_owner_runner_environment_id" not in event_indexes:
            batch_op.create_index(
                "ix_xhs_account_note_browse_events_owner_runner_environment_id",
                ["owner_runner_environment_id"],
                unique=False,
            )
        if dialect_name != "sqlite":
            batch_op.create_foreign_key(
                "fk_xhs_account_note_browse_events_owner_runner_environment_id",
                "xhs_environments",
                ["owner_runner_environment_id"],
                ["id"],
            )

    op.execute(
        """
        UPDATE xhs_account_note_browse_events
        SET owner_runner_environment_id = (
                SELECT n.assigned_runner_environment_id
                FROM xhs_account_notes AS n
                WHERE n.id = xhs_account_note_browse_events.note_id
            ),
            owner_runner_account_name = (
                SELECT e.account_name
                FROM xhs_environments AS e
                WHERE e.id = (
                    SELECT n.assigned_runner_environment_id
                    FROM xhs_account_notes AS n
                    WHERE n.id = xhs_account_note_browse_events.note_id
                )
            )
        WHERE owner_runner_environment_id IS NULL
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    event_columns = {column["name"] for column in inspector.get_columns("xhs_account_note_browse_events")}
    event_indexes = {index["name"] for index in inspector.get_indexes("xhs_account_note_browse_events")}
    with op.batch_alter_table("xhs_account_note_browse_events") as batch_op:
        if "ix_xhs_account_note_browse_events_owner_runner_environment_id" in event_indexes:
            batch_op.drop_index("ix_xhs_account_note_browse_events_owner_runner_environment_id")
        if "owner_runner_account_name" in event_columns:
            batch_op.drop_column("owner_runner_account_name")
        if "owner_runner_environment_id" in event_columns:
            batch_op.drop_column("owner_runner_environment_id")
