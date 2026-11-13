"""Native account locators and sync audit identities; no business-data rewrite."""

from alembic import op
import sqlalchemy as sa

revision = "e61113b0b002"
down_revision = "e61113a0b001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "xhs_accounts", sa.Column("profile_url", sa.String(1000), nullable=True)
    )
    for name in ("xhs_account_sync_run_items", "xhs_creator_sync_rows"):
        with op.batch_alter_table(name) as batch:
            batch.add_column(sa.Column("account_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                f"fk_{name}_account_id", "xhs_accounts", ["account_id"], ["id"]
            )
            batch.create_index(f"ix_{name}_account_id", ["account_id"])
            if name == "xhs_creator_sync_rows":
                batch.alter_column(
                    "environment_id", existing_type=sa.Integer(), nullable=True
                )
                batch.create_unique_constraint(
                    "uq_xhs_creator_master_run_row",
                    ["sync_run_id", "account_id", "source_row_index"],
                )


def downgrade():
    bind = op.get_bind()
    for name in ("xhs_account_sync_run_items", "xhs_creator_sync_rows"):
        if bind.execute(
            sa.text(f"SELECT 1 FROM {name} WHERE account_id IS NOT NULL LIMIT 1")
        ).first():
            raise RuntimeError(
                "Retain native account synchronization history; roll back application only"
            )
    if bind.execute(
        sa.text("SELECT 1 FROM xhs_accounts WHERE profile_url IS NOT NULL LIMIT 1")
    ).first():
        raise RuntimeError(
            "Retain independent profile locators; roll back application only"
        )
    for name in ("xhs_account_sync_run_items", "xhs_creator_sync_rows"):
        with op.batch_alter_table(name) as batch:
            batch.drop_index(f"ix_{name}_account_id")
            batch.drop_constraint(f"fk_{name}_account_id", type_="foreignkey")
            batch.drop_column("account_id")
            if name == "xhs_creator_sync_rows":
                batch.drop_constraint("uq_xhs_creator_master_run_row", type_="unique")
                batch.alter_column(
                    "environment_id", existing_type=sa.Integer(), nullable=False
                )
    op.drop_column("xhs_accounts", "profile_url")
