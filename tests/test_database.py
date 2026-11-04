from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from mtg_collection import config, database


def test_migrations_create_tables_in_data_dir(isolated_data):
    assert config.DATABASE_PATH.exists() and config.DATABASE_PATH.parent == isolated_data
    tables = set(inspect(database.engine()).get_table_names())
    assert {"users", "settings", "custom_prints", "collection_entries", "alembic_version"} <= tables


def test_upgrade_is_idempotent():
    database.upgrade()
    database.upgrade()
    head = ScriptDirectory(str(database.MIGRATIONS_DIR)).get_current_head()
    with database.engine().connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == head


def test_sqlite_pragmas():
    with database.engine().connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"


def test_upgrade_from_previous_version_keeps_users(tmp_path):
    """Banco criado na versão 0001 (só contas) migra para a atual sem perder os usuários."""
    from alembic import command
    from alembic.config import Config

    from mtg_collection.services import accounts
    database.configure(database.database_url(tmp_path / "old.db"))
    cfg = Config()
    cfg.set_main_option("script_location", str(database.MIGRATIONS_DIR))
    with database.engine().begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0001")
    with database.engine().begin() as conn:  # SQL direto: o ORM já conhece colunas que a 0001 não tem
        conn.execute(text("INSERT INTO users (username, display_name, password_hash, is_admin, session_token, "
                          "created_at) VALUES ('antigo', 'Antigo', 'x', 1, 't', '2026-01-01')"))
    database.upgrade()
    with database.session() as s:
        assert [u.username for u in accounts.list_users(s)] == ["antigo"]
    assert "collection_entries" in inspect(database.engine()).get_table_names()


def test_upgrade_from_0002_keeps_collection(tmp_path):
    """A coluna de pasta exige recriar a tabela da coleção no SQLite: os itens têm que sobreviver."""
    from alembic import command
    from alembic.config import Config

    from mtg_collection.services import accounts, collection
    from mtg_collection.services.scryfall import to_card
    from tests.sample_cards import BOLT
    database.configure(database.database_url(tmp_path / "v2.db"))
    cfg = Config()
    cfg.set_main_option("script_location", str(database.MIGRATIONS_DIR))
    with database.engine().begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0002")
    with database.engine().begin() as conn:  # dados gravados com o esquema antigo (sem folder_id)
        conn.execute(text("INSERT INTO users (username, display_name, password_hash, is_admin, session_token, "
                          "created_at) VALUES ('antigo', 'Antigo', 'x', 1, 't', '2026-01-01')"))
        conn.execute(text("INSERT INTO collection_entries (user_id, oracle_id, card_name, quantity, foil, is_proxy, "
                          "notes, scryfall_id, set_code, set_name, collector_number, rarity, type_line, created_at, "
                          "updated_at) VALUES (1, 'o-bolt', 'Lightning Bolt', 3, 0, 1, 'obs', '1', 'M10', "
                          "'Magic 2010', '146', 'common', 'Instant', '2026-01-01', '2026-01-01')"))
    database.upgrade()
    with database.session() as s:
        [entry] = collection.list_entries(s, 1)
        assert (entry.card_name, entry.quantity, entry.is_proxy, entry.notes, entry.folder_id) == (
            "Lightning Bolt", 3, True, "obs", None)
        assert accounts.list_users(s)[0].username == "antigo"
        collection.add_card(s, 1, to_card(BOLT))  # esquema novo funcionando
    with database.engine().connect() as conn:
        fks = conn.execute(text("PRAGMA foreign_key_list(collection_entries)")).fetchall()
    assert any(fk[2] == "folders" and fk[6] == "SET NULL" for fk in fks)


def test_downgrade_and_upgrade_again(tmp_path):
    from alembic import command
    from alembic.config import Config
    database.configure(database.database_url(tmp_path / "dg.db"))
    database.upgrade()
    cfg = Config()
    cfg.set_main_option("script_location", str(database.MIGRATIONS_DIR))
    with database.engine().begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "0002")
    assert "decks" not in inspect(database.engine()).get_table_names()
    database.upgrade()
    assert "decks" in inspect(database.engine()).get_table_names()


def test_upgrade_from_0003_keeps_decks(tmp_path):
    """Linhas de deck gravadas antes ganham os campos novos com valor padrão."""
    from alembic import command
    from alembic.config import Config
    database.configure(database.database_url(tmp_path / "v3.db"))
    cfg = Config()
    cfg.set_main_option("script_location", str(database.MIGRATIONS_DIR))
    with database.engine().begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0003")
    with database.engine().begin() as conn:
        conn.execute(text("INSERT INTO users (username, display_name, password_hash, is_admin, session_token, "
                          "created_at) VALUES ('antigo', 'Antigo', 'x', 1, 't', '2026-01-01')"))
        conn.execute(text("INSERT INTO decks (user_id, name, format, notes, visibility, cover_card_name, created_at, "
                          "updated_at) VALUES (1, 'Burn', 'modern', '', 'private', '', '2026-01-01', '2026-01-01')"))
        conn.execute(text("INSERT INTO deck_cards (deck_id, oracle_id, card_name, quantity, section, scryfall_id, "
                          "color_identity, type_line, mana_cost, created_at) VALUES (1, 'o-bolt', 'Lightning Bolt', "
                          "4, 'main', '1', 'R', 'Instant', '{R}', '2026-01-01')"))
    database.upgrade()
    from mtg_collection.services import decks
    with database.session() as s:
        [line] = decks.list_cards(s, 1, 1)
    assert (line.card_name, line.quantity, line.foil, line.is_proxy, line.notes, line.custom_card_id) == (
        "Lightning Bolt", 4, False, False, "", None)


def test_upgrade_from_0004_creates_original_version(tmp_path):
    from alembic import command
    from alembic.config import Config
    database.configure(database.database_url(tmp_path / "v4.db"))
    cfg = Config()
    cfg.set_main_option("script_location", str(database.MIGRATIONS_DIR))
    with database.engine().begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0004")
    with database.engine().begin() as conn:
        conn.execute(text("INSERT INTO users (username, display_name, password_hash, is_admin, session_token, "
                          "created_at) VALUES ('antigo', 'Antigo', 'x', 1, 't', '2026-01-01')"))
        for name in ("Burn", "Vazio"):
            conn.execute(text("INSERT INTO decks (user_id, name, format, notes, visibility, cover_card_name, "
                              f"created_at, updated_at) VALUES (1, '{name}', '', '', 'private', '', '2026-01-01', "
                              "'2026-01-01')"))
        conn.execute(text("INSERT INTO deck_cards (deck_id, oracle_id, card_name, quantity, section, scryfall_id, "
                          "color_identity, type_line, mana_cost, created_at) VALUES (1, 'o-bolt', 'Lightning Bolt', "
                          "4, 'main', '1', 'R', 'Instant', '{R}', '2026-01-01')"))
    database.upgrade()
    from mtg_collection.services import decks
    with database.session() as s:
        [line] = decks.list_cards(s, 1, 1)
        burn, empty = decks.get_deck(s, 1, 1), decks.get_deck(s, 1, 2)
        assert [v.name for v in decks.list_versions(s, 1, 2)] == ["Original"]
    assert (line.card_name, line.quantity) == ("Lightning Bolt", 4)
    assert (burn.version_name, burn.card_count, empty.version_name, empty.card_count) == ("Original", 4, "Original", 0)
