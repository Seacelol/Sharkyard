"""Confere se o deck vale no formato escolhido. Puro: recebe as linhas do deck e os dados das cartas (legalidade e
texto, vindos do Scryfall) e devolve avisos. Os avisos nunca impedem salvar o deck.

A seção "talvez" não entra na conta. Cartas sem dados (Scryfall fora do ar) só deixam de ter a legalidade
conferida; o resto das regras vale igual.
"""
import re
from collections import Counter
from dataclasses import dataclass

from mtg_collection.models import Card, DeckCard
from mtg_collection.services import commander, companion, scryfall


@dataclass(frozen=True, slots=True)
class FormatRules:
    """Regras de montagem de um formato que a validação confere. Legalidade de cada carta vem do Scryfall."""
    size: int  # mínimo de cartas no deck principal (com o comandante, nos formatos com comandante)
    exact: bool = False  # o tamanho tem que ser exato
    copies: int = 4  # máximo de cópias por carta (terrenos básicos e "any number" são exceção)
    sideboard: int | None = 15  # None: o formato não usa sideboard
    companion: bool = True  # o formato aceita companheiro


_SINGLETON = dict(copies=1, sideboard=None)
RULES = {
    "commander": FormatRules(100, True, **_SINGLETON),
    "duel": FormatRules(100, True, **_SINGLETON),
    "predh": FormatRules(100, True, **_SINGLETON),
    "paupercommander": FormatRules(100, True, **_SINGLETON),
    "brawl": FormatRules(100, True, **_SINGLETON),
    "standardbrawl": FormatRules(60, True, **_SINGLETON),
    "oathbreaker": FormatRules(60, True, **_SINGLETON),
    # Gladiator (Arena): no mínimo 100, singleton, sem sideboard e por isso sem companheiro
    "gladiator": FormatRules(100, copies=1, sideboard=None, companion=False),
}
CONSTRUCTED = FormatRules(60)
UNCHECKED = {"", "casual"}
_ANY_NUMBER = re.compile(r"a deck can have any number of cards named", re.I)
_UP_TO = re.compile(r"a deck can have up to (\w+) cards named", re.I)
_NUMBERS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def counted(lines: list[DeckCard]) -> list[DeckCard]:
    """Linhas que contam para o formato (tudo menos "talvez")."""
    return [line for line in lines if line.section != "maybe"]


def validate(fmt: str, lines: list[DeckCard], cards: dict[str, Card]) -> list[str]:
    """Avisos do deck no formato `fmt`. `cards` é indexado pelo oracle_id.
    O companheiro fica fora do deck: no Commander não conta nas 100; nos outros formatos ocupa vaga do sideboard."""
    if fmt in UNCHECKED:
        return []
    rules = RULES.get(fmt, CONSTRUCTED)
    has_commander = bool(commander.commander_kind(fmt))
    lines = counted(lines)
    deck = [line for line in lines if line.section in ("main", "commander")]
    companions = [line for line in lines if line.section == "companion"]
    side = [line for line in lines if line.section == "sideboard"]
    if not has_commander and rules.sideboard is not None:
        side += companions
    commanders = [line for line in lines if line.section == "commander"]
    warnings: list[str] = []

    total = sum(line.quantity for line in deck)
    if rules.exact and total != rules.size:
        warnings.append(f"O deck tem {total} cartas; o formato pede exatamente {rules.size}.")
    elif total < rules.size:
        warnings.append(f"O deck tem {total} cartas; o formato pede no mínimo {rules.size}.")

    if rules.sideboard is None:
        if any(line.section == "sideboard" for line in side):
            warnings.append("Este formato não usa sideboard; as cartas do sideboard ficam de fora.")
    elif (side_total := sum(line.quantity for line in side)) > rules.sideboard:
        warnings.append(f"O sideboard tem {side_total} cartas; o máximo é {rules.sideboard}.")

    if has_commander:
        warnings += _commander_warnings(fmt, commanders, deck + companions, cards)
    elif commanders:
        warnings.append("Este formato não tem comandante: " + ", ".join(sorted({c.card_name for c in commanders}))
                        + " fica de fora.")
    warnings += _companion_warnings(rules, companions, deck, cards)

    copies = Counter()
    names = {}
    for line in deck + ([] if rules.sideboard is None else side):
        copies[line.oracle_id] += line.quantity
        names[line.oracle_id] = line.card_name
    for oracle_id, count in copies.items():
        card = cards.get(oracle_id)
        limit = _copy_limit(rules, card, _line_for(lines, oracle_id))
        status = card.legalities.get(fmt) if card else None
        if status == "restricted":
            limit = min(limit, 1)
        if count > limit:
            what = "cópia" if limit == 1 else "cópias"
            warnings.append(f"{names[oracle_id]}: {count} cópias; o máximo é {limit} {what}.")
        if status == "banned":
            warnings.append(f"{names[oracle_id]} é banida neste formato.")
        elif status == "not_legal":
            warnings.append(f"{names[oracle_id]} não é legal neste formato.")

    custom = sorted({line.card_name for line in lines if line.custom_card_id})
    if custom:
        warnings.append("Cartas personalizadas não valem em formatos oficiais: " + ", ".join(custom) + ".")
    return warnings


