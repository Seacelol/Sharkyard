import asyncio

from nicegui import ui
from nicegui.testing import User

from tests.conftest import FakeScryfall


async def wait_debounce():
    await asyncio.sleep(0.2)


async def test_search_flow(user: User, fake_api: FakeScryfall):
    await user.open("/search")

    user.find(ui.input).type("bolt").trigger("keydown.enter")
    await user.should_see("200 cartas encontradas")
    await user.should_see("Lightning Bolt")

    user.find("Carregar mais").click()
    await asyncio.sleep(0.2)
    assert len(user.find("Lightning Bolt").elements) == 2
    await user.should_not_see("Carregar mais")

    user.find(ui.input).clear().type("nada")
    user.find(marker="search-button").click()
    await user.should_see("Nenhuma carta encontrada")
    await user.should_not_see("Lightning Bolt")


async def test_search_error_keeps_results(user: User, fake_api: FakeScryfall):
    await user.open("/search")
    user.find(ui.input).type("bolt").trigger("keydown.enter")
    await user.should_see("Lightning Bolt")

    user.find(ui.input).clear().type("erro")
    user.find(marker="search-button").click()
    await user.should_see("Sintaxe inválida")
    await user.should_see("Lightning Bolt")  # resultado anterior não some num erro


async def test_click_tile_opens_card_page(user: User, fake_api: FakeScryfall):
    await user.open("/search")
    user.find(ui.input).type("bolt").trigger("keydown.enter")
    await user.should_see("200 cartas encontradas")
    user.find(marker="card-tile").click()
    await user.should_see("Legalidade")
    await user.should_see("Magic 2010 (M10)")


async def test_query_in_url_runs_search(user: User, fake_api: FakeScryfall):
    await user.open("/search?q=bolt")
    await user.should_see("200 cartas encontradas")
    assert user.find(ui.input).elements.pop().value == "bolt"
    await asyncio.sleep(0.2)
    assert fake_api.suggest_calls == []  # valor inicial não dispara sugestões


async def test_suggestions_appear_while_typing(user: User, fake_api: FakeScryfall):
    await user.open("/search")
    user.find(ui.input).type("bo")
    await wait_debounce()
    await user.should_see("Instant · M10")  # linha secundária da sugestão
    await user.should_see(kind=ui.html, content='Lightning <span class="text-orange-600">Bo</span>lt')
    assert len(user.find(marker="suggestion").elements) == 2
    assert fake_api.suggest_calls == ["bo"]


async def test_debounce_only_last_text_is_requested(user: User, fake_api: FakeScryfall):
    await user.open("/search")
    user.find(ui.input).type("li").type("g").type("h")
    await wait_debounce()
    assert fake_api.suggest_calls == ["ligh"]


async def test_no_suggestions_for_short_text_or_syntax(user: User, fake_api: FakeScryfall):
    await user.open("/search")
    user.find(ui.input).type("b")
    await wait_debounce()
    user.find(ui.input).clear().type("t:dragon")
    await wait_debounce()
    assert fake_api.suggest_calls == []


async def test_click_suggestion_opens_card_page(user: User, fake_api: FakeScryfall):
    await user.open("/search")
    user.find(ui.input).type("bo")
    await wait_debounce()
    await user.should_see("Instant · M10")
    user.find(marker="suggestion-1").trigger("mousedown.prevent")
    await user.should_see("Legalidade")
    await user.should_see("Magic 2010 (M10)")


async def test_enter_hides_suggestions_and_searches(user: User, fake_api: FakeScryfall):
    await user.open("/search")
    user.find(ui.input).type("bo")
    await wait_debounce()
    await user.should_see("Instant · M10")
    user.find(ui.input).trigger("keydown.enter")
    await user.should_see("200 cartas encontradas")
    await user.should_not_see("Instant · M10")


async def test_escape_hides_suggestions(user: User, fake_api: FakeScryfall):
    await user.open("/search")
    user.find(ui.input).type("bo")
    await wait_debounce()
    await user.should_see("Instant · M10")
    user.find(ui.input).trigger("keydown.esc")
    await user.should_not_see("Instant · M10")
