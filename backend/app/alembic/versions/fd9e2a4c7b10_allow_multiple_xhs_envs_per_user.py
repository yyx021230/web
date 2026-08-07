"""allow multiple xhs environments per user

Revision ID: fd9e2a4c7b10
Revises: fd2a8c3e1b90
Create Date: 2026-06-23
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = "fd9e2a4c7b10"
down_revision: Union[str, Sequence[str], None] = "fd2a8c3e1b90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _unique_constraints() -> set[str]:
    inspector = inspect(op.get_bind())
    return {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("user_xhs_environments")
        if constraint["name"]
    }


def upgrade() -> None:
    unique_constraints = _unique_constraints()
    if "uq_user_xhs_env_user" not in unique_constraints:
        return

    with op.batch_alter_table("user_xhs_environments") as batch_op:
        batch_op.drop_constraint("uq_user_xhs_env_user", type_="unique")


def downgrade() -> None:
    bind = op.get_bind()
    unique_constraints = _unique_constraints()
    if "uq_user_xhs_env_user" in unique_constraints:
        return

    if bind.dialect.name == "sqlite":
        op.execute(
            """
            DELETE FROM user_xhs_environments
            WHERE id NOT IN (
                SELECT MIN(id) FROM user_xhs_environments GROUP BY user_id
            )
            """
        )
    else:
        op.execute(
            """
            DELETE FROM user_xhs_environments a
            USING user_xhs_environments b
            WHERE a.user_id = b.user_id
              AND a.id > b.id
            """
        )

    with op.batch_alter_table("user_xhs_environments") as batch_op:
        batch_op.create_unique_constraint("uq_user_xhs_env_user", ["user_id"])
