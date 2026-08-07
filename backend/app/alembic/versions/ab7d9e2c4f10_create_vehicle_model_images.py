"""create vehicle model images table

Revision ID: ab7d9e2c4f10
Revises: aa4f2c8d9b31
Create Date: 2026-06-25 15:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "ab7d9e2c4f10"
down_revision: Union[str, Sequence[str], None] = "aa4f2c8d9b31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "vehicle_model_images" in tables:
        return

    op.create_table(
        "vehicle_model_images",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("brand", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("label", sa.String(length=50), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source", sa.String(length=64), server_default="seed", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_vehicle_model_images_id"), "vehicle_model_images", ["id"], unique=False)
    op.create_index(op.f("ix_vehicle_model_images_brand"), "vehicle_model_images", ["brand"], unique=False)
    op.create_index(op.f("ix_vehicle_model_images_model"), "vehicle_model_images", ["model"], unique=False)
    op.create_index(op.f("ix_vehicle_model_images_label"), "vehicle_model_images", ["label"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "vehicle_model_images" not in tables:
        return

    op.drop_index(op.f("ix_vehicle_model_images_label"), table_name="vehicle_model_images")
    op.drop_index(op.f("ix_vehicle_model_images_model"), table_name="vehicle_model_images")
    op.drop_index(op.f("ix_vehicle_model_images_brand"), table_name="vehicle_model_images")
    op.drop_index(op.f("ix_vehicle_model_images_id"), table_name="vehicle_model_images")
    op.drop_table("vehicle_model_images")
