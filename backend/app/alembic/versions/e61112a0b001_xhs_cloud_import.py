"""Add cloud observation receipts and optional field provenance.

Revision ID: e61112a0b001
Revises: e61010a0b001
"""
from alembic import op
import sqlalchemy as sa

revision = "e61112a0b001"
down_revision = "e61010a0b001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("xhs_account_notes", sa.Column("metric_sources", sa.JSON(), nullable=True))
    op.add_column("xhs_account_notes", sa.Column("published_at_precision", sa.String(16), nullable=True))
    op.create_table(
        "xhs_cloud_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.String(120), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("item_id", sa.String(32), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("xhs_environments.id"), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("client_id", "run_id", "item_id", name="uq_xhs_cloud_import_identity"),
    )
    op.create_index("ix_xhs_cloud_imports_environment_id", "xhs_cloud_imports", ["environment_id"])
    op.create_index("ix_xhs_cloud_imports_captured_at", "xhs_cloud_imports", ["captured_at"])


def downgrade():
    bind = op.get_bind()
    imports = sa.table("xhs_cloud_imports", sa.column("id"))
    notes = sa.table("xhs_account_notes", sa.column("metric_sources"), sa.column("published_at_precision"))
    if (bind.scalar(sa.select(imports.c.id).limit(1)) is not None
            or bind.scalar(sa.select(sa.literal(1)).select_from(notes).where(sa.or_(
                notes.c.metric_sources.is_not(None), notes.c.published_at_precision.is_not(None))).limit(1)) is not None):
        raise RuntimeError("Retain observations/provenance; roll back application code without downgrading schema")
    op.drop_table("xhs_cloud_imports")
    op.drop_column("xhs_account_notes", "published_at_precision")
    op.drop_column("xhs_account_notes", "metric_sources")
