"""Correções da revisão dos serviços: versão personalizada nos decks, migrações, preço, cadastro, imagens,
limites de quantidade, tentativas de login, vitórias e contas desativadas."""
import threading
import time
from datetime import date

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

from mtg_collection import database
from mtg_collection.database.tables import CollectionEntryRow, DeckCardRow, UserRow
from mtg_collection.services import accounts, decks, login_throttle, ranking
from mtg_collection.services import collection as col
from mtg_collection.services import custom_cards as cc
from mtg_collection.services.accounts import AccountError
from mtg_collection.services.collection import CollectionError
from mtg_collection.services.decks import DeckError
from mtg_collection.services.scryfall import to_card
from mtg_collection.ui.components.custom_print_dialog import delete_warning
from tests.conftest import create_account
from tests.sample_cards import BOLT, BOLT_REPRINT, DELVER

BOLT_CARD, REPRINT_CARD, DELVER_CARD = map(to_card, (BOLT, BOLT_REPRINT, DELVER))
IMG_A, IMG_B = "a" * 32 + ".png", "b" * 32 + ".png"


def url(filename: str) -> str:
    return f"/custom-image/{filename}"


def run(fn, *args, **kwargs):
    with database.session() as s:
        return fn(s, *args, **kwargs)


@pytest.fixture
def users():
    create_account("marcelo")
    create_account("amigo")


def alembic(action, target: str) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(database.MIGRATIONS_DIR))
    with database.engine().begin() as conn:
        cfg.attributes["connection"] = conn
        action(cfg, target)


def snapshots(model) -> list[tuple]:
    with database.session() as s:
        return s.execute(select(model.custom_print_id, model.scryfall_id, model.set_name, model.image_small,
                                model.image_normal).order_by(model.id)).all()


# ---------- 1. apagar versão personalizada ----------
def test_delete_custom_print_keeps_deck_lines_as_official_print(users):
    custom = run(col.create_custom_print, 1, BOLT_CARD, "Alter", image_filename=IMG_A)
    card = col.as_card(custom, BOLT_CARD, url(IMG_A))
    run(col.add_card, 1, card, 3)
    deck = run(decks.create_deck, 1, "Burn")
    run(decks.add_card, 1, deck.id, card, 4)
    run(decks.create_version, 1, deck.id, "B")  # a linha existe nas duas versões
    usage = run(col.custom_print_usage, 1, custom.id)
    assert usage == col.CustomPrintUsage(copies=3, deck_lines=2)
    assert delete_warning(usage) == ("3 cópia(s) na coleção serão apagadas; "
                                     "2 linha(s) de deck voltam para a edição oficial.")
    assert delete_warning(col.CustomPrintUsage()) == ""

    assert run(col.delete_custom_print, 1, custom.id, BOLT_CARD) == usage
    assert run(col.list_entries, 1) == []  # a coleção perde as cópias, como antes
    for version in run(decks.list_versions, 1, deck.id):
        [line] = run(decks.list_cards, 1, deck.id, version.id)
        assert (line.quantity, line.scryfall_id, line.custom_print_id) == (4, "1", None)
        assert (line.set_code, line.set_name, line.collector_number, line.rarity) == (
            BOLT_CARD.set_code, BOLT_CARD.set_name, BOLT_CARD.collector_number, BOLT_CARD.rarity)
        assert (line.image_small, line.image_normal) == (BOLT_CARD.image_small, BOLT_CARD.image_normal)
    assert not run(col.custom_print_image_in_use, IMG_A)


def test_delete_custom_print_without_matching_base(users):
    """Sem a impressão base certa, a linha ainda fica no deck (oficial), sem apontar para a imagem apagada."""
    with_image = run(col.create_custom_print, 1, BOLT_CARD, "Alter", image_filename=IMG_A)
    plain = run(col.create_custom_print, 1, BOLT_CARD, "Sem imagem")
    deck = run(decks.create_deck, 1, "Burn")
    run(decks.add_card, 1, deck.id, col.as_card(with_image, BOLT_CARD, url(IMG_A)))
    run(decks.add_card, 1, deck.id, col.as_card(plain, BOLT_CARD))
    run(col.delete_custom_print, 1, with_image.id, REPRINT_CARD)  # outra edição: não serve de base
    run(col.delete_custom_print, 1, plain.id)
    assert snapshots(DeckCardRow) == [(None, "1", "", None, None),
                                      (None, "1", "", BOLT_CARD.image_small, BOLT_CARD.image_normal)]


