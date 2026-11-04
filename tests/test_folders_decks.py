import pytest

from mtg_collection import database
from mtg_collection.services import collection as col
from mtg_collection.services import decks, folders
from mtg_collection.services.decks import DeckError
from mtg_collection.services.folders import FolderError
from mtg_collection.services.scryfall import to_card
from tests.conftest import create_account
from tests.sample_cards import BOLT, DELVER, GOLD, LAND

BOLT_CARD, DELVER_CARD, GOLD_CARD, LAND_CARD = map(to_card, (BOLT, DELVER, GOLD, LAND))


@pytest.fixture
def users():
    create_account("marcelo")
    create_account("amigo")


def run(fn, *args, **kwargs):
    with database.session() as s:
        return fn(s, *args, **kwargs)


def test_card_parses_color_identity_and_art():
    assert GOLD_CARD.color_identity == ("R", "W") and GOLD_CARD.image_art_crop == "https://img/h-art.jpg"
    assert DELVER_CARD.image_art_crop == "https://img/d-art.jpg"  # dupla face: arte da frente
    assert LAND_CARD.color_identity == () and LAND_CARD.image_art_crop is None


# ---------- pastas ----------
def test_folder_crud_and_rules(users):
    a = run(folders.create_folder, 1, folders.COLLECTION, "  Trocas   e  vendas ")
    assert a.name == "Trocas e vendas" and a.kind == "collection"
    with pytest.raises(FolderError, match="Já existe"):
        run(folders.create_folder, 1, folders.COLLECTION, "TROCAS E VENDAS")
    run(folders.create_folder, 1, folders.DECKS, "Trocas e vendas")  # mesmo nome, outro tipo: ok
    run(folders.create_folder, 2, folders.COLLECTION, "Trocas e vendas")  # outro usuário: ok
    with pytest.raises(FolderError, match="nome"):
        run(folders.create_folder, 1, folders.COLLECTION, "   ")
    b = run(folders.create_folder, 1, folders.COLLECTION, "binder")
    assert [f.name for f in run(folders.list_folders, 1, folders.COLLECTION)] == ["binder", "Trocas e vendas"]
    with pytest.raises(FolderError, match="Já existe"):
        run(folders.rename_folder, 1, b.id, "trocas e vendas")
    assert run(folders.rename_folder, 1, b.id, "Binder azul").name == "Binder azul"
    assert run(folders.rename_folder, 1, b.id, "binder AZUL").name == "binder AZUL"  # a própria pode mudar caixa
    with pytest.raises(FolderError, match="não encontrada"):
        run(folders.rename_folder, 2, b.id, "roubada")
    with pytest.raises(FolderError, match="não encontrada"):
        run(folders.delete_folder, 2, b.id)


def test_collection_folders_move_and_delete_keeps_items(users):
    binder = run(folders.create_folder, 1, folders.COLLECTION, "Binder")
    a = run(col.add_card, 1, BOLT_CARD)
    b = run(col.add_card, 1, DELVER_CARD)
    assert run(col.move_entries, 1, [a.id, b.id, a.id], binder.id) == 2
    assert {e.folder_id for e in run(col.list_entries, 1)} == {binder.id}
    assert run(folders.list_folders, 1, folders.COLLECTION)[0].item_count == 2
    run(col.update_entry, 1, a.id, quantity=1, foil=False, is_proxy=False, price_paid_cents=None, notes="",
        folder_id=None)
    assert run(col.get_entry, 1, a.id).folder_id is None
    run(col.update_entry, 1, b.id, quantity=2, foil=False, is_proxy=False, price_paid_cents=None, notes="")
    assert run(col.get_entry, 1, b.id).folder_id == binder.id  # sem folder_id: continua na pasta
    run(folders.delete_folder, 1, binder.id)
    entries = run(col.list_entries, 1)
    assert len(entries) == 2 and {e.folder_id for e in entries} == {None}  # itens continuam, sem pasta


