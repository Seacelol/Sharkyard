import pytest

from mtg_collection import database
from mtg_collection.services import collection as col
from mtg_collection.services import custom_cards as cc
from mtg_collection.services import decks
from mtg_collection.services.decks import DeckError
from mtg_collection.services.scryfall import to_card
from tests.conftest import create_account
from tests.sample_cards import BOLT, BOLT_REPRINT, DELVER, GOLD

BOLT_CARD, REPRINT_CARD, DELVER_CARD, GOLD_CARD = map(to_card, (BOLT, BOLT_REPRINT, DELVER, GOLD))


@pytest.fixture
def deck():
    create_account("marcelo")
    create_account("amigo")
    with database.session() as s:
        return decks.create_deck(s, 1, "Teste", format="modern")


def run(fn, *args, **kwargs):
    with database.session() as s:
        return fn(s, *args, **kwargs)


# ---------- linhas ----------
def test_add_lines_merge_rules(deck):
    a = run(decks.add_card, 1, deck.id, BOLT_CARD, 2)
    assert run(decks.add_card, 1, deck.id, BOLT_CARD, 2).id == a.id  # soma
    proxy = run(decks.add_card, 1, deck.id, BOLT_CARD, 1, is_proxy=True)
    side = run(decks.add_card, 1, deck.id, BOLT_CARD, 1, section="sideboard")
    other = run(decks.add_card, 1, deck.id, REPRINT_CARD, 1)
    assert len({a.id, proxy.id, side.id, other.id}) == 4
    lines = run(decks.list_cards, 1, deck.id)
    assert [(c.set_code, c.quantity, c.section, c.is_proxy) for c in lines] == [
        ("M10", 4, "main", False), ("M10", 1, "main", True), ("2XM", 1, "main", False), ("M10", 1, "sideboard", False)]
    assert lines[0].collector_number == "146" and lines[0].rarity == "common"


def test_update_line(deck):
    line = run(decks.add_card, 1, deck.id, BOLT_CARD, 4)
    updated = run(decks.update_line, 1, deck.id, line.id, quantity=3, section="sideboard", foil=True, is_proxy=True,
                  price_paid_cents=500, notes=" emprestada ", printing=REPRINT_CARD)
    assert (updated.quantity, updated.section, updated.foil, updated.is_proxy) == (3, "sideboard", True, True)
    assert (updated.price_paid_cents, updated.notes, updated.scryfall_id, updated.set_code) == (
        500, "emprestada", "1b", "2XM")
    with pytest.raises(DeckError, match="outra carta"):
        run(decks.update_line, 1, deck.id, line.id, quantity=1, section="main", printing=DELVER_CARD)
    with pytest.raises(DeckError, match="quantidade"):
        run(decks.update_line, 1, deck.id, line.id, quantity=0, section="main")
    with pytest.raises(DeckError, match="Seção"):
        run(decks.update_line, 1, deck.id, line.id, quantity=1, section="banco")


def test_change_quantity_and_remove(deck):
    line = run(decks.add_card, 1, deck.id, BOLT_CARD, 2)
    assert run(decks.change_quantity, 1, deck.id, line.id, +1).quantity == 3
    assert run(decks.change_quantity, 1, deck.id, line.id, -3) is None  # chegou a zero: sai do deck
    assert run(decks.list_cards, 1, deck.id) == []
    line = run(decks.add_card, 1, deck.id, BOLT_CARD, 2)
    run(decks.remove_line, 1, deck.id, line.id)
    assert run(decks.list_cards, 1, deck.id) == []


def test_lines_are_private(deck):
    line = run(decks.add_card, 1, deck.id, BOLT_CARD)
    with pytest.raises(DeckError):
        run(decks.update_line, 2, deck.id, line.id, quantity=1, section="main")
    other = run(decks.create_deck, 1, "Outro")
    with pytest.raises(DeckError, match="não está neste deck"):
        run(decks.remove_line, 1, other.id, line.id)


