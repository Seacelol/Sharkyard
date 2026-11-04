"""tema da interface escolhido por cada usuário

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-27
"""
import sqlalchemy as sa
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('theme', sa.String(length=20), server_default='tubarao', nullable=False))
        batch_op.add_column(sa.Column('theme_mode', sa.String(length=10), server_default='auto', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('theme_mode')
        batch_op.drop_column('theme')
