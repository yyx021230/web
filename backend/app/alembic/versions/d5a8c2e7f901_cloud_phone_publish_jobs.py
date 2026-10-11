"""Durable Hermes cloud phone publishing; no historical schedule replay."""

from alembic import op
import sqlalchemy as sa

revision = "d5a8c2e7f901"
down_revision = "c47f2a6d9b10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hermes_publish_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("hermes_workflow_posts.id"), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("xhs_environments.id"), nullable=False),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("retry_at", sa.DateTime()),
        sa.Column("claim_token", sa.String(64)),
        sa.Column("lease_until", sa.DateTime()),
        sa.Column("device_id", sa.String(200)),
        sa.Column("app_slot", sa.String(8)),
        sa.Column("remote_job_id", sa.String(200)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("message", sa.String(500)),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("post_id", name="uq_hermes_publish_post"),
        sa.UniqueConstraint("request_key", name="uq_hermes_publish_request"),
    )
    op.create_index("ix_hermes_publish_due", "hermes_publish_jobs", ["status", "retry_at", "scheduled_at"])
    op.create_index("ix_hermes_publish_jobs_owner_user_id", "hermes_publish_jobs", ["owner_user_id"])
    op.create_table(
        "hermes_publish_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("hermes_publish_jobs.id"), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("remote_job_id", sa.String(200)),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("request_key", name="uq_hermes_publish_attempt_request"),
    )
    op.create_index("ix_hermes_publish_attempts_job_id", "hermes_publish_attempts", ["job_id"])


def downgrade() -> None:
    op.drop_table("hermes_publish_attempts")
    op.drop_table("hermes_publish_jobs")