# ---------- edição e carta personalizadas ----------
def test_custom_print_in_deck(deck):
    custom = run(col.create_custom_print, 1, BOLT_CARD, "Alter", code="ALT")
    line = run(decks.add_card, 1, deck.id, col.as_card(custom, BOLT_CARD))
    assert (line.custom_print_id, line.scryfall_id, line.set_name, line.set_code) == (custom.id, None, "Alter", "ALT")
    theirs = run(col.create_custom_print, 2, BOLT_CARD, "Do amigo")
    with pytest.raises(DeckError, match="não encontrada"):
        run(decks.add_card, 1, deck.id, col.as_card(theirs, BOLT_CARD))


def test_custom_card_lifecycle(deck):
    card = run(cc.create, 1, name="  Dragão   do Marcelo ", mana_cost="{3} {R}{R}", type_line="Creature — Dragon",
               oracle_text="Flying", power="5", toughness="5", deck_id=deck.id)
    assert (card.name, card.mana_cost, card.colors, card.deck_id) == ("Dragão do Marcelo", "{3}{R}{R}", "R", deck.id)
    assert not card.in_collection
    as_card = cc.as_card(card, "/custom-image/x.png")
    assert as_card.is_custom_card and not as_card.is_custom and as_card.oracle_id == f"customcard-{card.id}"
    assert as_card.color_identity == ("R",) and as_card.faces[0].power == "5" and as_card.legalities == {}
    line = run(decks.add_card, 1, deck.id, as_card, 2)
    assert (line.custom_card_id, line.scryfall_id, line.set_name, line.color_identity) == (
        card.id, None, "Carta personalizada", "R")
    assert run(decks.get_deck, 1, deck.id).colors == ("R",)
    # só existe neste deck: outro deck não pode usar, nem outro usuário
    other = run(decks.create_deck, 1, "Outro")
    with pytest.raises(DeckError, match="outro deck"):
        run(decks.add_card, 1, other.id, as_card)
    with pytest.raises(cc.CustomCardError):
        run(cc.get, 2, card.id)
    assert [c.name for c in run(cc.available_for_deck, 1, deck.id)] == ["Dragão do Marcelo"]
    assert run(cc.available_for_deck, 1, other.id) == []
    # foi para a coleção: vira da coleção e qualquer deck pode usar
    entry = run(col.add_card, 1, as_card)
    assert entry.custom_card_id == card.id and entry.set_name == "Carta personalizada"
    assert run(cc.get, 1, card.id).in_collection
    assert run(decks.add_card, 1, other.id, as_card).custom_card_id == card.id


def test_custom_card_colors_and_rename_sync(deck):
    card = run(cc.create, 1, name="Gold", mana_cost="{W/U}{B}", deck_id=deck.id)
    assert card.colors == "WUB"
    assert run(cc.create, 1, name="Explicit", mana_cost="{R}", colors="gw").colors == "WG"
    with pytest.raises(cc.CustomCardError, match="nome"):
        run(cc.create, 1, name="  ")
    run(decks.add_card, 1, deck.id, cc.as_card(card))
    updated, old_image = run(cc.update, 1, card.id, name="Gold 2", mana_cost="{G}", image_filename="f.png")
    assert old_image is None and updated.colors == "G"
    run(cc.sync_snapshots, 1, cc.as_card(updated, "/custom-image/f.png"))
    [line] = run(decks.list_cards, 1, deck.id)
    assert (line.card_name, line.mana_cost, line.color_identity, line.image_normal) == (
        "Gold 2", "{G}", "G", "/custom-image/f.png")
    _, old_image = run(cc.update, 1, card.id, name="Gold 2", remove_image=True)
    assert old_image == "f.png"


def test_deleting_deck_removes_deck_only_custom_cards(deck):
    only_here = run(cc.create, 1, name="Só aqui", deck_id=deck.id)
    kept = run(cc.create, 1, name="Na coleção", deck_id=deck.id)
    run(col.add_card, 1, cc.as_card(kept))
    run(decks.delete_decks, 1, [deck.id])
    with pytest.raises(cc.CustomCardError):
        run(cc.get, 1, only_here.id)
    assert run(cc.get, 1, kept.id).in_collection


