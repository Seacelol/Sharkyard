from nicegui.testing import User

from mtg_collection import database
from mtg_collection.services import collection, decks
from mtg_collection.services.scryfall import to_card
from tests.conftest import FakeScryfall
from tests.sample_cards import BOLT

PT_BOLT = {**BOLT, "id": "1-pt", "lang": "pt", "printed_name": "Relâmpago", "printed_type_line": "Mágica Instantânea",
           "printed_text": "Relâmpago causa 3 pontos de dano a qualquer alvo."}


def test_printed_fields_only_for_other_languages():
    pt, en = to_card(PT_BOLT), to_card({**BOLT, "printed_name": "ignorado"})
    assert (pt.display_name, pt.faces[0].printed_type_line) == ("Relâmpago", "Mágica Instantânea")
    assert (en.display_name, en.printed_name) == ("Lightning Bolt", "")


async def test_card_page_in_portuguese(user: User, fake_api: FakeScryfall):
    fake_api.cards["1-pt"] = to_card(PT_BOLT)
    await user.open("/card/1-pt")
    await user.should_see("Relâmpago causa 3 pontos de dano a qualquer alvo.")
    assert user.find(marker="card-title").elements.pop().text == "Relâmpago"
    await user.should_see(marker="card-english-name")  # o nome em inglês fica embaixo
    await user.should_see("Mágica Instantânea")
    await user.should_see(marker="oracle-english")  # texto Oracle em inglês, recolhido


async def test_english_card_page_unchanged(user: User, fake_api: FakeScryfall):
    await user.open("/card/1")
    await user.should_see("Legalidade")
    assert user.find(marker="card-title").elements.pop().text == "Lightning Bolt"
    await user.should_not_see(marker="card-english-name")
    await user.should_not_see(marker="oracle-english")


async def test_portuguese_print_marked_in_collection_and_deck(user: User, fake_api: FakeScryfall):
    with database.session() as s:
        collection.add_card(s, 1, to_card(PT_BOLT), 2)
        collection.add_card(s, 1, to_card(BOLT), 1)  # outra impressão: lote separado
        deck = decks.create_deck(s, 1, "Burn")
        decks.add_card(s, 1, deck.id, to_card(PT_BOLT), 4)
    with database.session() as s:
        langs = sorted(e.lang for e in collection.list_entries(s, 1))
        assert langs == ["en", "pt"]
        assert decks.line_as_card(decks.list_cards(s, 1, deck.id)[0]).lang == "pt"
    await user.open("/collection")
    await user.should_see(marker="lang-badge")
    await user.open(f"/deck/{deck.id}")
    await user.should_see(marker="badge-lang")
