"""add xhs excel metrics and login phone

Revision ID: e9f0a1b2c3d4
Revises: b1c2d3e4f5a6, d7e8f9a0b1c2
Create Date: 2026-06-09 12:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "e9f0a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = ("b1c2d3e4f5a6", "d7e8f9a0b1c2")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    env_columns = {column["name"] for column in inspector.get_columns("xhs_environments")}
    if "login_phone_number" not in env_columns:
        with op.batch_alter_table("xhs_environments") as batch_op:
            batch_op.add_column(sa.Column("login_phone_number", sa.String(length=30), nullable=True, comment="小红书手机号登录号码"))

    note_columns = {column["name"] for column in inspector.get_columns("xhs_account_notes")}
    with op.batch_alter_table("xhs_account_notes") as batch_op:
        if "exposure_count" not in note_columns:
            batch_op.add_column(sa.Column("exposure_count", sa.Integer(), nullable=False, server_default="0", comment="曝光量"))
        if "cover_click_rate" not in note_columns:
            batch_op.add_column(sa.Column("cover_click_rate", sa.Float(), nullable=False, server_default="0", comment="封面点击率百分比"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    note_columns = {column["name"] for column in inspector.get_columns("xhs_account_notes")}
    with op.batch_alter_table("xhs_account_notes") as batch_op:
        if "cover_click_rate" in note_columns:
            batch_op.drop_column("cover_click_rate")
        if "exposure_count" in note_columns:
            batch_op.drop_column("exposure_count")

    env_columns = {column["name"] for column in inspector.get_columns("xhs_environments")}
    if "login_phone_number" in env_columns:
        with op.batch_alter_table("xhs_environments") as batch_op:
            batch_op.drop_column("login_phone_number")