# ---------- deck x coleção ----------
def test_missing_in_collection_by_card_and_quantity(deck):
    run(decks.add_card, 1, deck.id, BOLT_CARD, 4)
    run(decks.add_card, 1, deck.id, DELVER_CARD, 2, section="sideboard")
    run(decks.add_card, 1, deck.id, GOLD_CARD, 3, section="maybe")  # "talvez" não conta
    run(col.add_card, 1, REPRINT_CARD, 2)  # 2 Bolts de outra edição contam
    run(col.add_card, 2, DELVER_CARD, 4)  # coleção de outro usuário não conta
    missing = run(decks.missing_in_collection, 1, deck.id)
    assert [(m.line.card_name, m.quantity) for m in missing] == [
        ("Lightning Bolt", 2), ("Delver of Secrets // Insectile Aberration", 2)]


def test_add_missing_to_collection_keeps_line_details(deck):
    line = run(decks.add_card, 1, deck.id, BOLT_CARD, 3)
    run(decks.update_line, 1, deck.id, line.id, quantity=3, section="main", foil=True, is_proxy=True,
        price_paid_cents=150, notes="impressa em casa")
    custom = run(cc.create, 1, name="Minha carta", deck_id=deck.id)
    run(decks.add_card, 1, deck.id, cc.as_card(custom, "/custom-image/a.png"))
    run(col.add_card, 1, BOLT_CARD, 1)
    from mtg_collection.services import folders
    binder = run(folders.create_folder, 1, folders.COLLECTION, "Do deck")
    assert run(decks.add_missing_to_collection, 1, deck.id, binder.id) == 3  # 2 Bolts + 1 personalizada
    entries = {(e.card_name, e.folder_id): e for e in run(col.list_entries, 1)}
    bolt = entries[("Lightning Bolt", binder.id)]
    assert (bolt.quantity, bolt.foil, bolt.is_proxy, bolt.price_paid_cents, bolt.notes, bolt.scryfall_id) == (
        2, True, True, 150, "impressa em casa", "1")
    mine = entries[("Minha carta", binder.id)]
    assert mine.custom_card_id == custom.id and mine.image_normal == "/custom-image/a.png"
    assert run(cc.get, 1, custom.id).in_collection
    assert run(decks.missing_in_collection, 1, deck.id) == []
    assert run(decks.add_missing_to_collection, 1, deck.id) == 0


def test_line_as_card_for_custom_print(deck):
    custom = run(col.create_custom_print, 1, BOLT_CARD, "Alter")
    run(decks.add_card, 1, deck.id, col.as_card(custom, BOLT_CARD), 2)
    assert run(decks.add_missing_to_collection, 1, deck.id) == 2
    [entry] = run(col.list_entries, 1)
    assert entry.custom_print_id == custom.id and entry.scryfall_id is None and entry.quantity == 2


def test_delete_deck_returns_custom_card_images(deck):
    run(cc.create, 1, name="Com imagem", deck_id=deck.id, image_filename="a" * 32 + ".png")
    kept = run(cc.create, 1, name="Coleção", deck_id=deck.id, image_filename="b" * 32 + ".png")
    run(cc.move_to_collection, 1, kept.id)
    assert run(decks.delete_decks, 1, [deck.id]) == ["a" * 32 + ".png"]


# ---------- zona de comando ----------
def test_set_commanders_and_companion(deck):
    from tests.sample_cards import LEGEND, RATS
    krenko, rats = to_card(LEGEND), to_card(RATS)
    run(decks.add_card, 1, deck.id, krenko, 1)  # veio da lista no principal: vira comandante, sem duplicar
    run(decks.add_card, 1, deck.id, GOLD_CARD, 3)
    run(decks.add_card, 1, deck.id, DELVER_CARD, 2, section="sideboard")
    run(decks.set_commanders, 1, deck.id, [krenko])
    assert lines_of(deck.id) == [("Krenko, Mob Boss", 1, "commander"), ("Lightning Helix", 3, "main"),
                                 ("Delver of Secrets // Insectile Aberration", 2, "sideboard")]
    got = run(decks.get_deck, 1, deck.id)
    assert got.colors == ("R",) and got.card_count == 4  # cor do comandante; sideboard não conta
    run(decks.set_commanders, 1, deck.id, [krenko, rats])
    run(decks.set_companion, 1, deck.id, DELVER_CARD)  # tinha 2 no sideboard: 1 vai para companheiro
    assert ("Delver of Secrets // Insectile Aberration", 1, "sideboard") in lines_of(deck.id)
    assert ("Delver of Secrets // Insectile Aberration", 1, "companion") in lines_of(deck.id)
    assert run(decks.get_deck, 1, deck.id).colors == ("B", "R")
    run(decks.set_commanders, 1, deck.id, [rats])
    run(decks.set_companion, 1, deck.id, None)
    assert [x for x in lines_of(deck.id) if x[2] in ("commander", "companion")] == [("Relentless Rats", 1, "commander")]
    with pytest.raises(DeckError, match="No máximo 2"):
        run(decks.set_commanders, 1, deck.id, [krenko, rats, GOLD_CARD])
    with pytest.raises(DeckError, match="diferentes"):
        run(decks.set_commanders, 1, deck.id, [krenko, krenko])


