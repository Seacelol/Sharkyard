"""Formatação de valores para exibição. Funções puras, sem NiceGUI."""
import html
import re
from datetime import date
from decimal import Decimal

SYMBOL_URL = "https://svgs.scryfall.io/card-symbols/{}.svg"  # *.scryfall.io não tem limite de requisições
_SYMBOL = re.compile(r"\{([^}]+)\}")
_REMINDER = re.compile(r"\(([^()]*)\)")

RARITY_LABELS = {"common": "Comum", "uncommon": "Incomum", "rare": "Rara", "mythic": "Mítica",
                 "special": "Especial", "bonus": "Bônus"}
RARITY_COLORS = {"common": "#1f2937", "uncommon": "#64748b", "rare": "#b08d1a", "mythic": "#d9480f",
                 "special": "#7c3aed", "bonus": "#7c3aed"}

# Ordem de exibição dos formatos; formatos que o Scryfall adicionar depois aparecem no fim
FORMAT_LABELS = {
    "standard": "Standard", "pioneer": "Pioneer", "modern": "Modern", "legacy": "Legacy",
    "vintage": "Vintage", "commander": "Commander", "oathbreaker": "Oathbreaker", "pauper": "Pauper",
    "paupercommander": "Pauper EDH", "duel": "Duel", "predh": "PreDH", "premodern": "Premodern",
    "oldschool": "Old School", "historic": "Historic", "timeless": "Timeless", "alchemy": "Alchemy",
    "brawl": "Brawl", "standardbrawl": "Std. Brawl", "gladiator": "Gladiator", "penny": "Penny",
    "future": "Future",
}
LEGALITY_LABELS = {"legal": "Legal", "banned": "Banida", "restricted": "Restrita", "not_legal": "Não legal"}

LANG_LABELS = {"en": "Inglês", "pt": "Português", "es": "Espanhol", "fr": "Francês", "de": "Alemão",
               "it": "Italiano", "ja": "Japonês", "ko": "Coreano", "ru": "Russo", "zhs": "Chinês simp.",
               "zht": "Chinês trad.", "ph": "Phyrexiano"}


def price(value: Decimal | None, symbol: str) -> str:
    return f"{symbol} {value:.2f}" if value is not None else f"{symbol} -"


def highlight(text: str, term: str, css_class: str = "text-orange-600") -> str:
    """HTML seguro do texto com a primeira ocorrência de `term` destacada (sem diferenciar maiúsculas)."""
    term = term.strip()
    start = text.lower().find(term.lower()) if term else -1
    if start < 0:
        return html.escape(text)
    end = start + len(term)
    return (f"{html.escape(text[:start])}<span class=\"{css_class}\">{html.escape(text[start:end])}</span>"
            f"{html.escape(text[end:])}")


def symbol_file(symbol: str) -> str:
    """Nome do arquivo SVG do Scryfall para um símbolo: 'W/U' -> 'WU', '2/W' -> '2W', '½' -> 'HALF'."""
    return {"½": "HALF", "∞": "INFINITY"}.get(symbol, symbol.replace("/", "").upper())


def symbols_html(text: str) -> str:
    """Escapa o texto e troca {W}, {2/U}, {T}... por ícones."""
    def to_img(match: re.Match) -> str:
        code = match.group(1)
        return (f'<img src="{SYMBOL_URL.format(html.escape(symbol_file(code)))}" alt="{{{html.escape(code)}}}" '
                f'title="{{{html.escape(code)}}}" class="mana-symbol">')
    return _SYMBOL.sub(to_img, html.escape(text, quote=False))


def rules_text_html(text: str) -> str:
    """Texto de regras com ícones e texto de lembrete (entre parênteses) em itálico."""
    escaped = symbols_html(text)
    return _REMINDER.sub(r'<span class="reminder">(\1)</span>', escaped)


def stats(power: str | None, toughness: str | None, loyalty: str | None, defense: str | None) -> str | None:
    """Números do canto da carta: poder/resistência, lealdade (planeswalker) ou defesa (batalha); None se não há."""
    if power is not None and toughness is not None:
        return f"{power}/{toughness}"
    if loyalty is not None:
        return f"Lealdade {loyalty}"
    if defense is not None:
        return f"Defesa {defense}"
    return None


def sorted_legalities(legalities: dict[str, str]) -> list[tuple[str, str, str]]:
    """[(rótulo do formato, status, rótulo do status)] na ordem de FORMAT_LABELS."""
    order = list(FORMAT_LABELS) + sorted(set(legalities) - set(FORMAT_LABELS))
    return [(FORMAT_LABELS.get(key, key.title()), status, LEGALITY_LABELS.get(status, status))
            for key in order if (status := legalities.get(key))]


def plural(count: int, singular: str, plural_form: str) -> str:
    return f"{count} {singular if count == 1 else plural_form}"


def brl(cents: int | None) -> str:
    """Centavos -> "R$ 1.234,56"."""
    if cents is None:
        return "-"
    reais, centavos = divmod(cents, 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{centavos:02d}"


def brl_input(cents: int | None) -> str:
    """Centavos -> texto para editar ("1234,56"); vazio se não tem preço."""
    return "" if cents is None else f"{cents // 100},{cents % 100:02d}"


def date_br(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else "-"
