"""create ai image providers

Revision ID: d32f9a4c8b21
Revises: 9f2c1c1bd33b
Create Date: 2026-05-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d32f9a4c8b21"
down_revision: Union[str, None] = "9f2c1c1bd33b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_image_providers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("model_name", sa.String(50), nullable=False, default="gptimage2"),
        sa.Column("provider_kind", sa.String(50), nullable=False, default="openai_images"),
        sa.Column("provider_model", sa.String(100), nullable=False, default="gpt-image-2"),
        sa.Column("endpoint_url", sa.String(500), nullable=False),
        sa.Column("api_key", sa.String(500), nullable=False),
        sa.Column("is_enabled", sa.Boolean, nullable=False, default=True),
        sa.Column("priority", sa.Integer, nullable=False, default=100),
        sa.Column("weight", sa.Integer, nullable=False, default=1),
        sa.Column("supports_text_input", sa.Boolean, nullable=False, default=True),
        sa.Column("supports_image_input", sa.Boolean, nullable=False, default=False),
        sa.Column("config", sa.JSON, default={}),
        sa.Column("last_health_status", sa.String(20), nullable=False, default="unknown"),
        sa.Column("last_health_error", sa.Text),
        sa.Column("last_checked_at", sa.DateTime),
        sa.Column("last_used_at", sa.DateTime),
        sa.Column("success_count", sa.Integer, nullable=False, default=0),
        sa.Column("failure_count", sa.Integer, nullable=False, default=0),
        sa.Column("avg_latency_ms", sa.Float),
        sa.Column("created_by", sa.Integer),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_ai_image_providers_id", "ai_image_providers", ["id"])
    op.create_index("ix_ai_image_providers_model_name", "ai_image_providers", ["model_name"])
    op.create_index("ix_ai_image_providers_created_by", "ai_image_providers", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_ai_image_providers_created_by", table_name="ai_image_providers")
    op.drop_index("ix_ai_image_providers_model_name", table_name="ai_image_providers")
    op.drop_index("ix_ai_image_providers_id", table_name="ai_image_providers")
    op.drop_table("ai_image_providers")