def lines_of(deck_id):
    return [(c.card_name, c.quantity, c.section) for c in run(decks.list_cards, 1, deck_id)]


# ---------- versões ----------
def test_versions_copy_switch_rename_delete(deck):
    from tests.sample_cards import LEGEND
    run(decks.add_card, 1, deck.id, BOLT_CARD, 4)
    line = run(decks.add_card, 1, deck.id, DELVER_CARD, 2, is_proxy=True)
    run(decks.update_line, 1, deck.id, line.id, quantity=2, section="main", is_proxy=True, notes="impressa")
    assert [(v.name, v.card_count) for v in run(decks.list_versions, 1, deck.id)] == [("Original", 6)]
    first = run(decks.get_deck, 1, deck.id).version_id

    copy = run(decks.create_version, 1, deck.id, "  Sem   Delver ")
    assert (copy.version_name, copy.version_count, copy.card_count) == ("Sem Delver", 2, 6)
    copied = run(decks.list_cards, 1, deck.id)
    assert [(c.card_name, c.quantity, c.is_proxy, c.notes) for c in copied] == [
        ("Delver of Secrets // Insectile Aberration", 2, True, "impressa"), ("Lightning Bolt", 4, False, "")]
    assert line.id not in {c.id for c in copied}  # cópia: linhas novas
    delver = next(c for c in copied if c.oracle_id == "o-delver")
    run(decks.remove_line, 1, deck.id, delver.id)
    run(decks.set_commanders, 1, deck.id, [to_card(LEGEND)])
    with pytest.raises(DeckError, match="não está neste deck"):
        run(decks.remove_line, 1, deck.id, line.id)  # linha da outra versão não é editada daqui
    assert [(v.name, v.card_count) for v in run(decks.list_versions, 1, deck.id)] == [
        ("Original", 6), ("Sem Delver", 5)]

    back = run(decks.select_version, 1, deck.id, first)
    assert back.version_name == "Original" and back.card_count == 6 and back.colors == ("U", "R")
    with pytest.raises(DeckError, match="Já existe"):
        run(decks.create_version, 1, deck.id, "sem delver")
    with pytest.raises(DeckError, match="nome"):
        run(decks.rename_version, 1, deck.id, first, " ")
    run(decks.rename_version, 1, deck.id, first, "Lista do torneio")
    after = run(decks.delete_version, 1, deck.id, first)  # apagou a atual: vai para a que sobrou
    assert (after.version_name, after.version_count, after.card_count) == ("Sem Delver", 1, 5)
    with pytest.raises(DeckError, match="pelo menos uma"):
        run(decks.delete_version, 1, deck.id, after.version_id)
    with pytest.raises(DeckError, match="Versão não encontrada"):
        run(decks.select_version, 1, deck.id, first)


def test_versions_are_private_and_deleted_with_deck(deck):
    run(decks.add_card, 1, deck.id, BOLT_CARD, 4)
    version = run(decks.create_version, 1, deck.id, "B")
    with pytest.raises(DeckError):
        run(decks.select_version, 2, deck.id, version.version_id)
    run(decks.delete_decks, 1, [deck.id])
    from sqlalchemy import func, select

    from mtg_collection.database.tables import DeckCardRow, DeckVersionRow
    with database.session() as s:
        assert s.scalar(select(func.count()).select_from(DeckCardRow)) == 0
        assert s.scalar(select(func.count()).select_from(DeckVersionRow)) == 0


