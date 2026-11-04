import asyncio

from nicegui.testing import User

from mtg_collection import database
from mtg_collection.services import collection as col
from tests.conftest import FakeScryfall, create_account


def entries(user_id: int = 1):
    with database.session() as s:
        return col.list_entries(s, user_id)


async def add_via_suggestion(user: User, text: str, card_id: str) -> None:
    user.find(marker="card-search").clear().type(text)
    await asyncio.sleep(0.2)
    user.find(marker=f"suggestion-{card_id}").trigger("mousedown.prevent")
    await asyncio.sleep(0.05)


async def test_empty_collection(user: User, fake_api: FakeScryfall):
    await user.open("/collection")
    await user.should_see("Sua coleção está vazia.")
    await user.should_see("0 cartas (0 originais · 0 proxies) · 0 diferentes · Total pago R$ 0,00")


async def test_add_from_suggestions_merges_quantity(user: User, fake_api: FakeScryfall):
    await user.open("/collection")
    await add_via_suggestion(user, "bo", "1")
    await user.should_see("Lightning Bolt (M10) adicionada. Agora você tem 1 nesse item.")
    await user.should_see("1 carta (1 original · 0 proxies) · 1 diferente · Total pago R$ 0,00")
    await add_via_suggestion(user, "bo", "1")
    await user.should_see("Agora você tem 2 nesse item.")
    await user.should_see("2x")
    assert [(e.card_name, e.quantity) for e in entries()] == [("Lightning Bolt", 2)]


async def test_enter_adds_only_exact_name(user: User, fake_api: FakeScryfall):
    await user.open("/collection")
    user.find(marker="card-search").type("lightn").trigger("keydown.enter")
    await user.should_see("Escolha a carta na lista de sugestões.")
    assert entries() == []
    user.find(marker="card-search").clear().type("lightning bolt").trigger("keydown.enter")
    await user.should_see("Lightning Bolt (M10) adicionada.")
    assert [e.card_name for e in entries()] == ["Lightning Bolt"]


async def test_edit_entry(user: User, fake_api: FakeScryfall):
    with database.session() as s:
        entry = col.add_card(s, 1, fake_api.cards["1"])
    await user.open("/collection")
    user.find(marker=f"edit-entry-{entry.id}").click()
    await asyncio.sleep(0.1)  # edições carregam com o diálogo aberto
    printing = user.find(marker="entry-printing").elements.pop()
    assert set(printing.options) == {"1", "1b"}
    printing.value = "1b"
    user.find(marker="entry-quantity").elements.pop().value = 3
    user.find(marker="entry-proxy").elements.pop().value = True
    user.find(marker="entry-foil").elements.pop().value = True
    user.find(marker="entry-price").elements.pop().value = "12,50"
    user.find(marker="entry-notes").elements.pop().value = "da caixa de trocas"
    user.find(marker="entry-save").click()
    await user.should_see("Item atualizado.")
    await user.should_see("Double Masters (2XM) #129")
    await user.should_see("3x")
    await user.should_see("R$ 12,50/un")
    await user.should_see(marker="proxy-badge")
    await user.should_see("3 cartas (0 originais · 3 proxies) · 1 diferente · Total pago R$ 37,50")
    [saved] = entries()
    assert (saved.scryfall_id, saved.quantity, saved.foil, saved.is_proxy) == ("1b", 3, True, True)
    assert saved.price_paid_cents == 1250 and saved.notes == "da caixa de trocas"


async def test_edit_validation(user: User, fake_api: FakeScryfall):
    with database.session() as s:
        entry = col.add_card(s, 1, fake_api.cards["1"])
    await user.open("/collection")
    user.find(marker=f"edit-entry-{entry.id}").click()
    await asyncio.sleep(0.1)
    user.find(marker="entry-price").elements.pop().value = "doze"
    user.find(marker="entry-save").click()
    await user.should_see("Preço inválido. Use algo como 12,50.")
    user.find(marker="entry-price").elements.pop().value = ""
    user.find(marker="entry-quantity").elements.pop().value = 0
    user.find(marker="entry-save").click()
    await user.should_see("A quantidade deve ser de 1 a 9999.")
    assert entries()[0].quantity == 1


