"""Independent account directory without rewriting legacy identities.

Revision ID: e61113a0b001
Revises: e61112a0b001
"""

from alembic import op
import sqlalchemy as sa

revision = "e61113a0b001"
down_revision = "e61112a0b001"
branch_labels = None
depends_on = None


def timestamps():
    return [
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    ]


def upgrade():
    op.create_table(
        "xhs_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("xhs_account_id", sa.String(100), nullable=False),
        sa.Column("account_name", sa.String(200), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("department", sa.String(32), nullable=False),
        sa.Column("account_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("owner_label", sa.String(255), nullable=False),
        sa.Column("login_phone_number", sa.String(30)),
        sa.Column("sim_device_label", sa.String(100), nullable=False),
        sa.Column("login_device_label", sa.String(100), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        *timestamps(),
        sqlite_autoincrement=True,
    )
    for column in ("owner_user_id", "department", "status"):
        op.create_index(f"ix_xhs_accounts_{column}", "xhs_accounts", [column])
    op.create_index(
        "ix_xhs_accounts_xhs_account_id",
        "xhs_accounts",
        ["xhs_account_id"],
        unique=True,
    )
    op.create_table(
        "xhs_account_master_imports",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("baseline_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        *timestamps(),
    )
    op.create_table(
        "xhs_account_history_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id", sa.Integer(), sa.ForeignKey("xhs_accounts.id"), nullable=False
        ),
        sa.Column(
            "environment_id",
            sa.Integer(),
            sa.ForeignKey("xhs_environments.id"),
            nullable=False,
        ),
        sa.Column("xhs_id_snapshot", sa.String(100), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", sa.DateTime()),
        *timestamps(),
        sa.UniqueConstraint(
            "account_id", "environment_id", name="uq_xhs_account_history_link"
        ),
    )
    op.create_index(
        "ix_xhs_account_history_links_account_id",
        "xhs_account_history_links",
        ["account_id"],
    )
    with op.batch_alter_table("xhs_account_notes") as batch:
        batch.alter_column("environment_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("account_id", sa.Integer()))
        batch.create_foreign_key(
            "fk_xhs_account_notes_account_id", "xhs_accounts", ["account_id"], ["id"]
        )
        batch.create_index("ix_xhs_account_notes_account_id", ["account_id"])
        batch.create_unique_constraint(
            "uq_xhs_account_notes_account_feed", ["account_id", "feed_id"]
        )
        batch.create_index(
            "uq_xhs_account_notes_account_creator_key",
            ["account_id", "creator_identity_key"],
            unique=True,
        )
    with op.batch_alter_table("xhs_cloud_imports") as batch:
        batch.alter_column("environment_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("account_id", sa.Integer()))
        batch.create_foreign_key(
            "fk_xhs_cloud_imports_account_id", "xhs_accounts", ["account_id"], ["id"]
        )
        batch.create_index("ix_xhs_cloud_imports_account_id", ["account_id"])


def downgrade():
    bind = op.get_bind()
    if any(
        bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None
        for table in (
            "xhs_accounts",
            "xhs_account_master_imports",
            "xhs_account_history_links",
        )
    ):
        raise RuntimeError(
            "Retain account identities/history; roll back application without dropping account data"
        )
    if bind.execute(
        sa.text(
            "SELECT 1 FROM xhs_account_notes WHERE account_id IS NOT NULL OR environment_id IS NULL LIMIT 1"
        )
    ).first():
        raise RuntimeError(
            "Retain independent notes; schema downgrade would lose identity"
        )
    if bind.execute(
        sa.text(
            "SELECT 1 FROM xhs_cloud_imports WHERE account_id IS NOT NULL OR environment_id IS NULL LIMIT 1"
        )
    ).first():
        raise RuntimeError(
            "Retain independent import receipts; schema downgrade would lose identity"
        )
    with op.batch_alter_table("xhs_cloud_imports") as batch:
        batch.drop_index("ix_xhs_cloud_imports_account_id")
        batch.drop_constraint("fk_xhs_cloud_imports_account_id", type_="foreignkey")
        batch.drop_column("account_id")
        batch.alter_column("environment_id", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("xhs_account_notes") as batch:
        batch.drop_index("uq_xhs_account_notes_account_creator_key")
        batch.drop_constraint("uq_xhs_account_notes_account_feed", type_="unique")
        batch.drop_index("ix_xhs_account_notes_account_id")
        batch.drop_constraint("fk_xhs_account_notes_account_id", type_="foreignkey")
        batch.drop_column("account_id")
        batch.alter_column("environment_id", existing_type=sa.Integer(), nullable=False)
    op.drop_table("xhs_account_history_links")
    op.drop_table("xhs_account_master_imports")
    op.drop_table("xhs_accounts")
