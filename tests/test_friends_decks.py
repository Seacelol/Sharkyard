from nicegui.testing import User

from mtg_collection import database
from mtg_collection.services import collection as col
from mtg_collection.services import decks
from mtg_collection.services.scryfall import to_card
from mtg_collection.ui.custom_images import save_image
from tests.conftest import FakeScryfall, create_account
from tests.sample_cards import BOLT, DELVER, LAND

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def run(fn, *args, **kwargs):
    with database.session() as s:
        return fn(s, *args, **kwargs)


def friend_deck(name="Burn do amigo", visibility="friends"):
    create_account("amigo", display_name="Amigo")
    deck = run(decks.create_deck, 2, name, format="modern", visibility=visibility)
    run(decks.add_card, 2, deck.id, to_card(BOLT), 4)
    run(decks.add_card, 2, deck.id, to_card(LAND), 20)
    return deck


async def test_list_filter_and_open(user: User, fake_api: FakeScryfall):
    deck = friend_deck()
    run(decks.create_deck, 2, "Privado do amigo")
    mine = run(decks.create_deck, 1, "Meu deck", visibility="friends")
    await user.open("/decks")
    user.find(marker="friends-decks").click()
    await user.should_see("Burn do amigo")
    await user.should_see("de Amigo")
    await user.should_not_see("Privado do amigo")
    await user.should_not_see("Meu deck")
    user.find(marker="friends-filter").type("xyz")
    await user.should_see("Nenhum deck com esse filtro.")
    user.find(marker="friends-filter").clear().type("modern")
    await user.should_see("Burn do amigo")
    user.find(marker=f"friend-deck-{deck.id}").click()
    await user.should_see(marker="deck-owner")
    await user.should_see("de Amigo · Modern")
    await user.should_see(marker="group-instant")
    await user.should_not_see(marker="conclude")
    assert mine.id


async def test_friend_chooses_version_without_changing_owner(user: User, fake_api: FakeScryfall):
    deck = friend_deck()
    run(decks.create_version, 2, deck.id, "Com Delver")
    run(decks.add_card, 2, deck.id, to_card(DELVER), 4)
    await user.open(f"/deck/{deck.id}")
    await user.should_see("28 cartas")
    select = user.find(marker="version-select").elements.pop()
    original = next(k for k, v in select.options.items() if v.startswith("Original"))
    select.value = original
    await user.should_see("24 cartas")
    assert run(decks.get_deck, 2, deck.id).version_name == "Com Delver"
    # estatísticas e o que falta na coleção de quem vê
    run(col.add_card, 1, to_card(BOLT), 4)
    user.find(marker="view-stats").click()
    await user.should_see(marker="stat-missing")
    texts = " ".join(e.text for e in user.find(marker="stat-missing").elements.pop().descendants()
                     if hasattr(e, "text"))
    assert "20" in texts  # faltam os 20 terrenos; os 4 Bolts já tem
    user.find(marker="export-deck").click()
    preview = user.find(marker="export-preview").elements.pop()
    assert preview.value == "4 Lightning Bolt\n20 Wastes\n"


async def test_private_deck_is_not_found(user: User, fake_api: FakeScryfall):
    deck = friend_deck(visibility="private")
    await user.open(f"/deck/{deck.id}")
    await user.should_see("Deck não encontrado.")


async def test_custom_print_image_visible_in_shared_deck(user: User, fake_api: FakeScryfall):
    deck = friend_deck()
    filename = save_image(PNG)
    custom = run(col.create_custom_print, 2, to_card(BOLT), "Alter", image_filename=filename)
    run(decks.add_card, 2, deck.id, col.as_card(custom, to_card(BOLT), f"/custom-image/{filename}"))
    await user.open(f"/deck/{deck.id}")
    await user.should_see(marker="badge-custom-print")
    assert (await user.http_client.get(f"/custom-image/{filename}")).status_code == 200
    run(decks.update_deck, 2, deck.id, name="Burn do amigo", visibility="private")
    assert (await user.http_client.get(f"/custom-image/{filename}")).status_code == 404