def test_collection_cannot_use_foreign_or_deck_folder(users):
    theirs = run(folders.create_folder, 2, folders.COLLECTION, "Do amigo")
    deck_folder = run(folders.create_folder, 1, folders.DECKS, "Decks")
    entry = run(col.add_card, 1, BOLT_CARD)
    for folder_id in (theirs.id, deck_folder.id, 999):
        with pytest.raises(FolderError, match="não encontrada"):
            run(col.move_entries, 1, [entry.id], folder_id)


def test_bulk_delete_entries_is_all_or_nothing(users):
    a = run(col.add_card, 1, BOLT_CARD)
    b = run(col.add_card, 1, DELVER_CARD)
    other = run(col.add_card, 2, BOLT_CARD)
    with pytest.raises(col.CollectionError):
        run(col.delete_entries, 1, [a.id, other.id])
    assert len(run(col.list_entries, 1)) == 2
    assert run(col.delete_entries, 1, [a.id, b.id]) == 2
    assert run(col.list_entries, 1) == [] and len(run(col.list_entries, 2)) == 1


# ---------- decks ----------
def test_create_update_deck(users):
    deck = run(decks.create_deck, 1, "  Burn   Modern ", format="modern", notes=" rápido ")
    assert (deck.name, deck.format, deck.notes, deck.visibility, deck.folder_id) == (
        "Burn Modern", "modern", "rápido", "private", None)
    assert deck.colors == () and deck.card_count == 0
    folder = run(folders.create_folder, 1, folders.DECKS, "Competitivo")
    updated = run(decks.update_deck, 1, deck.id, name="Burn", format="legacy", notes="", folder_id=folder.id,
                  visibility="friends")
    assert (updated.name, updated.format, updated.folder_id, updated.visibility) == (
        "Burn", "legacy", folder.id, "friends")
    with pytest.raises(DeckError, match="nome"):
        run(decks.create_deck, 1, "  ")
    with pytest.raises(DeckError, match="Visibilidade"):
        run(decks.update_deck, 1, deck.id, name="x", visibility="public")


def test_deck_colors_from_cards(users):
    deck = run(decks.create_deck, 1, "Boros")
    run(decks.add_card, 1, deck.id, LAND_CARD, quantity=4)
    assert run(decks.get_deck, 1, deck.id).colors == ("C",)  # só incolor
    run(decks.add_card, 1, deck.id, BOLT_CARD, quantity=4)
    run(decks.add_card, 1, deck.id, GOLD_CARD, quantity=2, section="sideboard")
    run(decks.add_card, 1, deck.id, BOLT_CARD, quantity=1)  # soma na mesma linha
    deck = run(decks.get_deck, 1, deck.id)
    assert deck.colors == ("W", "R") and deck.card_count == 9  # sideboard não conta
    cards = run(decks.list_cards, 1, deck.id)
    assert [(c.card_name, c.quantity, c.section) for c in cards] == [
        ("Lightning Bolt", 5, "main"), ("Wastes", 4, "main"), ("Lightning Helix", 2, "sideboard")]
    with pytest.raises(DeckError, match="Seção"):
        run(decks.add_card, 1, deck.id, BOLT_CARD, section="banco")


def test_list_move_and_delete_many(users):
    a = run(decks.create_deck, 1, "A")
    b = run(decks.create_deck, 1, "B")
    c = run(decks.create_deck, 1, "C")
    run(decks.create_deck, 2, "Do amigo")
    assert [d.name for d in run(decks.list_decks, 1)] == ["C", "B", "A"]  # mais recente primeiro
    folder = run(folders.create_folder, 1, folders.DECKS, "Casual")
    assert run(decks.move_decks, 1, [a.id, b.id], folder.id) == 2
    assert run(folders.list_folders, 1, folders.DECKS)[0].item_count == 2
    with pytest.raises(FolderError):
        run(decks.move_decks, 1, [c.id], run(folders.create_folder, 1, folders.COLLECTION, "Errada").id)
    run(decks.add_card, 1, a.id, BOLT_CARD)
    run(decks.delete_decks, 1, [a.id, c.id])
    assert [d.name for d in run(decks.list_decks, 1)] == ["B"]
    assert len(run(decks.list_decks, 2)) == 1


