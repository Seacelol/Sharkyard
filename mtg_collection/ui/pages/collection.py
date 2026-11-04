"""Minha coleção: adicionar pela busca, filtrar, ver totais e editar cada item."""
from nicegui import ui

from mtg_collection import database
from mtg_collection.models import Card, CollectionEntry, User
from mtg_collection.services import collection, folders, scryfall
from mtg_collection.ui import auth
from mtg_collection.ui import formatting as fmt
from mtg_collection.ui.components.card_search_input import CardSearchInput
from mtg_collection.ui.components.controls import lazy_img
from mtg_collection.ui.components.dialogs import confirm
from mtg_collection.ui.components.entry_dialog import open_entry_dialog
from mtg_collection.ui.components.folder_bar import NO_FOLDER, FolderBar
from mtg_collection.ui.components.selection_bar import SelectionBar
from mtg_collection.ui.layout import frame
from mtg_collection.ui.printings import CUSTOM_PREFIX
from mtg_collection.ui.routes import card_path
from mtg_collection.ui.set_icons import custom_set_icon, set_icon_url

PAGE_SIZE = 100
PROXY_FILTERS = {"all": "Todas", "real": "Só originais", "proxy": "Só proxies"}


def entry_icon(entry: CollectionEntry) -> None:
    """Símbolo da edição. Versão e carta personalizadas usam o tubarão do app."""
    if entry.custom_print_id or entry.custom_card_id:
        custom_set_icon()
    else:
        ui.element("div").classes(f"set-icon rarity-{entry.rarity} shrink-0") \
            .style(f"--icon: url('{set_icon_url(entry.set_code)}')")


def entry_page_path(entry: CollectionEntry) -> str | None:
    """Link para a página da carta do item, ou None quando não há página."""
    if entry.custom_card_id:
        return None  # carta personalizada não existe no Scryfall: não tem página
    if entry.custom_print_id:
        return card_path(f"{CUSTOM_PREFIX}{entry.custom_print_id}")
    return card_path(entry.scryfall_id or "")


