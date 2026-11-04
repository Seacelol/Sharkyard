"""ícone e bio do usuário

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-26
"""
import sqlalchemy as sa
from alembic import op

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('avatar_filename', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('bio', sa.String(length=20), server_default='', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('bio')
        batch_op.drop_column('avatar_filename')