def test_compare_versions(deck):
    run(decks.add_card, 1, deck.id, BOLT_CARD, 4)
    run(decks.add_card, 1, deck.id, DELVER_CARD, 2)
    run(decks.add_card, 1, deck.id, GOLD_CARD, 1, section="sideboard")
    first = run(decks.get_deck, 1, deck.id).version_id
    second = run(decks.create_version, 1, deck.id, "B").version_id
    by_name = {c.card_name: c for c in run(decks.list_cards, 1, deck.id)}
    run(decks.remove_line, 1, deck.id, by_name["Delver of Secrets // Insectile Aberration"].id)
    run(decks.change_quantity, 1, deck.id, by_name["Lightning Bolt"].id, -1)
    run(decks.add_card, 1, deck.id, REPRINT_CARD, 1)  # outra edição do Bolt: mesma carta
    run(decks.add_card, 1, deck.id, GOLD_CARD, 2)  # Helix entra no principal; o do sideboard fica
    changes = run(decks.compare_versions, 1, deck.id, first, second)
    assert [(c.card_name, c.section, c.before, c.after, c.delta) for c in changes] == [
        ("Delver of Secrets // Insectile Aberration", "main", 2, 0, -2), ("Lightning Helix", "main", 0, 2, 2)]
    assert run(decks.list_cards, 1, deck.id, first)[0].quantity == 2  # lê a outra versão sem trocar
    assert run(decks.get_deck, 1, deck.id).version_id == second


# ---------- decks dos amigos ----------
def test_shared_decks_read_only(deck):
    run(decks.add_card, 1, deck.id, BOLT_CARD, 4)
    first = run(decks.get_deck, 1, deck.id).version_id
    run(decks.create_version, 1, deck.id, "B")
    run(decks.add_card, 1, deck.id, DELVER_CARD, 2)
    hidden = run(decks.create_deck, 1, "Privado")
    assert run(decks.list_shared_decks, 2) == []
    with pytest.raises(DeckError):
        run(decks.get_shared_deck, 2, deck.id)
    run(decks.update_deck, 1, deck.id, name="Teste", format="modern", visibility="friends")
    [shared] = run(decks.list_shared_decks, 2)
    assert (shared.deck.name, shared.owner_name, shared.deck.version_name) == ("Teste", "marcelo", "B")
    assert run(decks.list_shared_decks, 1) == []  # o próprio dono não aparece na lista dos amigos
    assert [v.name for v in run(decks.shared_versions, 2, deck.id)] == ["Original", "B"]
    assert len(run(decks.shared_cards, 2, deck.id)) == 2
    assert [c.card_name for c in run(decks.shared_cards, 2, deck.id, first)] == ["Lightning Bolt"]
    assert run(decks.get_deck, 1, deck.id).version_name == "B"  # ver outra versão não muda a do dono
    with pytest.raises(DeckError):
        run(decks.get_shared_deck, 2, hidden.id)
    # o que falta na coleção de quem está vendo
    run(col.add_card, 2, BOLT_CARD, 3)
    missing = run(decks.missing_against, 2, run(decks.shared_cards, 2, deck.id))
    assert [(m.line.card_name, m.quantity) for m in missing] == [
        ("Delver of Secrets // Insectile Aberration", 2), ("Lightning Bolt", 1)]


def test_friend_sees_custom_image_only_in_visible_deck(deck):
    custom = run(col.create_custom_print, 1, BOLT_CARD, "Alter", image_filename="a" * 32 + ".png")
    run(decks.add_card, 1, deck.id, col.as_card(custom, BOLT_CARD, "/custom-image/" + "a" * 32 + ".png"))
    url = "/custom-image/" + "a" * 32 + ".png"
    assert not run(decks.can_view_card_image, 2, url)
    run(decks.update_deck, 1, deck.id, name="Teste", visibility="friends")
    assert run(decks.can_view_card_image, 2, url)
    assert not run(decks.can_view_card_image, 2, "/custom-image/" + "b" * 32 + ".png")
