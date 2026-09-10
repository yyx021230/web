"""add Hermes post publish schedule

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""

from alembic import op
import sqlalchemy as sa


revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hermes_workflow_posts") as batch_op:
        batch_op.add_column(sa.Column("publish_target_environment_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("scheduled_publish_at", sa.DateTime(), nullable=True))
        batch_op.create_foreign_key(
            op.f("fk_hermes_workflow_posts_publish_target_environment_id_xhs_environments"),
            "xhs_environments",
            ["publish_target_environment_id"],
            ["id"],
        )
    op.create_index(
        op.f("ix_hermes_workflow_posts_publish_target_environment_id"),
        "hermes_workflow_posts",
        ["publish_target_environment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_hermes_workflow_posts_scheduled_publish_at"),
        "hermes_workflow_posts",
        ["scheduled_publish_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_hermes_workflow_posts_scheduled_publish_at"), table_name="hermes_workflow_posts")
    op.drop_index(op.f("ix_hermes_workflow_posts_publish_target_environment_id"), table_name="hermes_workflow_posts")
    with op.batch_alter_table("hermes_workflow_posts") as batch_op:
        batch_op.drop_constraint(
            op.f("fk_hermes_workflow_posts_publish_target_environment_id_xhs_environments"),
            type_="foreignkey",
        )
        batch_op.drop_column("scheduled_publish_at")
        batch_op.drop_column("publish_target_environment_id")
