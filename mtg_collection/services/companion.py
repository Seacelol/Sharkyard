"""Condições de construção dos companheiros (os dez de Ikoria). Puro.

A condição vale para o "deck inicial": o principal mais o comandante (o companheiro e o sideboard ficam de fora).
Cada função devolve as cartas que quebram a condição; lista vazia = condição cumprida.
"""
import re
from collections.abc import Callable

from mtg_collection.models import Card, DeckCard
from mtg_collection.services.deck_stats import mana_value

PERMANENT_TYPES = ("Artifact", "Battle", "Creature", "Enchantment", "Land", "Planeswalker")
CARD_TYPES = ("Artifact", "Battle", "Creature", "Enchantment", "Instant", "Kindred", "Tribal", "Planeswalker",
              "Sorcery")
KAHEERA_TYPES = {"Cat", "Elemental", "Nightmare", "Dinosaur", "Beast"}
_SYMBOL = re.compile(r"\{([^}]+)\}")
_REMINDER = re.compile(r"\([^)]*\)")


def _front(type_line: str) -> str:
    return type_line.split(" // ")[0]


def _is_land(line: DeckCard) -> bool:
    return "Land" in _front(line.type_line)


def _value(line: DeckCard) -> int:
    return mana_value(line.mana_cost, line.type_line)


def _is_permanent(line: DeckCard) -> bool:
    return any(t in _front(line.type_line) for t in PERMANENT_TYPES)


def _gyruda(lines, cards, minimum):
    return [f"{x.card_name} ({_value(x)})" for x in lines if _value(x) % 2]


def _jegantha(lines, cards, minimum):
    def repeats(cost: str) -> bool:
        return any(len(set(symbols := _SYMBOL.findall(half))) < len(symbols) for half in cost.split(" // "))
    return [x.card_name for x in lines if repeats(x.mana_cost.upper())]


def _kaheera(lines, cards, minimum):
    def ok(line: DeckCard) -> bool:
        main, _, subtypes = _front(line.type_line).partition("—")
        return "Creature" not in main or bool(KAHEERA_TYPES & set(subtypes.split()))
    return [x.card_name for x in lines if not ok(x)]


def _keruga(lines, cards, minimum):
    return [f"{x.card_name} ({_value(x)})" for x in lines if not _is_land(x) and _value(x) < 3]


def _lurrus(lines, cards, minimum):
    return [f"{x.card_name} ({_value(x)})" for x in lines if _is_permanent(x) and _value(x) > 2]


def _lutri(lines, cards, minimum):
    return [f"{x.card_name} ({x.quantity})" for x in lines if not _is_land(x) and x.quantity > 1]


def _obosh(lines, cards, minimum):
    return [f"{x.card_name} ({_value(x)})" for x in lines if not _is_land(x) and _value(x) % 2 == 0]


def _umori(lines, cards, minimum):
    spells = [x for x in lines if not _is_land(x)]
    if not spells:
        return []
    shared = set(CARD_TYPES)
    for line in spells:
        shared &= {t for t in CARD_TYPES if t in _front(line.type_line)}
    return [] if shared else ["as mágicas não têm um tipo em comum"]


def _yorion(lines, cards, minimum):
    total = sum(x.quantity for x in lines)
    return [] if total >= minimum + 20 else [f"o deck tem {total} cartas; precisa de pelo menos {minimum + 20}"]


def _zirda(lines, cards, minimum):
    def activated(line: DeckCard) -> bool | None:
        """Habilidade ativada = algum "custo: efeito" no texto sem lembretes. None se a carta não foi carregada."""
        if "Basic" in line.type_line:
            return True  # básicos têm a habilidade de mana embutida
        card = cards.get(line.oracle_id)
        if card is None:
            return None  # sem texto: não dá para conferir
        text = _REMINDER.sub("", "\n".join([card.oracle_text, *(f.oracle_text for f in card.faces)]))
        return any(":" in part for part in text.splitlines())
    return [x.card_name for x in lines if _is_permanent(x) and activated(x) is False]


Check = Callable[[list[DeckCard], dict[str, Card], int], list[str]]
# nome da frente -> (condição em português, conferência)
COMPANIONS: dict[str, tuple[str, Check]] = {
    "Gyruda, Doom of Depths": ("cada carta com valor de mana par", _gyruda),
    "Jegantha, the Wellspring": ("nenhuma carta com o mesmo símbolo de mana repetido no custo", _jegantha),
    "Kaheera, the Orphanguard": ("cada criatura é Cat, Elemental, Nightmare, Dinosaur ou Beast", _kaheera),
    "Keruga, the Macrosage": ("cada mágica com valor de mana 3 ou mais", _keruga),
    "Lurrus of the Dream-Den": ("cada permanente com valor de mana 2 ou menos", _lurrus),
    "Lutri, the Spellchaser": ("cada mágica com nome diferente (uma cópia de cada)", _lutri),
    "Obosh, the Preypiercer": ("cada mágica com valor de mana ímpar", _obosh),
    "Umori, the Collector": ("todas as mágicas com um tipo em comum", _umori),
    "Yorion, Sky Nomad": ("pelo menos 20 cartas a mais que o mínimo do formato", _yorion),
    "Zirda, the Dawnwaker": ("cada permanente com uma habilidade ativada", _zirda),
}
MAX_LISTED = 6


def check(companion_name: str, deck: list[DeckCard], cards: dict[str, Card], minimum: int) -> str | None:
    """Aviso se o deck não cumpre a condição do companheiro; None se cumpre ou se não é um dos conhecidos."""
    entry = COMPANIONS.get(companion_name.split(" // ")[0])
    if entry is None:
        return None
    condition, conferir = entry
    offenders = conferir(deck, cards, minimum)
    if not offenders:
        return None
    listed = ", ".join(offenders[:MAX_LISTED]) + (f" e mais {len(offenders) - MAX_LISTED}"
                                                  if len(offenders) > MAX_LISTED else "")
    name = companion_name.split(",")[0]
    return f"Condição de {name} não cumprida ({condition}): {listed}."
