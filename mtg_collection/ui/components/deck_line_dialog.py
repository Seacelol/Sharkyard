"""Diálogo para editar uma carta do deck: edição (inclusive personalizada), quantidade, seção, foil, proxy,
preço pago e observações."""
from collections.abc import Callable

from nicegui import ui

from mtg_collection import database
from mtg_collection.models import Card, CustomPrint, DeckCard
from mtg_collection.services import collection, custom_cards, decks, scryfall
from mtg_collection.ui import formatting as fmt
from mtg_collection.ui.components.custom_card_dialog import open_custom_card_dialog
from mtg_collection.ui.components.custom_print_dialog import open_custom_print_dialog
from mtg_collection.ui.components.deck_dialog import SECTION_LABELS
from mtg_collection.ui.components.dialogs import close_dialog, maybe_await
from mtg_collection.ui.components.entry_dialog import printing_label
from mtg_collection.ui.printings import CUSTOM_PREFIX, all_printings, custom_card

SECTION_OPTIONS = {key: label.capitalize() for key, label in SECTION_LABELS.items()}


def line_print_key(line: DeckCard) -> str:
    """Chave da impressão da linha no seletor de edições (versões personalizadas levam CUSTOM_PREFIX)."""
    return f"{CUSTOM_PREFIX}{line.custom_print_id}" if line.custom_print_id else (line.scryfall_id or "")


async def open_line_dialog(user_id: int, deck_id: int, line: DeckCard, on_change: Callable[[], object]) -> None:
    """Edita uma linha do deck. Carta personalizada não tem outras edições: o diálogo oferece editar a carta."""
    printings: dict[str, Card] = {}
    current_key = line_print_key(line)
    current_label = f"{line.set_name}" + (f" ({line.set_code})" if line.set_code else "") + \
        (f" #{line.collector_number}" if line.collector_number else "")

    with ui.context.client.content, ui.dialog() as dialog, ui.card().classes("w-full max-w-lg gap-3"):
        with ui.row().classes("w-full items-center gap-3 no-wrap"):
            if line.image_small:
                ui.image(line.image_small).props("no-spinner").classes("w-12 shrink-0 rounded")
            with ui.column().classes("gap-0 min-w-0"):
                ui.label(line.card_name).classes("text-lg font-bold truncate w-full")
                ui.label("Editar carta do deck").classes("text-sm text-gray-500")
        printing = None
        if line.custom_card_id:
            async def edited(saved, _keep) -> None:
                ui.notify("Carta personalizada salva.", type="positive")
                await maybe_await(on_change())
                close_dialog(dialog)

            def edit_custom() -> None:
                with database.session() as s:
                    custom = custom_cards.get(s, user_id, line.custom_card_id)
                open_custom_card_dialog(user_id, deck_id, custom, edited)

            ui.button("Editar carta personalizada", icon="edit", on_click=edit_custom) \
                .props("outline no-caps").mark("line-edit-custom")
        else:
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                printing = ui.select({current_key: current_label}, value=current_key, label="Edição",
                                     with_input=True).props("outlined dense options-dense").classes("grow") \
                    .mark("line-printing")
                new_version = ui.button(icon="add_photo_alternate").props("flat round dense") \
                    .tooltip("Nova versão personalizada (arte ou edição sua)").mark("line-new-version")
                new_version.disable()
        with ui.row().classes("w-full items-center gap-4"):
            quantity = ui.number("Quantidade", value=line.quantity, min=1, max=decks.MAX_QUANTITY, step=1,
                                 format="%.0f").props("outlined dense").classes("w-28").mark("line-quantity")
            section = ui.select(SECTION_OPTIONS, value=line.section, label="Seção") \
                .props("outlined dense options-dense").classes("w-36").mark("line-section")
            foil = ui.checkbox("Foil", value=line.foil).mark("line-foil")
            proxy = ui.checkbox("Proxy", value=line.is_proxy).mark("line-proxy")
        price = ui.input("Preço pago por unidade", value=fmt.brl_input(line.price_paid_cents), placeholder="0,00") \
            .props("outlined dense prefix=R$").classes("w-full").mark("line-price")
        notes = ui.textarea("Observações", value=line.notes).props("outlined dense autogrow").classes("w-full") \
            .mark("line-notes")
        error = ui.label().classes("text-sm text-red-600").mark("line-error")
        error.visible = False

        async def save() -> None:
            try:
                cents = collection.parse_price(price.value)
                qty = int(quantity.value or 0)
                if qty != quantity.value:
                    raise decks.DeckError("A quantidade deve ser um número inteiro.")
                chosen = printings.get(printing.value) if printing and printing.value != current_key else None
                with database.session() as s:
                    decks.update_line(s, user_id, deck_id, line.id, quantity=qty, section=section.value,
                                      foil=foil.value, is_proxy=proxy.value, price_paid_cents=cents,
                                      notes=notes.value or "", printing=chosen)
            except (collection.CollectionError, decks.DeckError) as e:
                error.text, error.visible = str(e), True
                return
            await maybe_await(on_change())  # antes de fechar: fechar apaga o diálogo e o contexto dele
            close_dialog(dialog)

        async def remove() -> None:
            with database.session() as s:
                decks.remove_line(s, user_id, deck_id, line.id)
            ui.notify(f"{line.card_name} saiu do deck.", type="positive")
            await maybe_await(on_change())
            close_dialog(dialog)

        with ui.row().classes("w-full items-center justify-between mt-2"):
            ui.button("Tirar do deck", icon="delete", on_click=remove).props("flat no-caps color=negative") \
                .mark("line-delete")
            with ui.row().classes("gap-2"):
                ui.button("Cancelar", on_click=lambda: close_dialog(dialog)).props("flat no-caps")
                ui.button("Salvar", on_click=save).props("unelevated no-caps").mark("line-save")

    dialog.on("hide", lambda: close_dialog(dialog))
    dialog.open()
    if printing is None:
        return

    # as edições carregam com o diálogo já aberto
    try:
        cards = await all_printings(user_id, line.oracle_id)
    except scryfall.ScryfallError:
        printing.props('hint="Não foi possível carregar as outras edições agora."')
        return
    printings.update({c.id: c for c in cards})
    official = [c for c in cards if not c.is_custom]

    def show_options(value: str) -> None:
        options = {key: printing_label(card) for key, card in printings.items()}
        options.setdefault(current_key, current_label)
        printing.set_options(options, value=value)

    def version_saved(custom: CustomPrint) -> None:
        base = printings.get(custom.base_scryfall_id or "") or official[0]
        key = f"{CUSTOM_PREFIX}{custom.id}"
        printings[key] = custom_card(custom, base)
        show_options(key)

    def new_custom_version() -> None:
        selected = printings.get(printing.value)
        base = selected if selected and not selected.is_custom else official[0]
        open_custom_print_dialog(user_id, base, None, on_saved=version_saved)

    show_options(current_key)
    # o usuário pode ter fechado o diálogo enquanto as edições carregavam
    if official and not dialog.is_deleted:
        new_version.on_click(new_custom_version)
        new_version.enable()

