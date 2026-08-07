"""unique xhs environment owner

Revision ID: 0d8c7b6a5e4f
Revises: 99f6d1f104b3
Create Date: 2026-06-17
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = "0d8c7b6a5e4f"
down_revision: Union[str, Sequence[str], None] = "99f6d1f104b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    unique_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("user_xhs_environments")}

    if bind.dialect.name == "sqlite":
        op.execute(
            """
            DELETE FROM user_xhs_environments
            WHERE id NOT IN (
                SELECT MAX(id) FROM user_xhs_environments GROUP BY user_id
            )
            """
        )
        op.execute(
            """
            DELETE FROM user_xhs_environments
            WHERE id NOT IN (
                SELECT MAX(id) FROM user_xhs_environments GROUP BY environment_id
            )
            """
        )
        with op.batch_alter_table("user_xhs_environments") as batch_op:
            if "uq_user_xhs_env_user" not in unique_constraints:
                batch_op.create_unique_constraint("uq_user_xhs_env_user", ["user_id"])
            if "uq_user_xhs_env_environment" not in unique_constraints:
                batch_op.create_unique_constraint("uq_user_xhs_env_environment", ["environment_id"])
        return

    op.execute(
        """
        DELETE FROM user_xhs_environments a
        USING user_xhs_environments b
        WHERE a.user_id = b.user_id
          AND a.id < b.id
        """
    )
    op.execute(
        """
        DELETE FROM user_xhs_environments a
        USING user_xhs_environments b
        WHERE a.environment_id = b.environment_id
          AND a.id < b.id
        """
    )
    if "uq_user_xhs_env_user" not in unique_constraints:
        op.create_unique_constraint(
            "uq_user_xhs_env_user",
            "user_xhs_environments",
            ["user_id"],
        )
    if "uq_user_xhs_env_environment" not in unique_constraints:
        op.create_unique_constraint(
            "uq_user_xhs_env_environment",
            "user_xhs_environments",
            ["environment_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    unique_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("user_xhs_environments")}

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("user_xhs_environments") as batch_op:
            if "uq_user_xhs_env_environment" in unique_constraints:
                batch_op.drop_constraint("uq_user_xhs_env_environment", type_="unique")
            if "uq_user_xhs_env_user" in unique_constraints:
                batch_op.drop_constraint("uq_user_xhs_env_user", type_="unique")
        return

    if "uq_user_xhs_env_environment" in unique_constraints:
        op.drop_constraint(
            "uq_user_xhs_env_environment",
            "user_xhs_environments",
            type_="unique",
        )
    if "uq_user_xhs_env_user" in unique_constraints:
        op.drop_constraint(
            "uq_user_xhs_env_user",
            "user_xhs_environments",
            type_="unique",
        )
