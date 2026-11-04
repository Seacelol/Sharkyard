"""senha temporária (troca obrigatória) e conta desativada

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-27
"""
import sqlalchemy as sa
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('must_change_password', sa.Boolean(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('is_disabled', sa.Boolean(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('is_disabled')
        batch_op.drop_column('must_change_password')
