"""Miniatura de carta para grades de resultado."""
from collections.abc import Callable

from nicegui import ui

from mtg_collection.models import Card


def card_tile(card: Card, on_click: Callable[[Card], None]) -> ui.card:
    """Miniatura da carta usada em grades de resultado."""
    with ui.card().tight().mark("card-tile") \
            .classes("cursor-pointer hover:shadow-xl transition-shadow min-w-0 overflow-hidden") as tile:
        tile.on("click", lambda: on_click(card))
        if card.image_normal:
            ui.image(card.image_normal).classes("rounded-t")
        with ui.card_section().classes("py-2 w-full min-w-0"):
            ui.label(card.display_name).classes("font-medium leading-snug line-clamp-2 break-words w-full")
            ui.label(f"{card.set_code} #{card.collector_number}").classes("text-xs text-gray-500")
    return tile
