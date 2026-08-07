"""strip xhs profile stat account prefix

Revision ID: fda1b2c3d4e5
Revises: fd9e2a4c7b10
Create Date: 2026-06-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "fda1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "fd9e2a4c7b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE xhs_profile_stat_daily
            SET channel_account_name = REPLACE(channel_account_name, '【小红书】', '')
            WHERE channel_account_name LIKE '【小红书】%'
            """
        )
    )


def downgrade() -> None:
    pass
