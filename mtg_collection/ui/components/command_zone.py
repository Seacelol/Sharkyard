"""Campos da zona de comando: comandante, parceiro (quando a carta permite) e companheiro.
Usados no diálogo de criar/editar deck e no botão "Comandante" da página do deck."""
from collections.abc import Awaitable, Callable

from nicegui import ui

from mtg_collection import database
from mtg_collection.models import Card, Deck, DeckCard
from mtg_collection.services import commander, custom_cards, decks, scryfall
from mtg_collection.ui.components.card_search_input import CardSearchInput
from mtg_collection.ui.components.dialogs import close_dialog, maybe_await
from mtg_collection.ui.printings import custom_card_as_card

Suggest = Callable[[str], Awaitable[tuple[Card, ...]]]


class CardPicker:
    """Escolhe uma carta pela busca com sugestões. Escolhida, mostra a carta com um botão para tirar."""

    def __init__(self, label: str, marker: str, on_change: Callable[[], None] | None = None):
        self.label, self.marker = label, marker
        self.card: Card | None = None
        self.image: str | None = None
        self.suggest: Suggest | None = None
        self.accept: Callable[[Card], bool] = lambda card: True  # filtro extra das sugestões
        self._on_change = on_change
        self.container = ui.column().classes("w-full gap-1")
        self.render()

    def set(self, card: Card | None, image: str | None = None, notify: bool = True) -> None:
        self.card, self.image = card, image or (card.image_small if card else None)
        self.render()
        if notify and self._on_change:
            self._on_change()

    async def _suggestions(self, text: str) -> tuple[Card, ...]:
        cards = await (self.suggest or scryfall.client.suggest)(text)
        return tuple(card for card in cards if self.accept(card))

    def render(self) -> None:
        self.container.clear()
        with self.container:
            ui.label(self.label).classes("text-xs text-gray-500")
            if self.card is None:
                with ui.row().classes("w-full"):
                    CardSearchInput(on_submit=self._typed, on_select=self.set, placeholder="Digite o nome",
                                    suggest=self._suggestions, autofocus=False, marker=self.marker)
                return
            with ui.row().classes("w-full items-center gap-3 no-wrap rounded-lg border border-gray-200 px-2 py-1") \
                    .mark(f"{self.marker}-chosen"):
                if self.image:
                    ui.image(self.image).props("no-spinner").classes("w-10 shrink-0 rounded")
                with ui.column().classes("gap-0 grow min-w-0"):
                    ui.label(self.card.name).classes("font-medium truncate w-full")
                    ui.label(self.card.type_line).classes("text-xs text-gray-500 truncate w-full")
                ui.button(icon="close", on_click=lambda: self.set(None)).props("flat round dense") \
                    .tooltip("Tirar").mark(f"{self.marker}-clear")

    @staticmethod
    async def _typed(text: str) -> None:
        if text:
            ui.notify("Escolha a carta na lista de sugestões.", type="warning")


