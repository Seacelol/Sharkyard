"""ranking: vitórias e temporadas

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-26
"""
import sqlalchemy as sa
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('seasons',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('started_at', sa.Date(), nullable=False),
    sa.Column('ended_at', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('wins',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('deck_id', sa.Integer(), nullable=False),
    sa.Column('version_id', sa.Integer(), nullable=True),
    sa.Column('season_id', sa.Integer(), nullable=True),
    sa.Column('played_on', sa.Date(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['deck_id'], ['decks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version_id'], ['deck_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['season_id'], ['seasons.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('wins', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_wins_deck_id'), ['deck_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_wins_season_id'), ['season_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_wins_played_on'), ['played_on'], unique=False)
    with op.batch_alter_table('decks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('hidden_from_ranking', sa.Boolean(), server_default='0', nullable=False))
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('hidden_from_ranking', sa.Boolean(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('hidden_from_ranking')
    with op.batch_alter_table('decks', schema=None) as batch_op:
        batch_op.drop_column('hidden_from_ranking')
    op.drop_table('wins')
    op.drop_table('seasons')
