"""add_foreign_keys_to_xhs_posts

Revision ID: 0aa83ceebeb5
Revises: 99f6d1f104b3
Create Date: 2026-04-30 17:02:59.111772
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0aa83ceebeb5'
down_revision: Union[str, None] = '99f6d1f104b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite batch mode for xhs_posts foreign keys
    with op.batch_alter_table('xhs_posts', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_xhs_posts_user_id', 'users', ['user_id'], ['id']
        )
        batch_op.create_foreign_key(
            'fk_xhs_posts_env_id', 'xhs_environments', ['environment_id'], ['id']
        )


def downgrade() -> None:
    with op.batch_alter_table('xhs_posts', schema=None) as batch_op:
        batch_op.drop_constraint('fk_xhs_posts_user_id', type_='foreignkey')
        batch_op.drop_constraint('fk_xhs_posts_env_id', type_='foreignkey')
