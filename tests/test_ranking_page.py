from datetime import date, timedelta

from nicegui.testing import User

from mtg_collection import database
from mtg_collection.database.tables import UserRow
from mtg_collection.services import decks, ranking
from mtg_collection.services.ranking import period_start
from tests.conftest import FakeScryfall, create_account

TODAY = date.today()


def run(fn, *args, **kwargs):
    with database.session() as s:
        return fn(s, *args, **kwargs)


def setup_decks():
    create_account("ana", display_name="Ana")  # 2 (o 1 é o admin logado)
    create_account("bruno", display_name="Bruno")  # 3
    krenko = run(decks.create_deck, 2, "Krenko", format="commander", visibility="friends")
    burn = run(decks.create_deck, 3, "Burn", format="modern", visibility="friends")
    for _ in range(3):
        run(ranking.add_win, 2, krenko.id, TODAY - timedelta(days=60))
    run(ranking.add_win, 3, burn.id, TODAY)
    return krenko, burn


def test_period_start():
    day = date(2026, 10, 26)
    assert period_start("", day) is None
    assert period_start("month", day) == date(2026, 10, 1)
    assert period_start("year", day) == date(2026, 1, 1)
    assert period_start("30", day) == date(2026, 9, 26)


async def test_rankings_and_filters(user: User, fake_api: FakeScryfall):
    krenko, burn = setup_decks()
    await user.open("/ranking")
    await user.should_see(marker=f"ranked-deck-{krenko.id}")
    await user.should_see("de Ana · Commander")
    user.find(marker="tab-players").click()
    await user.should_see(marker="ranked-player-2")
    await user.should_see("1 deck · melhor: Krenko")
    user.find(marker="filter-period").elements.pop().value = "30"
    await user.should_not_see(marker=f"ranked-deck-{krenko.id}")
    await user.should_see(marker=f"ranked-deck-{burn.id}")
    user.find(marker="filter-period").elements.pop().value = ""
    user.find(marker="filter-format").elements.pop().value = "commander"
    await user.should_not_see(marker=f"ranked-deck-{burn.id}")


async def test_admin_seasons_hide_and_reset(user: User, fake_api: FakeScryfall):
    krenko, burn = setup_decks()
    await user.open("/ranking")
    await user.should_see("Nenhuma temporada aberta: as vitórias novas contam só no geral.")
    user.find(marker="start-season").click()
    user.find(marker="ask-text").type("Temporada 1")
    user.find(marker="ask-ok").click()
    await user.should_see("Temporada \"Temporada 1\" aberta. As próximas vitórias entram nela.")
    await user.should_see("Nenhuma vitória com esses filtros.")  # filtro foi para a temporada nova, ainda vazia
    run(ranking.add_win, 3, burn.id, TODAY)
    user.find(marker="filter-season").elements.pop().value = "geral"
    await user.should_see(marker=f"ranked-deck-{krenko.id}")
    # tirar do ranking
    user.find(marker=f"hide-deck-{krenko.id}").click()
    await user.should_see("\"Krenko\" saiu do ranking.")
    await user.should_not_see(marker=f"ranked-deck-{krenko.id}")
    user.find(marker="show-hidden").click()
    await user.should_see("Fora do ranking")
    user.find(marker=f"hide-deck-{krenko.id}").click()
    await user.should_see("\"Krenko\" voltou ao ranking.")
    # corrigir vitórias de outro jogador pelo menu do admin
    user.find(marker=f"deck-admin-wins-{burn.id}").click()
    await user.should_see("Vitórias de \"Burn\": 2")
    await user.should_see(marker="win-add")
    # zerar tudo
    user.find(marker="reset-ranking").click()
    user.find(marker="confirm-ok").click()
    await user.should_see("5 vitórias apagadas.")
    assert run(ranking.deck_ranking) == []


async def test_regular_user_has_no_admin_tools(user: User, fake_api: FakeScryfall):
    setup_decks()
    with database.session() as s:
        s.get(UserRow, 1).is_admin = False
    await user.open("/ranking")
    await user.should_see(marker="ranking-decks")
    await user.should_not_see(marker="ranking-admin")
    await user.should_not_see(marker="show-hidden")
