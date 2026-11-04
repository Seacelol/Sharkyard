"""Meus decks: grade com capa, cores e formato; criar, editar, pastas e gerenciar vários de uma vez.
A montagem de cada deck (/deck/<id>) fica em deck_builder.py."""
from nicegui import ui

from mtg_collection import database
from mtg_collection.models import Deck, User
from mtg_collection.services import decks, folders
from mtg_collection.ui import auth
from mtg_collection.ui import formatting as fmt
from mtg_collection.ui.components.controls import lazy_img
from mtg_collection.ui.components.deck_dialog import FORMATS, deck_cover_src, open_deck_dialog
from mtg_collection.ui.components.dialogs import confirm
from mtg_collection.ui.components.folder_bar import NO_FOLDER, FolderBar
from mtg_collection.ui.components.selection_bar import SelectionBar
from mtg_collection.ui.custom_images import discard_unused
from mtg_collection.ui.layout import frame
from mtg_collection.ui.routes import deck_path

# fundo da capa quando não há imagem: degradê com as cores do deck
COLOR_HEX = {"W": "#e9e2c0", "U": "#3b82c4", "B": "#3f3a45", "R": "#d0503a", "G": "#3f9a5a", "C": "#9ca3af"}


def colors_html(colors: tuple[str, ...]) -> str:
    """Símbolos de mana das cores do deck."""
    return fmt.symbols_html("".join(f"{{{c}}}" for c in colors))


def cover_background(colors: tuple[str, ...]) -> str:
    """CSS do degradê das cores; uma cor só ganha um tom escuro para ainda formar um degradê."""
    stops = [COLOR_HEX[c] for c in colors] or ["#334155", "#1e293b"]
    if len(stops) == 1:
        stops = [stops[0], "#1e293b"]
    return f"background: linear-gradient(135deg, {', '.join(stops)})"


def deck_cover(deck: Deck, height: str = "h-40") -> None:
    """Capa com as cores no canto superior direito (imagem, ou degradê das cores se não houver capa)."""
    src = deck_cover_src(deck)
    with ui.element("div").classes(f"relative w-full {height} overflow-hidden").style(
            "" if src else cover_background(deck.colors)):
        if src:
            lazy_img(src).classes("absolute inset-0 w-full h-full object-cover").mark("deck-cover-img")
        else:
            ui.icon("style").classes("absolute inset-0 m-auto text-white/40 text-6xl")
        if deck.colors:
            ui.html(colors_html(deck.colors), sanitize=False) \
                .classes("absolute top-2 right-2 rounded-full bg-black/40 px-1.5 py-0.5 text-lg leading-none") \
                .mark("deck-colors")


