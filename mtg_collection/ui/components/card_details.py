from nicegui import ui

from mtg_collection.models import Card
from mtg_collection.ui import formatting


def open_card_details(card: Card) -> None:
    """Abre um diálogo com os detalhes completos da carta."""
    with ui.dialog() as dialog, ui.card().classes("max-w-3xl"):
        with ui.row().classes("no-wrap gap-6"):
            if card.image_large:
                ui.image(card.image_large).classes("w-72 rounded-xl")
            with ui.column().classes("gap-1"):
                ui.label(card.name).classes("text-xl font-bold")
                ui.label(card.mana_cost).classes("text-gray-500")
                ui.label(card.type_line).classes("font-medium")
                ui.label(f"{card.set_name} ({card.set_code}) #{card.collector_number}, {card.rarity}") \
                    .classes("text-sm text-gray-500")
                ui.label(card.oracle_text).classes("whitespace-pre-line mt-2")
                ui.label(f"{formatting.price(card.price_usd, 'USD')}   {formatting.price(card.price_eur, 'EUR')}") \
                    .classes("mt-2")
                if card.scryfall_uri:
                    ui.link("Ver no Scryfall", card.scryfall_uri, new_tab=True)
        ui.button("Fechar", on_click=dialog.close).props("flat").classes("self-end")
    dialog.on("hide", dialog.delete)  # remove do DOM ao fechar
    dialog.open()
