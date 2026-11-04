import asyncio
import re

from nicegui import ui
from nicegui.testing import User

from mtg_collection import database
from mtg_collection.services import accounts, collection, decks
from mtg_collection.services.scryfall import to_card
from mtg_collection.ui import assets
from tests.conftest import FakeScryfall
from tests.sample_cards import BOLT


async def test_home_search_goes_to_results(user: User, fake_api: FakeScryfall):
    await user.open("/")
    await user.should_see(marker="home-logo")
    await user.should_see("Sua coleção: 0 cartas · 0 decks")
    user.find(ui.input).type("bolt").trigger("keydown.enter")
    await user.should_see("200 cartas encontradas")
    assert fake_api.search_queries[-1] == "bolt"


async def test_home_stats_and_random_card(user: User, fake_api: FakeScryfall):
    with database.session() as s:
        collection.add_card(s, 1, to_card(BOLT), 3)
        decks.create_deck(s, 1, "Burn")
    await user.open("/")
    await user.should_see("Sua coleção: 3 cartas · 1 deck")
    user.find(marker="random-card").click()
    await user.should_see("Delver of Secrets")


async def test_old_search_address_still_works(user: User, fake_api: FakeScryfall):
    await user.open("/?q=bolt")
    await user.should_see("200 cartas encontradas")


def mode(user_id: int = 1) -> str:
    with database.session() as s:
        return accounts.get_user(s, user_id).theme_mode


async def test_theme_saved_on_account(user: User, fake_api: FakeScryfall):
    user.javascript_rules[re.compile(r"document\.body\.classList\.contains")] = lambda _: False  # claro
    await user.open("/account")
    user.find(marker="theme-floresta").click()
    await asyncio.sleep(0.2)
    with database.session() as s:
        me = accounts.get_user(s, 1)
    assert (me.theme, me.theme_mode) == ("floresta", "auto")
    user.find(marker="theme-switch").click()  # claro -> escuro (sai do automático)
    await asyncio.sleep(0.2)
    assert mode() == "dark"
    user.find(marker="theme-auto").elements.pop().set_value(True)
    await asyncio.sleep(0.2)
    assert mode() == "auto"


async def test_header_switch_toggles_mode(user: User, fake_api: FakeScryfall):
    dark = {"now": True}
    user.javascript_rules[re.compile(r"document\.body\.classList\.contains")] = lambda _: dark["now"]
    await user.open("/collection")
    user.find(marker="header-mode-switch").click()
    await asyncio.sleep(0.2)
    assert mode() == "light"
    dark["now"] = False
    user.find(marker="header-mode-switch").click()
    await asyncio.sleep(0.2)
    assert mode() == "dark"
    await user.should_see("Minha coleção")  # não sai da página


def test_set_theme_rejects_unknown():
    import pytest
    with database.session() as s:
        accounts.register(s, "marcelo", "senha-forte-1")
        with pytest.raises(accounts.AccountError):
            accounts.set_theme(s, 1, "rosa", "auto")
        with pytest.raises(accounts.AccountError):
            accounts.set_theme(s, 1, "ilha", "noite")


async def test_pwa_files_are_public(user: User):
    """O navegador busca manifesto, service worker e ícones sem o cookie da sessão."""
    user.http_client.cookies.clear()
    manifest = await user.http_client.get("/manifest.webmanifest")
    assert manifest.status_code == 200 and manifest.json()["display"] == "standalone"
    for icon in manifest.json()["icons"]:
        assert (await user.http_client.get(icon["src"])).status_code == 200
    assert (await user.http_client.get("/sw.js")).status_code == 200
    shark = await user.http_client.get("/static/shark.svg")
    assert shark.status_code == 200 and b"<path" in shark.content
    assert assets.is_public("/static/logo.svg") and not assets.is_public("/collection")


async def test_theme_dialog_opens_only_once(user: User, fake_api: FakeScryfall):
    await user.open("/")
    user.find(marker="menu-theme").click()
    await user.should_see(marker="theme-dialog")
    user.find(marker="menu-theme").click()  # abrir de novo não empilha outra janela
    assert len(user.find(marker="theme-dialog").elements) == 1
    for key in ("ilha", "pantano"):
        user.find(marker=f"theme-{key}").click()
        await asyncio.sleep(0.1)
        await user.should_see(marker="theme-dialog")  # continua aberta
    with database.session() as s:
        assert accounts.get_user(s, 1).theme == "pantano"
    user.find(marker="theme-close").click()
    user.find(marker="menu-theme").click()
    assert len(user.find(marker="theme-dialog").elements) == 1


async def test_mobile_menu_goes_to_account(user: User, fake_api: FakeScryfall):
    await user.open("/")
    user.find(marker="menu-theme-mobile").click()
    await user.should_see("Trocar senha")


async def test_header_search_opens_in_place(user: User, fake_api: FakeScryfall):
    await user.open("/collection")
    await user.should_not_see(marker="header-search")
    user.find(marker="nav-search").click()
    await user.should_see(marker="header-search")
    await user.should_see("Minha coleção")  # não saiu da página
    user.find(marker="header-search").type("bo")
    await user.should_see(marker="header-search-suggestion-1")
    user.find(marker="header-search").trigger("keydown.enter")
    await user.should_see("200 cartas encontradas")
    user.find(marker="nav-search").click()
    user.find(marker="header-search-close").click()
    await user.should_not_see(marker="header-search")


async def test_bottom_nav_on_every_page(user: User, fake_api: FakeScryfall):
    await user.open("/decks")
    await user.should_see(marker="bottom-nav")
    user.find(marker="bottom-/ranking").click()
    await user.should_see("Vitórias dos decks visíveis")


async def test_app_name_in_title(user: User, fake_api: FakeScryfall):
    await user.open("/")
    await user.should_see("Sharkyard")
