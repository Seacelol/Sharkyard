"""idioma da impressão na coleção e no deck (ex.: português)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ('collection_entries', 'deck_cards'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('lang', sa.String(length=8), server_default='en', nullable=False))


def downgrade() -> None:
    for table in ('collection_entries', 'deck_cards'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column('lang')
