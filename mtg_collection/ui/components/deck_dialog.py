"""Diálogo para criar ou editar um deck: nome, formato, pasta, visibilidade, observações e capa."""
from collections.abc import Callable

from nicegui import background_tasks, ui

from mtg_collection import config, database
from mtg_collection.models import Deck
from mtg_collection.services import decks, folders, ranking
from mtg_collection.ui import formatting as fmt
from mtg_collection.ui.components.command_zone import CommandZone
from mtg_collection.ui.components.controls import SEGMENTED
from mtg_collection.ui.components.dialogs import close_dialog, confirm, limit
from mtg_collection.ui.components.folder_bar import NO_FOLDER
from mtg_collection.ui.components.image_picker import ImagePicker
from mtg_collection.ui.custom_images import ImageError, deck_cover_url, discard_if_unused, discard_unused, save_image

FORMATS = {"": "Sem formato", **fmt.FORMAT_LABELS, "casual": "Casual"}
SECTION_LABELS = {"main": "principal", "sideboard": "sideboard", "commander": "comandante",
                  "companion": "companheiro", "maybe": "talvez"}
COVER_MODES = {"none": "Sem capa", "card": "Carta do deck", "upload": "Enviar imagem"}


def deck_cover_src(deck: Deck) -> str | None:
    """Imagem de capa: a enviada tem prioridade sobre a arte de carta."""
    return deck_cover_url(deck.cover_filename) or deck.cover_art_url


