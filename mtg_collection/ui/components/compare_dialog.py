"""Compara duas versões do deck: o que entrou, o que saiu e o que mudou de quantidade."""
from nicegui import ui

from mtg_collection import database
from mtg_collection.models import Deck
from mtg_collection.services import decks
from mtg_collection.ui.components.deck_dialog import SECTION_LABELS
from mtg_collection.ui.components.dialogs import close_dialog


def open_compare_dialog(user_id: int, deck: Deck) -> None:
    """Começa comparando outra versão com a atual. Precisa de duas versões ou mais (o menu só habilita assim)."""
    with database.session() as s:
        versions = decks.list_versions(s, user_id, deck.id)
    options = {v.id: v.name for v in versions}
    other = next(v.id for v in versions if v.id != deck.version_id)
    with ui.context.client.content, ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl gap-3"):
        ui.label("Comparar versões").classes("text-lg font-bold")
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            a = ui.select(options, value=other, label="De").props("outlined dense options-dense") \
                .classes("grow").mark("compare-a")
            ui.icon("arrow_forward").classes("text-gray-500 shrink-0")
            b = ui.select(options, value=deck.version_id, label="Para").props("outlined dense options-dense") \
                .classes("grow").mark("compare-b")
        result = ui.column().classes("w-full gap-3 max-h-[60vh] overflow-y-auto").mark("compare-result")

        def group(title: str, changes: list[decks.Change], marker: str) -> None:
            if not changes:
                return
            with ui.column().classes("w-full gap-0").mark(marker):
                ui.label(title).classes("text-xs font-bold uppercase tracking-wider text-gray-500 mb-1")
                for change in changes:
                    sign = "+" if change.delta > 0 else "−"
                    color = "text-green-700" if change.delta > 0 else "text-red-700"
                    where = "" if change.section == "main" else f" ({SECTION_LABELS[change.section]})"
                    with ui.row().classes("w-full items-center gap-2 no-wrap py-1 border-b border-gray-100"):
                        ui.label(f"{sign}{abs(change.delta)}").classes(f"w-10 text-right font-semibold {color}")
                        ui.label(change.card_name + where).classes("grow text-sm truncate")
                        ui.label(f"{change.before} → {change.after}").classes("text-xs text-gray-500 shrink-0")

        def render() -> None:
            result.clear()
            with result:
                if a.value == b.value:
                    ui.label("Escolha duas versões diferentes.").classes("text-sm text-gray-500")
                    return
                with database.session() as s:
                    changes = decks.compare_versions(s, user_id, deck.id, a.value, b.value)
                if not changes:
                    ui.label("As duas versões têm as mesmas cartas.").classes("text-sm text-gray-500")
                    return
                added = sum(c.delta for c in changes if c.delta > 0)
                removed = -sum(c.delta for c in changes if c.delta < 0)
                ui.label(f"{added} carta(s) a mais e {removed} a menos em \"{options[b.value]}\".") \
                    .classes("text-sm text-gray-700").mark("compare-summary")
                group("Entraram", [c for c in changes if c.before == 0], "compare-in")
                group("Saíram", [c for c in changes if c.after == 0], "compare-out")
                group("Mudou a quantidade", [c for c in changes if c.before and c.after], "compare-changed")

        a.on_value_change(render)
        b.on_value_change(render)
        render()
        with ui.row().classes("w-full justify-end"):
            ui.button("Fechar", on_click=lambda: close_dialog(dialog)).props("flat no-caps")
    dialog.on("hide", lambda: close_dialog(dialog))
    dialog.open()
