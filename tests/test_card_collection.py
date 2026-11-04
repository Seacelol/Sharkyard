import asyncio

import httpx
from nicegui import ui
from nicegui.elements.upload_files import SmallFileUpload
from nicegui.testing import User

from mtg_collection import config, database
from mtg_collection.services import collection as col
from tests.conftest import FakeScryfall, create_account

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def entries(user_id: int = 1):
    with database.session() as s:
        return col.list_entries(s, user_id)


def customs(user_id: int = 1, oracle_id: str = "o-bolt"):
    with database.session() as s:
        return col.list_custom_prints(s, user_id, oracle_id)


async def open_card(user: User, card_id: str) -> None:
    await user.open(f"/card/{card_id}")
    await asyncio.sleep(0.1)


async def upload(user: User, data: bytes, name: str = "arte.png") -> None:
    up = user.find(marker="custom-upload").elements.pop()
    await up.handle_uploads([SmallFileUpload(name=name, content_type="image/png", _data=data)])
    await asyncio.sleep(0.05)


async def test_add_current_version_and_merge(user: User, fake_api: FakeScryfall):
    await open_card(user, "1")
    await user.should_see("Você ainda não tem esta carta.")
    user.find(marker="add-to-collection").click()
    await user.should_see("Adicionada à coleção. Agora você tem 1 nesse item.")
    await user.should_see("Você tem 1")
    user.find(marker="add-to-collection").click()
    await user.should_see("Você tem 2")
    user.find(marker="print-1b").click()  # outra edição, mesma página
    user.find(marker="add-to-collection").click()
    await user.should_see("Você tem 3")
    assert sorted((e.scryfall_id, e.quantity) for e in entries()) == [("1", 2), ("1b", 1)]


async def test_owned_list_shows_proxies_and_edits(user: User, fake_api: FakeScryfall):
    with database.session() as s:
        e = col.add_card(s, 1, fake_api.cards["1"], quantity=2)
        col.update_entry(s, 1, e.id, quantity=2, foil=False, is_proxy=True, price_paid_cents=None, notes="")
    await open_card(user, "1")
    await user.should_see("Você tem 2 (2 proxies)")
    user.find(marker=f"edit-owned-{e.id}").click()
    await asyncio.sleep(0.1)
    user.find(marker="entry-proxy").elements.pop().value = False
    user.find(marker="entry-save").click()
    await user.should_see("Você tem 2")
    await user.should_not_see("proxies)")


async def test_collection_box_only_shows_own_cards(user: User, fake_api: FakeScryfall):
    create_account("amigo")
    with database.session() as s:
        col.add_card(s, 2, fake_api.cards["1"])
    await open_card(user, "1")
    await user.should_see("Você ainda não tem esta carta.")


async def test_create_custom_version_with_image(user: User, fake_api: FakeScryfall):
    await open_card(user, "1")
    user.find(marker="new-custom").click()
    user.find(marker="custom-save").click()
    await user.should_see("Dê um nome para a versão.")
    user.find(marker="custom-name").type("Alter do João")
    user.find(marker="custom-code").type("alt")
    user.find(marker="custom-artist").type("João")
    await upload(user, PNG)
    user.find(marker="custom-save").click()
    await user.should_see("Versão salva.")
    [custom] = customs()
    assert (custom.name, custom.code, custom.artist, custom.base_scryfall_id) == ("Alter do João", "ALT", "João", "1")
    assert (config.CUSTOM_IMAGES_DIR / custom.image_filename).read_bytes() == PNG
    # a página passa a mostrar a versão nova, com ícone próprio na coluna
    await user.should_see(marker=f"print-custom-{custom.id}")
    await user.should_see(marker="custom-badge")
    await user.should_see("★ Alter do João (ALT) · versão personalizada")
    image = user.find(marker="main-image").elements.pop()
    assert image.props["src"] == f"/custom-image/{custom.image_filename}"
    # e dá para colocar na coleção
    user.find(marker="add-to-collection").click()
    await user.should_see("Você tem 1")
    [entry] = entries()
    assert entry.custom_print_id == custom.id and entry.set_name == "Alter do João"


