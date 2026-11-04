"""Conexão com o banco SQLite e aplicação das migrações.

Uso: `with database.session() as s: ...` (faz commit no fim ou rollback se der erro).
"""
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from mtg_collection import config

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def database_url(path: Path) -> str:
    return f"sqlite:///{path}"


def configure(url: str | None = None) -> Engine:
    """Cria a conexão. Sem argumento, usa o arquivo em config.DATABASE_PATH."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    if url is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        url = database_url(config.DATABASE_PATH)
    _engine = create_engine(url)
    event.listen(_engine, "connect", _sqlite_pragmas)
    event.listen(_engine, "checkout", _foreign_keys_on)
    _session_factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def _sqlite_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode = WAL")  # leituras não esperam escritas: melhor com vários usuários
    cursor.execute("PRAGMA busy_timeout = 5000")
    cursor.close()


def _foreign_keys_on(dbapi_connection, _record, _proxy) -> None:
    """O SQLite vem com chaves estrangeiras desligadas. Liga a cada vez que a conexão sai do pool (e não só ao
    abrir): as migrações desligam na conexão que usam, e ela não pode voltar desligada para o resto do app."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


def engine() -> Engine:
    if _engine is None:
        configure()
    return _engine


def upgrade() -> None:
    """Aplica as migrações pendentes (cria o banco na primeira vez)."""
    from alembic import command
    from alembic.config import Config

    alembic_config = Config()
    alembic_config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine().begin() as connection:
        alembic_config.attributes["connection"] = connection
        command.upgrade(alembic_config, "head")


@contextmanager
def session() -> Iterator[Session]:
    if _session_factory is None:
        configure()
    with _session_factory() as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
