import pytest

from mtg_collection import database
from mtg_collection.services import collection as col
from mtg_collection.services.collection import CollectionError
from mtg_collection.services.scryfall import to_card
from tests.conftest import create_account
from tests.sample_cards import BOLT, BOLT_REPRINT, DELVER

BOLT_CARD, REPRINT_CARD, DELVER_CARD = to_card(BOLT), to_card(BOLT_REPRINT), to_card(DELVER)


@pytest.fixture
def users():
    create_account("marcelo")
    create_account("amigo")
    return 1, 2


def run(fn, *args, **kwargs):
    with database.session() as s:
        return fn(s, *args, **kwargs)


def test_parse_price():
    assert col.parse_price("") is None and col.parse_price(None) is None
    assert col.parse_price("12,50") == 1250
    assert col.parse_price("R$ 1.234,56") == 123456
    assert col.parse_price("7") == 700
    assert col.parse_price("3.5") == 350
    assert col.parse_price("0") == 0
    for bad in ("abc", "-1", "1,234", "12,5,0"):
        with pytest.raises(CollectionError):
            col.parse_price(bad)


def test_add_card_copies_display_data(users):
    entry = run(col.add_card, 1, BOLT_CARD)
    assert entry.quantity == 1 and entry.card_name == "Lightning Bolt" and entry.scryfall_id == "1"
    assert entry.set_code == "M10" and entry.collector_number == "146" and entry.image_normal == BOLT_CARD.image_normal
    assert not entry.foil and not entry.is_proxy and entry.price_paid is None


def test_quick_add_merges_only_plain_lots(users):
    first = run(col.add_card, 1, BOLT_CARD)
    again = run(col.add_card, 1, BOLT_CARD, quantity=3)
    assert again.id == first.id and again.quantity == 4
    other_print = run(col.add_card, 1, REPRINT_CARD)
    assert other_print.id != first.id
    # lote com preço não é "simples": nova adição cria outra linha
    run(col.update_entry, 1, first.id, quantity=4, foil=False, is_proxy=False, price_paid_cents=500, notes="")
    third = run(col.add_card, 1, BOLT_CARD)
    assert third.id not in (first.id, other_print.id) and third.quantity == 1


def test_update_entry_fields_and_print(users):
    entry = run(col.add_card, 1, BOLT_CARD)
    updated = run(col.update_entry, 1, entry.id, quantity=2, foil=True, is_proxy=True, price_paid_cents=1250,
                  notes="  comprei na loja  ", printing=REPRINT_CARD)
    assert (updated.quantity, updated.foil, updated.is_proxy) == (2, True, True)
    assert updated.price_paid_cents == 1250 and updated.total_paid_cents == 2500 and str(updated.price_paid) == "12.5"
    assert updated.notes == "comprei na loja"
    assert updated.scryfall_id == "1b" and updated.set_code == "2XM" and updated.collector_number == "129"


def test_update_rejects_other_card_and_bad_values(users):
    entry = run(col.add_card, 1, BOLT_CARD)
    with pytest.raises(CollectionError, match="outra carta"):
        run(col.update_entry, 1, entry.id, quantity=1, foil=False, is_proxy=False, price_paid_cents=None,
            notes="", printing=DELVER_CARD)
    for qty in (0, -1, 10000):
        with pytest.raises(CollectionError, match="quantidade"):
            run(col.update_entry, 1, entry.id, quantity=qty, foil=False, is_proxy=False, price_paid_cents=None,
                notes="")
    with pytest.raises(CollectionError, match="Preço"):
        run(col.update_entry, 1, entry.id, quantity=1, foil=False, is_proxy=False, price_paid_cents=-5, notes="")


def test_users_cannot_touch_each_other(users):
    mine = run(col.add_card, 1, BOLT_CARD)
    with pytest.raises(CollectionError, match="não encontrado"):
        run(col.update_entry, 2, mine.id, quantity=5, foil=False, is_proxy=False, price_paid_cents=None, notes="")
    with pytest.raises(CollectionError, match="não encontrado"):
        run(col.delete_entry, 2, mine.id)
    with pytest.raises(CollectionError, match="não encontrado"):
        run(col.get_entry, 2, mine.id)
    assert run(col.list_entries, 2) == []
    assert run(col.get_entry, 1, mine.id).quantity == 1


def test_delete_and_list(users):
    a = run(col.add_card, 1, BOLT_CARD)
    run(col.add_card, 1, DELVER_CARD)
    run(col.add_card, 2, BOLT_CARD)
    assert [e.card_name for e in run(col.list_entries, 1)] == ["Delver of Secrets // Insectile Aberration",
                                                                "Lightning Bolt"]
    assert len(run(col.list_entries, 1, oracle_id="o-bolt")) == 1
    run(col.delete_entry, 1, a.id)
    assert [e.card_name for e in run(col.list_entries, 1)] == ["Delver of Secrets // Insectile Aberration"]


def test_summary(users):
    a = run(col.add_card, 1, BOLT_CARD, quantity=3)
    run(col.update_entry, 1, a.id, quantity=3, foil=False, is_proxy=False, price_paid_cents=1000, notes="")
    b = run(col.add_card, 1, REPRINT_CARD)
    run(col.update_entry, 1, b.id, quantity=2, foil=False, is_proxy=True, price_paid_cents=None, notes="")
    run(col.add_card, 1, DELVER_CARD)
    summary = col.summarize(run(col.list_entries, 1))
    assert (summary.entries, summary.cards, summary.real_cards, summary.proxies) == (3, 6, 4, 2)
    assert summary.unique_cards == 2 and summary.total_paid_cents == 3000


