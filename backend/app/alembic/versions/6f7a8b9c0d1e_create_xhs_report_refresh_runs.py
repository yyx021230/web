"""create xhs report refresh run history

Revision ID: 6f7a8b9c0d1e
Revises: 5e6f7a8b9c0d
Create Date: 2026-08-10 19:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6f7a8b9c0d1e"
down_revision: Union[str, Sequence[str], None] = "5e6f7a8b9c0d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "xhs_report_refresh_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=32), server_default="manual", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("schedule_run_id", sa.Integer(), nullable=True),
        sa.Column("request_config", sa.JSON(), nullable=False),
        sa.Column("result_summary", sa.JSON(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_xhs_report_refresh_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["schedule_run_id"], ["xhs_schedule_run_logs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index(
        "ix_xhs_report_refresh_runs_job_id",
        "xhs_report_refresh_runs",
        ["job_id"],
        unique=True,
    )
    op.create_index(
        "ix_xhs_report_refresh_runs_requested_by_user_id",
        "xhs_report_refresh_runs",
        ["requested_by_user_id"],
    )
    op.create_index(
        "ix_xhs_report_refresh_runs_schedule_run_id",
        "xhs_report_refresh_runs",
        ["schedule_run_id"],
    )
    op.create_index(
        "ix_xhs_report_refresh_runs_source",
        "xhs_report_refresh_runs",
        ["source"],
    )
    op.create_index(
        "ix_xhs_report_refresh_runs_status",
        "xhs_report_refresh_runs",
        ["status"],
    )
    op.create_index(
        "ix_xhs_report_refresh_runs_status_finished",
        "xhs_report_refresh_runs",
        ["status", "finished_at"],
    )


def downgrade() -> None:
    op.drop_table("xhs_report_refresh_runs")