class CollectionPage:
    """A coleção inteira é carregada de uma vez; filtros e pastas são aplicados em memória e a lista mostra
    PAGE_SIZE itens por vez ("Mostrar mais"), para não desenhar milhares de linhas."""
    def __init__(self, user: User):
        self.user = user
        self.shown = PAGE_SIZE
        self.entries: list[CollectionEntry] = []
        self.selecting = False
        self.selected_ids: set[int] = set()
        self._build()
        self.refresh()

    def _build(self) -> None:
        with ui.column().classes("w-full max-w-5xl mx-auto gap-4"):
            with ui.row().classes("w-full items-end justify-between"):
                with ui.column().classes("gap-0"):
                    ui.label("Minha coleção").classes("text-2xl font-bold")
                    self.summary = ui.label().classes("text-sm text-gray-600").mark("collection-summary")
                self.select_button = ui.button("Selecionar", icon="checklist", on_click=self._start_selecting) \
                    .props("outline no-caps").mark("start-selecting")
            with ui.row().classes("w-full"):
                self.search = CardSearchInput(on_submit=self.add_typed, on_select=self.add_card,
                                              placeholder="Adicionar carta à coleção")
            self.folders = FolderBar(self.user.id, folders.COLLECTION, on_change=self._folders_changed)
            with ui.row().classes("w-full items-center gap-3"):
                self.filter_text = ui.input(placeholder="Filtrar por nome, edição ou observação") \
                    .props("outlined dense clearable").classes("grow").mark("collection-filter")
                self.proxy_filter = ui.select(PROXY_FILTERS, value="all") \
                    .props("outlined dense options-dense").classes("w-40").mark("collection-proxy-filter")
            self.filter_text.on_value_change(self._filters_changed)
            self.proxy_filter.on_value_change(self._filters_changed)
            self.selection = SelectionBar(on_move=self._move_selected, on_delete=self._delete_selected,
                                          on_select_all=self._select_all, on_cancel=self._stop_selecting,
                                          delete_label="Apagar")
            self.list = ui.column().classes("w-full gap-0")
            self.more_button = ui.button("Mostrar mais", on_click=self._show_more).props("flat no-caps") \
                .classes("self-center")

    # ---------- ações ----------
    def _current_folder(self) -> int | None:
        """Pasta aberta (para onde vão as cartas adicionadas pela busca)."""
        return self.folders.selected if isinstance(self.folders.selected, int) else None

    def add_card(self, card: Card) -> None:
        """Adiciona uma cópia na pasta aberta (soma ao item igual, se já existir)."""
        try:
            with database.session() as s:
                entry = collection.add_card(s, self.user.id, card, folder_id=self._current_folder())
        except (collection.CollectionError, folders.FolderError) as e:
            ui.notify(str(e), type="negative")
            return
        ui.notify(f"{card.name} ({card.set_code}) adicionada. Agora você tem {entry.quantity} nesse item.",
                  type="positive")
        self.search.clear()
        self.refresh()

    async def add_typed(self, text: str) -> None:
        """Enter só adiciona se o texto for exatamente o nome de uma carta (evita adicionar a carta errada)."""
        if not text:
            return
        try:
            suggestions = await scryfall.client.suggest(text, limit=1)
        except scryfall.ScryfallError as e:
            ui.notify(str(e), type="negative")
            return
        names = {suggestions[0].name.lower(), suggestions[0].name.split(" // ")[0].lower()} if suggestions else set()
        if text.lower() in names:
            self.add_card(suggestions[0])
        else:
            ui.notify("Escolha a carta na lista de sugestões.", type="warning")

    def edit(self, entry: CollectionEntry):
        return open_entry_dialog(self.user.id, entry, on_change=self.refresh)

    # ---------- seleção múltipla ----------
    def _start_selecting(self) -> None:
        self.selecting, self.selected_ids = True, set()
        self.select_button.visible = False
        self.selection.show(self.folders.folder_options())
        self.selection.set_count(0)
        self._render()

    def _stop_selecting(self) -> None:
        self.selecting, self.selected_ids = False, set()
        self.select_button.visible = True
        self.selection.hide()
        self._render()

    def _toggle(self, entry_id: int, checked: bool) -> None:
        (self.selected_ids.add if checked else self.selected_ids.discard)(entry_id)
        self.selection.set_count(len(self.selected_ids))

    def _select_all(self) -> None:
        self.selected_ids = {e.id for e in self._filtered()}
        self.selection.set_count(len(self.selected_ids))
        self._render()

    def _move_selected(self, folder_id: int | None) -> None:
        if not self.selected_ids:
            ui.notify("Marque os itens primeiro.", type="warning")
            return
        with database.session() as s:
            moved = collection.move_entries(s, self.user.id, list(self.selected_ids), folder_id)
        name = self.folders.folder_options().get(folder_id or NO_FOLDER, "")
        ui.notify(f"{fmt.plural(moved, 'item movido', 'itens movidos')} para \"{name}\".", type="positive")
        self.selected_ids = set()
        self.selection.set_count(0)
        self.refresh()

    def _delete_selected(self) -> None:
        if not self.selected_ids:
            ui.notify("Marque os itens primeiro.", type="warning")
            return
        chosen = [e for e in self.entries if e.id in self.selected_ids]
        copies = sum(e.quantity for e in chosen)

        def delete() -> None:
            with database.session() as s:
                collection.delete_entries(s, self.user.id, [e.id for e in chosen])
            ui.notify(f"{fmt.plural(len(chosen), 'item removido', 'itens removidos')}.", type="positive")
            self.selected_ids = set()
            self.selection.set_count(0)
            self.refresh()

        confirm(f"Apagar {fmt.plural(len(chosen), 'item', 'itens')} da coleção?", delete,
                detail=f"São {fmt.plural(copies, 'carta', 'cartas')} no total.")

    # ---------- lista ----------
    def refresh(self) -> None:
        """Relê coleção e pastas do banco e redesenha (depois de qualquer gravação)."""
        self.folders.load()
        with database.session() as s:
            self.entries = collection.list_entries(s, self.user.id)
        self.folders.render(total=len(self.entries), without_folder=sum(e.folder_id is None for e in self.entries))
        self.selection.move_to.set_options(self.folders.folder_options(), value=None)
        in_folder = [e for e in self.entries if self.folders.matches(e.folder_id)]
        summary = collection.summarize(in_folder)
        self.summary.text = (
            f"{fmt.plural(summary.cards, 'carta', 'cartas')} "
            f"({fmt.plural(summary.real_cards, 'original', 'originais')} · "
            f"{fmt.plural(summary.proxies, 'proxy', 'proxies')}) · "
            f"{fmt.plural(summary.unique_cards, 'diferente', 'diferentes')} · "
            f"Total pago {fmt.brl(summary.total_paid_cents)}")
        self._render()

    def _folders_changed(self) -> None:
        self.shown = PAGE_SIZE
        self.refresh()

    def _filters_changed(self) -> None:
        self.shown = PAGE_SIZE
        self._render()

    def _show_more(self) -> None:
        self.shown += PAGE_SIZE
        self._render()

    def _filtered(self) -> list[CollectionEntry]:
        needle = (self.filter_text.value or "").strip().lower()
        mode = self.proxy_filter.value
        return [e for e in self.entries
                if self.folders.matches(e.folder_id)
                and (not needle or needle in f"{e.card_name} {e.set_name} {e.set_code} {e.notes}".lower())
                and (mode == "all" or (mode == "proxy") == e.is_proxy)]

    def _render(self) -> None:
        entries = self._filtered()
        self.list.clear()
        with self.list:
            if not self.entries:
                ui.label("Sua coleção está vazia. Adicione cartas pela busca acima ou pelo botão "
                         "\"Adicionar\" na página de cada carta.").classes("text-gray-500 py-8 self-center")
            elif not entries:
                filtering = (self.filter_text.value or "").strip() or self.proxy_filter.value != "all"
                ui.label("Nenhum item com esse filtro." if filtering else "Esta pasta está vazia.") \
                    .classes("text-gray-500 py-8 self-center")
            for entry in entries[:self.shown]:
                self._row(entry)
        self.more_button.visible = len(entries) > self.shown

    def _row(self, entry: CollectionEntry) -> None:
        with ui.row().classes("w-full items-center gap-2 sm:gap-3 no-wrap px-1 sm:px-2 py-2 border-b border-gray-100 "
                              "hover:bg-gray-50").mark(f"entry entry-{entry.id}"):
            if self.selecting:
                ui.checkbox(value=entry.id in self.selected_ids,
                            on_change=lambda e, i=entry.id: self._toggle(i, e.value)).mark(f"select-entry-{entry.id}")
            path = entry_page_path(entry)
            if entry.image_small:
                image = lazy_img(entry.image_small) \
                    .classes("w-10 shrink-0 rounded-sm" + (" cursor-pointer" if path else ""))
                if path:
                    image.on("click", lambda p=path: ui.navigate.to(p))
            with ui.column().classes("gap-0 grow min-w-0"):
                if path:
                    ui.link(entry.card_name, path).classes("font-medium truncate w-full text-gray-900 no-underline")
                else:
                    ui.label(entry.card_name).classes("font-medium truncate w-full")
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    entry_icon(entry)
                    number = f" #{entry.collector_number}" if entry.collector_number else ""
                    code = f" ({entry.set_code})" if entry.set_code else ""
                    ui.label(f"{entry.set_name}{code}{number}").classes("text-xs text-gray-500 truncate min-w-0")
                # no celular as marcas ficam embaixo do nome; em telas maiores, numa coluna à direita
                with ui.row().classes("items-center gap-1 sm:hidden"):
                    self._flags(entry)
            with ui.row().classes("items-center gap-1 shrink-0 max-sm:hidden"):
                self._flags(entry)
            with ui.column().classes("gap-0 items-end shrink-0 sm:w-28"):
                ui.label(f"{entry.quantity}x").classes("font-semibold")
                if entry.price_paid_cents is not None:
                    ui.label(f"{fmt.brl(entry.price_paid_cents)}/un").classes("text-xs text-gray-500 whitespace-nowrap")
            ui.button(icon="edit", on_click=lambda e=entry: self.edit(e)).props("flat round dense") \
                .tooltip("Editar").mark(f"edit-entry-{entry.id}")

    @staticmethod
    def _flags(entry: CollectionEntry) -> None:
        if entry.custom_card_id:
            ui.badge("Carta personalizada").props("color=deep-purple-7").tooltip("Não existe no Magic")
        elif entry.custom_print_id:
            ui.badge("Personalizada").props("color=primary").tooltip("Edição personalizada")
        if entry.lang != "en" and not (entry.custom_card_id or entry.custom_print_id):
            ui.badge(entry.lang.upper()).props("color=teal-7").tooltip(fmt.LANG_LABELS.get(entry.lang, entry.lang)) \
                .mark("lang-badge")
        if entry.foil:
            ui.badge("Foil").props("color=amber-7")
        if entry.is_proxy:
            ui.badge("Proxy").props("color=grey-6").mark("proxy-badge")
        if entry.notes:
            ui.icon("sticky_note_2").classes("text-gray-400 text-lg").tooltip(entry.notes)


@ui.page("/collection")
def collection_page() -> None:
    with frame("Minha coleção"):
        CollectionPage(auth.current_user())