class CommandZone:
    """Os três campos, montados no contexto atual. `fmt` decide se há comandante e quem pode ser."""

    def __init__(self, fmt: str):
        self.fmt = fmt
        self._loaded_second = False
        self.ready = False  # só grava depois de carregar o que o deck já tem (senão apagaria o comandante)
        with ui.column().classes("w-full gap-2").mark("command-zone"):
            self.commander_area = ui.column().classes("w-full gap-2")
            with self.commander_area:
                self.commander = CardPicker("Comandante", "commander-pick", on_change=self._commander_changed)
                self.partner = CardPicker("Segundo comandante (parceiro)", "partner-pick")
                self.partner_hint = ui.label().classes("text-xs text-gray-500")
            self.companion = CardPicker("Companheiro (opcional, fica fora do deck)", "companion-pick")
        self.companion.suggest = lambda text: scryfall.client.suggest_where(text, commander.COMPANION_QUERY)
        self.set_format(fmt)

    @property
    def has_commander(self) -> bool:
        return bool(commander.commander_kind(self.fmt))

    def set_format(self, fmt: str) -> None:
        self.fmt = fmt
        self.commander_area.visible = self.has_commander
        query = commander.commander_query(fmt)
        if query:
            self.commander.suggest = lambda text: scryfall.client.suggest_where(text, query)
            self.partner.suggest = self.commander.suggest
        self._commander_changed()

    def _commander_changed(self) -> None:
        first = self.commander.card
        self.partner.accept = (lambda card: commander.can_pair(first, card)) if first else (lambda card: False)
        can = bool(first) and (first.custom_card_id is not None or commander.can_have_partner(first))
        self.partner.container.visible = can or self.partner.card is not None
        if not first and self.partner.card and not self._loaded_second:
            self.partner.set(None, notify=False)
        self.partner_hint.text = "" if not first or can else f"{first.name} não tem parceiro."
        self.partner_hint.visible = bool(self.partner_hint.text)

    def commanders(self) -> list[Card]:
        return [card for card in (self.commander.card, self.partner.card) if card]

    async def load(self, user_id: int, lines: list[DeckCard]) -> None:
        """Preenche com as cartas que o deck já tem na zona de comando (dados completos vêm do Scryfall)."""
        zone = [line for line in lines if line.section in ("commander", "companion")]
        if not zone:
            self.ready = True
            return
        cards = await _full_cards(user_id, zone)
        commanders = [(line, card) for line, card in zip(zone, cards, strict=True) if line.section == "commander"]
        companions = [(line, card) for line, card in zip(zone, cards, strict=True) if line.section == "companion"]
        # o parceiro entra antes e sem avisar: o _commander_changed disparado pelo comandante já o encontra e,
        # com _loaded_second ligado, não o descarta no meio da carga
        self._loaded_second = len(commanders) > 1
        if len(commanders) > 1:
            self.partner.set(commanders[1][1], commanders[1][0].image_small, notify=False)
        if commanders:
            self.commander.set(commanders[0][1], commanders[0][0].image_small)
        if companions:
            self.companion.set(companions[0][1], companions[0][0].image_small, notify=False)
        self._loaded_second = False
        self.ready = True

    def save(self, s, user_id: int, deck_id: int) -> None:
        """Grava na mesma sessão do resto do deck. Fora dos formatos com comandante, não mexe nos comandantes."""
        if not self.ready:
            return
        if self.has_commander:
            decks.set_commanders(s, user_id, deck_id, self.commanders())
        decks.set_companion(s, user_id, deck_id, self.companion.card)


async def _full_cards(user_id: int, lines: list[DeckCard]) -> list[Card]:
    """Card completo (com texto, para conferir parceiro) de cada linha. Sem Scryfall, usa os dados da linha."""
    result: list[Card | None] = [None] * len(lines)
    official = [i for i, line in enumerate(lines) if not line.custom_card_id]
    custom = [i for i, line in enumerate(lines) if line.custom_card_id]
    if custom:
        with database.session() as s:  # uma sessão só para todas as personalizadas (busca pela chave)
            for i in custom:
                try:
                    result[i] = custom_card_as_card(custom_cards.get(s, user_id, lines[i].custom_card_id))
                except custom_cards.CustomCardError:
                    pass
    if official:
        try:
            found = await scryfall.client.find_cards([{"oracle_id": lines[i].oracle_id} for i in official])
        except scryfall.ScryfallError:
            found = [None] * len(official)
        for i, card in zip(official, found, strict=True):
            result[i] = card
    return [card or decks.line_as_card(line) for card, line in zip(result, lines, strict=True)]


async def open_command_zone_dialog(user_id: int, deck: Deck, lines: list[DeckCard],
                                   on_saved: Callable[[], object]) -> None:
    """Diálogo da zona de comando de um deck existente. Abre antes de carregar as cartas (que podem vir do
    Scryfall); até lá, CommandZone.ready impede que salvar apague o que o deck já tem."""
    with ui.context.client.content, ui.dialog() as dialog, ui.card().classes("w-full max-w-lg gap-3"):
        ui.label("Zona de comando").classes("text-lg font-bold")
        zone = CommandZone(deck.format)
        error = ui.label().classes("text-sm text-red-600").mark("zone-error")
        error.visible = False

        async def save() -> None:
            try:
                with database.session() as s:
                    zone.save(s, user_id, deck.id)
            except decks.DeckError as e:
                error.text, error.visible = str(e), True
                return
            ui.notify("Zona de comando salva.", type="positive")
            await maybe_await(on_saved())
            close_dialog(dialog)

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=lambda: close_dialog(dialog)).props("flat no-caps")
            ui.button("Salvar", on_click=save).props("unelevated no-caps").mark("zone-save")
    dialog.on("hide", lambda: close_dialog(dialog))
    dialog.open()
    await zone.load(user_id, lines)