def test_decks_isolated_between_users(users):
    mine = run(decks.create_deck, 1, "Meu")
    for fn, args in ((decks.get_deck, ()), (decks.list_cards, ())):
        with pytest.raises(DeckError, match="não encontrado"):
            run(fn, 2, mine.id, *args)
    with pytest.raises(DeckError):
        run(decks.update_deck, 2, mine.id, name="roubado")
    with pytest.raises(DeckError):
        run(decks.delete_decks, 2, [mine.id])
    with pytest.raises(DeckError):
        run(decks.add_card, 2, mine.id, BOLT_CARD)
    theirs = run(decks.create_deck, 2, "Dele")
    with pytest.raises(DeckError):
        run(decks.delete_decks, 1, [mine.id, theirs.id])  # tudo ou nada
    assert len(run(decks.list_decks, 1)) == 1


def test_cover_card_upload_and_clear(users):
    deck = run(decks.create_deck, 1, "Delver")
    card = run(decks.add_card, 1, deck.id, DELVER_CARD)
    run(decks.add_card, 1, deck.id, LAND_CARD)
    deck, old = run(decks.set_cover_card, 1, deck.id, card.id)
    assert old is None and deck.cover_art_url == "https://img/d-art.jpg" and deck.cover_card_name.startswith("Delver")
    land = [c for c in run(decks.list_cards, 1, deck.id) if c.card_name == "Wastes"][0]
    deck, _ = run(decks.set_cover_card, 1, deck.id, land.id)
    assert deck.cover_art_url == "https://img/w-n.jpg"  # sem art_crop: usa a imagem normal
    deck, old = run(decks.set_cover_image, 1, deck.id, "a" * 32 + ".png")
    assert old is None and deck.cover_filename == "a" * 32 + ".png"
    assert run(decks.cover_image_in_use, "a" * 32 + ".png")
    deck, old = run(decks.set_cover_card, 1, deck.id, card.id)  # carta de novo: imagem enviada sai
    assert old == "a" * 32 + ".png" and deck.cover_filename is None
    assert not run(decks.cover_image_in_use, "a" * 32 + ".png")
    deck, _ = run(decks.clear_cover, 1, deck.id)
    assert deck.cover_art_url is None and deck.cover_card_name == ""
    other = run(decks.create_deck, 1, "Outro")
    with pytest.raises(DeckError, match="não está neste deck"):
        run(decks.set_cover_card, 1, other.id, card.id)


def test_cover_visibility(users):
    deck = run(decks.create_deck, 1, "Privado")
    run(decks.set_cover_image, 1, deck.id, "b" * 32 + ".jpg")
    assert run(decks.can_view_cover, 1, "b" * 32 + ".jpg")
    assert not run(decks.can_view_cover, 2, "b" * 32 + ".jpg")
    run(decks.update_deck, 1, deck.id, name="Privado", visibility="friends")
    assert run(decks.can_view_cover, 2, "b" * 32 + ".jpg")
    assert not run(decks.can_view_cover, 1, "naoexiste.png")


def test_delete_decks_returns_cover_files(users):
    a = run(decks.create_deck, 1, "A")
    b = run(decks.create_deck, 1, "B")
    run(decks.set_cover_image, 1, a.id, "c" * 32 + ".png")
    assert run(decks.delete_decks, 1, [a.id, b.id]) == ["c" * 32 + ".png"]


def test_deleting_user_removes_everything(users):
    from mtg_collection.database.tables import UserRow
    deck = run(decks.create_deck, 1, "Deck")
    run(decks.add_card, 1, deck.id, BOLT_CARD)
    run(folders.create_folder, 1, folders.DECKS, "Pasta")
    with database.session() as s:
        s.delete(s.get(UserRow, 1))
    assert run(decks.list_decks, 2) == [] and run(folders.list_folders, 1, folders.DECKS) == []
