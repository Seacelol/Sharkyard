from datetime import date, timedelta

import pytest

from mtg_collection import database
from mtg_collection.services import decks, ranking
from mtg_collection.services.ranking import Filters, RankingError
from tests.conftest import create_account

TODAY = date.today()


def run(fn, *args, **kwargs):
    with database.session() as s:
        return fn(s, *args, **kwargs)


@pytest.fixture
def people():
    create_account("admin", display_name="Admin")  # 1: admin
    create_account("ana", display_name="Ana")  # 2
    create_account("bruno", display_name="Bruno")  # 3


def public_deck(owner, name, fmt="commander"):
    return run(decks.create_deck, owner, name, format=fmt, visibility="friends")


def wins(actor, deck, n, day=TODAY):
    for _ in range(n):
        run(ranking.add_win, actor, deck.id, day)


def test_register_and_permissions(people):
    deck = public_deck(2, "Krenko")
    win = run(ranking.add_win, 2, deck.id, TODAY - timedelta(days=1), "  mesa de 4  ")
    assert (win.notes, win.version_name, win.season_id) == ("mesa de 4", "Original", None)
    with pytest.raises(RankingError, match="não encontrado"):
        run(ranking.add_win, 3, deck.id, TODAY)  # outro usuário não lança no deck da Ana
    with pytest.raises(RankingError, match="futuro"):
        run(ranking.add_win, 2, deck.id, TODAY + timedelta(days=1))
    admin_win = run(ranking.add_win, 1, deck.id, TODAY)  # admin lança em qualquer deck
    assert run(ranking.win_count, deck.id) == 2
    run(ranking.update_win, 2, win.id, played_on=TODAY, notes="editada")
    with pytest.raises(RankingError, match="admin"):
        run(ranking.update_win, 2, win.id, played_on=TODAY, season_id=None)
    with pytest.raises(RankingError):
        run(ranking.delete_win, 3, admin_win.id)
    run(ranking.delete_win, 1, admin_win.id)
    assert [w.notes for w in run(ranking.list_wins, 3, deck.id)] == ["editada"]  # deck visível: amigo vê
    private = run(decks.create_deck, 2, "Privado")
    with pytest.raises(RankingError):
        run(ranking.list_wins, 3, private.id)
    assert run(ranking.list_wins, 1, private.id) == []  # admin vê


def test_rankings_positions_and_filters(people):
    krenko, atraxa = public_deck(2, "Krenko"), public_deck(2, "Atraxa")
    burn = public_deck(3, "Burn", fmt="modern")
    private = run(decks.create_deck, 3, "Privado", format="modern")
    wins(2, krenko, 3, TODAY - timedelta(days=40))
    wins(2, atraxa, 1)
    wins(3, burn, 3)
    wins(3, private, 9)  # privado não entra
    ranked = run(ranking.deck_ranking)
    # empate em 3: quem chegou antes (última vitória mais antiga) fica na frente; os dois dividem o 1º
    assert [(d.position, d.name, d.wins) for d in ranked] == [(1, "Krenko", 3), (1, "Burn", 3), (3, "Atraxa", 1)]
    players = run(ranking.player_ranking)
    assert [(p.position, p.name, p.wins, p.decks, p.best_deck) for p in players] == [
        (1, "Ana", 4, 2, "Krenko"), (2, "Bruno", 3, 1, "Burn")]
    assert [d.name for d in run(ranking.deck_ranking, Filters(format="modern"))] == ["Burn"]
    assert [d.name for d in run(ranking.deck_ranking, Filters(since=TODAY - timedelta(days=7)))] == ["Burn", "Atraxa"]
    assert run(ranking.ranking_formats) == ["commander", "modern"]


def test_seasons(people):
    deck = public_deck(2, "Krenko")
    wins(2, deck, 2)  # antes de qualquer temporada
    with pytest.raises(RankingError, match="admin"):
        run(ranking.start_season, 2, "T1")
    first = run(ranking.start_season, 1, "Temporada 1")
    wins(2, deck, 3)
    second = run(ranking.start_season, 1, "Temporada 2")
    wins(2, deck, 1)
    assert [s.name for s in run(ranking.list_seasons)] == ["Temporada 2", "Temporada 1"]
    assert run(ranking.active_season).id == second.id
    assert not [s for s in run(ranking.list_seasons) if s.id == first.id][0].active
    assert run(ranking.deck_ranking)[0].wins == 6  # geral: todas
    assert run(ranking.deck_ranking, Filters(season_id=first.id))[0].wins == 3
    assert run(ranking.deck_ranking, Filters(season_id=second.id))[0].wins == 1
    with pytest.raises(RankingError, match="Já existe"):
        run(ranking.start_season, 1, "temporada 1")
    run(ranking.end_season, 1)
    assert run(ranking.active_season) is None
    run(ranking.delete_season, 1, first.id)
    assert run(ranking.deck_ranking)[0].wins == 6  # as vitórias continuam no geral


def test_admin_hide_and_reset(people):
    krenko, burn = public_deck(2, "Krenko"), public_deck(3, "Burn")
    wins(2, krenko, 2)
    wins(3, burn, 1)
    run(ranking.set_deck_hidden, 1, krenko.id, True)
    assert [d.name for d in run(ranking.deck_ranking)] == ["Burn"]
    assert [(d.name, d.hidden) for d in run(ranking.deck_ranking, Filters(include_hidden=True))] == [
        ("Krenko", True), ("Burn", False)]
    run(ranking.set_deck_hidden, 1, krenko.id, False)
    run(ranking.set_player_hidden, 1, 3, True)
    assert [p.name for p in run(ranking.player_ranking)] == ["Ana"]
    assert [(p.name, p.hidden) for p in run(ranking.player_ranking, Filters(include_hidden=True))] == [
        ("Ana", False), ("Bruno", True)]
    with pytest.raises(RankingError, match="admin"):
        run(ranking.set_player_hidden, 2, 3, False)
    season = run(ranking.start_season, 1, "T")
    wins(2, krenko, 1)
    assert run(ranking.reset, 1, season.id) == 1
    assert run(ranking.win_count, krenko.id) == 2
    with pytest.raises(RankingError):
        run(ranking.reset, 2)
    assert run(ranking.reset, 1) == 3
    assert run(ranking.deck_ranking) == []


def test_deleting_deck_removes_its_wins(people):
    deck = public_deck(2, "Krenko")
    wins(2, deck, 2)
    run(decks.delete_decks, 2, [deck.id])
    assert run(ranking.deck_ranking) == []
