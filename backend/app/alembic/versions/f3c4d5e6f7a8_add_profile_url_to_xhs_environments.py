"""add profile url to xhs environments

Revision ID: f3c4d5e6f7a8
Revises: f2b1c3d4e5f6
Create Date: 2026-05-19 17:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "f2b1c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("xhs_environments", sa.Column("profile_url", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    op.drop_column("xhs_environments", "profile_url")
