"""Barra do modo de seleção múltipla: quantos estão marcados, mover para pasta, apagar, marcar todos."""
from collections.abc import Callable

from nicegui import ui

from mtg_collection.ui.components.folder_bar import NO_FOLDER


class SelectionBar:
    """Barra das ações em lote; começa escondida. Quem usa guarda a seleção e só avisa a contagem (set_count).
    `on_move` recebe a pasta de destino (None = sem pasta)."""
    def __init__(self, on_move: Callable[[int | None], None], on_delete: Callable[[], None],
                 on_select_all: Callable[[], None], on_cancel: Callable[[], None], delete_label: str = "Apagar"):
        self.on_move = on_move
        with ui.row().classes("w-full items-center gap-3 rounded-lg bg-blue-50 border border-blue-200 px-3 py-2") \
                .mark("selection-bar") as self.row:
            self.count = ui.label().classes("font-medium").mark("selection-count")
            ui.button("Marcar todos", icon="select_all", on_click=on_select_all).props("flat dense no-caps") \
                .mark("select-all")
            ui.element("div").classes("grow")
            self.move_to = ui.select({}, label="Mover para").props("outlined dense options-dense") \
                .classes("w-48").mark("move-to")
            self.move_to.on_value_change(self._move)
            ui.button(delete_label, icon="delete", on_click=on_delete).props("flat dense no-caps color=negative") \
                .mark("delete-selected")
            ui.button("Concluir", on_click=on_cancel).props("flat dense no-caps").mark("selection-done")
        self.row.visible = False

    def show(self, folder_options: dict) -> None:
        self.move_to.set_options(folder_options, value=None)
        self.row.visible = True

    def hide(self) -> None:
        self.row.visible = False

    def set_count(self, count: int) -> None:
        self.count.text = f"{count} selecionado" + ("" if count == 1 else "s")

    def _move(self, e) -> None:
        if e.value is None:
            return
        target = None if e.value == NO_FOLDER else e.value
        self.move_to.value = None  # volta ao rótulo "Mover para" para poder mover de novo
        self.on_move(target)
