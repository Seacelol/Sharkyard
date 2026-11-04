"""cartas personalizadas e detalhes do deck

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-26
"""
import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('custom_cards',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('deck_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('mana_cost', sa.String(length=80), nullable=False),
    sa.Column('type_line', sa.String(length=200), nullable=False),
    sa.Column('oracle_text', sa.Text(), nullable=False),
    sa.Column('power', sa.String(length=8), nullable=False),
    sa.Column('toughness', sa.String(length=8), nullable=False),
    sa.Column('loyalty', sa.String(length=8), nullable=False),
    sa.Column('colors', sa.String(length=5), nullable=False),
    sa.Column('image_filename', sa.String(length=80), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['deck_id'], ['decks.id'], name='fk_custom_cards_deck_id', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('custom_cards', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_custom_cards_deck_id'), ['deck_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_custom_cards_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('collection_entries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('custom_card_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_collection_entries_custom_card_id'), ['custom_card_id'], unique=False)
        batch_op.create_foreign_key('fk_collection_entries_custom_card_id', 'custom_cards', ['custom_card_id'], ['id'], ondelete='CASCADE')

    with op.batch_alter_table('deck_cards', schema=None) as batch_op:
        batch_op.add_column(sa.Column('custom_card_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('foil', sa.Boolean(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('is_proxy', sa.Boolean(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('price_paid_cents', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('notes', sa.Text(), server_default='', nullable=False))
        batch_op.add_column(sa.Column('set_code', sa.String(length=12), server_default='', nullable=False))
        batch_op.add_column(sa.Column('set_name', sa.String(length=120), server_default='', nullable=False))
        batch_op.add_column(sa.Column('collector_number', sa.String(length=16), server_default='', nullable=False))
        batch_op.add_column(sa.Column('rarity', sa.String(length=16), server_default='', nullable=False))
        batch_op.create_index(batch_op.f('ix_deck_cards_custom_card_id'), ['custom_card_id'], unique=False)
        batch_op.create_foreign_key('fk_deck_cards_custom_card_id', 'custom_cards', ['custom_card_id'], ['id'], ondelete='CASCADE')



def downgrade() -> None:
    with op.batch_alter_table('deck_cards', schema=None) as batch_op:
        batch_op.drop_constraint('fk_deck_cards_custom_card_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_deck_cards_custom_card_id'))
        batch_op.drop_column('rarity')
        batch_op.drop_column('collector_number')
        batch_op.drop_column('set_name')
        batch_op.drop_column('set_code')
        batch_op.drop_column('notes')
        batch_op.drop_column('price_paid_cents')
        batch_op.drop_column('is_proxy')
        batch_op.drop_column('foil')
        batch_op.drop_column('custom_card_id')

    with op.batch_alter_table('collection_entries', schema=None) as batch_op:
        batch_op.drop_constraint('fk_collection_entries_custom_card_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_collection_entries_custom_card_id'))
        batch_op.drop_column('custom_card_id')

    with op.batch_alter_table('custom_cards', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_custom_cards_user_id'))
        batch_op.drop_index(batch_op.f('ix_custom_cards_deck_id'))

    op.drop_table('custom_cards')