class DecksPage:
    """Grade de decks do usuário. No modo de seleção, clicar no card marca o deck em vez de abrir."""
    def __init__(self, user: User):
        self.user = user
        self.decks: list[Deck] = []
        self.selecting = False
        self.selected_ids: set[int] = set()
        self._build()
        self.refresh()

    def _build(self) -> None:
        with ui.column().classes("w-full max-w-6xl mx-auto gap-4"):
            with ui.row().classes("w-full items-end justify-between"):
                with ui.column().classes("gap-0"):
                    ui.label("Meus decks").classes("text-2xl font-bold")
                    self.summary = ui.label().classes("text-sm text-gray-600").mark("decks-summary")
                # no celular só os ícones nos dois primeiros, para caber numa linha
                with ui.row().classes("gap-2 no-wrap"):
                    with ui.button(icon="group", on_click=lambda: ui.navigate.to("/decks/friends")) \
                            .props("flat no-caps").tooltip("Decks dos amigos").mark("friends-decks"):
                        ui.label("Dos amigos").classes("ml-2 max-sm:hidden")
                    with ui.button(icon="checklist", on_click=self._start_selecting).props("outline no-caps") \
                            .tooltip("Gerenciar vários").mark("start-selecting") as self.manage_button:
                        ui.label("Gerenciar").classes("ml-2 max-sm:hidden")
                    ui.button("Novo deck", icon="add", on_click=self._new_deck).props("unelevated no-caps") \
                        .mark("new-deck")
            self.folders = FolderBar(self.user.id, folders.DECKS, on_change=self.refresh, item_label="decks")
            self.selection = SelectionBar(on_move=self._move_selected, on_delete=self._delete_selected,
                                          on_select_all=self._select_all, on_cancel=self._stop_selecting)
            # dois por linha no celular; nas telas maiores, quantos couberem
            self.grid = ui.element("div").classes(
                "grid gap-3 sm:gap-4 w-full grid-cols-2 "
                "sm:[grid-template-columns:repeat(auto-fill,minmax(230px,1fr))]").mark("decks-grid")

    # ---------- dados ----------
    def refresh(self) -> None:
        self.folders.load()
        with database.session() as s:
            self.decks = decks.list_decks(s, self.user.id)
        self.folders.render(total=len(self.decks), without_folder=sum(d.folder_id is None for d in self.decks))
        self.selection.move_to.set_options(self.folders.folder_options(), value=None)
        self.selected_ids &= {d.id for d in self.decks}
        self.selection.set_count(len(self.selected_ids))
        visible = self._visible()
        self.summary.text = f"{fmt.plural(len(visible), 'deck', 'decks')}"
        self._render(visible)

    def _visible(self) -> list[Deck]:
        return [d for d in self.decks if self.folders.matches(d.folder_id)]

    def _current_folder(self) -> int | None:
        return self.folders.selected if isinstance(self.folders.selected, int) else None

    # ---------- ações ----------
    def _new_deck(self) -> None:
        open_deck_dialog(self.user.id, None, self.folders.folder_options(), on_saved=lambda _: self.refresh(),
                         default_folder=self._current_folder())

    def _edit(self, deck: Deck) -> None:
        open_deck_dialog(self.user.id, deck, self.folders.folder_options(), on_saved=lambda _: self.refresh(),
                         on_deleted=self.refresh)

    def _open(self, deck: Deck) -> None:
        if self.selecting:
            self._toggle(deck.id, deck.id not in self.selected_ids)
            self._render(self._visible())
        else:
            ui.navigate.to(deck_path(deck.id))

    # ---------- seleção múltipla ----------
    def _start_selecting(self) -> None:
        self.selecting, self.selected_ids = True, set()
        self.manage_button.visible = False
        self.selection.show(self.folders.folder_options())
        self.selection.set_count(0)
        self._render(self._visible())

    def _stop_selecting(self) -> None:
        self.selecting, self.selected_ids = False, set()
        self.manage_button.visible = True
        self.selection.hide()
        self._render(self._visible())

    def _toggle(self, deck_id: int, checked: bool) -> None:
        (self.selected_ids.add if checked else self.selected_ids.discard)(deck_id)
        self.selection.set_count(len(self.selected_ids))

    def _select_all(self) -> None:
        self.selected_ids = {d.id for d in self._visible()}
        self.selection.set_count(len(self.selected_ids))
        self._render(self._visible())

    def _move_selected(self, folder_id: int | None) -> None:
        if not self.selected_ids:
            ui.notify("Marque os decks primeiro.", type="warning")
            return
        with database.session() as s:
            moved = decks.move_decks(s, self.user.id, list(self.selected_ids), folder_id)
        name = self.folders.folder_options().get(folder_id or NO_FOLDER, "")
        ui.notify(f"{fmt.plural(moved, 'deck movido', 'decks movidos')} para \"{name}\".", type="positive")
        self.selected_ids = set()
        self.refresh()

    def _delete_selected(self) -> None:
        if not self.selected_ids:
            ui.notify("Marque os decks primeiro.", type="warning")
            return
        chosen = [d for d in self.decks if d.id in self.selected_ids]

        def delete() -> None:
            with database.session() as s:
                files = decks.delete_decks(s, self.user.id, [d.id for d in chosen])
            discard_unused(files)
            ui.notify(f"{fmt.plural(len(chosen), 'deck apagado', 'decks apagados')}.", type="positive")
            self.selected_ids = set()
            self.refresh()

        names = ", ".join(d.name for d in chosen[:5]) + ("..." if len(chosen) > 5 else "")
        confirm(f"Apagar {fmt.plural(len(chosen), 'deck', 'decks')}?", delete,
                detail=f"{names}. As cartas da sua coleção não são afetadas.")

    # ---------- grade ----------
    def _render(self, visible: list[Deck]) -> None:
        self.grid.clear()
        with self.grid:
            if not self.decks:
                with ui.column().classes("col-span-full items-center py-12 gap-3"):
                    ui.icon("style").classes("text-5xl text-gray-300")
                    ui.label("Você ainda não tem decks.").classes("text-gray-500")
                    ui.button("Criar o primeiro deck", icon="add", on_click=self._new_deck) \
                        .props("unelevated no-caps")
            elif not visible:
                ui.label("Esta pasta está vazia.").classes("col-span-full text-gray-500 py-8 text-center")
            for deck in visible:
                self._tile(deck)

    def _tile(self, deck: Deck) -> None:
        selected = deck.id in self.selected_ids
        ring = "ring-2 ring-blue-500" if selected else ""
        with ui.card().tight() \
                .classes(f"cursor-pointer hover:shadow-xl transition-shadow overflow-hidden min-w-0 {ring}") \
                .mark(f"deck deck-{deck.id}") as tile:
            tile.on("click", lambda d=deck: self._open(d))
            with ui.element("div").classes("relative w-full"):
                deck_cover(deck, height="h-24 sm:h-40")
                if self.selecting:
                    # click.stop: o clique na caixa não chega ao card (senão o card desfaria a marcação)
                    ui.checkbox(value=selected, on_change=lambda e, i=deck.id: self._toggle(i, e.value)) \
                        .props("dark").classes("absolute top-1 left-1 bg-black/40 rounded") \
                        .on("click.stop", lambda: None).mark(f"select-deck-{deck.id}")
            with ui.row().classes("w-full items-start no-wrap gap-2 px-3 py-2"):
                with ui.column().classes("gap-0 grow min-w-0"):
                    ui.label(deck.name).classes("font-semibold truncate w-full")
                    details = [FORMATS.get(deck.format, deck.format) if deck.format else "Sem formato",
                               fmt.plural(deck.card_count, "carta", "cartas")]
                    if deck.version_count > 1:
                        details.append(f"{deck.version_name} ({deck.version_count} versões)")
                    ui.label(" · ".join(details)).classes("text-xs text-gray-500").mark("deck-details")
                    if deck.notes:  # duas linhas na grade; o texto todo fica na página do deck
                        ui.label(deck.notes).classes("text-xs text-gray-500 line-clamp-2 break-words w-full")
                with ui.row().classes("items-center gap-0 shrink-0"):
                    if deck.visibility == "friends":
                        ui.icon("group").classes("text-gray-400 text-base").tooltip("Visível para os amigos")
                    if not self.selecting:
                        ui.button(icon="edit", on_click=lambda d=deck: self._edit(d)) \
                            .props("flat round dense size=sm").on("click.stop", lambda: None) \
                            .tooltip("Editar").mark(f"edit-deck-{deck.id}")


@ui.page("/decks")
def decks_page() -> None:
    with frame("Meus decks"):
        DecksPage(auth.current_user())

