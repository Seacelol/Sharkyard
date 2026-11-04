"""Lê listas de deck em texto. Puro: não consulta a API.

Formato principal, uma carta por linha:
    3 Lightning Bolt
    3x Lightning Bolt
    Lightning Bolt            (sem número = 1)

Também entende o que Arena, Moxfield e MTGO exportam:
    4 Lightning Bolt (M10) 146     edição e número: usa essa impressão
    4 Lightning Bolt (M10)         só a edição
    1 Lightning Bolt (2XM) 129 *F* foil
    Sideboard / Commander / Companion / ...   cabeçalhos trocam a seção das linhas seguintes
    SB: 2 Pyroblast                linha avulsa do sideboard
    // comentário  ou  # comentário
"""
import re
from dataclasses import dataclass

MAX_QUANTITY = 999

_SECTION_HEADERS = {
    "deck": "main", "main": "main", "mainboard": "main", "maindeck": "main", "principal": "main",
    "sideboard": "sideboard", "side": "sideboard", "sb": "sideboard", "reserva": "sideboard",
    "commander": "commander", "commanders": "commander", "comandante": "commander",
    "companion": "companion", "companheiro": "companion",
    "maybe": "maybe", "maybeboard": "maybe", "considering": "maybe", "talvez": "maybe",
}
_LINE = re.compile(
    r"^(?:(?P<qty>\d+)\s*[xX]?\s+)?"           # quantidade: "3 ", "3x ", "3 x "
    r"(?P<name>.+?)"                            # nome
    r"(?:\s+\((?P<set>[A-Za-z0-9]{2,6})\)"      # (SET)
    r"(?:\s+(?P<number>[A-Za-z0-9\-★]+))?)?"    # número de colecionador
    r"(?P<foil>\s+\*[FE]\*)?\s*$")              # *F* foil / *E* etched (Moxfield)


@dataclass(frozen=True, slots=True)
class DecklistLine:
    """Linha da lista já interpretada. line_no aponta a linha original, para as mensagens de erro."""
    line_no: int
    quantity: int
    name: str
    section: str = "main"
    set_code: str | None = None
    collector_number: str | None = None
    foil: bool = False


@dataclass(frozen=True, slots=True)
class DecklistError:
    line_no: int
    text: str
    reason: str


def parse_decklist(text: str, default_section: str = "main") -> tuple[list[DecklistLine], list[DecklistError]]:
    """Linhas reconhecidas e linhas com erro. `default_section` vale até aparecer um cabeçalho de seção."""
    lines: list[DecklistLine] = []
    errors: list[DecklistError] = []
    section = default_section
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith(("//", "#")):
            continue
        header = line.rstrip(":").strip().lower()
        if header in _SECTION_HEADERS:
            section = _SECTION_HEADERS[header]
            continue
        line_section = section
        if line.lower().startswith("sb:"):
            line, line_section = line[3:].strip(), "sideboard"
        match = _LINE.match(line)
        if not match or not match["name"].strip():
            errors.append(DecklistError(line_no, raw.strip(), "Não entendi a linha."))
            continue
        quantity = int(match["qty"]) if match["qty"] else 1
        if not 1 <= quantity <= MAX_QUANTITY:
            errors.append(DecklistError(line_no, raw.strip(), f"Quantidade deve ser de 1 a {MAX_QUANTITY}."))
            continue
        lines.append(DecklistLine(
            line_no=line_no, quantity=quantity, name=" ".join(match["name"].split()), section=line_section,
            set_code=match["set"].lower() if match["set"] else None, collector_number=match["number"],
            foil=bool(match["foil"])))
    return lines, errors
