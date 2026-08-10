"""create scheduler leader leases

Revision ID: 7a8b9c0d1e2f
Revises: 6f7a8b9c0d1e
Create Date: 2026-08-10 23:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7a8b9c0d1e2f"
down_revision: Union[str, Sequence[str], None] = "6f7a8b9c0d1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scheduler_leases",
        sa.Column("lease_key", sa.String(length=128), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=True),
        sa.Column("acquired_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
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
        sa.PrimaryKeyConstraint("lease_key"),
    )
    op.create_index(
        "ix_scheduler_leases_owner_id",
        "scheduler_leases",
        ["owner_id"],
    )
    op.create_index(
        "ix_scheduler_leases_lease_expires_at",
        "scheduler_leases",
        ["lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_table("scheduler_leases")
