"""Painel de estatísticas da versão aberta do deck: números principais, curva de mana, tipos, cores e raridade.
Gráficos em HTML simples (barras finas, ponta arredondada, dica ao passar o mouse)."""
from decimal import Decimal

from nicegui import background_tasks, ui

from mtg_collection.models import Card, DeckCard
from mtg_collection.services import deck_stats, scryfall
from mtg_collection.services.deck_stats import CURVE_MAX, DECK_SECTIONS, DeckStats
from mtg_collection.ui import formatting as fmt
from mtg_collection.ui.components.controls import SEGMENTED

CREATURE = "#2a78d6"  # série 1 da paleta
OTHER = "#eb6834"  # série 2
SINGLE = "#2a78d6"
CURVE_HEIGHT = 140  # px da barra mais alta


def stat_tile(label: str, value: str, marker: str, hint: str = "") -> None:
    """Bloco com um número em destaque e o rótulo em cima."""
    with ui.column().classes("gap-0 rounded-lg bg-gray-50 px-3 py-2 min-w-0").mark(marker):
        ui.label(label).classes("text-xs text-gray-500 truncate w-full")
        ui.label(value).classes("text-xl font-semibold text-gray-900")
        if hint:
            ui.label(hint).classes("text-xs text-gray-500")


def curve_chart(stats: DeckStats) -> None:
    """Curva de mana em colunas empilhadas (criaturas embaixo, outras mágicas em cima), na escala da coluna
    mais alta. A última coluna junta CURVE_MAX ou mais."""
    peak = max(stats.curve.values(), default=0) or 1
    with ui.row().classes("items-center gap-4 text-xs text-gray-600"):  # legenda: duas séries
        for color, label in ((CREATURE, "Criaturas"), (OTHER, "Outras mágicas")):
            with ui.row().classes("items-center gap-1"):
                ui.element("span").classes("inline-block w-3 h-3 rounded-sm").style(f"background:{color}")
                ui.label(label)
    with ui.row().classes("w-full items-end no-wrap gap-2 border-b border-gray-300 pt-4") \
            .style(f"height:{CURVE_HEIGHT + 24}px").mark("curve-chart"):
        for value in range(CURVE_MAX + 1):
            total, creatures = stats.curve[value], stats.creature_curve[value]
            with ui.column().classes("grow basis-0 items-center gap-0 h-full justify-end min-w-0"):
                ui.label(str(total) if total else "").classes("text-xs text-gray-700 mb-0.5")
                with ui.column().classes("w-full max-w-10 gap-[2px] items-stretch"):
                    other = total - creatures
                    # segmento de cima com a ponta arredondada; 2px de espaço entre os dois
                    if other:
                        ui.element("div").classes("rounded-t").style(
                            f"height:{other / peak * CURVE_HEIGHT}px;background:{OTHER}")
                    if creatures:
                        ui.element("div").classes("" if other else "rounded-t").style(
                            f"height:{creatures / peak * CURVE_HEIGHT}px;background:{CREATURE}")
                if total:
                    ui.tooltip(f"Valor de mana {value}{'+' if value == CURVE_MAX else ''}: {creatures} criatura(s), "
                               f"{other} outra(s)")
    with ui.row().classes("w-full no-wrap gap-2 text-xs text-gray-500"):
        for value in range(CURVE_MAX + 1):
            ui.label(f"{value}+" if value == CURVE_MAX else str(value)).classes("grow basis-0 text-center")


def bar_list(rows: list[tuple[str, int]], total: int, marker: str, icons: dict[str, str] | None = None) -> None:
    """Barras horizontais de uma série só: rótulo, barra e número (com %)."""
    peak = max((count for _, count in rows), default=0) or 1
    with ui.column().classes("w-full gap-1.5").mark(marker):
        for label, count in rows:
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                with ui.row().classes("w-36 shrink-0 items-center gap-1 no-wrap"):
                    if icons and label in icons:
                        ui.html(icons[label], sanitize=False).classes("shrink-0")
                    ui.label(label).classes("text-sm text-gray-700 truncate")
                with ui.element("div").classes("grow h-3"):
                    ui.element("div").classes("h-full rounded-r").style(
                        f"width:{count / peak * 100}%;background:{SINGLE};min-width:2px")
                share = f" ({count / total:.0%})" if total else ""
                ui.label(f"{count}{share}").classes("w-20 shrink-0 text-right text-sm text-gray-700")


def card_value(card: Card, foil: bool) -> Decimal | None:
    prices = card.prices
    return (prices.usd_foil or prices.usd) if foil else (prices.usd or prices.usd_foil)


async def fetch_cards(lines: list[DeckCard]) -> dict[int, Card]:
    """Dados do Scryfall de cada linha do deck (edição da linha; versão personalizada usa a carta), numa leva.
    id da linha -> Card. Erro do Scryfall sobe como ScryfallError."""
    deck = [line for line in lines if line.section in DECK_SECTIONS and not line.custom_card_id]
    ids = [{"id": line.scryfall_id} if line.scryfall_id else {"oracle_id": line.oracle_id} for line in deck]
    cards = await scryfall.client.find_cards(ids) if ids else []
    return {line.id: card for line, card in zip(deck, cards, strict=True) if card}


