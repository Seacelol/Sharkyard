"""versões de deck

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-26
"""
import sqlalchemy as sa
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('deck_versions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('deck_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['deck_id'], ['decks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('deck_versions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_deck_versions_deck_id'), ['deck_id'], unique=False)
    with op.batch_alter_table('decks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('current_version_id', sa.Integer(), nullable=True))
    with op.batch_alter_table('deck_cards', schema=None) as batch_op:
        batch_op.add_column(sa.Column('version_id', sa.Integer(), nullable=True))

    # cada deck que já existe ganha a versão "Original" com as cartas que tinha
    op.execute("INSERT INTO deck_versions (deck_id, name, created_at) SELECT id, 'Original', created_at FROM decks")
    op.execute("UPDATE decks SET current_version_id = "
               "(SELECT v.id FROM deck_versions v WHERE v.deck_id = decks.id)")
    op.execute("UPDATE deck_cards SET version_id = "
               "(SELECT d.current_version_id FROM decks d WHERE d.id = deck_cards.deck_id)")

    with op.batch_alter_table('deck_cards', schema=None) as batch_op:
        batch_op.alter_column('version_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_index(batch_op.f('ix_deck_cards_version_id'), ['version_id'], unique=False)
        batch_op.create_foreign_key('fk_deck_cards_version_id', 'deck_versions', ['version_id'], ['id'],
                                    ondelete='CASCADE')


def downgrade() -> None:
    # volta a ter uma lista só por deck: ficam as cartas da versão atual
    op.execute("DELETE FROM deck_cards WHERE version_id NOT IN "
               "(SELECT current_version_id FROM decks WHERE current_version_id IS NOT NULL)")
    with op.batch_alter_table('deck_cards', schema=None) as batch_op:
        batch_op.drop_constraint('fk_deck_cards_version_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_deck_cards_version_id'))
        batch_op.drop_column('version_id')
    with op.batch_alter_table('decks', schema=None) as batch_op:
        batch_op.drop_column('current_version_id')
    with op.batch_alter_table('deck_versions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_deck_versions_deck_id'))
    op.drop_table('deck_versions')
