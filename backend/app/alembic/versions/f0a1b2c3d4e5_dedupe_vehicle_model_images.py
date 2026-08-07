"""dedupe vehicle model images

Revision ID: f0a1b2c3d4e5
Revises: e5f6a7b8c9d0
Create Date: 2026-06-29 09:50:00.000000
"""

from alembic import op


revision = "f0a1b2c3d4e5"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite has no DELETE ... USING. Keep the oldest exact duplicate instead.
        op.execute(
            """
            DELETE FROM vehicle_model_images
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM vehicle_model_images
                GROUP BY brand, model, label, url
            )
            """
        )
        op.create_index(
            "uq_vehicle_model_images_exact",
            "vehicle_model_images",
            ["brand", "model", "label", "url"],
            unique=True,
        )
        return

    op.execute(
        """
        WITH ranked AS (
            SELECT id, row_number() OVER (PARTITION BY brand, model, label, url ORDER BY id) AS rn
            FROM vehicle_model_images
        )
        DELETE FROM vehicle_model_images v USING ranked r
        WHERE v.id = r.id AND r.rn > 1
        """
    )
    op.create_unique_constraint("uq_vehicle_model_images_exact", "vehicle_model_images", ["brand", "model", "label", "url"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.drop_index("uq_vehicle_model_images_exact", table_name="vehicle_model_images")
    else:
        op.drop_constraint("uq_vehicle_model_images_exact", "vehicle_model_images", type_="unique")
