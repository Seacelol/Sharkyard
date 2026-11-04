"""Cartas criadas pelo usuário (não existem no Magic). Sem interface.

Uma carta nasce dentro de um deck (deck_id preenchido) e só existe nele. Quando vai para a coleção, deck_id fica
vazio: ela passa a ser do usuário e pode entrar em qualquer deck. Apagar o deck apaga as cartas que só existiam nele.
"""
import re

from sqlalchemy import or_, select
from sqlalchemy import update as sql_update  # "update" já é a função de editar a carta
from sqlalchemy.orm import Session

from mtg_collection import config
from mtg_collection.database.tables import CollectionEntryRow, CustomCardRow, DeckCardRow, DeckRow
from mtg_collection.models import Card, CardFace, CustomCard, Prices

PREFIX = "customcard-"  # id e oracle_id das cartas personalizadas, para não colidir com os do Scryfall
COLOR_ORDER = "WUBRG"


class CustomCardError(Exception):
    """Erro com mensagem pronta para mostrar ao usuário."""


def to_custom_card(row: CustomCardRow) -> CustomCard:
    return CustomCard(id=row.id, name=row.name, mana_cost=row.mana_cost, type_line=row.type_line,
                      oracle_text=row.oracle_text, power=row.power, toughness=row.toughness, loyalty=row.loyalty,
                      colors=row.colors, image_filename=row.image_filename, deck_id=row.deck_id,
                      created_at=row.created_at)


def oracle_id_for(custom_id: int) -> str:
    return f"{PREFIX}{custom_id}"


def colors_from_cost(mana_cost: str) -> str:
    """Cores que aparecem no custo ("{2}{R}{W/U}" -> "WUR"), na ordem WUBRG."""
    symbols = "".join(re.findall(r"\{([^}]*)\}", mana_cost.upper()))
    return "".join(c for c in COLOR_ORDER if c in symbols)


def as_card(custom: CustomCard, image_url: str | None = None) -> Card:
    """A carta personalizada como Card, para entrar no deck e na coleção como qualquer outra."""
    face = CardFace(name=custom.name, mana_cost=custom.mana_cost, type_line=custom.type_line,
                    oracle_text=custom.oracle_text, power=custom.power or None,
                    toughness=custom.toughness or None, loyalty=custom.loyalty or None,
                    image_normal=image_url, image_large=image_url)
    return Card(
        id=oracle_id_for(custom.id), oracle_id=oracle_id_for(custom.id), name=custom.name, set_code="",
        set_name="Carta personalizada", collector_number="", rarity="special", type_line=custom.type_line,
        mana_cost=custom.mana_cost, oracle_text=custom.oracle_text, faces=(face,), legalities={},
        prices=Prices(), color_identity=tuple(custom.colors), custom_card_id=custom.id,
        image_small=image_url, image_normal=image_url, image_large=image_url, image_art_crop=image_url,
    )


def create(s: Session, user_id: int, *, name: str, mana_cost: str = "", type_line: str = "", oracle_text: str = "",
           power: str = "", toughness: str = "", loyalty: str = "", colors: str | None = None,
           image_filename: str | None = None, deck_id: int | None = None) -> CustomCard:
    """Cria a carta. Com deck_id, existe só naquele deck; sem, já nasce na coleção do usuário."""
    if deck_id is not None:
        _check_deck(s, user_id, deck_id)
    row = CustomCardRow(user_id=user_id, deck_id=deck_id, image_filename=image_filename,
                        **_fields(name, mana_cost, type_line, oracle_text, power, toughness, loyalty, colors))
    s.add(row)
    s.flush()
    return to_custom_card(row)


def update(s: Session, user_id: int, custom_id: int, *, name: str, mana_cost: str = "", type_line: str = "",
           oracle_text: str = "", power: str = "", toughness: str = "", loyalty: str = "",
           colors: str | None = None, image_filename: str | None = None, remove_image: bool = False
           ) -> tuple[CustomCard, str | None]:
    """Atualiza a carta. Devolve (carta, imagem antiga que deixou de ser usada)."""
    row = _row(s, user_id, custom_id)
    for key, value in _fields(name, mana_cost, type_line, oracle_text, power, toughness, loyalty, colors).items():
        setattr(row, key, value)
    old = None
    if image_filename or remove_image:
        old, row.image_filename = row.image_filename, image_filename
    s.flush()
    return to_custom_card(row), old


def get(s: Session, user_id: int, custom_id: int) -> CustomCard:
    return to_custom_card(_row(s, user_id, custom_id))


def available_for_deck(s: Session, user_id: int, deck_id: int) -> list[CustomCard]:
    """As da coleção do usuário mais as que existem só neste deck."""
    query = select(CustomCardRow).where(CustomCardRow.user_id == user_id,
                                        or_(CustomCardRow.deck_id.is_(None), CustomCardRow.deck_id == deck_id))
    return [to_custom_card(r) for r in s.scalars(query.order_by(CustomCardRow.name))]


def move_to_collection(s: Session, user_id: int, custom_id: int) -> CustomCard:
    """A carta deixa de ser só do deck: passa a poder ser usada em qualquer deck."""
    row = _row(s, user_id, custom_id)
    row.deck_id = None
    s.flush()
    return to_custom_card(row)


def sync_snapshots(s: Session, user_id: int, card: Card) -> None:
    """Depois de editar a carta, atualiza as cópias de exibição guardadas na coleção e nos decks."""
    _row(s, user_id, card.custom_card_id)
    common = dict(card_name=card.name, type_line=card.type_line, image_small=card.image_small,
                  image_normal=card.image_normal)
    # um UPDATE por tabela, por mais cópias que existam
    s.execute(sql_update(CollectionEntryRow).where(CollectionEntryRow.custom_card_id == card.custom_card_id)
              .values(**common))
    s.execute(sql_update(DeckCardRow).where(DeckCardRow.custom_card_id == card.custom_card_id)
              .values(**common, mana_cost=card.mana_cost, image_art_crop=card.image_art_crop,
                      color_identity="".join(card.color_identity)))
    s.expire_all()


def image_in_use(s: Session, filename: str) -> bool:
    return s.scalar(select(CustomCardRow.id).where(CustomCardRow.image_filename == filename)) is not None


def image_owner(s: Session, filename: str) -> int | None:
    return s.scalar(select(CustomCardRow.user_id).where(CustomCardRow.image_filename == filename))


def _fields(name, mana_cost, type_line, oracle_text, power, toughness, loyalty, colors) -> dict:
    name = " ".join(name.split())
    if not name:
        raise CustomCardError("Dê um nome para a carta.")
    mana_cost = mana_cost.replace(" ", "")
    if colors is None:
        colors = colors_from_cost(mana_cost)
    colors = "".join(c for c in COLOR_ORDER if c in colors.upper())
    return dict(name=name[:config.CUSTOM_CARD_NAME_MAX], mana_cost=mana_cost[:80],
                type_line=" ".join(type_line.split())[:200],
                oracle_text=oracle_text.strip(), power=power.strip()[:8], toughness=toughness.strip()[:8],
                loyalty=loyalty.strip()[:8], colors=colors)


def _check_deck(s: Session, user_id: int, deck_id: int) -> None:
    deck = s.get(DeckRow, deck_id)
    if deck is None or deck.user_id != user_id:
        raise CustomCardError("Deck não encontrado.")


def _row(s: Session, user_id: int, custom_id: int | None) -> CustomCardRow:
    row = s.get(CustomCardRow, custom_id) if custom_id else None
    if row is None or row.user_id != user_id:
        raise CustomCardError("Carta personalizada não encontrada.")
    return row