# ---------- 2. trocar a imagem da versão ----------
def test_update_custom_print_syncs_snapshots(users):
    custom = run(col.create_custom_print, 1, BOLT_CARD, "Alter", image_filename=IMG_A)
    card = col.as_card(custom, BOLT_CARD, url(IMG_A))
    run(col.add_card, 1, card)
    deck = run(decks.create_deck, 1, "Burn")
    run(decks.add_card, 1, deck.id, card)
    run(decks.create_version, 1, deck.id, "B")

    run(col.update_custom_print, 1, custom.id, "Nova", image_filename=IMG_B, image_url=url(IMG_B))
    assert not run(col.custom_print_image_in_use, IMG_A)  # pode apagar o arquivo antigo: ninguém mais aponta
    assert snapshots(CollectionEntryRow) == [(custom.id, None, "Nova", url(IMG_B), url(IMG_B))]
    assert snapshots(DeckCardRow) == [(custom.id, None, "Nova", url(IMG_B), url(IMG_B))] * 2

    run(col.update_custom_print, 1, custom.id, "Nova", remove_image=True, base=BOLT_CARD)
    expected = (custom.id, None, "Nova", BOLT_CARD.image_small, BOLT_CARD.image_normal)
    assert snapshots(CollectionEntryRow) == [expected] and snapshots(DeckCardRow) == [expected] * 2
    assert not run(col.custom_print_image_in_use, IMG_B)


# ---------- 3. migrações não apagam dados ----------
def test_downgrade_and_upgrade_keep_user_data(users):
    run(col.add_card, 1, BOLT_CARD, 2)
    deck = run(decks.create_deck, 1, "Burn", visibility="friends")
    run(decks.add_card, 1, deck.id, BOLT_CARD, 4)
    run(ranking.add_win, 1, deck.id, date.today())

    def counts():
        with database.engine().connect() as conn:
            return {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar()
                    for t in ("users", "collection_entries", "decks", "deck_versions", "deck_cards", "wins")}

    before = counts()
    assert all(before.values())
    alembic(command.downgrade, "0006")  # várias tabelas pai (users, decks...) são recriadas no caminho
    database.upgrade()
    assert counts() == before
    with database.engine().connect() as conn:  # a conexão usada na migração volta com as chaves ligadas
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
    with database.session() as s:
        assert [c.quantity for c in decks.list_cards(s, 1, deck.id)] == [4]


def test_migration_refuses_broken_references(tmp_path):
    database.configure(database.database_url(tmp_path / "fk.db"))
    alembic(command.upgrade, "0010")
    with database.engine().connect() as conn:  # linha órfã, gravada com as chaves desligadas
        conn.exec_driver_sql("PRAGMA foreign_keys = OFF")
        conn.execute(text("INSERT INTO folders (user_id, kind, name, created_at) "
                          "VALUES (99, 'decks', 'x', '2026-01-01')"))
        conn.commit()
    with pytest.raises(RuntimeError, match="referências quebradas"):
        database.upgrade()
    with database.engine().connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0010"


# ---------- 4. preço ----------
def test_parse_price_thousands_and_non_finite():
    assert col.parse_price("1.500") == 150000
    assert col.parse_price("R$ 1.500") == 150000
    assert col.parse_price("1.500,25") == 150025
    assert col.parse_price("1,50") == 150 and col.parse_price("1.50") == 150
    assert col.parse_price("1.234,56") == 123456 and col.parse_price("R$ 10") == 1000
    assert col.parse_price(",5") == 50
    for bad in ("NaN", "nan", "Infinity", "inf", "-inf", "1e3", "+5", "1_000", "1.2.3,4", "1.23,4", "."):
        with pytest.raises(CollectionError):
            col.parse_price(bad)
    with pytest.raises(CollectionError, match="alto"):
        col.parse_price("1.234.567")


