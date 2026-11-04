"""Vitórias e ranking. Sem interface.

- O dono registra as vitórias dos próprios decks; o admin registra, edita e apaga as de qualquer deck.
- Entram no ranking os decks visíveis para os amigos, de contas ativas, que não foram tirados do ranking pelo admin
  (nem o dono).
- Cada vitória fica na temporada que estava aberta quando foi registrada (o admin pode mudar).
- Posição no estilo de competição: empates dividem a posição e a seguinte pula (1, 1, 3).
"""
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from mtg_collection import config
from mtg_collection.database.tables import DeckRow, DeckVersionRow, SeasonRow, UserRow, WinRow
from mtg_collection.models import RankedDeck, RankedPlayer, Season, Win

MAX_NOTES = 500
PERIODS = {"": "Todo o período", "30": "Últimos 30 dias", "month": "Este mês", "year": "Este ano"}


def period_start(period: str, today: date | None = None) -> date | None:
    """Primeiro dia do período do filtro (None = sem limite)."""
    today = today or date.today()
    if period == "30":
        return today - timedelta(days=30)
    if period == "month":
        return today.replace(day=1)
    if period == "year":
        return today.replace(month=1, day=1)
    return None


class RankingError(Exception):
    """Erro com mensagem pronta para mostrar ao usuário."""


@dataclass(frozen=True, slots=True)
class Filters:
    """Recorte do ranking escolhido na tela. Os campos vazios não filtram."""
    season_id: int | None = None  # None: todas as temporadas (geral)
    format: str = ""  # "" todos os formatos
    since: date | None = None  # só vitórias a partir desta data
    include_hidden: bool = False  # admin vê os ocultos (marcados)


def to_season(row: SeasonRow) -> Season:
    return Season(id=row.id, name=row.name, started_at=row.started_at, ended_at=row.ended_at)


# ---------- vitórias ----------
def add_win(s: Session, actor_id: int, deck_id: int, played_on: date, notes: str = "",
            version_id: int | None = None) -> Win:
    """Dono ou admin. Sem versão, vale a versão atual do deck; a vitória entra na temporada aberta, se houver."""
    deck = _editable_deck(s, actor_id, deck_id)
    _check_version(s, deck, version_id)
    _check_date(played_on)
    active = active_season(s)
    row = WinRow(deck_id=deck.id, version_id=version_id or deck.current_version_id, played_on=played_on,
                 notes=_notes(notes), season_id=active.id if active else None, created_by=actor_id)
    s.add(row)
    s.flush()
    return _to_win(s, row)


def update_win(s: Session, actor_id: int, win_id: int, *, played_on: date, notes: str = "",
               version_id: int | None | type = ..., season_id: int | None | type = ...) -> Win:
    """Dono ou admin. Só o admin muda a temporada (season_id=None tira de qualquer temporada).
    version_id e season_id omitidos ficam como estão; None tira a versão (ou a temporada)."""
    row = _win_row(s, actor_id, win_id)
    if version_id is not ...:
        _check_version(s, s.get(DeckRow, row.deck_id), version_id)
        row.version_id = version_id
    _check_date(played_on)
    row.played_on, row.notes = played_on, _notes(notes)
    if season_id is not ...:
        if not _is_admin(s, actor_id):
            raise RankingError("Só o admin muda a temporada de uma vitória.")
        if season_id is not None and s.get(SeasonRow, season_id) is None:
            raise RankingError("Temporada não encontrada.")
        row.season_id = season_id
    s.flush()
    return _to_win(s, row)


def delete_win(s: Session, actor_id: int, win_id: int) -> None:
    s.delete(_win_row(s, actor_id, win_id))
    s.flush()


def list_wins(s: Session, viewer_id: int, deck_id: int) -> list[Win]:
    """Histórico do deck, mais recente primeiro. Dono e admin sempre veem; amigos, se o deck estiver visível."""
    deck = s.get(DeckRow, deck_id)
    if deck is None or not (deck.user_id == viewer_id or deck.visibility == "friends" or _is_admin(s, viewer_id)):
        raise RankingError("Deck não encontrado.")
    # versão e temporada de cada vitória na mesma consulta (antes, duas buscas por vitória)
    rows = s.execute(select(WinRow, DeckVersionRow.name, SeasonRow.name)
                     .outerjoin(DeckVersionRow, DeckVersionRow.id == WinRow.version_id)
                     .outerjoin(SeasonRow, SeasonRow.id == WinRow.season_id)
                     .where(WinRow.deck_id == deck_id).order_by(WinRow.played_on.desc(), WinRow.id.desc()))
    return [_win(row, version or "", season or "") for row, version, season in rows]