def estimated_value(lines: list[DeckCard], cards: dict[int, Card]) -> tuple[Decimal, int]:
    """(total em dólar, cópias sem preço)."""
    total, missing = Decimal(0), 0
    for line in lines:
        if line.section not in DECK_SECTIONS:
            continue
        card = cards.get(line.id)
        price = card_value(card, line.foil) if card else None
        if price is None:
            missing += line.quantity
        else:
            total += price * line.quantity
    return total, missing


COLOR_NAMES = {"W": "Branco", "U": "Azul", "B": "Preto", "R": "Vermelho", "G": "Verde", "C": "Incolor"}


def render_sources(container: ui.element, stats: DeckStats, lines: list[DeckCard], cards: dict[int, Card]) -> None:
    """Fontes de mana dos terrenos ao lado da parte de cada cor nos custos (precisa do texto do Scryfall)."""
    texts = {line_id: "\n".join([card.oracle_text, *(f.oracle_text for f in card.faces)])
             for line_id, card in cards.items()}
    sources = deck_stats.land_sources(lines, texts)
    total_pips = sum(stats.pips.values())
    container.clear()
    with container:
        if not sources:
            ui.label("Não deu para saber que mana os terrenos geram.").classes("text-sm text-gray-500")
            return
        icons = {COLOR_NAMES[c]: fmt.symbols_html(f"{{{c}}}") for c in sources}
        bar_list([(COLOR_NAMES[c], n) for c, n in sources.items()], stats.lands, "stats-sources", icons)
        hints = [f"{COLOR_NAMES[c]}: {stats.pips.get(c, 0) / total_pips:.0%} dos símbolos"
                 for c in sources if c != "C" and total_pips]
        if hints:
            ui.label(" · ".join(hints)).classes("text-xs text-gray-500")
        ui.label("Um terreno que gera várias cores conta em cada uma; a porcentagem é sobre os terrenos.") \
            .classes("text-xs text-gray-500")


def probability_section(lines: list[DeckCard]) -> None:
    """Mão inicial (quantos terrenos) e chance de ter uma carta até certo turno."""
    deck = deck_stats.library(lines)
    size = sum(line.quantity for line in deck)
    if not size:
        return
    section = "text-xs font-bold uppercase tracking-wider text-gray-500 mt-2"
    ui.label("Mão inicial").classes(section)
    dist = deck_stats.opening_lands(lines)
    two_to_four = sum(dist[k] for k in (2, 3, 4))
    ui.label(f"Chance de abrir com 2 a 4 terrenos: {two_to_four:.0%}").classes("text-sm text-gray-700") \
        .mark("hand-two-to-four")
    rows = [(fmt.plural(k, "terreno", "terrenos"), round(p * 1000)) for k, p in dist.items()]
    peak = max(count for _, count in rows) or 1
    with ui.column().classes("w-full gap-1").mark("hand-distribution"):
        for (label, permille), p in zip(rows, dist.values(), strict=True):
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.label(label).classes("w-28 shrink-0 text-sm text-gray-700")
                with ui.element("div").classes("grow h-3"):
                    ui.element("div").classes("h-full rounded-r").style(
                        f"width:{permille / peak * 100}%;background:{SINGLE};min-width:2px")
                ui.label(f"{p:.1%}".replace(".", ",")).classes("w-16 shrink-0 text-right text-sm text-gray-700")

    ui.label("Chance de ter uma carta").classes(section)
    options = {line.oracle_id: line.card_name for line in sorted(deck, key=lambda x: x.card_name)}
    copies = {}
    for line in deck:
        copies[line.oracle_id] = copies.get(line.oracle_id, 0) + line.quantity
    with ui.row().classes("w-full items-center gap-2"):
        card = ui.select(options, value=next(iter(options)), with_input=True, label="Carta") \
            .props("outlined dense options-dense").classes("grow min-w-[12rem]").mark("draw-card")
        turn = ui.number("Até o turno", value=3, min=1, max=20, step=1, format="%.0f") \
            .props("outlined dense").classes("w-28").mark("draw-turn")
        play = ui.toggle({True: "Começando", False: "Comprando"}, value=True).props(SEGMENTED) \
            .mark("draw-play")
    result = ui.label().classes("text-sm text-gray-700").mark("draw-result")

    def update() -> None:
        turns = int(turn.value or 1)
        seen = deck_stats.cards_seen(turns, play.value)
        count = copies.get(card.value, 0)
        chance = deck_stats.at_least_one(size, count, seen)
        result.text = (f"{chance:.0%} de ter pelo menos uma de {fmt.plural(count, 'cópia', 'cópias')}"
                       f" até o turno {turns} ({seen} cartas vistas, sem contar efeitos de comprar ou buscar).")

    for widget in (card, turn, play):
        widget.on_value_change(update)
    update()


