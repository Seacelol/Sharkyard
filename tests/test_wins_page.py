from datetime import date, timedelta

from nicegui.testing import User

from mtg_collection import database
from mtg_collection.database.tables import UserRow
from mtg_collection.services import decks, ranking
from tests.conftest import FakeScryfall, create_account


def run(fn, *args, **kwargs):
    with database.session() as s:
        return fn(s, *args, **kwargs)


def count_label(user: User) -> str:
    return user.find(marker="deck-wins-count").elements.pop().text


async def test_owner_registers_edits_and_deletes(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Krenko", format="commander")
    await user.open(f"/deck/{deck.id}")
    assert count_label(user) == "0"
    user.find(marker="deck-wins").click()
    await user.should_see(marker="wins-private")  # privado: avisa que não conta no ranking
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    user.find(marker="win-date").elements.pop().value = yesterday
    user.find(marker="win-notes").type("mesa de 4")
    user.find(marker="win-add").click()
    await user.should_see("Vitória registrada.")
    await user.should_see("Vitórias de \"Krenko\": 1")
    assert count_label(user) == "1"
    [win] = run(ranking.list_wins, 1, deck.id)
    assert (win.played_on.isoformat(), win.notes, win.version_name) == (yesterday, "mesa de 4", "Original")
    user.find(marker=f"win-edit-{win.id}").click()
    user.find(marker="win-edit-notes").clear().type("final")
    user.find(marker="win-edit-save").click()
    await user.should_see("Vitória salva.")
    assert run(ranking.list_wins, 1, deck.id)[0].notes == "final"
    user.find(marker="win-date").elements.pop().value = (date.today() + timedelta(days=2)).isoformat()
    user.find(marker="win-add").click()
    await user.should_see("A data da vitória não pode ser no futuro.")
    user.find(marker=f"win-delete-{win.id}").click()
    await user.should_see("Nenhuma vitória registrada ainda.")
    assert count_label(user) == "0"


async def test_friend_sees_wins_read_only(user: User, fake_api: FakeScryfall):
    create_account("amigo", display_name="Amigo")
    deck = run(decks.create_deck, 2, "Burn", format="modern", visibility="friends")
    run(ranking.add_win, 2, deck.id, date.today(), "torneio")
    with database.session() as s:  # o usuário logado é o admin; aqui ele vira um amigo comum
        s.get(UserRow, 1).is_admin = False
    await user.open(f"/deck/{deck.id}")
    assert count_label(user) == "1"
    user.find(marker="deck-wins").click()
    await user.should_see("torneio")
    await user.should_not_see(marker="win-add")
