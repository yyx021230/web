"""add user roles and xhs buyer account assignments

Revision ID: 1f2e3d4c5b6a
Revises: 0d8c7b6a5e4f, e9f0a1b2c3d4
Create Date: 2026-06-18 10:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "1f2e3d4c5b6a"
down_revision: Union[str, Sequence[str], None] = ("0d8c7b6a5e4f", "e9f0a1b2c3d4")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "user_roles" not in tables:
        op.create_table(
            "user_roles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "role", name="uq_user_role"),
        )
        op.create_index(op.f("ix_user_roles_id"), "user_roles", ["id"], unique=False)
        op.create_index(op.f("ix_user_roles_user_id"), "user_roles", ["user_id"], unique=False)
        op.create_index(op.f("ix_user_roles_role"), "user_roles", ["role"], unique=False)

    bind.execute(
        sa.text(
            """
            INSERT INTO user_roles (user_id, role)
            SELECT users.id, COALESCE(NULLIF(users.role, ''), 'viewer')
            FROM users
            WHERE NOT EXISTS (
                SELECT 1 FROM user_roles
                WHERE user_roles.user_id = users.id
                  AND user_roles.role = COALESCE(NULLIF(users.role, ''), 'viewer')
            )
            """
        )
    )

    if "xhs_ad_account_buyer_assignments" not in tables:
        op.create_table(
            "xhs_ad_account_buyer_assignments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.String(length=64), nullable=False),
            sa.Column("account_name", sa.String(length=255), server_default="", nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("account_id", name="uq_xhs_ad_account_buyer_account"),
        )
        op.create_index(
            op.f("ix_xhs_ad_account_buyer_assignments_id"),
            "xhs_ad_account_buyer_assignments",
            ["id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_xhs_ad_account_buyer_assignments_account_id"),
            "xhs_ad_account_buyer_assignments",
            ["account_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_xhs_ad_account_buyer_assignments_user_id"),
            "xhs_ad_account_buyer_assignments",
            ["user_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "xhs_ad_account_buyer_assignments" in tables:
        op.drop_index(op.f("ix_xhs_ad_account_buyer_assignments_user_id"), table_name="xhs_ad_account_buyer_assignments")
        op.drop_index(op.f("ix_xhs_ad_account_buyer_assignments_account_id"), table_name="xhs_ad_account_buyer_assignments")
        op.drop_index(op.f("ix_xhs_ad_account_buyer_assignments_id"), table_name="xhs_ad_account_buyer_assignments")
        op.drop_table("xhs_ad_account_buyer_assignments")

    if "user_roles" in tables:
        op.drop_index(op.f("ix_user_roles_role"), table_name="user_roles")
        op.drop_index(op.f("ix_user_roles_user_id"), table_name="user_roles")
        op.drop_index(op.f("ix_user_roles_id"), table_name="user_roles")
        op.drop_table("user_roles")