async def test_custom_version_rejects_non_image(user: User, fake_api: FakeScryfall):
    await open_card(user, "1")
    user.find(marker="new-custom").click()
    user.find(marker="custom-name").type("Teste")
    await upload(user, b"%PDF-1.4 nada de imagem", name="arquivo.png")
    await user.should_see("Envie uma imagem PNG, JPG ou WebP.")
    user.find(marker="custom-save").click()
    await user.should_see("Versão salva.")
    assert customs()[0].image_filename is None
    assert not config.CUSTOM_IMAGES_DIR.exists() or not any(config.CUSTOM_IMAGES_DIR.iterdir())


async def test_edit_and_delete_custom_version(user: User, fake_api: FakeScryfall):
    with database.session() as s:
        custom = col.create_custom_print(s, 1, fake_api.cards["1"], "Primeira")
    await open_card(user, f"custom-{custom.id}")  # abre direto pela URL da versão
    await user.should_see(marker="custom-badge")
    await user.should_see("Primeira")
    user.find(marker="add-to-collection").click()
    await user.should_see("Você tem 1")

    user.find(marker="edit-custom").click()
    user.find(marker="custom-name").clear().type("Renomeada")
    await upload(user, JPG, "a.jpg")
    user.find(marker="custom-save").click()
    await user.should_see("Versão salva.")
    first_file = customs()[0].image_filename
    assert customs()[0].name == "Renomeada" and first_file.endswith(".jpg")
    await user.should_see("Renomeada")
    assert entries()[0].set_name == "Renomeada"

    # trocar a imagem apaga o arquivo antigo
    user.find(marker="edit-custom").click()
    await upload(user, PNG)
    user.find(marker="custom-save").click()
    await user.should_see("Versão salva.")
    assert not (config.CUSTOM_IMAGES_DIR / first_file).exists()

    user.find(marker="edit-custom").click()
    user.find(marker="custom-delete").click()
    await user.should_see("1 cópia(s) na coleção serão apagadas.")
    user.find(marker="confirm-ok").click()
    await user.should_see("Versão apagada.")
    assert customs() == [] and entries() == []
    assert not any(config.CUSTOM_IMAGES_DIR.iterdir())
    await user.should_not_see(marker="custom-badge")  # voltou para a impressão oficial
    await user.should_see("Magic 2010 (M10)")


async def test_custom_version_of_other_user_is_hidden(user: User, fake_api: FakeScryfall):
    create_account("amigo")
    with database.session() as s:
        other = col.create_custom_print(s, 2, fake_api.cards["1"], "Do amigo", image_filename="a" * 32 + ".png")
    await open_card(user, "1")
    await user.should_not_see(marker=f"print-custom-{other.id}")
    await open_card(user, f"custom-{other.id}")
    await user.should_see("Não foi possível abrir a carta: Versão personalizada não encontrada.")


async def test_custom_image_route_only_for_owner(user: User, fake_api: FakeScryfall):
    from mtg_collection.ui.custom_images import save_image
    create_account("amigo")
    mine, theirs = save_image(PNG), save_image(JPG)
    with database.session() as s:
        col.create_custom_print(s, 1, fake_api.cards["1"], "Minha", image_filename=mine)
        col.create_custom_print(s, 2, fake_api.cards["1"], "Dele", image_filename=theirs)
    await open_card(user, "1")  # só para ter o cookie de sessão do usuário logado
    client: httpx.AsyncClient = user.http_client
    ok = await client.get(f"/custom-image/{mine}")
    assert ok.status_code == 200 and ok.content == PNG and ok.headers["content-type"] == "image/png"
    assert (await client.get(f"/custom-image/{theirs}")).status_code == 404
    assert (await client.get("/custom-image/..%2Fdata.db")).status_code == 404
    from mtg_collection.services import custom_cards
    card_image, their_card = save_image(PNG), save_image(PNG)
    with database.session() as s:
        custom_cards.create(s, 1, name="Minha carta", image_filename=card_image)
        custom_cards.create(s, 2, name="Dele", image_filename=their_card)
    assert (await client.get(f"/custom-image/{card_image}")).status_code == 200
    assert (await client.get(f"/custom-image/{their_card}")).status_code == 404


async def test_collection_page_links_custom_entry_to_its_page(user: User, fake_api: FakeScryfall):
    with database.session() as s:
        custom = col.create_custom_print(s, 1, fake_api.cards["1"], "Alter")
        col.add_card(s, 1, col.as_card(custom, fake_api.cards["1"]))
    await user.open("/collection")
    await user.should_see("Alter")
    link = user.find(kind=ui.link, content="Lightning Bolt").elements.pop()
    assert link.props["href"] == f"/card/custom-{custom.id}"
