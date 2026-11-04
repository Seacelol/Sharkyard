import asyncio

from nicegui.elements.upload_files import SmallFileUpload
from nicegui.testing import User

from mtg_collection import config, database
from mtg_collection.services import decks, folders
from mtg_collection.services.scryfall import to_card
from tests.conftest import FakeScryfall, create_account
from tests.sample_cards import BOLT, DELVER, GOLD, LAND

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def run(fn, *args, **kwargs):
    with database.session() as s:
        return fn(s, *args, **kwargs)


def my_decks(user_id: int = 1):
    return run(decks.list_decks, user_id)


async def upload_cover(user: User, data: bytes = PNG) -> None:
    up = user.find(marker="deck-cover-upload").elements.pop()
    await up.handle_uploads([SmallFileUpload(name="capa.png", content_type="image/png", _data=data)])
    await asyncio.sleep(0.05)


async def test_empty_state_and_create(user: User, fake_api: FakeScryfall):
    await user.open("/decks")
    await user.should_see("Você ainda não tem decks.")
    user.find(marker="new-deck").click()
    user.find(marker="deck-save").click()
    await user.should_see("Dê um nome para o deck.")
    user.find(marker="deck-name").type("Burn")
    user.find(marker="deck-format").elements.pop().value = "modern"
    user.find(marker="deck-notes").type("lista do torneio")
    user.find(marker="deck-save").click()
    await user.should_see("Deck \"Burn\" criado.")
    await user.should_see("Modern · 0 cartas")
    await user.should_see("1 deck")
    [deck] = my_decks()
    assert (deck.name, deck.format, deck.notes, deck.visibility) == ("Burn", "modern", "lista do torneio", "private")


