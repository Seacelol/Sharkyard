"""Impressões de uma carta para o usuário: as do Scryfall mais as versões personalizadas dele."""
from mtg_collection import database
from mtg_collection.models import Card, CollectionEntry, CustomCard, CustomPrint
from mtg_collection.services import collection, custom_cards, scryfall
from mtg_collection.ui.custom_images import custom_image_url

CUSTOM_PREFIX = "custom-"


def custom_card(custom: CustomPrint, base: Card) -> Card:
    return collection.as_card(custom, base, custom_image_url(custom.image_filename))


def user_custom_cards(user_id: int, oracle_id: str, official: list[Card], fallback: Card | None) -> list[Card]:
    """Versões personalizadas como Card. A base de cada uma é a impressão em que foi criada (ou a carta atual)."""
    with database.session() as s:
        customs = collection.list_custom_prints(s, user_id, oracle_id)
    by_id = {c.id: c for c in official}
    cards = []
    for custom in customs:
        base = by_id.get(custom.base_scryfall_id) or fallback or (official[0] if official else None)
        if base is not None:
            cards.append(custom_card(custom, base))
    return cards


async def load_custom_card(user_id: int, card_id: str) -> tuple[Card, Card]:
    """Abre uma versão personalizada pelo id da página ("custom-12"): (versão, impressão base).
    Erro se a versão não for do usuário."""
    try:
        custom_id = int(card_id.removeprefix(CUSTOM_PREFIX))
    except ValueError:
        raise collection.CollectionError("Versão personalizada não encontrada.") from None
    with database.session() as s:
        custom = collection.get_custom_print(s, user_id, custom_id)
    base = await scryfall.client.get_card(custom.base_scryfall_id)
    return custom_card(custom, base), base


async def all_printings(user_id: int, oracle_id: str, fallback: Card | None = None) -> list[Card]:
    """Impressões oficiais (1ª página, até 175) seguidas das versões personalizadas do usuário."""
    official = list((await scryfall.client.get_prints(oracle_id)).cards)
    return official + user_custom_cards(user_id, oracle_id, official, fallback)


def custom_card_as_card(custom: CustomCard) -> Card:
    """Carta personalizada (que não existe no Magic) como Card, com a URL da imagem enviada."""
    return custom_cards.as_card(custom, custom_image_url(custom.image_filename))


async def entry_card(user_id: int, entry: CollectionEntry) -> Card:
    """A carta completa de um item da coleção (para levar a um deck com a mesma edição)."""
    with database.session() as s:
        if entry.custom_card_id:
            return custom_card_as_card(custom_cards.get(s, user_id, entry.custom_card_id))
        custom = collection.get_custom_print(s, user_id, entry.custom_print_id) if entry.custom_print_id else None
    if custom:
        return custom_card(custom, await scryfall.client.get_card(custom.base_scryfall_id))
    return await scryfall.client.get_card(entry.scryfall_id)
