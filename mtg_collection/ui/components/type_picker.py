"""Seletor de tipos no estilo do Scryfall: escolhe da lista, vira etiqueta, clicar em É/NÃO alterna."""
from collections.abc import Callable

from nicegui import ui

GROUP_LABELS = {
    "card-types": "tipo",
    "supertypes": "supertipo",
    "artifact-types": "tipo de artefato",
    "battle-types": "tipo de batalha",
    "creature-types": "tipo de criatura",
    "enchantment-types": "tipo de encantamento",
    "land-types": "tipo de terreno",
    "planeswalker-types": "tipo de planeswalker",
    "spell-types": "tipo de mágica",
}


def type_options(catalogs: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """nome -> rótulo com o grupo ("Dragon · tipo de criatura"). Digitar o grupo também filtra a lista.
    Segue a ordem dos catálogos (tipos principais primeiro); um nome repetido fica no primeiro grupo."""
    options: dict[str, str] = {}
    for key, names in catalogs.items():
        group = GROUP_LABELS.get(key, key)
        for name in names:
            options.setdefault(name, f"{name} · {group}")
    return options


class TypePicker:
    """Lista de tipos escolhidos para a busca, cada um marcado como "é" ou "não é". As opções chegam depois,
    por set_catalogs, porque os catálogos vêm do Scryfall."""
    def __init__(self, on_change: Callable[[], None]):
        self._on_change = on_change
        self.selected: list[tuple[str, bool]] = []  # (tipo, True = é / False = não é)
        with ui.column().classes("w-full gap-2"):
            self.select = ui.select({}, with_input=True, label="Carregando tipos...") \
                .props("outlined dense options-dense").classes("w-full").mark("type-picker")
            self.chips = ui.row().classes("gap-2")
        self.select.on_value_change(lambda e: self.add(e.value))
        # sem "fill-input" o campo fica vazio depois de escolher (o NiceGUI liga essa opção por padrão)
        self.select.props(remove="fill-input")
        # a cada letra, destaca a 1ª opção da lista: Enter escolhe ela, como no Scryfall (setas seguem funcionando)
        select_id = self.select.id
        self.select.on("input-value", js_handler=f"""() => setTimeout(() => {{
            runMethod({select_id}, 'setOptionIndex', [-1]);
            runMethod({select_id}, 'moveOptionSelection', [1, true]);
        }}, 30)""")

    def set_catalogs(self, catalogs: dict[str, tuple[str, ...]]) -> None:
        self.select.set_options(type_options(catalogs))
        self.select.props('label="Digite para filtrar (ex: dragon, legendary, equipment)"')

    def add(self, name: str | None) -> None:
        if not name:
            return
        if all(existing != name for existing, _ in self.selected):
            self.selected.append((name, True))
        self.select.value = None  # limpa o campo para escolher o próximo
        self._changed()

    def toggle(self, name: str) -> None:
        self.selected = [(n, not inc if n == name else inc) for n, inc in self.selected]
        self._changed()

    def remove(self, name: str) -> None:
        self.selected = [(n, inc) for n, inc in self.selected if n != name]
        self._changed()

    def clear(self) -> None:
        self.selected = []
        self.select.value = None
        self._changed()

    def _changed(self) -> None:
        self._render()
        self._on_change()

    def _render(self) -> None:
        self.chips.clear()
        with self.chips:
            for name, include in self.selected:
                with ui.element("div").classes("inline-flex items-center gap-2 rounded-full border border-gray-300 "
                                               "bg-gray-50 pl-1 pr-2 py-0.5").mark(f"type-chip type-chip-{name}"):
                    ui.button("É" if include else "NÃO", on_click=lambda n=name: self.toggle(n)) \
                        .props(f"unelevated dense rounded size=sm color={'positive' if include else 'negative'}") \
                        .classes("px-2 text-xs").tooltip("Clique para alternar entre é / não é") \
                        .mark(f"type-toggle-{name}")
                    ui.label(name).classes("text-sm")
                    ui.icon("close", size="xs").classes("cursor-pointer text-gray-500 hover:text-gray-800") \
                        .on("click", lambda n=name: self.remove(n)).mark(f"type-remove-{name}")
