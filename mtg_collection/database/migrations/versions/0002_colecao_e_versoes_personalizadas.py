"""colecao e versoes personalizadas

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26
"""
import sqlalchemy as sa
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('custom_prints',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('oracle_id', sa.String(length=36), nullable=False),
    sa.Column('card_name', sa.String(length=200), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('code', sa.String(length=8), nullable=False),
    sa.Column('artist', sa.String(length=80), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('image_filename', sa.String(length=80), nullable=True),
    sa.Column('base_scryfall_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('custom_prints', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_custom_prints_oracle_id'), ['oracle_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_custom_prints_user_id'), ['user_id'], unique=False)

    op.create_table('collection_entries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('oracle_id', sa.String(length=36), nullable=False),
    sa.Column('card_name', sa.String(length=200), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('foil', sa.Boolean(), nullable=False),
    sa.Column('is_proxy', sa.Boolean(), nullable=False),
    sa.Column('price_paid_cents', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('scryfall_id', sa.String(length=36), nullable=True),
    sa.Column('custom_print_id', sa.Integer(), nullable=True),
    sa.Column('set_code', sa.String(length=12), nullable=False),
    sa.Column('set_name', sa.String(length=120), nullable=False),
    sa.Column('collector_number', sa.String(length=16), nullable=False),
    sa.Column('rarity', sa.String(length=16), nullable=False),
    sa.Column('type_line', sa.String(length=200), nullable=False),
    sa.Column('image_small', sa.String(length=300), nullable=True),
    sa.Column('image_normal', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('price_paid_cents IS NULL OR price_paid_cents >= 0', name='price_not_negative'),
    sa.CheckConstraint('quantity >= 1', name='quantity_positive'),
    sa.ForeignKeyConstraint(['custom_print_id'], ['custom_prints.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('collection_entries', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_collection_entries_custom_print_id'), ['custom_print_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_collection_entries_oracle_id'), ['oracle_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_collection_entries_user_id'), ['user_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('collection_entries', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_collection_entries_user_id'))
        batch_op.drop_index(batch_op.f('ix_collection_entries_oracle_id'))
        batch_op.drop_index(batch_op.f('ix_collection_entries_custom_print_id'))

    op.drop_table('collection_entries')
    with op.batch_alter_table('custom_prints', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_custom_prints_user_id'))
        batch_op.drop_index(batch_op.f('ix_custom_prints_oracle_id'))

    op.drop_table('custom_prints')
