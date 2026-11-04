"""Estatísticas de uma versão do deck. Puro: usa só os dados guardados nas linhas.

Contam o deck principal e o comandante; sideboard, companheiro e "talvez" ficam de fora.
"""
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from mtg_collection.models import DeckCard

DECK_SECTIONS = ("main", "commander")
CURVE_MAX = 7  # a última coluna da curva junta 7 ou mais
COLORS = "WUBRG"
# tipos na ordem em que aparecem; uma carta com dois tipos (ex: criatura artefato) conta nos dois
TYPES = (("Creature", "Criaturas"), ("Planeswalker", "Planeswalkers"), ("Instant", "Mágicas instantâneas"),
         ("Sorcery", "Feitiços"), ("Artifact", "Artefatos"), ("Enchantment", "Encantamentos"),
         ("Battle", "Batalhas"), ("Land", "Terrenos"))
RARITIES = (("common", "Comum"), ("uncommon", "Incomum"), ("rare", "Rara"), ("mythic", "Mítica"),
            ("special", "Especial"))
_SYMBOL = re.compile(r"\{([^}]+)\}")


@dataclass(frozen=True, slots=True)
class DeckStats:
    """Números do deck para a tela de estatísticas. Contagens são em cópias, não em linhas."""
    cards: int = 0
    lands: int = 0
    average_mana_value: float = 0.0  # das mágicas (sem terrenos)
    curve: dict[int, int] = field(default_factory=dict)  # valor de mana -> cópias (0 a 7+, sem terrenos)
    creature_curve: dict[int, int] = field(default_factory=dict)  # parte da curva que é criatura
    types: list[tuple[str, int]] = field(default_factory=list)
    pips: dict[str, int] = field(default_factory=dict)  # símbolos de mana colorida nos custos, W U B R G
    rarities: list[tuple[str, int]] = field(default_factory=list)
    proxies: int = 0
    custom: int = 0  # cartas personalizadas e edições personalizadas
    paid_cents: int = 0  # soma de preço pago x cópias, nas linhas com preço
    priced_cards: int = 0  # cópias que têm preço pago

    @property
    def spells(self) -> int:
        return self.cards - self.lands


def mana_value(mana_cost: str, type_line: str = "") -> int:
    """Valor de mana do custo. "{2}{W/U}{X}" = 3. Carta dividida soma as metades; aventura e afins (onde a
    segunda metade é um feitiço avulso da mesma carta) usam só a primeira."""
    halves = [half for half in mana_cost.split(" // ")]
    if len(halves) > 1 and any(word in type_line for word in ("Adventure", "Omen")):
        halves = halves[:1]
    return sum(_symbol_value(symbol) for half in halves for symbol in _SYMBOL.findall(half))


def _symbol_value(symbol: str) -> int:
    symbol = symbol.upper()
    if symbol.isdigit():
        return int(symbol)
    if symbol in ("X", "Y", "Z"):
        return 0
    if "/" in symbol:  # híbrido: {2/W} vale 2, {W/U} e {W/P} valem 1
        first = symbol.split("/")[0]
        return int(first) if first.isdigit() else 1
    return 0 if symbol == "HALF" or symbol.startswith("H") else 1


def pips(mana_cost: str) -> Counter:
    counts = Counter()
    for symbol in _SYMBOL.findall(mana_cost.upper()):
        for color in COLORS:
            if color in symbol.split("/"):
                counts[color] += 1
    return counts


def is_land(line: DeckCard) -> bool:
    # dupla face com terreno só atrás (ex: "Instant // Land") conta como mágica pela frente
    return "Land" in line.type_line.split(" // ")[0]


def compute(lines: list[DeckCard]) -> DeckStats:
    """Calcula as estatísticas das linhas da versão; ignora as seções fora de DECK_SECTIONS."""
    deck = [line for line in lines if line.section in DECK_SECTIONS]
    cards = sum(line.quantity for line in deck)
    lands = sum(line.quantity for line in deck if is_land(line))
    curve = dict.fromkeys(range(CURVE_MAX + 1), 0)
    creature_curve = dict.fromkeys(range(CURVE_MAX + 1), 0)
    total_value = 0
    color_pips = Counter()
    for line in deck:
        color_pips.update({color: count * line.quantity for color, count in pips(line.mana_cost).items()})
        if is_land(line):
            continue
        value = mana_value(line.mana_cost, line.type_line)
        total_value += value * line.quantity
        curve[min(value, CURVE_MAX)] += line.quantity
        if "Creature" in line.type_line.split(" // ")[0]:
            creature_curve[min(value, CURVE_MAX)] += line.quantity
    # tipo pela face da frente, como a contagem de terrenos (dupla face "Mágica // Terreno" conta como mágica)
    types = [(label, sum(line.quantity for line in deck if key in line.type_line.split(" // ")[0]))
             for key, label in TYPES]
    rarities = [(label, sum(line.quantity for line in deck if line.rarity == key)) for key, label in RARITIES]
    priced = [line for line in deck if line.price_paid_cents is not None]
    return DeckStats(
        cards=cards, lands=lands,
        average_mana_value=round(total_value / (cards - lands), 2) if cards > lands else 0.0,
        curve=curve, creature_curve=creature_curve,
        types=[(label, count) for label, count in types if count],
        pips={color: color_pips[color] for color in COLORS if color_pips[color]},
        rarities=[(label, count) for label, count in rarities if count],
        proxies=sum(line.quantity for line in deck if line.is_proxy),
        custom=sum(line.quantity for line in deck if line.custom_card_id or line.custom_print_id),
        paid_cents=sum(line.price_paid_cents * line.quantity for line in priced),
        priced_cards=sum(line.quantity for line in priced),
    )