async def test_delete_entry(user: User, fake_api: FakeScryfall):
    with database.session() as s:
        entry = col.add_card(s, 1, fake_api.cards["1"])
    await user.open("/collection")
    user.find(marker=f"edit-entry-{entry.id}").click()
    await asyncio.sleep(0.1)
    user.find(marker="entry-delete").click()
    await asyncio.sleep(0.05)
    user.find(marker="confirm-ok").click()
    await user.should_see("Item apagado.")
    await user.should_see("Sua coleção está vazia.")
    assert entries() == []


async def test_filters(user: User, fake_api: FakeScryfall):
    with database.session() as s:
        col.add_card(s, 1, fake_api.cards["1"])
        delver = col.add_card(s, 1, fake_api.cards["2"])
        col.update_entry(s, 1, delver.id, quantity=1, foil=False, is_proxy=True, price_paid_cents=None,
                         notes="emprestada")
    await user.open("/collection")
    assert len(user.find(marker="entry").elements) == 2
    user.find(marker="collection-filter").type("emprest")
    await asyncio.sleep(0.05)
    assert len(user.find(marker="entry").elements) == 1
    user.find(marker="collection-filter").clear()
    user.find(marker="collection-proxy-filter").elements.pop().value = "real"
    await asyncio.sleep(0.05)
    assert len(user.find(marker="entry").elements) == 1
    await user.should_see("Lightning Bolt")
    user.find(marker="collection-proxy-filter").elements.pop().value = "proxy"
    await asyncio.sleep(0.05)
    await user.should_see("Delver of Secrets // Insectile Aberration")
    await user.should_not_see("Lightning Bolt")
    user.find(marker="collection-filter").type("zzz")
    await user.should_see("Nenhum item com esse filtro.")


async def test_only_own_collection_is_visible(user: User, fake_api: FakeScryfall):
    create_account("amigo")
    with database.session() as s:
        col.add_card(s, 2, fake_api.cards["2"])
    await user.open("/collection")
    await user.should_see("Sua coleção está vazia.")
    await user.should_not_see("Delver of Secrets")


def folders_of(user_id: int = 1):
    from mtg_collection.services import folders
    with database.session() as s:
        return folders.list_folders(s, user_id, folders.COLLECTION)


async def create_folder_ui(user: User, name: str) -> None:
    user.find(marker="folder-new").click()
    user.find(marker="ask-text").type(name)
    user.find(marker="ask-ok").click()
    await user.should_see(f"Pasta \"{name}\" criada.")


async def test_folder_create_filter_and_add_into_it(user: User, fake_api: FakeScryfall):
    with database.session() as s:
        col.add_card(s, 1, fake_api.cards["1"])
    await user.open("/collection")
    await user.should_see("Todas (1)")
    await user.should_see("Sem pasta (1)")
    await create_folder_ui(user, "Binder")
    [binder] = folders_of()
    # pasta criada fica aberta: vazia, e a carta adicionada pela busca entra nela
    await user.should_see("Esta pasta está vazia.")
    await add_via_suggestion(user, "bo", "1")
    await user.should_see("Binder (1)")
    assert sorted((e.folder_id or 0) for e in entries()) == [0, binder.id]  # não somou no lote sem pasta
    user.find(marker="folder-chip-none").click()
    await user.should_see("1 carta (1 original")
    user.find(marker="folder-chip-all").click()
    await user.should_see("2 cartas (2 originais")


