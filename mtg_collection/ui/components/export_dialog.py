"""Diálogo de exportação da versão aberta do deck: escolhe o formato, vê o resultado, copia ou baixa."""
from nicegui import ui

from mtg_collection.models import Deck, DeckCard
from mtg_collection.services import deck_export
from mtg_collection.ui.components.dialogs import close_dialog


def open_export_dialog(deck: Deck, lines: list[DeckCard]) -> None:
    """Exporta as linhas recebidas (a versão aberta). A prévia é o próprio conteúdo copiado ou baixado."""
    options = {key: f.label for key, f in deck_export.FORMATS.items()}
    custom = any(line.custom_card_id or line.custom_print_id for line in lines)
    with ui.context.client.content, ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl gap-3"):
        title = f"Exportar \"{deck.name}\"" + (f" · {deck.version_name}" if deck.version_count > 1 else "")
        ui.label(title).classes("text-lg font-bold")
        fmt = ui.select(options, value="texto", label="Formato").props("outlined dense options-dense") \
            .classes("w-full").mark("export-format")
        description = ui.label().classes("text-sm text-gray-600")
        preview = ui.textarea().props("outlined readonly rows=14").classes("w-full font-mono text-xs") \
            .mark("export-preview")
        if custom:
            ui.label("Cartas e edições personalizadas vão só pelo nome: outros sites não conhecem essas cartas.") \
                .classes("text-xs text-amber-800")

        def update() -> None:
            description.text = deck_export.FORMATS[fmt.value].description
            preview.value = deck_export.export(fmt.value, deck.name, lines)

        def copy() -> None:
            ui.clipboard.write(preview.value)
            ui.notify("Copiado.", type="positive")

        def download() -> None:
            chosen = deck_export.FORMATS[fmt.value]
            ui.download.content(preview.value, deck_export.filename(deck.name, deck.version_name, fmt.value),
                                media_type=f"{chosen.media_type}; charset=utf-8")

        fmt.on_value_change(update)
        update()
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Fechar", on_click=lambda: close_dialog(dialog)).props("flat no-caps")
            ui.button("Copiar", icon="content_copy", on_click=copy).props("outline no-caps").mark("export-copy")
            ui.button("Baixar arquivo", icon="download", on_click=download).props("unelevated no-caps") \
                .mark("export-download")
    dialog.on("hide", lambda: close_dialog(dialog))
    dialog.open()
