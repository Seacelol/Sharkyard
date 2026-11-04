"""Monta consultas na sintaxe do Scryfall a partir de filtros. Puro: sem API e sem interface.

Referência da sintaxe: https://scryfall.com/docs/syntax
"""
import re
from dataclasses import dataclass, field

OPERATORS = ("=", "!=", "<", "<=", ">", ">=")
COLOR_ORDER = "wubrg"
_SAFE_WORD = re.compile(r"[\w'\-,.!?]+")


@dataclass
class Comparison:
    """Filtro numérico da tela (operador + valor), como mana value ou poder."""
    op: str = ">="
    value: str = ""

    def clause(self, keyword: str) -> str:
        """Trecho da consulta ("pow>=3"), ou "" sem valor. Operador desconhecido vira "=" para não quebrar a busca."""
        value = self.value.strip().replace(" ", "")
        if not value:
            return ""
        op = self.op if self.op in OPERATORS else "="
        return f"{keyword}{op}{value}"


@dataclass
class SearchFilters:
    """Tudo que a busca avançada permite escolher. Campo vazio não entra na consulta."""
    name: str = ""
    oracle_text: str = ""
    types: list[tuple[str, bool]] = field(default_factory=list)  # (tipo, True = é / False = não é)
    colors: set[str] = field(default_factory=set)  # letras de "wubrg" e/ou "c" (incolor)
    color_mode: str = ">="  # "=" exatamente, ">=" incluindo, "<=" no máximo
    identity: set[str] = field(default_factory=set)
    mana_cost: str = ""
    mana_value: Comparison = field(default_factory=Comparison)
    power: Comparison = field(default_factory=Comparison)
    toughness: Comparison = field(default_factory=Comparison)
    loyalty: Comparison = field(default_factory=Comparison)
    format: str = ""
    legality: str = "legal"  # "legal", "banned" ou "restricted"
    sets: list[str] = field(default_factory=list)
    rarities: list[str] = field(default_factory=list)
    artist: str = ""
    flavor_text: str = ""
    price_currency: str = "usd"
    price: Comparison = field(default_factory=lambda: Comparison("<="))
    language: str = ""  # "" = padrão do Scryfall (inglês), "any" = todos
    order: str = ""
    direction: str = ""
    all_prints: bool = False


def build_query(f: SearchFilters) -> str:
    """Junta os filtros preenchidos numa consulta do Scryfall (separados por espaço = E)."""
    parts = [
        _words(f.name),
        _phrase("o", f.oracle_text),
        " ".join(("" if include else "-") + _keyword("t", name) for name, include in f.types if name.strip()),
        _colors("c", f.colors, f.color_mode),
        _colors("id", f.identity, "<="),
        f"m:{f.mana_cost.replace(' ', '')}" if f.mana_cost.strip() else "",
        f.mana_value.clause("mv"),
        f.power.clause("pow"),
        f.toughness.clause("tou"),
        f.loyalty.clause("loy"),
        _legality(f.format, f.legality),
        _any_of("s", f.sets),
        _any_of("r", f.rarities),
        _phrase("a", f.artist),
        _phrase("ft", f.flavor_text),
        f.price.clause(f.price_currency) if f.price_currency in ("usd", "eur", "tix") else "",
        f"lang:{f.language}" if f.language else "",
        f"order:{f.order}" if f.order else "",
        f"direction:{f.direction}" if f.direction in ("asc", "desc") else "",
        "unique:prints" if f.all_prints else "",
    ]
    return " ".join(p for p in parts if p)


def _clean(text: str) -> str:
    return text.replace('"', "").strip()


def _quote(value: str) -> str:
    return value if _SAFE_WORD.fullmatch(value) else f'"{value}"'


def _keyword(keyword: str, value: str) -> str:
    value = _clean(value)
    return f"{keyword}:{_quote(value)}" if value else ""


def _phrase(keyword: str, text: str) -> str:
    return _keyword(keyword, " ".join(text.split()))


def _words(text: str) -> str:
    """Palavras soltas buscam no nome da carta. Termos com caracteres especiais vão entre aspas."""
    return " ".join(_quote(word) for word in _clean(text).split() if word)


def _colors(keyword: str, selected: set[str], mode: str) -> str:
    letters = "".join(c for c in COLOR_ORDER if c in selected)
    if letters:  # "incolor" junto com cores seria contraditório: as cores prevalecem
        return f"{keyword}{mode if mode in ('=', '>=', '<=') else '>='}{letters}"
    return f"{keyword}=c" if "c" in selected else ""


def _legality(format_key: str, legality: str) -> str:
    if not format_key:
        return ""
    keyword = {"legal": "f", "banned": "banned", "restricted": "restricted"}.get(legality, "f")
    return f"{keyword}:{format_key}"


def _any_of(keyword: str, values: list[str]) -> str:
    clauses = [f"{keyword}:{v.strip().lower()}" for v in values if v.strip()]
    if len(clauses) > 1:
        return "(" + " OR ".join(clauses) + ")"
    return clauses[0] if clauses else ""
