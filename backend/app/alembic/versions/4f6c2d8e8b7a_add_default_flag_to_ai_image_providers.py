"""add default flag to ai image providers

Revision ID: 4f6c2d8e8b7a
Revises: d32f9a4c8b21
Create Date: 2026-05-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "4f6c2d8e8b7a"
down_revision: Union[str, None] = "d32f9a4c8b21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_image_providers", sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.false()))
    op.execute(
        """
        UPDATE ai_image_providers
        SET is_default = CASE
            WHEN provider_kind = 'openai_images' AND endpoint_url LIKE '%duckcoding.ai%' THEN TRUE
            ELSE FALSE
        END
        WHERE model_name = 'gptimage2'
        """
    )
    op.execute(
        """
        UPDATE ai_image_providers
        SET supports_image_input = TRUE
        WHERE model_name = 'gptimage2' AND provider_kind = 'openai_images' AND endpoint_url LIKE '%duckcoding.ai%'
        """
    )


def downgrade() -> None:
    op.drop_column("ai_image_providers", "is_default")