def open_deck_dialog(user_id: int, deck: Deck | None, folder_options: dict, on_saved: Callable[[Deck], None],
                     on_deleted: Callable[[], None] | None = None, default_folder: int | None = None) -> None:
    """Cria (deck=None) ou edita um deck. Dados, zona de comando e capa são gravados na mesma sessão: se algo
    falhar, nada muda. A imagem de capa antiga só é apagada depois de gravar e se ninguém mais a usar."""
    pending: dict[str, bytes] = {}
    cards = []
    if deck:
        with database.session() as s:
            cards = decks.list_cards(s, user_id, deck.id)
    card_options = {c.id: c.card_name + ("" if c.section == "main" else f" ({SECTION_LABELS[c.section]})")
                    for c in cards}
    current_card = next((c.id for c in cards if deck and deck.cover_art_url and
                         deck.cover_art_url in (c.image_art_crop, c.image_normal)), None)
    initial_mode = "upload" if deck and deck.cover_filename else "card" if deck and deck.cover_art_url else "none"

    with ui.context.client.content, ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl gap-3"):
        ui.label("Editar deck" if deck else "Novo deck").classes("text-lg font-bold")
        name = ui.input("Nome do deck", value=deck.name if deck else "") \
            .props(f"outlined dense autofocus {limit(config.DECK_NAME_MAX)}").classes("w-full").mark("deck-name")
        with ui.element("div").classes("w-full grid gap-3 grid-cols-1 sm:grid-cols-2"):
            format_select = ui.select(FORMATS, value=deck.format if deck and deck.format in FORMATS else "",
                                      label="Formato", with_input=True) \
                .props("outlined dense options-dense").classes("grow").mark("deck-format")
            folder = ui.select(folder_options, value=(deck.folder_id if deck else default_folder) or NO_FOLDER,
                               label="Pasta").props("outlined dense options-dense").classes("grow").mark("deck-folder")
        zone = CommandZone(format_select.value or "")
        format_select.on_value_change(lambda e: zone.set_format(e.value or ""))
        visible = ui.switch("Visível para os amigos", value=bool(deck and deck.visibility == "friends")) \
            .mark("deck-visible")
        notes = ui.textarea("Observações", value=deck.notes if deck else "").props("outlined dense autogrow") \
            .classes("w-full").mark("deck-notes")

        ui.label("Capa").classes("text-xs font-bold uppercase tracking-wider text-gray-500 mt-1")
        with ui.element("div").classes("w-full flex flex-col sm:flex-row items-start gap-4"):
            preview = ui.image(deck_cover_src(deck) if deck and initial_mode != "none" else "") \
                .props("no-spinner fit=cover").classes("w-full sm:w-44 h-32 shrink-0 rounded-lg bg-gray-100") \
                .mark("deck-preview")
            with ui.column().classes("grow gap-2 w-full sm:w-auto"):
                mode = ui.toggle(COVER_MODES, value=initial_mode).props(SEGMENTED).mark("deck-cover-mode")
                card_area = ui.column().classes("w-full gap-1")
                with card_area:
                    if card_options:
                        card_select = ui.select(card_options, value=current_card, label="Carta",
                                                with_input=True) \
                            .props("outlined dense options-dense").classes("w-full").mark("deck-cover-card")
                    else:
                        card_select = None
                        ui.label("Adicione cartas ao deck para escolher uma delas como capa.") \
                            .classes("text-sm text-gray-500")
                upload_area = ui.column().classes("w-full gap-1")
                with upload_area:
                    ui.label("PNG, JPG ou WebP até 8 MB.").classes("text-xs text-gray-500")

                    def picked(data: bytes, url: str) -> None:
                        pending["data"] = data
                        preview.set_source(url)

                    ImagePicker(picked, marker="deck-cover")

        def card_art(card_id) -> str:
            card = next((c for c in cards if c.id == card_id), None)
            return (card.image_art_crop or card.image_normal or "") if card else ""

        def update_cover_ui() -> None:
            card_area.visible = mode.value == "card"
            upload_area.visible = mode.value == "upload"
            if mode.value == "none":
                preview.set_source("")
            elif mode.value == "card":
                preview.set_source(card_art(card_select.value) if card_select else "")
            elif "data" not in pending:
                preview.set_source(deck_cover_url(deck.cover_filename) if deck and deck.cover_filename else "")

        mode.on_value_change(update_cover_ui)
        if card_select:
            card_select.on_value_change(update_cover_ui)
        update_cover_ui()

        error = ui.label().classes("text-sm text-red-600").mark("deck-error")
        error.visible = False

        def save() -> None:
            new_file = None
            try:
                if mode.value == "card" and (card_select is None or card_select.value is None):
                    raise decks.DeckError("Escolha a carta da capa.")
                if mode.value == "upload" and "data" not in pending and not (deck and deck.cover_filename):
                    raise decks.DeckError("Escolha a imagem da capa.")
                if "data" in pending and mode.value == "upload":
                    new_file = save_image(pending["data"])
                fields = dict(name=name.value or "", format=format_select.value or "", notes=notes.value or "",
                              folder_id=None if folder.value == NO_FOLDER else folder.value,
                              visibility="friends" if visible.value else "private")
                with database.session() as s:
                    saved = decks.update_deck(s, user_id, deck.id, **fields) if deck else \
                        decks.create_deck(s, user_id, **fields)
                    zone.save(s, user_id, saved.id)
                    old_file = None
                    if mode.value == "none":
                        saved, old_file = decks.clear_cover(s, user_id, saved.id)
                    elif mode.value == "card":
                        saved, old_file = decks.set_cover_card(s, user_id, saved.id, card_select.value)
                    elif new_file:
                        saved, old_file = decks.set_cover_image(s, user_id, saved.id, new_file)
            except (decks.DeckError, folders.FolderError, ImageError) as e:
                discard_if_unused(new_file)
                error.text, error.visible = str(e), True
                return
            discard_if_unused(old_file)
            ui.notify("Deck salvo." if deck else f"Deck \"{saved.name}\" criado.", type="positive")
            on_saved(saved)  # antes de fechar: fechar apaga o diálogo e o contexto dele
            close_dialog(dialog)

        def ask_delete() -> None:
            def delete() -> None:
                with database.session() as s:
                    files = decks.delete_decks(s, user_id, [deck.id])
                discard_unused(files)
                ui.notify(f"Deck \"{deck.name}\" apagado.", type="positive")
                if on_deleted:
                    on_deleted()
                close_dialog(dialog)

            with database.session() as s:
                wins = ranking.win_count(s, deck.id)
            extra = f" As {wins} vitórias dele saem do ranking." if wins else ""
            confirm(f"Apagar o deck \"{deck.name}\"?", delete,
                    detail=f"As cartas da sua coleção não são afetadas.{extra}")

        with ui.row().classes("w-full items-center justify-between mt-2"):
            if deck:
                ui.button("Apagar deck", icon="delete", on_click=ask_delete).props("flat no-caps color=negative") \
                    .mark("deck-delete")
            else:
                ui.element("div")
            with ui.row().classes("gap-2"):
                ui.button("Cancelar", on_click=lambda: close_dialog(dialog)).props("flat no-caps")
                ui.button("Salvar" if deck else "Criar deck", on_click=save).props("unelevated no-caps") \
                    .mark("deck-save")

    dialog.on("hide", lambda: close_dialog(dialog))
    dialog.open()
    # comandante e companheiro atuais: os dados completos vêm do Scryfall, com o diálogo já aberto
    background_tasks.create(zone.load(user_id, cards), name="deck-dialog-command-zone")
