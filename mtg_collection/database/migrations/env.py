"""Ambiente do Alembic. O app aplica as migrações sozinho ao iniciar (database.upgrade()).

Para criar uma migração nova depois de mudar tables.py:
    alembic revision --autogenerate -m "descrição"
"""
from alembic import context
from sqlalchemy import Connection, create_engine

from mtg_collection import config as app_config
from mtg_collection.database import database_url
from mtg_collection.database.tables import Base

target_metadata = Base.metadata


def _migrate(connection: Connection) -> None:
    """Roda as migrações com as chaves estrangeiras desligadas e confere tudo no fim.

    No SQLite, mudar uma coluna recria a tabela (cria a nova, copia, apaga a antiga). Com as chaves ligadas,
    apagar a tabela antiga dispara o ON DELETE CASCADE e leva junto as linhas das tabelas filhas (ex.: recriar
    "users" apagava todos os decks). O PRAGMA só vale fora de transação, por isso vem antes de tudo e é conferido.
    A conexão volta a ter as chaves ligadas ao sair do pool de novo (database._foreign_keys_on)."""
    connection.exec_driver_sql("PRAGMA foreign_keys = OFF")
    if connection.exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError("Não deu para desligar as chaves estrangeiras: rode as migrações fora de uma transação.")
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
    # dentro da mesma transação: se algo ficou apontando para o nada, o erro desfaz a migração
    problems = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if problems:
        raise RuntimeError(f"A migração deixou referências quebradas: {problems[:5]}")


def run_migrations() -> None:
    """Ponto de entrada do Alembic: usa a conexão do app se houver, senão abre uma própria (linha de comando)."""
    connection = context.config.attributes.get("connection")
    if connection is not None:  # chamado pelo app, com a conexão já aberta
        _migrate(connection)
        return
    # chamado pela linha de comando (alembic revision/upgrade)
    app_config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url(app_config.DATABASE_PATH))
    with engine.begin() as conn:
        _migrate(conn)


run_migrations()
