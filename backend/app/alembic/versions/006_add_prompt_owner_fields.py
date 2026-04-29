"""add prompt owner fields

Revision ID: 006
Revises: 005
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"

    cols = {c["name"] for c in inspector.get_columns("prompt_examples")}
    if "is_public" not in cols:
        op.add_column(
            "prompt_examples",
            sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    if "created_by" not in cols:
        op.add_column("prompt_examples", sa.Column("created_by", sa.Integer(), nullable=True))
    if "updated_by" not in cols:
        op.add_column("prompt_examples", sa.Column("updated_by", sa.Integer(), nullable=True))

    idxs = {i["name"] for i in inspector.get_indexes("prompt_examples")}
    if "ix_prompt_examples_created_by" not in idxs:
        op.create_index("ix_prompt_examples_created_by", "prompt_examples", ["created_by"])
    if "ix_prompt_examples_updated_by" not in idxs:
        op.create_index("ix_prompt_examples_updated_by", "prompt_examples", ["updated_by"])

    # SQLite 不支持 ALTER TABLE ADD CONSTRAINT，跳过外键追加
    if not is_sqlite:
        fks = {fk["name"] for fk in inspector.get_foreign_keys("prompt_examples") if fk.get("name")}
        if "fk_prompt_examples_created_by_users" not in fks:
            op.create_foreign_key(
                "fk_prompt_examples_created_by_users",
                "prompt_examples",
                "users",
                ["created_by"],
                ["id"],
                ondelete="SET NULL",
            )
        if "fk_prompt_examples_updated_by_users" not in fks:
            op.create_foreign_key(
                "fk_prompt_examples_updated_by_users",
                "prompt_examples",
                "users",
                ["updated_by"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"

    if not is_sqlite:
        fks = {fk["name"] for fk in inspector.get_foreign_keys("prompt_examples") if fk.get("name")}
        if "fk_prompt_examples_updated_by_users" in fks:
            op.drop_constraint("fk_prompt_examples_updated_by_users", "prompt_examples", type_="foreignkey")
        if "fk_prompt_examples_created_by_users" in fks:
            op.drop_constraint("fk_prompt_examples_created_by_users", "prompt_examples", type_="foreignkey")

    idxs = {i["name"] for i in inspector.get_indexes("prompt_examples")}
    if "ix_prompt_examples_updated_by" in idxs:
        op.drop_index("ix_prompt_examples_updated_by", table_name="prompt_examples")
    if "ix_prompt_examples_created_by" in idxs:
        op.drop_index("ix_prompt_examples_created_by", table_name="prompt_examples")

    cols = {c["name"] for c in inspector.get_columns("prompt_examples")}
    if "updated_by" in cols:
        op.drop_column("prompt_examples", "updated_by")
    if "created_by" in cols:
        op.drop_column("prompt_examples", "created_by")
    if "is_public" in cols:
        op.drop_column("prompt_examples", "is_public")