def render_stats(stats: DeckStats, missing_in_collection: int,
                 lines: list[DeckCard]) -> tuple[ui.label, ui.element]:
    """Desenha o painel no contexto atual. Devolve (rótulo do valor estimado, área das fontes de mana), que são
    preenchidos depois com os dados do Scryfall, sem travar a página."""
    if not stats.cards:
        ui.label("Sem cartas no deck principal para calcular.").classes("text-gray-500 py-8 self-center")
        return ui.label(), ui.column()
    with ui.element("div").classes("grid gap-2 w-full grid-cols-2 sm:grid-cols-4"):
        stat_tile("Cartas", str(stats.cards), "stat-cards")
        stat_tile("Terrenos", str(stats.lands), "stat-lands",
                  f"{stats.lands / stats.cards:.0%} do deck")
        stat_tile("Valor de mana médio", f"{stats.average_mana_value:.2f}".replace(".", ","), "stat-average",
                  "sem terrenos")
        stat_tile("Faltam na coleção", str(missing_in_collection), "stat-missing", "com sideboard e companheiro")
        stat_tile("Proxies", str(stats.proxies), "stat-proxies")
        stat_tile("Personalizadas", str(stats.custom), "stat-custom")
        stat_tile("Pago", fmt.brl(stats.paid_cents) if stats.priced_cards else "-", "stat-paid",
                  f"{fmt.plural(stats.priced_cards, 'carta', 'cartas')} com preço" if stats.priced_cards else "")
        with ui.column().classes("gap-0 rounded-lg bg-gray-50 px-3 py-2 min-w-0").mark("stat-value"):
            ui.label("Valor estimado (Scryfall)").classes("text-xs text-gray-500 truncate w-full")
            value = ui.label("...").classes("text-xl font-semibold text-gray-900")
            ui.label("em dólar, edição de cada carta").classes("text-xs text-gray-500")

    section = "text-xs font-bold uppercase tracking-wider text-gray-500 mt-2"
    ui.label("Curva de mana").classes(section)
    curve_chart(stats)
    with ui.element("div").classes("grid gap-6 w-full grid-cols-1 md:grid-cols-2"):
        with ui.column().classes("gap-2"):
            ui.label("Tipos").classes(section)
            bar_list(stats.types, stats.cards, "stats-types")
        with ui.column().classes("gap-2"):
            ui.label("Símbolos de mana nos custos").classes(section)
            names = {"W": "Branco", "U": "Azul", "B": "Preto", "R": "Vermelho", "G": "Verde"}
            rows = [(names[color], count) for color, count in stats.pips.items()]
            icons = {names[c]: fmt.symbols_html(f"{{{c}}}") for c in stats.pips}
            if rows:
                bar_list(rows, sum(stats.pips.values()), "stats-colors", icons)
            else:
                ui.label("Nenhum símbolo colorido.").classes("text-sm text-gray-500")
            ui.label("Raridade").classes(section)
            bar_list(stats.rarities, stats.cards, "stats-rarity")
    with ui.element("div").classes("grid gap-6 w-full grid-cols-1 md:grid-cols-2"):
        with ui.column().classes("gap-2"):
            ui.label("Fontes de mana (terrenos)").classes(section)
            sources = ui.column().classes("w-full gap-1").mark("stats-sources-area")
            with sources:
                ui.label("Carregando...").classes("text-sm text-gray-500")
        with ui.column().classes("gap-2"):
            probability_section(lines)
    return value, sources


class StatsLoader:
    """Valor e fontes de mana vêm do Scryfall em segundo plano. Cada + ou - com a aba aberta começa outra busca,
    e elas podem terminar fora de ordem: só a mais recente escreve no painel (as outras são descartadas)."""

    def __init__(self):
        self._version = 0

    def start(self, value: ui.label, sources: ui.element, stats: DeckStats, lines: list[DeckCard]) -> None:
        self._version += 1
        background_tasks.create(self._load(self._version, value, sources, stats, lines), name="deck-stats")

    async def _load(self, version: int, value: ui.label, sources: ui.element, stats: DeckStats,
                    lines: list[DeckCard]) -> None:
        try:
            cards = await fetch_cards(lines)
        except scryfall.ScryfallError:
            cards = None
        if version != self._version or value.is_deleted:  # painel já foi refeito por uma busca mais nova
            return
        if cards is None:
            value.text = "indisponível"
            cards = {}  # sem texto: as fontes saem só pelos tipos básicos
        else:
            total, unpriced = estimated_value(lines, cards)
            value.text = f"US$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            if unpriced:
                with value:  # tarefa em segundo plano: o lugar do elemento novo precisa ser explícito
                    ui.tooltip(f"{fmt.plural(unpriced, 'carta sem preço', 'cartas sem preço')} no Scryfall")
        if not sources.is_deleted:
            render_sources(sources, stats, lines, cards)
