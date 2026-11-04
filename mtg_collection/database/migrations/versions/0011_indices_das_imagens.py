"""índices para conferir de quem é uma imagem personalizada e em que decks ela aparece

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-04
"""
from alembic import op

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None

# cada pedido de imagem personalizada procura o dono pelo nome do arquivo e, para amigos, as linhas de deck
# que usam a versão: sem índice, as duas consultas percorrem a tabela inteira
INDEXES = (
    ('ix_custom_prints_image_filename', 'custom_prints', 'image_filename'),
    ('ix_custom_cards_image_filename', 'custom_cards', 'image_filename'),
    ('ix_deck_cards_custom_print_id', 'deck_cards', 'custom_print_id'),
)


def upgrade() -> None:
    for name, table, column in INDEXES:
        op.create_index(name, table, [column])


def downgrade() -> None:
    for name, table, _column in INDEXES:
        op.drop_index(name, table_name=table)