def win_count(s: Session, deck_id: int) -> int:
    return s.scalar(select(func.count()).select_from(WinRow).where(WinRow.deck_id == deck_id)) or 0


def can_edit_wins(s: Session, actor_id: int, deck_id: int) -> bool:
    deck = s.get(DeckRow, deck_id)
    return deck is not None and (deck.user_id == actor_id or _is_admin(s, actor_id))


# ---------- rankings ----------
def deck_ranking(s: Session, filters: Filters | None = None) -> list[RankedDeck]:
    """Decks por número de vitórias. No empate, fica na frente quem chegou primeiro ao placar (última vitória
    mais antiga), e depois o nome."""
    filters = filters or Filters()
    rows = s.execute(
        _eligible(filters)
        .add_columns(DeckRow.id, DeckRow.name, DeckRow.format, DeckRow.hidden_from_ranking, UserRow.id,
                     UserRow.display_name, UserRow.hidden_from_ranking,
                     func.count(WinRow.id), func.max(WinRow.played_on))
        .group_by(DeckRow.id)).all()
    items = [dict(deck_id=r[0], name=r[1], format=r[2], owner_id=r[4], owner_name=r[5], wins=r[7], last_win=r[8],
                  hidden=bool(r[3] or r[6])) for r in rows]
    items.sort(key=lambda x: (-x["wins"], x["last_win"], x["name"].lower()))  # empate: quem chegou antes
    return [RankedDeck(position=p, **item) for p, item in zip(_positions([x["wins"] for x in items]), items,
                                                               strict=True)]


def player_ranking(s: Session, filters: Filters | None = None) -> list[RankedPlayer]:
    """Jogadores somando as vitórias dos decks. Parte do ranking de decks para aplicar exatamente as mesmas
    regras de elegibilidade e filtros."""
    profiles = {row.id: row for row in s.execute(
        select(UserRow.id, UserRow.hidden_from_ranking, UserRow.avatar_filename, UserRow.bio)).all()}
    players: dict[int, dict] = {}
    for deck in deck_ranking(s, filters):  # já vem do melhor para o pior: o primeiro de cada um é o melhor deck
        player = players.setdefault(deck.owner_id, dict(
            user_id=deck.owner_id, name=deck.owner_name, wins=0, decks=0, best_deck=deck.name,
            last_win=deck.last_win, hidden=bool(profiles[deck.owner_id].hidden_from_ranking),
            avatar_filename=profiles[deck.owner_id].avatar_filename, bio=profiles[deck.owner_id].bio))
        player["wins"] += deck.wins
        player["decks"] += 1
        player["last_win"] = max(player["last_win"], deck.last_win)
    items = sorted(players.values(), key=lambda x: (-x["wins"], x["last_win"], x["name"].lower()))
    return [RankedPlayer(position=p, **item) for p, item in zip(_positions([x["wins"] for x in items]), items,
                                                                 strict=True)]


def ranking_formats(s: Session) -> list[str]:
    """Formatos que têm alguma vitória (para o filtro)."""
    query = select(DeckRow.format).join(WinRow, WinRow.deck_id == DeckRow.id).distinct()
    return sorted(f for f in s.scalars(query) if f)


def _eligible(filters: Filters):
    query = select().select_from(WinRow).join(DeckRow, DeckRow.id == WinRow.deck_id) \
        .join(UserRow, UserRow.id == DeckRow.user_id) \
        .where(DeckRow.visibility == "friends", UserRow.is_disabled.is_(False))  # conta desativada sai do ranking
    if not filters.include_hidden:
        query = query.where(DeckRow.hidden_from_ranking.is_(False), UserRow.hidden_from_ranking.is_(False))
    if filters.season_id is not None:
        query = query.where(WinRow.season_id == filters.season_id)
    if filters.format:
        query = query.where(DeckRow.format == filters.format)
    if filters.since:
        query = query.where(WinRow.played_on >= filters.since)
    return query


def _positions(scores: list[int]) -> list[int]:
    positions, last = [], None
    for index, score in enumerate(scores, start=1):
        positions.append(positions[-1] if score == last else index)
        last = score
    return positions


# ---------- temporadas e admin ----------
def list_seasons(s: Session) -> list[Season]:
    return [to_season(r) for r in s.scalars(select(SeasonRow).order_by(SeasonRow.started_at.desc(),
                                                                        SeasonRow.id.desc()))]


def active_season(s: Session) -> Season | None:
    row = s.scalar(select(SeasonRow).where(SeasonRow.ended_at.is_(None)).order_by(SeasonRow.id.desc()))
    return to_season(row) if row else None