def _commander_warnings(fmt: str, commanders: list[DeckCard], others: list[DeckCard],
                        cards: dict[str, Card]) -> list[str]:
    count = sum(line.quantity for line in commanders)
    if count == 0:
        return ["Falta o comandante: escolha no topo da página do deck."]
    warnings = []
    known = [cards.get(line.oracle_id) for line in commanders]
    if count > 2:
        warnings.append(f"Há {count} comandantes; o máximo é 2 (com parceiro).")
    elif len(commanders) == 2 and all(known) and not any(line.custom_card_id for line in commanders):
        if not commander.can_pair(*known):
            warnings.append(f"{commanders[0].card_name} e {commanders[1].card_name} não podem ser comandantes "
                            "juntos: os dois precisam ser parceiros um do outro.")
    for line, card in zip(commanders, known, strict=True):
        if line.custom_card_id or (card is None and not line.type_line):
            continue  # sem dados para conferir; a carta personalizada já tem aviso próprio
        text = commander.card_text(card) if card else ""
        paired_background = card is not None and commander.is_background(card) and any(
            other and commander.partner_ability(other).background for other in known)
        has_pt = card is not None and any(face.power is not None for face in card.faces)
        if not paired_background and not commander.can_lead(fmt, line.type_line, text, has_pt):
            warnings.append(f"{line.card_name} não pode ser comandante neste formato.")
    identity = set("".join(line.color_identity for line in commanders))
    outside = sorted({line.card_name for line in others if line.section != "commander"
                      and not set(line.color_identity) <= identity})
    if outside:
        warnings.append("Fora da identidade de cor do comandante: " + ", ".join(outside) + ".")
    return warnings


def _companion_warnings(rules: FormatRules, companions: list[DeckCard], deck: list[DeckCard],
                        cards: dict[str, Card]) -> list[str]:
    if companions and not rules.companion:
        return ["Este formato não permite companheiro."]
    warnings = []
    if sum(line.quantity for line in companions) > 1:
        warnings.append("Só pode haver um companheiro.")
    for line in companions:
        card = cards.get(line.oracle_id)
        if card and not line.custom_card_id and not commander.is_companion(card):
            warnings.append(f"{line.card_name} não tem a habilidade Companheiro (Companion).")
    for line in companions:
        if line.custom_card_id:
            continue
        if line.card_name.split(" // ")[0] in companion.COMPANIONS:
            if warning := companion.check(line.card_name, deck, cards, rules.size):
                warnings.append(warning)
        elif (card := cards.get(line.oracle_id)) and commander.is_companion(card):
            warnings.append(f"A condição de {line.card_name} não é conferida automaticamente; confira no texto.")
    return warnings


def _copy_limit(rules: FormatRules, card: Card | None, line: DeckCard) -> int:
    type_line = (card.type_line if card else line.type_line).lower()
    if "basic" in type_line and "land" in type_line:
        return 10 ** 6
    text = commander.card_text(card) if card else ""
    if _ANY_NUMBER.search(text):
        return 10 ** 6
    if match := _UP_TO.search(text):
        return _NUMBERS.get(match[1].lower(), rules.copies)
    return rules.copies


def _line_for(lines: list[DeckCard], oracle_id: str) -> DeckCard:
    return next(line for line in lines if line.oracle_id == oracle_id)


async def check(fmt: str, lines: list[DeckCard]) -> list[str]:
    """Busca legalidade e texto das cartas no Scryfall e valida. Se a API falhar, valida o resto e avisa."""
    if fmt in UNCHECKED:
        return []
    oracle_ids = sorted({line.oracle_id for line in counted(lines) if not line.custom_card_id})
    cards: dict[str, Card] = {}
    note = []
    if oracle_ids:
        try:
            found = await scryfall.client.find_cards([{"oracle_id": o} for o in oracle_ids])
            cards = {card.oracle_id: card for card in found if card}
        except scryfall.ScryfallError:
            note = ["Não deu para consultar a legalidade das cartas no Scryfall agora; o resto foi conferido."]
    return validate(fmt, lines, cards) + note
