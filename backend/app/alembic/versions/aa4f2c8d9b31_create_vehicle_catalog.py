"""create vehicle catalog table

Revision ID: aa4f2c8d9b31
Revises: fda1b2c3d4e5
Create Date: 2026-06-25 15:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "aa4f2c8d9b31"
down_revision: Union[str, Sequence[str], None] = "fda1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "vehicle_catalog" in tables:
        return

    op.create_table(
        "vehicle_catalog",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mid", sa.String(length=64), nullable=True),
        sa.Column("brand", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("model_id", sa.String(length=120), nullable=True),
        sa.Column("source", sa.String(length=64), server_default="seed", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("brand", "model", name="uq_vehicle_catalog_brand_model"),
    )
    op.create_index(op.f("ix_vehicle_catalog_id"), "vehicle_catalog", ["id"], unique=False)
    op.create_index(op.f("ix_vehicle_catalog_mid"), "vehicle_catalog", ["mid"], unique=False)
    op.create_index(op.f("ix_vehicle_catalog_brand"), "vehicle_catalog", ["brand"], unique=False)
    op.create_index(op.f("ix_vehicle_catalog_model"), "vehicle_catalog", ["model"], unique=False)
    op.create_index(op.f("ix_vehicle_catalog_model_id"), "vehicle_catalog", ["model_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "vehicle_catalog" not in tables:
        return

    op.drop_index(op.f("ix_vehicle_catalog_model_id"), table_name="vehicle_catalog")
    op.drop_index(op.f("ix_vehicle_catalog_model"), table_name="vehicle_catalog")
    op.drop_index(op.f("ix_vehicle_catalog_brand"), table_name="vehicle_catalog")
    op.drop_index(op.f("ix_vehicle_catalog_mid"), table_name="vehicle_catalog")
    op.drop_index(op.f("ix_vehicle_catalog_id"), table_name="vehicle_catalog")
    op.drop_table("vehicle_catalog")
