import asyncio

from nicegui.testing import User

from mtg_collection import database
from mtg_collection.services import decks
from mtg_collection.services.scryfall import to_card
from tests.conftest import FakeScryfall, create_account
from tests.sample_cards import BOLT, DELVER, LAND


def run(fn, *args, **kwargs):
    with database.session() as s:
        return fn(s, *args, **kwargs)


def make_deck(owner=1, **kwargs):
    deck = run(decks.create_deck, owner, "Burn", format="modern", **kwargs)
    for card, qty in ((BOLT, 4), (DELVER, 2), (LAND, 1)):
        run(decks.add_card, owner, deck.id, to_card(card), qty)
    return deck


async def test_owner_opens_view_then_edits(user: User, fake_api: FakeScryfall):
    deck = make_deck()
    await user.open(f"/deck/{deck.id}")
    await user.should_see(marker="deck-name")
    await user.should_see("Mágicas instantâneas")
    await user.should_not_see("Adicionar cartas")  # sem painel de adicionar
    await user.should_not_see(marker="line-plus-1")  # nem + e - nas cartas
    user.find(marker="open-builder").click()
    await user.should_see("Adicionar cartas")
    await user.should_see(marker="line-plus-1")
    user.find(marker="back-to-view").click()
    await user.should_see(marker="open-builder")


async def test_view_modes_and_memory(user: User, fake_api: FakeScryfall):
    deck = make_deck()
    await user.open(f"/deck/{deck.id}")
    await user.should_see(marker="mode-list")
    toggle = user.find(marker="view-mode").elements.pop()
    for mode in ("compact", "images", "stacks"):
        toggle.set_value(mode)
        await user.should_see(marker=f"mode-{mode}")
        await user.should_see(marker="group-instant")
    assert len(user.find(marker="view-card").elements) == 3
    await user.should_see("4x")  # quantidade em cima da imagem
    await user.open(f"/deck/{deck.id}")
    await user.should_see(marker="mode-stacks")  # lembra o último modo
    user.find(marker="view-card-1").click()  # imagem abre a página da carta
    await user.should_see("Legalidade")


async def test_edit_opens_version_being_viewed(user: User, fake_api: FakeScryfall):
    deck = make_deck()
    second = run(decks.create_version, 1, deck.id, "Sem Delver")
    run(decks.select_version, 1, deck.id, deck.version_id)  # atual volta a ser a original
    await user.open(f"/deck/{deck.id}")
    user.find(marker="version-select").elements.pop().set_value(second.version_id)
    await asyncio.sleep(0.1)
    assert run(decks.get_deck, 1, deck.id).version_id == deck.version_id  # só ver não muda a atual
    user.find(marker="open-builder").click()
    await user.should_see("Adicionar cartas")
    assert run(decks.get_deck, 1, deck.id).version_id == second.version_id


async def test_friend_cannot_open_builder(user: User, fake_api: FakeScryfall):
    create_account("amigo")
    deck = make_deck(owner=2, visibility="friends")
    await user.open(f"/deck/{deck.id}/edit")
    await user.should_see(marker="deck-owner")  # volta para a página de ver
    await user.should_not_see(marker="open-builder")
    await user.should_not_see("Adicionar cartas")


async def test_cards_have_big_preview_on_hover(user: User, fake_api: FakeScryfall):
    deck = make_deck()
    await user.open(f"/deck/{deck.id}")
    toggle = user.find(marker="view-mode").elements.pop()
    for mode, marker in (("list", "view-line"), ("compact", "view-line"), ("images", "view-card"),
                         ("stacks", "view-card")):
        toggle.set_value(mode)
        await user.should_see(marker=f"mode-{mode}")
        previews = [e.props.get("data-preview") for e in user.find(marker=marker).elements]
        assert previews and all(previews), mode  # cada carta com imagem leva o endereço da imagem grande
