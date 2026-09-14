"""add prompt source metadata

Revision ID: b36e8d1f4a2c
Revises: a25f7c9e1d3b
"""

from alembic import op
import sqlalchemy as sa


revision = "b36e8d1f4a2c"
down_revision = "a25f7c9e1d3b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "prompt_examples",
        sa.Column("source_kind", sa.String(length=20), nullable=False, server_default="internal"),
    )
    op.add_column("prompt_examples", sa.Column("source_name", sa.String(length=100), nullable=True))
    op.add_column("prompt_examples", sa.Column("source_url", sa.String(length=1000), nullable=True))
    op.add_column("prompt_examples", sa.Column("source_license", sa.String(length=100), nullable=True))
    op.add_column("prompt_examples", sa.Column("source_author", sa.String(length=255), nullable=True))
    op.add_column("prompt_examples", sa.Column("external_id", sa.String(length=255), nullable=True))
    op.create_index("ix_prompt_examples_source_kind", "prompt_examples", ["source_kind"])
    op.create_index("ix_prompt_examples_external_id", "prompt_examples", ["external_id"])


def downgrade() -> None:
    op.drop_index("ix_prompt_examples_external_id", table_name="prompt_examples")
    op.drop_index("ix_prompt_examples_source_kind", table_name="prompt_examples")
    op.drop_column("prompt_examples", "external_id")
    op.drop_column("prompt_examples", "source_author")
    op.drop_column("prompt_examples", "source_license")
    op.drop_column("prompt_examples", "source_url")
    op.drop_column("prompt_examples", "source_name")
    op.drop_column("prompt_examples", "source_kind")