async def test_folder_rules_rename_and_delete(user: User, fake_api: FakeScryfall):
    await user.open("/collection")
    await create_folder_ui(user, "Trocas")
    user.find(marker="folder-new").click()
    user.find(marker="ask-text").type("TROCAS")
    user.find(marker="ask-ok").click()
    await user.should_see("Já existe uma pasta com esse nome.")
    user.find(marker="ask-text").clear().type("Vendas")
    user.find(marker="ask-ok").click()
    await user.should_see("Pasta \"Vendas\" criada.")
    user.find(marker="folder-rename").click()
    user.find(marker="ask-text").clear().type("Vendas 2026")
    user.find(marker="ask-ok").click()
    await user.should_see("Vendas 2026 (0)")
    user.find(marker="folder-delete").click()
    await user.should_see("voltam para \"Sem pasta\"")
    user.find(marker="confirm-ok").click()
    await user.should_see("Pasta \"Vendas 2026\" apagada.")
    assert [f.name for f in folders_of()] == ["Trocas"]


async def test_folder_in_entry_dialog(user: User, fake_api: FakeScryfall):
    from mtg_collection.services import folders
    with database.session() as s:
        entry = col.add_card(s, 1, fake_api.cards["1"])
        binder = folders.create_folder(s, 1, folders.COLLECTION, "Binder")
    await user.open("/collection")
    user.find(marker=f"edit-entry-{entry.id}").click()
    await asyncio.sleep(0.1)
    folder = user.find(marker="entry-folder").elements.pop()
    assert folder.options == {"none": "Sem pasta", binder.id: "Binder"} and folder.value == "none"
    folder.value = binder.id
    user.find(marker="entry-save").click()
    await user.should_see("Binder (1)")
    assert entries()[0].folder_id == binder.id


async def test_selection_move_and_remove(user: User, fake_api: FakeScryfall):
    from mtg_collection.services import folders
    with database.session() as s:
        a = col.add_card(s, 1, fake_api.cards["1"])
        b = col.add_card(s, 1, fake_api.cards["2"])
        c = col.add_card(s, 1, fake_api.cards["1b"])
        binder = folders.create_folder(s, 1, folders.COLLECTION, "Binder")
    await user.open("/collection")
    await user.should_not_see(marker="selection-bar")
    user.find(marker="start-selecting").click()
    await user.should_see("0 selecionados")
    user.find(marker=f"select-entry-{a.id}").elements.pop().value = True
    user.find(marker=f"select-entry-{b.id}").elements.pop().value = True
    await user.should_see("2 selecionados")
    user.find(marker="move-to").elements.pop().value = binder.id
    await user.should_see("2 itens movidos para \"Binder\".")
    assert {e.id: e.folder_id for e in entries()} == {a.id: binder.id, b.id: binder.id, c.id: None}
    await user.should_see("0 selecionados")
    user.find(marker="select-all").click()
    await user.should_see("3 selecionados")
    user.find(marker="delete-selected").click()
    await user.should_see("São 3 cartas no total.")
    user.find(marker="confirm-ok").click()
    await user.should_see("3 itens removidos.")
    assert entries() == []
    user.find(marker="selection-done").click()
    await user.should_not_see(marker="selection-bar")


async def test_select_all_respects_folder_and_filters(user: User, fake_api: FakeScryfall):
    from mtg_collection.services import folders
    with database.session() as s:
        binder = folders.create_folder(s, 1, folders.COLLECTION, "Binder")
        col.add_card(s, 1, fake_api.cards["1"], folder_id=binder.id)
        col.add_card(s, 1, fake_api.cards["2"])
    await user.open("/collection")
    user.find(marker=f"folder-chip-{binder.id}").click()
    user.find(marker="start-selecting").click()
    user.find(marker="select-all").click()
    await user.should_see("1 selecionado")
    user.find(marker="delete-selected").click()
    user.find(marker="confirm-ok").click()
    await user.should_see("1 item removido.")
    assert [e.card_name for e in entries()] == ["Delver of Secrets // Insectile Aberration"]