# ---------- 5. cadastro ao mesmo tempo ----------
def test_register_race_on_empty_database_makes_one_admin(monkeypatch):
    accounts_register = accounts.register
    original = accounts.regenerate_invite_code
    started = threading.Event()

    def slow_invite(s):  # o primeiro cadastro segura a gravação enquanto o segundo começa
        started.set()
        time.sleep(0.5)
        return original(s)

    monkeypatch.setattr(accounts, "regenerate_invite_code", slow_invite)
    errors = []

    def second():
        started.wait(5)
        try:
            with database.session() as s:
                accounts_register(s, "bruno", "senha-forte-1")
        except AccountError as e:
            errors.append(str(e))

    thread = threading.Thread(target=second)
    thread.start()
    with database.session() as s:
        accounts_register(s, "ana", "senha-forte-1")
    thread.join(10)
    with database.session() as s:
        admins = s.scalars(select(UserRow.username).where(UserRow.is_admin.is_(True))).all()
        total = s.scalar(select(func.count()).select_from(UserRow))
    assert admins == ["ana"] and total == 1
    assert errors and "convite" in errors[0]


def test_register_recheck_and_duplicate_name(monkeypatch):
    create_account("ana")
    monkeypatch.setattr(accounts, "has_users", lambda s: False)  # como se tivesse lido o banco ainda vazio
    with pytest.raises(AccountError, match="convite"):
        run(accounts.register, "bruno", "senha-forte-1")
    monkeypatch.undo()
    monkeypatch.setattr(accounts, "_username_taken", lambda s, name: False)  # outra aba gravou o mesmo nome
    with pytest.raises(AccountError, match="já está em uso"):
        run(accounts.register, "ana", "senha-forte-1", invite_code=run(accounts.invite_code))
    with database.session() as s:
        assert s.scalar(select(func.count()).select_from(UserRow)) == 1


