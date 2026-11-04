"""Campo de busca de cartas com sugestões enquanto o usuário digita."""
import asyncio
from collections.abc import Awaitable, Callable

from nicegui import ui

from mtg_collection.models import Card
from mtg_collection.services import scryfall
from mtg_collection.ui import formatting

DEBOUNCE_SECONDS = 0.3
SYNTAX_CHARS = set(":<>=")  # com sintaxe do Scryfall (ex: t:dragon) não faz sentido sugerir nomes


class CardSearchInput:
    """Campo com lista de sugestões. Enter chama `on_submit` com o texto; clicar numa sugestão chama `on_select`.
    `suggest` troca a fonte das sugestões (ex.: só comandantes); `marker` distingue vários campos na mesma página."""
    def __init__(
        self,
        on_submit: Callable[[str], Awaitable[None]],
        on_select: Callable[[Card], None],
        placeholder: str = "",
        value: str = "",
        suggest: Callable[[str], Awaitable[tuple[Card, ...]]] | None = None,
        autofocus: bool = True,
        marker: str = "card-search",
    ):
        self._on_submit = on_submit
        self._on_select = on_select
        self.suggest = suggest  # None: sugestões padrão (qualquer carta)
        # marcadores das sugestões: "suggestion-<id>" na busca principal, "<marker>-suggestion-<id>" nas outras
        self._prefix = "" if marker == "card-search" else f"{marker}-"
        self._version = 0  # incrementa a cada tecla; respostas de versões antigas são descartadas

        with ui.element("div").classes("relative grow") as self.container:
            self.input = ui.input(placeholder=placeholder, value=value) \
                .props("outlined dense clearable" + (" autofocus" if autofocus else "")).classes("w-full") \
                .mark(marker)
            self.dropdown = ui.card().tight() \
                .classes("absolute top-full left-0 right-0 mt-1 z-50 max-h-[70vh] overflow-y-auto shadow-xl "
                         "text-gray-900")  # dentro do cabeçalho o texto herdaria o branco
            self.dropdown.visible = False

        self.input.on_value_change(self._on_type)
        self.input.on("keydown.enter", self._submit)
        self.input.on("keydown.esc", self.hide)
        self.input.on("blur", self.hide)
        self.input.on("focus", self._show_if_filled)

    @property
    def value(self) -> str:
        return (self.input.value or "").strip()

    def hide(self) -> None:
        self.dropdown.visible = False

    def clear(self) -> None:
        self._version += 1  # descarta sugestões pendentes
        self.input.value = ""
        self._render(())

    def _show_if_filled(self) -> None:
        self.dropdown.visible = bool(self.dropdown.default_slot.children)

    async def _submit(self) -> None:
        self._version += 1  # cancela sugestões pendentes
        self.hide()
        await self._on_submit(self.value)

    async def _on_type(self) -> None:
        self._version += 1
        version, text = self._version, self.value
        if len(text) < 2 or SYNTAX_CHARS & set(text):
            self._render(())
            return
        await asyncio.sleep(DEBOUNCE_SECONDS)
        if version != self._version:
            return
        try:
            cards = await (self.suggest or scryfall.client.suggest)(text)
        except scryfall.ScryfallError:
            return  # sugestão é opcional; erro de verdade aparece na busca completa
        if version == self._version:
            self._render(cards, text)

    def _render(self, cards: tuple[Card, ...], text: str = "") -> None:
        self.dropdown.clear()
        with self.dropdown:
            for card in cards:
                self._suggestion(card, text)
        self.dropdown.visible = bool(cards)

    def _suggestion(self, card: Card, text: str) -> None:
        row_classes = "w-full no-wrap items-center gap-3 px-3 py-2 cursor-pointer hover:bg-gray-100 " \
                      "border-b border-gray-200 last:border-b-0"
        with ui.row().classes(row_classes).mark(f"suggestion {self._prefix}suggestion-{card.id}") as row:
            # mousedown.prevent evita que o input perca o foco (e feche a lista) antes do clique
            row.on("mousedown.prevent", lambda: self._select(card))
            if card.image_small:
                ui.image(card.image_small).props("no-spinner no-transition").classes("w-10 shrink-0 rounded")
            with ui.column().classes("gap-0 min-w-0"):
                ui.html(formatting.highlight(card.name, text), sanitize=False) \
                    .classes("font-bold truncate w-full")
                ui.label(f"{card.type_line} · {card.set_code}") \
                    .classes("text-sm italic text-gray-500 truncate w-full pr-1")

    def _select(self, card: Card) -> None:
        self._version += 1
        self.hide()
        self._on_select(card)
