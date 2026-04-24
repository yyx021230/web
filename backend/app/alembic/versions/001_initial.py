"""initial tables

Revision ID: 001
Revises:
Create Date: 2026-04-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(50), unique=True, nullable=False),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("avatar", sa.String(500)),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_email", "users", ["email"])

    # Templates
    op.create_table(
        "templates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1000)),
        sa.Column("thumbnail", sa.String(500)),
        sa.Column("fabric_json", sa.Text, nullable=False),
        sa.Column("category", sa.String(100)),
        sa.Column("tags", sa.JSON, default=[]),
        sa.Column("created_by", sa.Integer),
        sa.Column("is_public", sa.Boolean, default=True),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_templates_id", "templates", ["id"])
    op.create_index("ix_templates_category", "templates", ["category"])
    op.create_index("ix_templates_created_by", "templates", ["created_by"])
    op.create_index("ix_templates_deleted_at", "templates", ["deleted_at"])

    # Projects
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("fabric_json", sa.Text),
        sa.Column("thumbnail", sa.String(500)),
        sa.Column("status", sa.String(20), default="draft"),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_projects_id", "projects", ["id"])
    op.create_index("ix_projects_user_id", "projects", ["user_id"])
    op.create_index("ix_projects_deleted_at", "projects", ["deleted_at"])

    # Materials
    op.create_table(
        "materials",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("width", sa.Integer),
        sa.Column("height", sa.Integer),
        sa.Column("category", sa.String(100)),
        sa.Column("tags", sa.JSON, default=[]),
        sa.Column("created_by", sa.Integer),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_materials_id", "materials", ["id"])
    op.create_index("ix_materials_category", "materials", ["category"])
    op.create_index("ix_materials_created_by", "materials", ["created_by"])
    op.create_index("ix_materials_deleted_at", "materials", ["deleted_at"])

    # AI Tasks
    op.create_table(
        "ai_tasks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("model_name", sa.String(50), nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("negative_prompt", sa.Text),
        sa.Column("params", sa.JSON, default={}),
        sa.Column("status", sa.String(20), default="pending"),
        sa.Column("result_urls", sa.JSON, default=[]),
        sa.Column("error", sa.Text),
        sa.Column("elapsed_seconds", sa.Float),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime),
    )
    op.create_index("ix_ai_tasks_id", "ai_tasks", ["id"])
    op.create_index("ix_ai_tasks_user_id", "ai_tasks", ["user_id"])

    # Dify Instances
    op.create_table(
        "dify_instances",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("api_key", sa.String(500), nullable=False),
        sa.Column("is_default", sa.Boolean, default=False),
        sa.Column("created_by", sa.Integer),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_dify_instances_id", "dify_instances", ["id"])

    # Dify Workflows
    op.create_table(
        "dify_workflows",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("instance_id", sa.Integer, sa.ForeignKey("dify_instances.id"), nullable=False),
        sa.Column("app_id", sa.String(100), nullable=False),
        sa.Column("app_name", sa.String(255), nullable=False),
        sa.Column("app_type", sa.String(20), nullable=False),
        sa.Column("inputs_schema", sa.JSON, default={}),
        sa.Column("description", sa.Text),
        sa.Column("is_enabled", sa.Boolean, default=True),
        sa.Column("created_by", sa.Integer),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_dify_workflows_id", "dify_workflows", ["id"])
    op.create_index("ix_dify_workflows_instance_id", "dify_workflows", ["instance_id"])

    # Dify Run Logs
    op.create_table(
        "dify_run_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workflow_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("inputs", sa.JSON, default={}),
        sa.Column("outputs", sa.JSON, default={}),
        sa.Column("status", sa.String(20), default="running"),
        sa.Column("task_id", sa.String(100)),
        sa.Column("error", sa.Text),
        sa.Column("started_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime),
        sa.Column("elapsed_ms", sa.Float),
    )
    op.create_index("ix_dify_run_logs_id", "dify_run_logs", ["id"])
    op.create_index("ix_dify_run_logs_workflow_id", "dify_run_logs", ["workflow_id"])
    op.create_index("ix_dify_run_logs_user_id", "dify_run_logs", ["user_id"])


def downgrade() -> None:
    op.drop_table("dify_run_logs")
    op.drop_table("dify_workflows")
    op.drop_table("dify_instances")
    op.drop_table("ai_tasks")
    op.drop_table("materials")
    op.drop_table("projects")
    op.drop_table("templates")
    op.drop_table("users")