async def test_colors_and_card_count_on_tile(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Boros", format="commander")
    for card, qty in ((BOLT, 4), (GOLD, 2), (LAND, 1)):
        run(decks.add_card, 1, deck.id, to_card(card), quantity=qty)
    await user.open("/decks")
    await user.should_see("Commander · 7 cartas")
    colors = user.find(marker="deck-colors").elements.pop()
    assert "card-symbols/W.svg" in colors.content and "card-symbols/R.svg" in colors.content
    assert colors.content.index("W.svg") < colors.content.index("R.svg")  # ordem WUBRG


async def test_edit_with_cover_from_card(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Delver")
    run(decks.add_card, 1, deck.id, to_card(DELVER), quantity=4)
    await user.open("/decks")
    user.find(marker=f"edit-deck-{deck.id}").click()
    user.find(marker="deck-name").clear().type("Delver Pauper")
    user.find(marker="deck-format").elements.pop().value = "pauper"
    user.find(marker="deck-visible").elements.pop().value = True
    user.find(marker="deck-cover-mode").elements.pop().value = "card"
    card_select = user.find(marker="deck-cover-card").elements.pop()
    card_select.value = next(iter(card_select.options))
    assert user.find(marker="deck-preview").elements.pop().source == "https://img/d-art.jpg"
    user.find(marker="deck-save").click()
    await user.should_see("Deck salvo.")
    await user.should_see("Delver Pauper")
    [saved] = my_decks()
    assert (saved.format, saved.visibility, saved.cover_art_url) == ("pauper", "friends", "https://img/d-art.jpg")
    img = user.find(marker="deck-cover-img").elements.pop()
    assert "https://img/d-art.jpg" in img.props["src"]


async def test_cover_from_card_needs_cards(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Vazio")
    await user.open("/decks")
    user.find(marker=f"edit-deck-{deck.id}").click()
    user.find(marker="deck-cover-mode").elements.pop().value = "card"
    await user.should_see("Adicione cartas ao deck para escolher uma delas como capa.")
    user.find(marker="deck-save").click()
    await user.should_see("Escolha a carta da capa.")


async def test_upload_cover_then_replace_and_remove(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Arte")
    await user.open("/decks")
    user.find(marker=f"edit-deck-{deck.id}").click()
    user.find(marker="deck-cover-mode").elements.pop().value = "upload"
    user.find(marker="deck-save").click()
    await user.should_see("Escolha a imagem da capa.")
    await upload_cover(user)
    await user.should_see("capa.png: pronta para salvar")
    user.find(marker="deck-save").click()
    await user.should_see("Deck salvo.")
    first = my_decks()[0].cover_filename
    assert (config.CUSTOM_IMAGES_DIR / first).read_bytes() == PNG
    response = await user.http_client.get(f"/deck-cover/{first}")
    assert response.status_code == 200 and response.content == PNG

    user.find(marker=f"edit-deck-{deck.id}").click()
    assert user.find(marker="deck-cover-mode").elements.pop().value == "upload"
    await upload_cover(user, PNG + b"novo")
    user.find(marker="deck-save").click()
    await user.should_see("Deck salvo.")
    second = my_decks()[0].cover_filename
    assert second != first and not (config.CUSTOM_IMAGES_DIR / first).exists()  # antiga apagada

    user.find(marker=f"edit-deck-{deck.id}").click()
    user.find(marker="deck-cover-mode").elements.pop().value = "none"
    user.find(marker="deck-save").click()
    await user.should_see("Deck salvo.")
    assert my_decks()[0].cover_filename is None and not (config.CUSTOM_IMAGES_DIR / second).exists()


async def test_create_with_upload_cover(user: User, fake_api: FakeScryfall):
    await user.open("/decks")
    user.find(marker="new-deck").click()
    user.find(marker="deck-name").type("Com capa")
    user.find(marker="deck-cover-mode").elements.pop().value = "upload"
    await upload_cover(user)
    user.find(marker="deck-save").click()
    await user.should_see("Deck \"Com capa\" criado.")
    assert my_decks()[0].cover_filename.endswith(".png")


async def test_delete_from_dialog(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Velho")
    await user.open("/decks")
    user.find(marker=f"edit-deck-{deck.id}").click()
    user.find(marker="deck-delete").click()
    await user.should_see("As cartas da sua coleção não são afetadas.")
    user.find(marker="confirm-ok").click()
    await user.should_see("Deck \"Velho\" apagado.")
    await user.should_see("Você ainda não tem decks.")
    assert my_decks() == []


async def test_folders_and_new_deck_goes_to_open_folder(user: User, fake_api: FakeScryfall):
    run(decks.create_deck, 1, "Solto")
    await user.open("/decks")
    user.find(marker="folder-new").click()
    user.find(marker="ask-text").type("Competitivo")
    user.find(marker="ask-ok").click()
    await user.should_see("Pasta \"Competitivo\" criada.")
    await user.should_see("Esta pasta está vazia.")
    user.find(marker="new-deck").click()
    [folder] = run(folders.list_folders, 1, folders.DECKS)
    assert user.find(marker="deck-folder").elements.pop().value == folder.id  # já vem na pasta aberta
    user.find(marker="deck-name").type("Torneio")
    user.find(marker="deck-save").click()
    await user.should_see("Competitivo (1)")
    await user.should_see("Torneio")
    await user.should_not_see("Solto")
    user.find(marker="folder-chip-all").click()
    await user.should_see("Solto")
    await user.should_see("Todos (2)")


async def test_manage_move_and_delete_many(user: User, fake_api: FakeScryfall):
    a = run(decks.create_deck, 1, "A")
    b = run(decks.create_deck, 1, "B")
    c = run(decks.create_deck, 1, "C")
    folder = run(folders.create_folder, 1, folders.DECKS, "Casual")
    run(decks.set_cover_image, 1, c.id, "d" * 32 + ".png")
    (config.CUSTOM_IMAGES_DIR).mkdir(parents=True, exist_ok=True)
    (config.CUSTOM_IMAGES_DIR / ("d" * 32 + ".png")).write_bytes(PNG)
    await user.open("/decks")
    user.find(marker="start-selecting").click()
    await user.should_see("0 selecionados")
    await user.should_not_see(marker=f"edit-deck-{a.id}")  # no modo gerenciar, clicar seleciona
    user.find(marker=f"deck-{a.id}").click()
    user.find(marker=f"select-deck-{b.id}").elements.pop().value = True
    await user.should_see("2 selecionados")
    user.find(marker="move-to").elements.pop().value = folder.id
    await user.should_see("2 decks movidos para \"Casual\".")
    assert {d.name: d.folder_id for d in my_decks()} == {"A": folder.id, "B": folder.id, "C": None}
    user.find(marker="select-all").click()
    await user.should_see("3 selecionados")
    user.find(marker="delete-selected").click()
    await user.should_see("Apagar 3 decks?")
    user.find(marker="confirm-ok").click()
    await user.should_see("3 decks apagados.")
    assert my_decks() == []
    assert not (config.CUSTOM_IMAGES_DIR / ("d" * 32 + ".png")).exists()  # capa apagada junto
    user.find(marker="selection-done").click()
    await user.should_see(marker="start-selecting")


async def test_only_own_decks_and_cover_privacy(user: User, fake_api: FakeScryfall):
    create_account("amigo")
    theirs = run(decks.create_deck, 2, "Deck do amigo")
    run(decks.set_cover_image, 2, theirs.id, "e" * 32 + ".png")
    config.CUSTOM_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    (config.CUSTOM_IMAGES_DIR / ("e" * 32 + ".png")).write_bytes(PNG)
    await user.open("/decks")
    await user.should_not_see("Deck do amigo")
    assert (await user.http_client.get(f"/deck-cover/{'e' * 32}.png")).status_code == 404  # privado
    await user.open(f"/deck/{theirs.id}")
    await user.should_see("Deck não encontrado.")
    run(decks.update_deck, 2, theirs.id, name="Deck do amigo", visibility="friends")
    assert (await user.http_client.get(f"/deck-cover/{'e' * 32}.png")).status_code == 200  # visível p/ amigos
    await user.open("/decks")
    await user.should_not_see("Deck do amigo")  # "Meus decks" continua só com os meus
    await user.open(f"/deck/{theirs.id}")
    await user.should_see(marker="deck-owner")  # visível: abre só para ver
    await user.should_not_see(marker="edit-deck")

