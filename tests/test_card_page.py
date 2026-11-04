import asyncio

from nicegui import ui
from nicegui.testing import User

from tests.conftest import FakeScryfall


async def open_card(user: User, card_id: str) -> None:
    await user.open(f"/card/{card_id}")
    await asyncio.sleep(0.1)  # versões e rulings carregam depois da página aparecer


async def test_card_info(user: User, fake_api: FakeScryfall):
    await open_card(user, "1")
    await user.should_see("Lightning Bolt")
    await user.should_see("Magic 2010 (M10)")
    await user.should_see("#146")
    await user.should_see("Comum")
    await user.should_see("17/07/2009")
    await user.should_see("Instant")
    await user.should_see("The sparkmage shrieked.")
    await user.should_see("Ilustração: Christopher Moeller")
    await user.should_see(kind=ui.html, content='class="mana-symbol"')
    await user.should_not_see("Virar carta")  # carta de uma face só


async def test_prices(user: User, fake_api: FakeScryfall):
    await open_card(user, "1")
    await user.should_see("US$ 1.25  ·  € -")
    await user.should_see("US$ 4.00  ·  € -")  # foil
    await user.should_see("0.03 tix")
    await user.should_see("Ver no Scryfall")


async def test_legalities(user: User, fake_api: FakeScryfall):
    await open_card(user, "1")
    for label in ("Legal", "Restrita", "Banida", "Não legal", "Modern", "Vintage", "Oathbreaker", "Newformat"):
        await user.should_see(label)


async def test_prints_column_and_load_more(user: User, fake_api: FakeScryfall):
    await open_card(user, "1")
    assert len(user.find(marker="print").elements) == 2
    await user.should_see("Magic 2010 (M10) · #146 · Comum · 2009 · US$ 1.25")  # legenda da versão aberta
    icon = user.find(marker="print-1b").elements.pop().default_slot.children[0]
    assert "rarity-uncommon" in icon.classes and "/set-icon/2xm.svg" in icon.style["--icon"]
    user.find(marker="more-prints").click()
    await asyncio.sleep(0.1)
    assert fake_api.prints_pages == [1, 2]
    assert len(user.find(marker="print").elements) == 3
    await user.should_not_see(marker="more-prints")


async def test_hover_swaps_image_in_browser(user: User, fake_api: FakeScryfall):
    await open_card(user, "1")
    image_id = user.find(marker="main-image").elements.pop().id
    reprint = user.find(marker="print-1b").elements.pop()
    hover = [listener for listener in reprint._event_listeners.values() if listener.type == "mouseenter"]
    assert len(hover) == 1
    assert f"c{image_id}" in hover[0].js_handler and "https://img/bolt-n.jpg" in hover[0].js_handler
    assert "Double Masters (2XM) · #129 · Incomum · 2020 · US$ 2.10" in hover[0].js_handler
    caption = user.find(marker="print-caption").elements.pop()
    leave = [li for li in user.find(marker="prints-list").elements.pop()._event_listeners.values()
             if li.type == "mouseleave"]
    assert len(leave) == 1 and "dataset.current" in leave[0].js_handler and f"c{caption.id}" in leave[0].js_handler


async def test_click_print_switches_in_place_without_requests(user: User, fake_api: FakeScryfall):
    await open_card(user, "1")
    await user.should_see(marker="print-1b")
    image = user.find(marker="main-image").elements.pop()
    user.find(marker="print-1b").click()
    await asyncio.sleep(0.1)
    # conteúdo trocou para a outra versão
    await user.should_see("Double Masters (2XM)")
    await user.should_see("#129")
    await user.should_see("Incomum")
    await user.should_see("US$ 2.10  ·  € 1.80")
    await user.should_see("Double Masters (2XM) · #129 · Incomum · 2020 · US$ 2.10")  # legenda
    await user.should_see("Rulings (1)")  # rulings continuam lá
    # mesma página: mesmos elementos, nenhuma requisição nova
    assert user.find(marker="main-image").elements.pop() is image
    assert fake_api.card_calls == ["1"] and fake_api.rulings_calls == ["1"] and fake_api.prints_pages == [1]
    # destaque mudou de versão
    current = "ring-blue-400"
    assert current in user.find(marker="print-1b").elements.pop().classes
    assert current not in user.find(marker="print-1").elements.pop().classes
    # clicar na versão já aberta não faz nada
    user.find(marker="print-1b").click()
    assert fake_api.card_calls == ["1"]


async def test_switch_print_resets_double_faced_state(user: User, fake_api: FakeScryfall):
    fake_api.cards["2b"] = type(fake_api.cards["2"])(**{
        **{k: getattr(fake_api.cards["2"], k) for k in fake_api.cards["2"].__slots__},
        "id": "2b", "set_code": "MID", "set_name": "Innistrad: Midnight Hunt"})
    await open_card(user, "2")
    user.find("Virar carta").click()
    image = user.find(marker="main-image").elements.pop()
    assert image.props["src"] == "https://img/d2-l.jpg"
    user.find(marker="print-2b").click()
    await user.should_see("Innistrad: Midnight Hunt (MID)")
    assert image.props["src"] == "https://img/d-l.jpg"  # volta para a frente na versão nova
    await user.should_see("Virar carta")


async def test_rulings(user: User, fake_api: FakeScryfall):
    await open_card(user, "1")
    await user.should_see("Rulings (1)")
    await user.should_see("07/08/2020")
    await user.should_see(kind=ui.html, content="This can target a planeswalker.")


async def test_double_faced_card(user: User, fake_api: FakeScryfall):
    await open_card(user, "2")
    await user.should_see("Delver of Secrets")
    await user.should_see("Insectile Aberration")
    await user.should_see("1/1")
    await user.should_see("3/2")
    await user.should_see("Rulings (0)")
    await user.should_see("Nenhum ruling para esta carta.")
    image = user.find(marker="main-image").elements.pop()
    assert image.props["src"] == image.props["data-current"] == "https://img/d-l.jpg"
    user.find("Virar carta").click()
    assert image.props["src"] == image.props["data-current"] == "https://img/d2-l.jpg"
    user.find("Virar carta").click()
    assert image.props["src"] == "https://img/d-l.jpg"


async def test_card_not_found(user: User, fake_api: FakeScryfall):
    await open_card(user, "nao-existe")
    await user.should_see("Não foi possível abrir a carta: No card found with the given ID")
    await user.should_see("Voltar")
