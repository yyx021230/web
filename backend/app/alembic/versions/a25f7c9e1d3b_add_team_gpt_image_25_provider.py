"""add Team GPT Image 2.5 provider pool

Revision ID: a25f7c9e1d3b
Revises: c3d4e5f6a7b8
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "a25f7c9e1d3b"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def _config_dict(value) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def upgrade() -> None:
    bind = op.get_bind()
    sources = bind.execute(
        sa.text(
            """
            SELECT name, endpoint_url, api_key, is_enabled, is_default,
                   priority, weight, supports_text_input, supports_image_input,
                   config, created_by
            FROM ai_image_providers
            WHERE model_name = 'gptimage2'
              AND provider_kind = 'openai_images'
              AND lower(endpoint_url) LIKE '%teamorouter.cn%'
            ORDER BY is_default DESC, priority ASC, id ASC
            """
        )
    ).mappings().all()

    for source in sources:
        exists = bind.execute(
            sa.text(
                """
                SELECT 1 FROM ai_image_providers
                WHERE model_name = 'gptimage25'
                  AND endpoint_url = :endpoint_url
                LIMIT 1
                """
            ),
            {"endpoint_url": source["endpoint_url"]},
        ).first()
        if exists:
            continue

        config = _config_dict(source["config"])
        config["generation_modes"] = ["fast", "precision"]
        insert_statement = sa.text(
            """
            INSERT INTO ai_image_providers (
                name, model_name, provider_kind, provider_model,
                endpoint_url, api_key, is_enabled, is_default,
                priority, weight, supports_text_input, supports_image_input,
                config, last_health_status, success_count, failure_count,
                created_by
            ) VALUES (
                :name, 'gptimage25', 'openai_images', 'gpt-image-2.5-flare',
                :endpoint_url, :api_key, :is_enabled, :is_default,
                :priority, :weight, :supports_text_input, :supports_image_input,
                :config, 'unknown', 0, 0, :created_by
            )
            """
        ).bindparams(sa.bindparam("config", type_=sa.JSON()))
        bind.execute(
            insert_statement,
            {
                "name": f"{source['name']} · GPT Image 2.5",
                "endpoint_url": source["endpoint_url"],
                "api_key": source["api_key"],
                "is_enabled": source["is_enabled"],
                "is_default": source["is_default"],
                "priority": source["priority"],
                "weight": source["weight"],
                "supports_text_input": source["supports_text_input"],
                "supports_image_input": source["supports_image_input"],
                "config": config,
                "created_by": source["created_by"],
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            DELETE FROM ai_image_providers
            WHERE model_name = 'gptimage25'
              AND provider_model = 'gpt-image-2.5-flare'
              AND lower(endpoint_url) LIKE '%teamorouter.cn%'
              AND name LIKE '%· GPT Image 2.5'
            """
        )
    )
