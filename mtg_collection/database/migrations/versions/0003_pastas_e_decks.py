"""pastas e decks

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26
"""
import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('folders',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('folders', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_folders_user_id'), ['user_id'], unique=False)

    op.create_table('decks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('folder_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('format', sa.String(length=30), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('visibility', sa.String(length=16), nullable=False),
    sa.Column('cover_filename', sa.String(length=80), nullable=True),
    sa.Column('cover_art_url', sa.String(length=300), nullable=True),
    sa.Column('cover_card_name', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['folder_id'], ['folders.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('decks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_decks_folder_id'), ['folder_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_decks_user_id'), ['user_id'], unique=False)

    op.create_table('deck_cards',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('deck_id', sa.Integer(), nullable=False),
    sa.Column('oracle_id', sa.String(length=36), nullable=False),
    sa.Column('card_name', sa.String(length=200), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('section', sa.String(length=16), nullable=False),
    sa.Column('scryfall_id', sa.String(length=36), nullable=True),
    sa.Column('custom_print_id', sa.Integer(), nullable=True),
    sa.Column('color_identity', sa.String(length=5), nullable=False),
    sa.Column('type_line', sa.String(length=200), nullable=False),
    sa.Column('mana_cost', sa.String(length=80), nullable=False),
    sa.Column('image_small', sa.String(length=300), nullable=True),
    sa.Column('image_normal', sa.String(length=300), nullable=True),
    sa.Column('image_art_crop', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('quantity >= 1', name='deck_quantity_positive'),
    sa.ForeignKeyConstraint(['custom_print_id'], ['custom_prints.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['deck_id'], ['decks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('deck_cards', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_deck_cards_deck_id'), ['deck_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_deck_cards_oracle_id'), ['oracle_id'], unique=False)

    with op.batch_alter_table('collection_entries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('folder_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_collection_entries_folder_id'), ['folder_id'], unique=False)
        batch_op.create_foreign_key('fk_collection_entries_folder_id', 'folders', ['folder_id'], ['id'],
                                    ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('collection_entries', schema=None) as batch_op:
        batch_op.drop_constraint('fk_collection_entries_folder_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_collection_entries_folder_id'))
        batch_op.drop_column('folder_id')

    with op.batch_alter_table('deck_cards', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_deck_cards_oracle_id'))
        batch_op.drop_index(batch_op.f('ix_deck_cards_deck_id'))

    op.drop_table('deck_cards')
    with op.batch_alter_table('decks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_decks_user_id'))
        batch_op.drop_index(batch_op.f('ix_decks_folder_id'))

    op.drop_table('decks')
    with op.batch_alter_table('folders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_folders_user_id'))

    op.drop_table('folders')