# ---------- 6. imagens: índices e permissão ----------
def test_image_indexes_exist():
    with database.engine().connect() as conn:
        names = set(conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'index'")).scalars())
        plan = " ".join(str(r) for r in conn.execute(text(
            "EXPLAIN QUERY PLAN SELECT id FROM custom_prints WHERE image_filename = 'x'")))
    assert {"ix_custom_prints_image_filename", "ix_custom_cards_image_filename",
            "ix_deck_cards_custom_print_id"} <= names
    assert "ix_custom_prints_image_filename" in plan


def test_metadata_matches_migrations():
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from mtg_collection.database.tables import Base
    with database.engine().connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert [d for d in diff if d[0] in ("add_index", "remove_index")] == []


def test_friend_sees_custom_card_and_print_images(users):
    deck = run(decks.create_deck, 1, "Burn")
    custom = run(col.create_custom_print, 1, BOLT_CARD, "Alter", image_filename=IMG_A)
    run(decks.add_card, 1, deck.id, col.as_card(custom, BOLT_CARD, url(IMG_A)))
    made = run(cc.create, 1, name="Minha", image_filename=IMG_B, deck_id=deck.id)
    run(decks.add_card, 1, deck.id, cc.as_card(made, url(IMG_B)))
    assert not run(decks.can_view_card_image, 2, url(IMG_A))
    assert not run(decks.can_view_card_image, 2, url(IMG_B))
    run(decks.update_deck, 1, deck.id, name="Burn", visibility="friends")
    assert run(decks.can_view_card_image, 2, url(IMG_A)) and run(decks.can_view_card_image, 2, url(IMG_B))
    assert not run(decks.can_view_card_image, 1, url(IMG_A))  # o dono vê pela posse, não por aqui
    assert not run(decks.can_view_card_image, 2, url("c" * 32 + ".png"))
    with database.session() as s:  # dono desativado (é o admin, então direto no banco)
        s.get(UserRow, 1).is_disabled = True
    assert not run(decks.can_view_card_image, 2, url(IMG_A))


# ---------- 7. o que falta na coleção ----------
def test_missing_against_sums_only_deck_cards(users):
    run(col.add_card, 2, BOLT_CARD, 1)
    run(col.add_card, 2, REPRINT_CARD, 1, foil=True)  # outra edição conta para a mesma carta
    run(col.add_card, 2, DELVER_CARD, 5)
    deck = run(decks.create_deck, 1, "Burn")
    run(decks.add_card, 1, deck.id, BOLT_CARD, 4)
    run(decks.add_card, 1, deck.id, DELVER_CARD, 1, "maybe")  # "talvez" não conta
    missing = run(decks.missing_against, 2, run(decks.list_cards, 1, deck.id))
    assert [(m.line.card_name, m.quantity) for m in missing] == [("Lightning Bolt", 2)]
    assert run(decks.missing_against, 2, []) == []


# ---------- 8. limites de quantidade ----------
def test_add_cards_counts_only_what_fits(users):
    run(col.add_card, 1, BOLT_CARD, col.MAX_QUANTITY - 2)
    added = run(col.add_cards, 1, [col.NewItem(BOLT_CARD, 5), col.NewItem(DELVER_CARD, col.MAX_QUANTITY),
                                   col.NewItem(DELVER_CARD, 3), col.NewItem(BOLT_CARD, 1, notes="obs")])
    assert added == 2 + col.MAX_QUANTITY + 1
    assert run(col.count_cards, 1) == 2 * col.MAX_QUANTITY + 1


def test_deck_add_card_reports_full_line(users):
    deck = run(decks.create_deck, 1, "Burn")
    run(decks.add_card, 1, deck.id, BOLT_CARD, decks.MAX_QUANTITY - 1)
    assert run(decks.add_card, 1, deck.id, BOLT_CARD, 5).quantity == decks.MAX_QUANTITY  # soma o que cabe
    with pytest.raises(DeckError, match="máximo"):
        run(decks.add_card, 1, deck.id, BOLT_CARD, 1)


# ---------- 9. tentativas de login ----------
class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_throttle_forgets_expired_and_caps_keys(monkeypatch):
    clock = Clock()
    t = login_throttle.LoginThrottle(clock)
    for i in range(50):
        t.failed(f"robo{i}", "1.1.1.1")
    assert len(t._failures) == 51  # 50 nomes e 1 endereço
    clock.now += login_throttle.WINDOW_SECONDS + 1
    t.failed("depois", "2.2.2.2")
    assert set(t._failures) == {"user:depois", "addr:2.2.2.2"}  # os vencidos saíram
    monkeypatch.setattr(login_throttle, "MAX_KEYS", 10)
    for i in range(30):
        t.failed(f"outro{i}", "2.2.2.2")
    assert len(t._failures) <= 10 and "addr:2.2.2.2" in t._failures  # o endereço ativo fica (erro recente)
    for _ in range(login_throttle.MAX_PER_USER):
        t.failed("alvo", "3.3.3.3")
    assert "user:alvo" not in t._failures and t.wait_seconds("alvo", "4.4.4.4") > 0  # bloqueado sem contagem


# ---------- 10. editar vitória ----------
def test_update_win_keeps_version_when_omitted(users):
    deck = run(decks.create_deck, 1, "Burn", visibility="friends")
    win = run(ranking.add_win, 1, deck.id, date.today())
    assert win.version_id is not None
    assert run(ranking.update_win, 1, win.id, played_on=date.today(), notes="x").version_id == win.version_id
    assert run(ranking.update_win, 1, win.id, played_on=date.today(), version_id=None).version_id is None
    assert [w.version_name for w in run(ranking.list_wins, 1, deck.id)] == [""]


# ---------- 11. conta desativada ----------
def test_disabled_account_disappears_for_friends(users):
    deck = run(decks.create_deck, 2, "Do amigo", visibility="friends")
    run(ranking.add_win, 2, deck.id, date.today())
    assert [x.deck.name for x in run(decks.list_shared_decks, 1)] == ["Do amigo"]
    assert [p.name for p in run(ranking.player_ranking)] == ["amigo"]
    run(accounts.set_disabled, 1, 2, True)
    assert run(decks.list_shared_decks, 1) == []
    for fn in (decks.get_shared_deck, decks.shared_versions, decks.shared_cards):
        with pytest.raises(DeckError, match="não encontrado"):
            run(fn, 1, deck.id)
    assert run(ranking.deck_ranking) == [] and run(ranking.player_ranking) == []
    assert run(ranking.deck_ranking, ranking.Filters(include_hidden=True)) == []
    run(accounts.set_disabled, 1, 2, False)  # reativada, volta tudo (os dados continuam lá)
    assert len(run(decks.list_shared_decks, 1)) == 1 and len(run(ranking.deck_ranking)) == 1
