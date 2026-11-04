"""Barra de pastas (coleção ou decks): filtrar por pasta, criar, renomear e apagar."""
from collections.abc import Callable

from nicegui import ui

from mtg_collection import config, database
from mtg_collection.models import Folder
from mtg_collection.services import folders
from mtg_collection.ui.components.dialogs import ask_text, confirm

ALL = "all"
NO_FOLDER = "none"


class FolderBar:
    """`selected` é ALL, NO_FOLDER ou o id da pasta. `on_change` é chamado ao trocar de pasta ou ao
    criar/renomear/apagar uma (a página recarrega a lista)."""

    def __init__(self, user_id: int, kind: str, on_change: Callable[[], None], item_label: str = "itens"):
        self.user_id = user_id
        self.kind = kind
        self.on_change = on_change
        self.item_label = item_label
        self.selected: str | int = ALL
        self.folders: list[Folder] = []
        self.row = ui.row().classes("w-full items-center gap-2").mark("folder-bar")

    def load(self) -> list[Folder]:
        with database.session() as s:
            self.folders = folders.list_folders(s, self.user_id, self.kind)
        if isinstance(self.selected, int) and all(f.id != self.selected for f in self.folders):
            self.selected = ALL  # pasta escolhida foi apagada
        return self.folders

    def matches(self, folder_id: int | None) -> bool:
        if self.selected == ALL:
            return True
        if self.selected == NO_FOLDER:
            return folder_id is None
        return folder_id == self.selected

    def render(self, total: int, without_folder: int) -> None:
        self.row.clear()
        with self.row:
            self._chip(f"Todas ({total})" if self.kind == folders.COLLECTION else f"Todos ({total})", ALL, "apps")
            self._chip(f"Sem pasta ({without_folder})", NO_FOLDER, "folder_off")
            for folder in self.folders:
                name = folder.name if len(folder.name) <= config.FOLDER_NAME_MAX \
                    else folder.name[:config.FOLDER_NAME_MAX - 1] + "…"  # pastas antigas, de antes do limite
                self._chip(f"{name} ({folder.item_count})", folder.id, "folder")
            ui.button("Nova pasta", icon="create_new_folder", on_click=self._create) \
                .props("flat dense no-caps size=sm").mark("folder-new")
            if isinstance(self.selected, int):
                with ui.button(icon="more_vert").props("flat round dense size=sm").mark("folder-menu"):
                    with ui.menu():
                        ui.menu_item("Renomear pasta", on_click=self._rename).mark("folder-rename")
                        ui.menu_item("Apagar pasta", on_click=self._delete).mark("folder-delete")

    def folder_options(self) -> dict:
        """Opções para escolher pasta (em diálogos e na seleção múltipla)."""
        return {NO_FOLDER: "Sem pasta", **{f.id: f.name for f in self.folders}}

    # ---------- ações ----------
    def _chip(self, label: str, value: str | int, icon: str) -> None:
        style = "unelevated color=primary" if self.selected == value else "outline color=grey-7"
        ui.button(label, icon=icon, on_click=lambda v=value: self._select(v)) \
            .props(f"no-caps dense rounded size=sm {style}").classes("px-2").mark(f"folder-chip folder-chip-{value}")

    def _select(self, value: str | int) -> None:
        self.selected = value
        self.on_change()

    def _create(self) -> None:
        def save(name: str) -> str | None:
            try:
                with database.session() as s:
                    folder = folders.create_folder(s, self.user_id, self.kind, name)
            except folders.FolderError as e:
                return str(e)
            self.selected = folder.id
            ui.notify(f"Pasta \"{folder.name}\" criada.", type="positive")
            self.on_change()
            return None

        ask_text("Nova pasta", "Nome da pasta", save, ok_label="Criar", max_length=config.FOLDER_NAME_MAX)

    def _current(self) -> Folder | None:
        return next((f for f in self.folders if f.id == self.selected), None)

    def _rename(self) -> None:
        folder = self._current()

        def save(name: str) -> str | None:
            try:
                with database.session() as s:
                    folders.rename_folder(s, self.user_id, folder.id, name)
            except folders.FolderError as e:
                return str(e)
            self.on_change()
            return None

        ask_text("Renomear pasta", "Nome da pasta", save, value=folder.name, max_length=config.FOLDER_NAME_MAX)

    def _delete(self) -> None:
        folder = self._current()

        def delete() -> None:
            with database.session() as s:
                folders.delete_folder(s, self.user_id, folder.id)
            self.selected = ALL
            ui.notify(f"Pasta \"{folder.name}\" apagada.", type="positive")
            self.on_change()

        confirm(f"Apagar a pasta \"{folder.name}\"?", delete,
                detail=f"Os {self.item_label} dela não são apagados: voltam para \"Sem pasta\".")
