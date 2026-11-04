"""Diálogo para editar um item da coleção: edição, quantidade, foil, proxy, preço pago e observações."""
from collections.abc import Callable

from nicegui import ui

from mtg_collection import database
from mtg_collection.models import Card, CollectionEntry
from mtg_collection.services import collection, folders, scryfall
from mtg_collection.ui import formatting as fmt
from mtg_collection.ui.components.dialogs import close_dialog, confirm
from mtg_collection.ui.components.folder_bar import NO_FOLDER
from mtg_collection.ui.printings import CUSTOM_PREFIX, all_printings


def printing_label(card: Card) -> str:
    """Texto da impressão no seletor de edições (versões personalizadas com estrela)."""
    if card.is_custom:
        return f"★ {card.set_name}" + (f" ({card.set_code})" if card.set_code else "") + " · versão personalizada"
    year = f" · {card.released_at.year}" if card.released_at else ""
    return f"{card.set_name} ({card.set_code}) #{card.collector_number}{year}"


def entry_print_key(entry: CollectionEntry) -> str:
    """Chave da impressão do item no seletor de edições (versões personalizadas levam CUSTOM_PREFIX)."""
    return f"{CUSTOM_PREFIX}{entry.custom_print_id}" if entry.custom_print_id else (entry.scryfall_id or "")


async def open_entry_dialog(user_id: int, entry: CollectionEntry, on_change: Callable[[], None]) -> None:
    """Edita um item da coleção. Abre na hora com a edição atual; a lista das outras edições chega depois.
    A impressão só é trocada se o usuário escolher outra (`chosen` fica None se não mudou)."""
    printings: dict[str, Card] = {}
    current_key = entry_print_key(entry)
    current_label = entry.set_name + (f" ({entry.set_code})" if entry.set_code else "") + \
        (f" #{entry.collector_number}" if entry.collector_number else "")

    # criado na raiz da página: se ficasse dentro da lista que o abriu, seria apagado quando ela é redesenhada
    with ui.context.client.content, ui.dialog() as dialog, ui.card().classes("w-full max-w-lg gap-3"):
        with ui.row().classes("w-full items-center gap-3 no-wrap"):
            if entry.image_small:
                ui.image(entry.image_small).props("no-spinner").classes("w-12 shrink-0 rounded")
            with ui.column().classes("gap-0 min-w-0"):
                ui.label(entry.card_name).classes("text-lg font-bold truncate w-full")
                ui.label("Editar item da coleção").classes("text-sm text-gray-500")
        printing = ui.select({current_key: current_label}, value=current_key, label="Edição", with_input=True) \
            .props("outlined dense options-dense").classes("w-full").mark("entry-printing")
        with ui.row().classes("w-full items-center gap-4"):
            quantity = ui.number("Quantidade", value=entry.quantity, min=1, max=collection.MAX_QUANTITY, step=1,
                                 format="%.0f").props("outlined dense").classes("w-32").mark("entry-quantity")
            foil = ui.checkbox("Foil", value=entry.foil).mark("entry-foil")
            proxy = ui.checkbox("Proxy", value=entry.is_proxy).mark("entry-proxy") \
                .tooltip("Cópia que não é a carta original: aparece separada nos totais")
        with database.session() as s:
            folder_list = folders.list_folders(s, user_id, folders.COLLECTION)
        folder = ui.select({NO_FOLDER: "Sem pasta", **{f.id: f.name for f in folder_list}},
                           value=entry.folder_id or NO_FOLDER, label="Pasta") \
            .props("outlined dense options-dense").classes("w-full").mark("entry-folder")
        price = ui.input("Preço pago por unidade", value=fmt.brl_input(entry.price_paid_cents),
                         placeholder="0,00").props("outlined dense prefix=R$").classes("w-full").mark("entry-price")
        notes = ui.textarea("Observações", value=entry.notes).props("outlined dense autogrow") \
            .classes("w-full").mark("entry-notes")
        error = ui.label().classes("text-sm text-red-600").mark("entry-error")
        error.visible = False

        def save() -> None:
            try:
                cents = collection.parse_price(price.value)
                qty = int(quantity.value or 0)
                if qty != quantity.value:
                    raise collection.CollectionError("A quantidade deve ser um número inteiro.")
                chosen = printings.get(printing.value) if printing.value != current_key else None
                with database.session() as s:
                    collection.update_entry(s, user_id, entry.id, quantity=qty, foil=foil.value,
                                            is_proxy=proxy.value, price_paid_cents=cents, notes=notes.value or "",
                                            printing=chosen,
                                            folder_id=None if folder.value == NO_FOLDER else folder.value)
            except collection.CollectionError as e:
                error.text = str(e)
                error.visible = True
                return
            ui.notify("Item atualizado.", type="positive")
            on_change()  # antes de fechar: fechar apaga o diálogo e o contexto dele
            close_dialog(dialog)

        def ask_delete() -> None:
            def delete() -> None:
                with database.session() as s:
                    collection.delete_entry(s, user_id, entry.id)
                ui.notify("Item apagado.", type="positive")
                on_change()
                close_dialog(dialog)

            confirm(f"Apagar {entry.quantity}x {entry.card_name} da coleção?", delete)

        with ui.row().classes("w-full items-center justify-between mt-2"):
            ui.button("Apagar", icon="delete", on_click=ask_delete).props("flat no-caps color=negative") \
                .mark("entry-delete")
            with ui.row().classes("gap-2"):
                ui.button("Cancelar", on_click=lambda: close_dialog(dialog)).props("flat no-caps")
                ui.button("Salvar", on_click=save).props("unelevated no-caps").mark("entry-save")

    dialog.on("hide", lambda: close_dialog(dialog))  # fechar clicando fora ou com Esc
    dialog.open()

    if entry.custom_card_id:
        printing.disable()  # carta personalizada: não tem outras edições
        return
    # as edições carregam com o diálogo já aberto
    try:
        cards = await all_printings(user_id, entry.oracle_id)
    except scryfall.ScryfallError:
        printing.props('hint="Não foi possível carregar as outras edições agora."')
        return
    printings.update({c.id: c for c in cards})
    options = {key: printing_label(card) for key, card in printings.items()}
    options.setdefault(current_key, current_label)  # edição atual pode estar além das 175 primeiras
    printing.set_options(options, value=current_key)
