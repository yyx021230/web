"""add scrape review workflow tables

Revision ID: a9c3e1f7b2d4
Revises: 4f6c2d8e8b7a, f1a2b3c4d5e6
Create Date: 2026-05-14 11:20:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9c3e1f7b2d4"
down_revision: Union[str, Sequence[str], None] = ("4f6c2d8e8b7a", "f1a2b3c4d5e6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scrape_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reviewer_mode", sa.String(length=20), nullable=False),
        sa.Column("source_config", sa.JSON(), nullable=True),
        sa.Column("max_items", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("saved_path", sa.String(length=500), nullable=True),
        sa.Column("run_meta", sa.JSON(), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("approved_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("needs_second_review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scrape_tasks_id"), "scrape_tasks", ["id"], unique=False)
    op.create_index(op.f("ix_scrape_tasks_source"), "scrape_tasks", ["source"], unique=False)
    op.create_index(op.f("ix_scrape_tasks_status"), "scrape_tasks", ["status"], unique=False)
    op.create_index(op.f("ix_scrape_tasks_created_by"), "scrape_tasks", ["created_by"], unique=False)

    op.create_table(
        "scrape_task_reviewers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["scrape_tasks.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "user_id", name="uq_scrape_task_reviewer"),
    )
    op.create_index(op.f("ix_scrape_task_reviewers_id"), "scrape_task_reviewers", ["id"], unique=False)
    op.create_index(op.f("ix_scrape_task_reviewers_task_id"), "scrape_task_reviewers", ["task_id"], unique=False)
    op.create_index(op.f("ix_scrape_task_reviewers_user_id"), "scrape_task_reviewers", ["user_id"], unique=False)

    op.create_table(
        "scrape_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=120), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_keyword", sa.String(length=255), nullable=True),
        sa.Column("post_url", sa.String(length=500), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=True),
        sa.Column("publish_date", sa.Date(), nullable=True),
        sa.Column("copy_type", sa.String(length=50), nullable=True),
        sa.Column("brand", sa.String(length=100), nullable=True),
        sa.Column("likes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comments", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("collects", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shares", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("review_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("reviewer_id", sa.Integer(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("copywriting_id", sa.Integer(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.ForeignKeyConstraint(["copywriting_id"], ["copywritings.id"]),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["scrape_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "external_id", name="uq_scrape_candidate_task_external"),
    )
    op.create_index(op.f("ix_scrape_candidates_id"), "scrape_candidates", ["id"], unique=False)
    op.create_index(op.f("ix_scrape_candidates_task_id"), "scrape_candidates", ["task_id"], unique=False)
    op.create_index(op.f("ix_scrape_candidates_publish_date"), "scrape_candidates", ["publish_date"], unique=False)
    op.create_index(op.f("ix_scrape_candidates_copy_type"), "scrape_candidates", ["copy_type"], unique=False)
    op.create_index(op.f("ix_scrape_candidates_brand"), "scrape_candidates", ["brand"], unique=False)
    op.create_index(op.f("ix_scrape_candidates_source"), "scrape_candidates", ["source"], unique=False)
    op.create_index(op.f("ix_scrape_candidates_review_status"), "scrape_candidates", ["review_status"], unique=False)
    op.create_index(op.f("ix_scrape_candidates_reviewer_id"), "scrape_candidates", ["reviewer_id"], unique=False)
    op.create_index(op.f("ix_scrape_candidates_copywriting_id"), "scrape_candidates", ["copywriting_id"], unique=False)

    op.create_table(
        "scrape_candidate_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.ForeignKeyConstraint(["candidate_id"], ["scrape_candidates.id"]),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["scrape_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scrape_candidate_reviews_id"), "scrape_candidate_reviews", ["id"], unique=False)
    op.create_index(op.f("ix_scrape_candidate_reviews_task_id"), "scrape_candidate_reviews", ["task_id"], unique=False)
    op.create_index(op.f("ix_scrape_candidate_reviews_candidate_id"), "scrape_candidate_reviews", ["candidate_id"], unique=False)
    op.create_index(op.f("ix_scrape_candidate_reviews_reviewer_id"), "scrape_candidate_reviews", ["reviewer_id"], unique=False)
    op.create_index(op.f("ix_scrape_candidate_reviews_action"), "scrape_candidate_reviews", ["action"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_scrape_candidate_reviews_action"), table_name="scrape_candidate_reviews")
    op.drop_index(op.f("ix_scrape_candidate_reviews_reviewer_id"), table_name="scrape_candidate_reviews")
    op.drop_index(op.f("ix_scrape_candidate_reviews_candidate_id"), table_name="scrape_candidate_reviews")
    op.drop_index(op.f("ix_scrape_candidate_reviews_task_id"), table_name="scrape_candidate_reviews")
    op.drop_index(op.f("ix_scrape_candidate_reviews_id"), table_name="scrape_candidate_reviews")
    op.drop_table("scrape_candidate_reviews")

    op.drop_index(op.f("ix_scrape_candidates_copywriting_id"), table_name="scrape_candidates")
    op.drop_index(op.f("ix_scrape_candidates_reviewer_id"), table_name="scrape_candidates")
    op.drop_index(op.f("ix_scrape_candidates_review_status"), table_name="scrape_candidates")
    op.drop_index(op.f("ix_scrape_candidates_source"), table_name="scrape_candidates")
    op.drop_index(op.f("ix_scrape_candidates_brand"), table_name="scrape_candidates")
    op.drop_index(op.f("ix_scrape_candidates_copy_type"), table_name="scrape_candidates")
    op.drop_index(op.f("ix_scrape_candidates_publish_date"), table_name="scrape_candidates")
    op.drop_index(op.f("ix_scrape_candidates_task_id"), table_name="scrape_candidates")
    op.drop_index(op.f("ix_scrape_candidates_id"), table_name="scrape_candidates")
    op.drop_table("scrape_candidates")

    op.drop_index(op.f("ix_scrape_task_reviewers_user_id"), table_name="scrape_task_reviewers")
    op.drop_index(op.f("ix_scrape_task_reviewers_task_id"), table_name="scrape_task_reviewers")
    op.drop_index(op.f("ix_scrape_task_reviewers_id"), table_name="scrape_task_reviewers")
    op.drop_table("scrape_task_reviewers")

    op.drop_index(op.f("ix_scrape_tasks_created_by"), table_name="scrape_tasks")
    op.drop_index(op.f("ix_scrape_tasks_status"), table_name="scrape_tasks")
    op.drop_index(op.f("ix_scrape_tasks_source"), table_name="scrape_tasks")
    op.drop_index(op.f("ix_scrape_tasks_id"), table_name="scrape_tasks")
    op.drop_table("scrape_tasks")
