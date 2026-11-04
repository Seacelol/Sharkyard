"""Regras da zona de comando: quem pode ser comandante em cada formato, quais pares de comandantes valem
(as variações de parceiro) e quem pode ser companheiro. Puro: lê só o tipo e o texto das cartas."""
import re
from dataclasses import dataclass

from mtg_collection.models import Card

# formato -> que tipo de carta lidera o deck
COMMANDER_FORMATS = {
    "commander": "creature", "duel": "creature", "predh": "creature", "paupercommander": "pauper",
    "brawl": "brawler", "standardbrawl": "brawler", "oathbreaker": "planeswalker",
}
# busca do Scryfall que acha quem pode ser comandante (o texto digitado é somado a ela)
_COMMANDER_QUERIES = {
    "creature": "is:commander", "brawler": "is:brawler", "planeswalker": "t:planeswalker",
    "pauper": "(t:creature or t:background) r:uncommon",
}
COMPANION_QUERY = "is:companion"

_PARTNER_WITH = re.compile(r"^partner with ([^(]+?)\s*(?:\(|$)")
_PARTNER_GROUP = re.compile(r"^partner\s*[—–-]\s*([^(]+?)\s*(?:\(|$)")
_COMPANION = re.compile(r"^companion\s*[—–-]", re.M | re.I)


@dataclass(frozen=True, slots=True)
class PartnerAbility:
    """Formas de ter dois comandantes que a carta permite. Falso (bool) quando ela não permite nenhuma."""
    plain: bool = False  # "Partner": combina com qualquer outra carta com partner
    partner_with: str = ""  # "Partner with X": só com X (e X precisa ter "Partner with" esta)
    groups: frozenset[str] = frozenset()  # "Partner—Survivors", "Friends forever"...: só com o mesmo grupo
    background: bool = False  # "Choose a Background": com um Background
    doctors_companion: bool = False  # "Doctor's companion": com um Time Lord Doctor

    def __bool__(self) -> bool:
        return self.plain or bool(self.partner_with or self.groups) or self.background or self.doctors_companion


def commander_kind(fmt: str) -> str:
    return COMMANDER_FORMATS.get(fmt, "")


def commander_query(fmt: str) -> str:
    return _COMMANDER_QUERIES.get(commander_kind(fmt), "")


def card_text(card: Card) -> str:
    return "\n".join([card.oracle_text, *(face.oracle_text for face in card.faces)])


def front_name(name: str) -> str:
    return name.split(" // ")[0].strip()


def partner_ability(card: Card) -> PartnerAbility:
    """Lê as habilidades de parceria no texto de regras (todas as faces). A linha pode juntar várias habilidades
    separadas por vírgula, por isso cada parte é conferida."""
    plain = background = doctor = False
    partner_with = ""
    groups = set()
    for line in card_text(card).lower().splitlines():
        if match := _PARTNER_WITH.match(line.strip()):  # o nome citado pode ter vírgula
            partner_with = match[1].strip()
            continue
        for part in (p.strip() for p in line.split(",")):
            if match := _PARTNER_WITH.match(part):
                partner_with = match[1].strip()
            elif match := _PARTNER_GROUP.match(part):
                groups.add(match[1].strip())
            elif part == "friends forever" or part.startswith("friends forever ("):
                groups.add("friends forever")
            elif part == "partner" or part.startswith("partner ("):
                plain = True
            elif part.startswith("choose a background"):
                background = True
            elif part.startswith("doctor's companion"):
                doctor = True
    return PartnerAbility(plain, partner_with, frozenset(groups), background, doctor)


def is_background(card: Card) -> bool:
    type_line = card.type_line.lower()
    return "legendary" in type_line and "enchantment" in type_line and "background" in type_line


def is_time_lord_doctor(card: Card) -> bool:
    main, _, subtypes = card.type_line.partition("—")
    return "Legendary" in main and "Creature" in main and subtypes.split() == ["Time", "Lord", "Doctor"]


def can_have_partner(card: Card) -> bool:
    """Admite um segundo comandante (tem alguma forma de parceiro, ou é Background ou Time Lord Doctor)."""
    return bool(partner_ability(card)) or is_background(card) or is_time_lord_doctor(card)


def can_pair(a: Card, b: Card) -> bool:
    """Os dois podem ser comandantes juntos."""
    if a.oracle_id and a.oracle_id == b.oracle_id:
        return False
    pa, pb = partner_ability(a), partner_ability(b)
    if pa.plain and pb.plain:
        return True
    if pa.partner_with and pb.partner_with:
        return pa.partner_with == front_name(b.name).lower() and pb.partner_with == front_name(a.name).lower()
    if pa.groups & pb.groups:
        return True
    if (pa.background and is_background(b)) or (pb.background and is_background(a)):
        return True
    return (pa.doctors_companion and is_time_lord_doctor(b)) or (pb.doctors_companion and is_time_lord_doctor(a))


def can_lead(fmt: str, type_line: str, text: str, has_pt: bool = False) -> bool:
    """Pode ser comandante sozinho neste formato (Background só vale junto de quem tem Choose a Background)."""
    type_line, text = type_line.lower(), text.lower()
    kind = commander_kind(fmt)
    if "can be your commander" in text:
        return True
    if kind == "pauper":
        return "creature" in type_line or "background" in type_line
    if kind == "planeswalker":
        return "planeswalker" in type_line or "can be your oathbreaker" in text
    legendary = "legendary" in type_line
    if kind == "brawler":  # Brawl: também veículo ou espaçonave lendária com poder/resistência
        return legendary and ("creature" in type_line or "planeswalker" in type_line or "vehicle" in type_line
                              or ("spacecraft" in type_line and has_pt))
    return legendary and "creature" in type_line


def is_companion(card: Card) -> bool:
    return bool(_COMPANION.search(card_text(card)))