def start_season(s: Session, actor_id: int, name: str, today: date | None = None) -> Season:
    """Abre uma temporada nova (fecha a atual). As vitórias registradas daqui em diante entram nela."""
    _require_admin(s, actor_id)
    name = " ".join(name.split())[:config.SEASON_NAME_MAX]
    if not name:
        raise RankingError("Dê um nome para a temporada.")
    if any(season.name.lower() == name.lower() for season in list_seasons(s)):
        raise RankingError(f"Já existe uma temporada chamada \"{name}\".")
    today = today or date.today()
    end_season(s, actor_id, today)
    row = SeasonRow(name=name, started_at=today)
    s.add(row)
    s.flush()
    return to_season(row)


def end_season(s: Session, actor_id: int, today: date | None = None) -> Season | None:
    """Só admin. Fecha a temporada aberta; devolve None se não havia nenhuma. As vitórias continuam nela."""
    _require_admin(s, actor_id)
    row = s.scalar(select(SeasonRow).where(SeasonRow.ended_at.is_(None)))
    if row is None:
        return None
    row.ended_at = today or date.today()
    s.flush()
    return to_season(row)


def delete_season(s: Session, actor_id: int, season_id: int) -> None:
    """Apaga a temporada. As vitórias dela continuam no ranking geral."""
    _require_admin(s, actor_id)
    row = s.get(SeasonRow, season_id)
    if row is None:
        raise RankingError("Temporada não encontrada.")
    s.delete(row)
    s.flush()


def set_deck_hidden(s: Session, actor_id: int, deck_id: int, hidden: bool) -> None:
    """Só admin. Tira o deck do ranking (ou devolve) sem apagar as vitórias."""
    _require_admin(s, actor_id)
    deck = s.get(DeckRow, deck_id)
    if deck is None:
        raise RankingError("Deck não encontrado.")
    deck.hidden_from_ranking = hidden
    s.flush()


def set_player_hidden(s: Session, actor_id: int, user_id: int, hidden: bool) -> None:
    """Só admin. Tira todos os decks da pessoa do ranking (ou devolve) sem apagar as vitórias."""
    _require_admin(s, actor_id)
    user = s.get(UserRow, user_id)
    if user is None:
        raise RankingError("Usuário não encontrado.")
    user.hidden_from_ranking = hidden
    s.flush()


def reset(s: Session, actor_id: int, season_id: int | None = None) -> int:
    """Apaga as vitórias (de uma temporada, ou todas). Devolve quantas saíram."""
    _require_admin(s, actor_id)
    query = delete(WinRow)
    if season_id is not None:
        query = query.where(WinRow.season_id == season_id)
    removed = s.execute(query).rowcount
    s.flush()
    return removed


# ---------- internos ----------
def _is_admin(s: Session, user_id: int) -> bool:
    return bool(s.scalar(select(UserRow.is_admin).where(UserRow.id == user_id)))


def _require_admin(s: Session, user_id: int) -> None:
    if not _is_admin(s, user_id):
        raise RankingError("Só o admin pode fazer isso.")


def _editable_deck(s: Session, actor_id: int, deck_id: int) -> DeckRow:
    deck = s.get(DeckRow, deck_id)
    if deck is None or not (deck.user_id == actor_id or _is_admin(s, actor_id)):
        raise RankingError("Deck não encontrado.")
    return deck


def _win_row(s: Session, actor_id: int, win_id: int) -> WinRow:
    row = s.get(WinRow, win_id)
    if row is None:
        raise RankingError("Vitória não encontrada.")
    _editable_deck(s, actor_id, row.deck_id)
    return row


def _check_version(s: Session, deck: DeckRow, version_id: int | None) -> None:
    if version_id is None:
        return
    version = s.get(DeckVersionRow, version_id)
    if version is None or version.deck_id != deck.id:
        raise RankingError("Versão não encontrada.")


def _check_date(played_on: date) -> None:
    if played_on > date.today():
        raise RankingError("A data da vitória não pode ser no futuro.")


def _notes(notes: str) -> str:
    return notes.strip()[:MAX_NOTES]


def _to_win(s: Session, row: WinRow) -> Win:
    version = s.get(DeckVersionRow, row.version_id) if row.version_id else None
    season = s.get(SeasonRow, row.season_id) if row.season_id else None
    return _win(row, version.name if version else "", season.name if season else "")


def _win(row: WinRow, version_name: str, season_name: str) -> Win:
    return Win(id=row.id, deck_id=row.deck_id, played_on=row.played_on, notes=row.notes, version_id=row.version_id,
               version_name=version_name, season_id=row.season_id, season_name=season_name)