def test_custom_print_lifecycle(users):
    custom = run(col.create_custom_print, 1, BOLT_CARD, "  Alter do João ", code="al-t!", artist=" João ",
                 notes="pintada à mão", image_filename="abc.png")
    assert (custom.name, custom.code, custom.artist, custom.oracle_id) == ("Alter do João", "ALT", "João", "o-bolt")
    assert custom.base_scryfall_id == "1" and custom.card_name == "Lightning Bolt"
    assert [c.id for c in run(col.list_custom_prints, 1, "o-bolt")] == [custom.id]
    assert run(col.list_custom_prints, 2, "o-bolt") == []  # só o dono vê

    card = col.as_card(custom, BOLT_CARD, "/custom-image/abc.png")
    assert card.is_custom and card.id == f"custom-{custom.id}" and card.set_name == "Alter do João"
    assert card.image_large == "/custom-image/abc.png" and card.faces[0].image_large == "/custom-image/abc.png"
    assert card.oracle_text == BOLT_CARD.oracle_text and card.prices.usd is None and card.artist == "João"

    entry = run(col.add_card, 1, card)
    assert entry.custom_print_id == custom.id and entry.scryfall_id is None
    assert entry.set_name == "Alter do João" and entry.rarity == "special" and entry.base_scryfall_id == "1"
    assert run(col.add_card, 1, card).quantity == 2  # soma no mesmo lote

    run(col.update_custom_print, 1, custom.id, "Alter Final", code="AF")
    renamed = run(col.get_entry, 1, entry.id)
    assert renamed.set_name == "Alter Final" and renamed.set_code == "AF"  # coleção acompanha o nome

    updated = run(col.update_custom_print, 1, custom.id, "Alter Final", remove_image=True)
    assert updated.image_filename is None
    assert col.as_card(updated, BOLT_CARD).image_large == BOLT_CARD.image_large  # sem imagem: usa a da base

    assert run(col.delete_custom_print, 1, custom.id) == col.CustomPrintUsage(copies=2, deck_lines=0)
    assert run(col.list_entries, 1) == []


def test_custom_print_rules(users):
    with pytest.raises(CollectionError, match="nome"):
        run(col.create_custom_print, 1, BOLT_CARD, "   ")
    custom = run(col.create_custom_print, 1, BOLT_CARD, "Minha")
    custom_card = col.as_card(custom, BOLT_CARD)
    with pytest.raises(CollectionError, match="impressão oficial"):
        run(col.create_custom_print, 1, custom_card, "Versão de versão")
    with pytest.raises(CollectionError, match="não encontrada"):
        run(col.add_card, 2, custom_card)  # versão de outro usuário
    with pytest.raises(CollectionError, match="não encontrada"):
        run(col.update_custom_print, 2, custom.id, "Roubada")
    with pytest.raises(CollectionError, match="não encontrada"):
        run(col.delete_custom_print, 2, custom.id)
    entry = run(col.add_card, 1, REPRINT_CARD)
    moved = run(col.update_entry, 1, entry.id, quantity=1, foil=False, is_proxy=False, price_paid_cents=None,
                notes="", printing=custom_card)
    assert moved.custom_print_id == custom.id and moved.set_name == "Minha"


def test_image_owner(users):
    run(col.create_custom_print, 1, BOLT_CARD, "Minha", image_filename="f1.png")
    assert run(col.custom_print_owner, "f1.png") == 1
    assert run(col.custom_print_owner, "outra.png") is None


def test_database_constraints(users):
    from sqlalchemy.exc import IntegrityError

    from mtg_collection.database.tables import CollectionEntryRow
    with pytest.raises(IntegrityError):
        with database.session() as s:
            s.add(CollectionEntryRow(user_id=1, oracle_id="x", card_name="x", quantity=0, notes=""))
            s.flush()


def test_add_cards_in_batch_follows_add_card_rules():
    from mtg_collection.services.collection import NewItem, add_cards
    create_account("marcelo")
    with database.session() as s:
        bolt, delver = to_card(BOLT), to_card(DELVER)
        col.add_card(s, 1, bolt, 2)  # lote que já existe: soma nele
        added = add_cards(s, 1, [NewItem(bolt, 1), NewItem(delver, 1), NewItem(delver, 2),  # repetida soma
                                 NewItem(delver, 1, foil=True), NewItem(bolt, 1, price_paid_cents=500)])
    assert added == 6
    with database.session() as s:
        lots = sorted((e.card_name, e.quantity, e.foil, e.price_paid_cents) for e in col.list_entries(s, 1))
    assert lots == [("Delver of Secrets // Insectile Aberration", 1, True, None),
                    ("Delver of Secrets // Insectile Aberration", 3, False, None),
                    ("Lightning Bolt", 1, False, 500), ("Lightning Bolt", 3, False, None)]


def test_batch_move_and_delete_are_all_or_nothing():
    create_account("marcelo")
    create_account("amigo")
    with database.session() as s:
        mine = col.add_card(s, 1, to_card(BOLT), 1)
        theirs = col.add_card(s, 2, to_card(BOLT), 1)
    with database.session() as s, pytest.raises(CollectionError):
        col.delete_entries(s, 1, [mine.id, theirs.id])
    with database.session() as s, pytest.raises(CollectionError):
        col.move_entries(s, 1, [mine.id, theirs.id], None)
    with database.session() as s:
        assert len(col.list_entries(s, 1)) == 1 and len(col.list_entries(s, 2)) == 1
        assert col.delete_entries(s, 1, [mine.id, mine.id]) == 1  # repetido conta uma vez
    with database.session() as s:
        assert col.list_entries(s, 1) == []