# ---------- grupos por tipo (lista do deck e exportação) ----------
# ordem de exibição dos grupos
TYPE_GROUPS = (("creature", "Creature", "Criaturas"), ("planeswalker", "Planeswalker", "Planeswalkers"),
               ("battle", "Battle", "Batalhas"), ("instant", "Instant", "Mágicas instantâneas"),
               ("sorcery", "Sorcery", "Feitiços"), ("artifact", "Artifact", "Artefatos"),
               ("enchantment", "Enchantment", "Encantamentos"), ("land", "Land", "Terrenos"))
OTHER_GROUP = ("other", "Outras")
# cada carta entra em um grupo só, pelo primeiro tipo desta ordem que ela tiver: criatura artefato vai para
# criaturas e terreno artefato para terrenos
_PRIORITY = ("creature", "planeswalker", "battle", "instant", "sorcery", "land", "artifact", "enchantment")
_WORDS = {key: word for key, word, _ in TYPE_GROUPS}


def type_group(type_line: str) -> str:
    """Grupo da carta pela face da frente. Terreno criatura (Dryad Arbor) fica em criaturas."""
    front = type_line.split(" // ")[0]
    return next((key for key in _PRIORITY if _WORDS[key] in front), OTHER_GROUP[0])


def group_by_type(lines: list[DeckCard]) -> list[tuple[str, str, list[DeckCard]]]:
    """[(chave, título, linhas)] na ordem dos grupos, só os que têm cartas."""
    labels = [(key, label) for key, _, label in TYPE_GROUPS] + [OTHER_GROUP]
    return [(key, label, group) for key, label in labels
            if (group := [line for line in lines if type_group(line.type_line) == key])]


# ---------- fontes de mana dos terrenos ----------
BASIC_TYPES = {"Plains": "W", "Island": "U", "Swamp": "B", "Mountain": "R", "Forest": "G"}
_ADD = re.compile(r"\badd\b[^.]*", re.I)
_FETCH = re.compile(r"search your library for (?:an? |up to \w+ )?([^.]*?)cards?\b", re.I)


def land_colors(type_line: str, text: str, deck_basics: set[str] = frozenset()) -> set[str]:
    """Cores (WUBRG e C) que o terreno gera. Lê os tipos básicos, as frases "Add ..." e as de buscar terreno
    ("search your library for a Forest or Plains card"). Buscar "basic land" vale pelas cores dos básicos do deck."""
    colors = {color for name, color in BASIC_TYPES.items() if name in type_line}
    for clause in _ADD.findall(text):
        lower = clause.lower()
        if "any color" in lower or "any one color" in lower or "any type" in lower:
            colors |= set(COLORS)
        colors |= {s for s in _SYMBOL.findall(clause.upper()) if s in COLORS + "C"}
    for target in _FETCH.findall(text):
        found = {color for name, color in BASIC_TYPES.items() if name.lower() in target.lower()}
        colors |= found or (set(deck_basics) if "basic land" in target.lower() else set())
    if "Wastes" in type_line:
        colors.add("C")
    return colors


def land_sources(lines: list[DeckCard], texts: dict[int, str]) -> dict[str, int]:
    """Quantos terrenos do deck geram cada cor. `texts`: id da linha -> texto de regras (do Scryfall)."""
    deck = [line for line in lines if line.section in DECK_SECTIONS and is_land(line)]
    basics = {color for line in deck if "Basic" in line.type_line
              for name, color in BASIC_TYPES.items() if name in line.type_line}
    counts = Counter()
    for line in deck:
        # Wastes é "Basic Land" sem subtipo: sem o texto do Scryfall, reconhece pelo nome
        extra = {"C"} if line.card_name == "Wastes" else set()
        for color in land_colors(line.type_line, texts.get(line.id, ""), basics) | extra:
            counts[color] += line.quantity
    return {color: counts[color] for color in COLORS + "C" if counts[color]}


# ---------- probabilidades ----------
OPENING_HAND = 7


def library(lines: list[DeckCard]) -> list[DeckCard]:
    """Cartas que vão para o grimório: o principal (o comandante começa na zona de comando)."""
    return [line for line in lines if line.section == "main"]


def at_least_one(deck_size: int, copies: int, seen: int) -> float:
    """Chance de ver pelo menos uma das `copies` cartas entre as `seen` primeiras do grimório."""
    if copies <= 0 or deck_size <= 0:
        return 0.0
    seen = min(seen, deck_size)
    return 1 - math.comb(deck_size - copies, seen) / math.comb(deck_size, seen)


def exactly(deck_size: int, copies: int, seen: int, k: int) -> float:
    seen = min(seen, deck_size)
    if k > copies or k > seen or seen - k > deck_size - copies:
        return 0.0
    return math.comb(copies, k) * math.comb(deck_size - copies, seen - k) / math.comb(deck_size, seen)


def opening_lands(lines: list[DeckCard]) -> dict[int, float]:
    """Chance de abrir a mão de 7 com 0, 1, ... 7 terrenos."""
    deck = library(lines)
    size = sum(line.quantity for line in deck)
    lands = sum(line.quantity for line in deck if is_land(line))
    return {k: exactly(size, lands, OPENING_HAND, k) for k in range(OPENING_HAND + 1)}


def cards_seen(turn: int, on_the_play: bool) -> int:
    """Cartas vistas até o turno `turn`: a mão de 7 mais uma compra por turno (quem começa não compra no 1º)."""
    return OPENING_HAND + turn - (1 if on_the_play else 0)
