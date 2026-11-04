"""Montagem do deck (/deck/<id>): adicionar cartas pela busca, da coleção, por lista em texto ou criando cartas
personalizadas; editar cada linha; e "Concluir", que revisa, avisa se o deck não vale no formato e oferece
pôr na coleção as cartas que faltam. Cada mudança é salva na hora; "Concluir" não é obrigatório para salvar."""
from nicegui import ui

from mtg_collection import config, database
from mtg_collection.models import Card, CollectionEntry, CustomCard, Deck, DeckCard, User
from mtg_collection.services import (
    collection,
    commander,
    custom_cards,
    deck_stats,
    deck_validation,
    decklist,
    decks,
    folders,
    ranking,
    scryfall,
)
from mtg_collection.ui import formatting as fmt
from mtg_collection.ui.components.card_search_input import CardSearchInput
from mtg_collection.ui.components.command_zone import open_command_zone_dialog
from mtg_collection.ui.components.compare_dialog import open_compare_dialog
from mtg_collection.ui.components.controls import back_button, lazy_img
from mtg_collection.ui.components.custom_card_dialog import open_custom_card_dialog
from mtg_collection.ui.components.deck_dialog import FORMATS, open_deck_dialog
from mtg_collection.ui.components.deck_line_dialog import SECTION_OPTIONS, open_line_dialog
from mtg_collection.ui.components.deck_stats_view import StatsLoader, render_stats
from mtg_collection.ui.components.dialogs import ask_text, close_dialog, confirm
from mtg_collection.ui.components.expandable_text import expandable_text
from mtg_collection.ui.components.export_dialog import open_export_dialog
from mtg_collection.ui.components.folder_bar import NO_FOLDER
from mtg_collection.ui.components.wins_dialog import open_wins_dialog
from mtg_collection.ui.pages.decks import deck_cover
from mtg_collection.ui.printings import CUSTOM_PREFIX, custom_card_as_card, entry_card
from mtg_collection.ui.routes import card_path, deck_path
from mtg_collection.ui.set_icons import custom_set_icon, set_icon_url

COLLECTION_ROWS = 50  # itens da coleção mostrados de uma vez na aba "Da coleção"
SECTION_TITLES = {"commander": "Comandante", "companion": "Companheiro", "main": "Principal",
                  "sideboard": "Sideboard", "maybe": "Talvez"}
SECTION_ORDER = tuple(SECTION_TITLES)
# comandante e companheiro são escolhidos na zona de comando, não pelo painel de adicionar
ADD_SECTIONS = {key: SECTION_OPTIONS[key] for key in ("main", "sideboard", "maybe")}
# cabeçalhos usados ao devolver para a caixa de texto as linhas que não foram reconhecidas
SECTION_HEADERS = {"main": "Deck", "commander": "Commander", "companion": "Companion", "sideboard": "Sideboard",
                   "maybe": "Maybeboard"}


def line_badges(line: DeckCard) -> None:
    """Etiquetas da linha (personalizada, idioma, foil, proxy). Usadas na lista, na revisão e no "falta na coleção"."""
    if line.custom_card_id:
        ui.badge("Carta personalizada").props("color=deep-purple-7").mark("badge-custom-card") \
            .tooltip("Não existe no Magic")
    elif line.custom_print_id:
        ui.badge("Personalizada").props("color=primary").mark("badge-custom-print") \
            .tooltip("Edição personalizada")
    if line.lang != "en" and not (line.custom_card_id or line.custom_print_id):
        ui.badge(line.lang.upper()).props("color=teal-7").tooltip(fmt.LANG_LABELS.get(line.lang, line.lang)) \
            .mark("badge-lang")
    if line.foil:
        ui.badge("Foil").props("color=amber-7")
    if line.is_proxy:
        ui.badge("Proxy").props("color=grey-6").mark("badge-proxy")


def line_page_path(line: DeckCard) -> str | None:
    """Link para a página da carta da linha, ou None quando não há página."""
    if line.custom_card_id:
        return None  # não existe no Scryfall: não tem página de carta
    if line.custom_print_id:
        return card_path(f"{CUSTOM_PREFIX}{line.custom_print_id}")
    return card_path(line.scryfall_id or "")


def set_icon(code: str, rarity: str, custom: bool) -> None:
    """Símbolo pequeno da edição; personalizadas usam o tubarão do app."""
    if custom:
        custom_set_icon(18)
    else:
        ui.element("div").classes(f"set-icon rarity-{rarity} shrink-0").style(
            f"--icon: url('{set_icon_url(code)}'); width: 18px; height: 18px")


def section_counts(lines: list[DeckCard]) -> dict[str, int]:
    """Cópias por seção (todas as seções presentes, mesmo com zero)."""
    counts = dict.fromkeys(SECTION_ORDER, 0)
    for line in lines:
        counts[line.section] += line.quantity
    return counts


# as quatro abas cabem na largura do celular sem rolar
TABS_CSS = """
.deck-add-tabs .q-tab { padding: 0 6px; min-width: 0; }
@media (max-width: 639px) { .deck-add-tabs .q-tab__label { font-size: 12px; } }
"""


class DeckBuilder:
    """Tela de montagem da versão atual do deck: painel de adicionar à esquerda, lista (ou estatísticas) à
    direita. Cada ação grava na hora e chama refresh(); só o + e o - atualizam a tela por partes, para não
    redesenhar a lista inteira a cada clique."""

    def __init__(self, user: User, deck: Deck):
        self.user = user
        self.deck = deck
        self.lines: list[DeckCard] = []
        self.entries: list[CollectionEntry] | None = None  # None: ainda não lida (a aba Coleção não abriu)
        self._qty_labels: dict[int, ui.label] = {}  # linha -> rótulo da quantidade (o + e o - mexem só nele)
        self._group_of: dict[int, str] = {}  # linha -> grupo da lista em que ela aparece
        self._group_totals: dict[str, ui.label] = {}
        self._stats_loader = StatsLoader()
        self._build()
        self.refresh()

    # ---------- estrutura ----------
    def _build(self) -> None:
        ui.add_css(TABS_CSS)
        with ui.column().classes("w-full max-w-6xl mx-auto gap-4"):
            back_button("Ver deck", lambda: ui.navigate.to(deck_path(self.deck.id))).mark("back-to-view")
            self.header = ui.card().tight().classes("w-full overflow-hidden")
            with ui.element("div").classes("grid gap-4 w-full items-start grid-cols-1 lg:grid-cols-5"):
                with ui.card().classes("w-full gap-3 lg:col-span-2 lg:sticky lg:top-20"):
                    self._add_panel()
                with ui.column().classes("w-full gap-2 lg:col-span-3"):
                    with ui.tabs().props("dense no-caps align=left").classes("text-gray-700") as self.view:
                        cards_tab = ui.tab("Cartas", icon="view_list").mark("view-cards")
                        self.stats_tab = ui.tab("Estatísticas", icon="insights").mark("view-stats")
                    with ui.tab_panels(self.view, value=cards_tab).props("animated=false") \
                            .classes("w-full bg-transparent"):
                        with ui.tab_panel(cards_tab).classes("p-0"):
                            self.deck_list = ui.column().classes("w-full gap-4 p-1").mark("deck-list")
                        with ui.tab_panel(self.stats_tab).classes("p-0"):
                            self.stats_area = ui.card().classes("w-full gap-3").mark("deck-stats")
                    self.view.on_value_change(self._render_stats)

    def _add_panel(self) -> None:
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("Adicionar cartas").classes("text-lg font-bold")
            self.section = ui.select(ADD_SECTIONS, value="main", label="Em") \
                .props("outlined dense options-dense").classes("w-36").mark("add-section")
        with ui.tabs().props("dense no-caps align=left").classes("w-full text-gray-700 deck-add-tabs") as tabs:
            search_tab = ui.tab("Buscar", icon="search").mark("tab-search")
            collection_tab = ui.tab("Coleção", icon="inventory_2").mark("tab-collection")
            text_tab = ui.tab("Lista", icon="notes").mark("tab-text")
            custom_tab = ui.tab("Personalizada", icon="auto_awesome").mark("tab-custom")
        self.add_tabs, self.collection_tab = tabs, collection_tab
        # a coleção pode ter milhares de itens: só é lida quando a aba abre (e relida a cada vez que abre)
        tabs.on_value_change(lambda: self._render_collection(reload=True))
        with ui.tab_panels(tabs, value=search_tab).classes("w-full").props("animated=false"):
            with ui.tab_panel(search_tab).classes("p-0 pt-2 gap-2"):
                with ui.row().classes("w-full items-start gap-2 no-wrap"):
                    self.search = CardSearchInput(on_submit=self._add_typed, on_select=self._add_searched,
                                                  placeholder="Nome da carta")
                    self.search_qty = self._qty_input("search-qty")
                self.identity_only = ui.checkbox("Só cartas na identidade de cor do comandante", value=True) \
                    .props("dense").classes("text-sm").mark("identity-filter")
                self.identity_only.on_value_change(self._update_search_filter)
                ui.label("Escolha a carta na lista: entra a edição padrão. Troque a edição depois, no lápis.") \
                    .classes("text-xs text-gray-500")
            with ui.tab_panel(collection_tab).classes("p-0 pt-2 gap-2"):
                self.collection_filter = ui.input(placeholder="Filtrar a coleção por nome ou edição") \
                    .props("outlined dense clearable").classes("w-full").mark("collection-filter")
                self.collection_filter.on_value_change(self._render_collection)
                self.collection_list = ui.column().classes("w-full gap-0 max-h-[28rem] overflow-y-auto") \
                    .mark("collection-list")
            with ui.tab_panel(text_tab).classes("p-0 pt-2 gap-2"):
                ui.label("Uma carta por linha: \"4 Lightning Bolt\" ou \"4x Lightning Bolt\". Também aceita listas "
                         "exportadas do Arena, Moxfield e MTGO.").classes("text-xs text-gray-500")
                self.text = ui.textarea(placeholder="4 Lightning Bolt\n2x Counterspell\n\nSideboard\n2 Pyroblast") \
                    .props("outlined dense rows=8").classes("w-full font-mono text-sm").mark("decklist-text")
                ui.button("Adicionar lista", icon="playlist_add", on_click=self._import_text) \
                    .props("unelevated no-caps").mark("decklist-import")
                self.text_result = ui.column().classes("w-full gap-1").mark("decklist-result")
            with ui.tab_panel(custom_tab).classes("p-0 pt-2 gap-2"):
                ui.button("Criar carta personalizada", icon="add", on_click=self._new_custom_card) \
                    .props("outline no-caps").mark("new-custom-card")
                self.custom_list = ui.column().classes("w-full gap-0").mark("custom-list")

    @staticmethod
    def _qty_input(marker: str) -> ui.number:
        return ui.number(value=1, min=1, max=decks.MAX_QUANTITY, step=1, format="%.0f") \
            .props("outlined dense").classes("w-20 shrink-0").mark(marker)

    # ---------- dados ----------
    def refresh(self) -> None:
        """Relê deck, linhas e personalizadas e redesenha tudo que depende deles."""
        with database.session() as s:
            self.deck = decks.get_deck(s, self.user.id, self.deck.id)
            self.lines = decks.list_cards(s, self.user.id, self.deck.id)
            self.customs = custom_cards.available_for_deck(s, self.user.id, self.deck.id)
        self._render_header()
        self._update_search_filter()
        self._render_lines()
        self._render_stats()
        self._render_collection()
        self._render_customs()

    def _add(self, card: Card, quantity: int, *, foil: bool = False, is_proxy: bool = False,
             section: str | None = None) -> bool:
        try:
            with database.session() as s:
                decks.add_card(s, self.user.id, self.deck.id, card, quantity, section or self.section.value,
                               foil=foil, is_proxy=is_proxy)
        except decks.DeckError as e:
            ui.notify(str(e), type="negative")
            return False
        return True

    @staticmethod
    def _quantity(field: ui.number) -> int | None:
        value = field.value
        if value is None or value != int(value) or not 1 <= value <= decks.MAX_QUANTITY:
            ui.notify(f"Quantidade deve ser um número inteiro de 1 a {decks.MAX_QUANTITY}.", type="warning")
            return None
        return int(value)

    # ---------- buscar ----------
    def _commanders(self) -> list[DeckCard]:
        return [line for line in self.lines if line.section == "commander"]

    def _update_search_filter(self) -> None:
        """Com comandante, a busca pode sugerir só cartas dentro da identidade de cor dele."""
        commanders = self._commanders() if commander.commander_kind(self.deck.format) else []
        self.identity_only.visible = bool(commanders)
        if not commanders or not self.identity_only.value:
            self.search.suggest = None
            return
        letters = "".join(c for c in "WUBRG" if any(c in line.color_identity for line in commanders))
        query = f"id<={letters.lower()}" if letters else "id:c"
        self.search.suggest = lambda text: scryfall.client.suggest_where(text, query)


    def _add_searched(self, card: Card) -> None:
        quantity = self._quantity(self.search_qty)
        if quantity and self._add(card, quantity):
            ui.notify(f"{quantity}x {card.name} no deck ({SECTION_OPTIONS[self.section.value].lower()}).",
                      type="positive")
            self.search.clear()
            self.search_qty.value = 1
            self.refresh()

    async def _add_typed(self, text: str) -> None:
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
            self._add_searched(suggestions[0])
        else:
            ui.notify("Escolha a carta na lista de sugestões.", type="warning")

    # ---------- da coleção ----------
    def _collection_open(self) -> bool:
        # o valor das abas pode ser o próprio ui.tab ou o nome dele, conforme quem trocou a aba
        return self.add_tabs.value in (self.collection_tab, self.collection_tab.props.get("name"))

    def _render_collection(self, reload: bool = False) -> None:
        if not self._collection_open():
            return
        if reload or self.entries is None:
            with database.session() as s:
                self.entries = collection.list_entries(s, self.user.id)
        needle = (self.collection_filter.value or "").strip().lower()
        entries = [e for e in self.entries
                   if not needle or needle in f"{e.card_name} {e.set_name} {e.set_code}".lower()]
        in_deck = {}
        for line in self.lines:
            in_deck[line.oracle_id] = in_deck.get(line.oracle_id, 0) + line.quantity
        self.collection_list.clear()
        with self.collection_list:
            if not self.entries:
                ui.label("Sua coleção está vazia.").classes("text-sm text-gray-500 py-4")
            elif not entries:
                ui.label("Nada na coleção com esse filtro.").classes("text-sm text-gray-500 py-4")
            for entry in entries[:COLLECTION_ROWS]:
                self._collection_row(entry, in_deck.get(entry.oracle_id, 0))
            if len(entries) > COLLECTION_ROWS:
                ui.label(f"Mostrando {COLLECTION_ROWS} de {len(entries)}. Use o filtro para achar as outras.") \
                    .classes("text-xs text-gray-500 py-2")

    def _collection_row(self, entry: CollectionEntry, in_deck: int) -> None:
        with ui.row().classes("w-full items-center gap-2 no-wrap py-1.5 border-b border-gray-100") \
                .mark(f"collection-entry collection-entry-{entry.id}"):
            if entry.image_small:
                lazy_img(entry.image_small).classes("w-8 shrink-0 rounded-sm")
            with ui.column().classes("gap-0 grow min-w-0"):
                ui.label(entry.card_name).classes("text-sm font-medium truncate w-full")
                details = [entry.set_name + (f" ({entry.set_code})" if entry.set_code else ""),
                           f"tem {entry.quantity}"]
                if in_deck:
                    details.append(f"{in_deck} no deck")
                if entry.is_proxy:
                    details.append("proxy")
                if entry.foil:
                    details.append("foil")
                ui.label(" · ".join(details)).classes("text-xs text-gray-500 truncate w-full")
            qty = self._qty_input(f"collection-qty-{entry.id}").classes("w-16")
            ui.button(icon="add", on_click=lambda e=entry, q=qty: self._add_entry(e, q)) \
                .props("flat round dense color=primary").tooltip("Pôr no deck").mark(f"add-entry-{entry.id}")

    async def _add_entry(self, entry: CollectionEntry, qty: ui.number) -> None:
        quantity = self._quantity(qty)
        if not quantity:
            return
        try:
            card = await entry_card(self.user.id, entry)
        except (scryfall.ScryfallError, collection.CollectionError, custom_cards.CustomCardError) as e:
            ui.notify(f"Não foi possível adicionar: {e}", type="negative")
            return
        if self._add(card, quantity, foil=entry.foil, is_proxy=entry.is_proxy):
            ui.notify(f"{quantity}x {entry.card_name} no deck.", type="positive")
            self.refresh()

    # ---------- lista em texto ----------
    async def _import_text(self) -> None:
        text = self.text.value or ""
        parsed, errors = decklist.parse_decklist(text, self.section.value)
        if not parsed and not errors:
            ui.notify("Cole a lista de cartas primeiro.", type="warning")
            return
        customs = {c.name.lower(): c for c in self.customs}
        official = [line for line in parsed if line.name.lower() not in customs]
        try:
            found = await self._find(official)
        except scryfall.ScryfallError as e:
            ui.notify(f"Não deu para consultar o Scryfall: {e}", type="negative")
            return
        added, failed = 0, []
        with database.session() as s:  # uma sessão para a lista toda, não uma por linha
            for line in parsed:
                card = custom_card_as_card(customs[line.name.lower()]) if line.name.lower() in customs \
                    else found.get(line.line_no)
                if card is None:
                    failed.append((line, "Carta não encontrada no Scryfall."))
                    continue
                try:  # add_card confere tudo antes de mexer no deck: o erro de uma linha não estraga as outras
                    decks.add_card(s, self.user.id, self.deck.id, card, line.quantity,
                                   line.section or self.section.value, foil=line.foil)
                except decks.DeckError as e:
                    failed.append((line, str(e)))
                    continue
                added += line.quantity
        self._show_import_result(added, failed, errors)
        self.refresh()

    async def _find(self, lines: list[decklist.DecklistLine]) -> dict[int, Card]:
        """Cartas da lista pelo Scryfall, em lote. Com edição que não bate, tenta de novo só pelo nome."""
        def identifier(line: decklist.DecklistLine, with_set: bool) -> dict:
            if with_set and line.set_code and line.collector_number:
                return {"set": line.set_code, "collector_number": line.collector_number}
            if with_set and line.set_code:
                return {"name": line.name, "set": line.set_code}
            return {"name": line.name}

        if not lines:
            return {}
        cards = await scryfall.client.find_cards([identifier(line, True) for line in lines])
        found = {line.line_no: card for line, card in zip(lines, cards, strict=True) if card}
        retry = [line for line in lines if line.line_no not in found and line.set_code]
        if retry:
            cards = await scryfall.client.find_cards([identifier(line, False) for line in retry])
            found |= {line.line_no: card for line, card in zip(retry, cards, strict=True) if card}
        return found

    def _show_import_result(self, added: int, failed: list, errors: list[decklist.DecklistError]) -> None:
        problems = sorted([(e.line_no, e.text, e.reason) for e in errors] +
                          [(line.line_no, f"{line.quantity} {line.name}", reason) for line, reason in failed])
        self.text_result.clear()
        with self.text_result:
            if added:
                ui.label(f"{fmt.plural(added, 'carta adicionada', 'cartas adicionadas')}.") \
                    .classes("text-sm text-green-700")
            if problems:
                ui.label(f"{fmt.plural(len(problems), 'linha não reconhecida', 'linhas não reconhecidas')}: "
                         "ficaram na caixa acima para corrigir e adicionar de novo.").classes("text-sm text-red-700")
                for line_no, text, reason in problems:
                    ui.label(f"Linha {line_no}: {text} ({reason})").classes("text-xs text-gray-600") \
                        .mark("decklist-problem")
        # só o que falhou volta para a caixa, com o cabeçalho da seção quando ela não é a escolhida
        retry, section = [], self.section.value
        for line, _ in sorted(failed, key=lambda item: item[0].line_no):
            if line.section != section:
                section = line.section
                retry.append(SECTION_HEADERS[section])
            retry.append(f"{line.quantity} {line.name}")
        retry += [e.text for e in errors]
        self.text.value = "\n".join(retry)

    # ---------- personalizadas ----------
    def _render_customs(self) -> None:
        self.custom_list.clear()
        with self.custom_list:
            if not self.customs:
                ui.label("Cartas que não existem no Magic. Criadas aqui, ficam só neste deck, a não ser que você "
                         "marque para guardar na coleção.").classes("text-xs text-gray-500 py-2")
            for custom in self.customs:
                self._custom_row(custom)

    def _custom_row(self, custom: CustomCard) -> None:
        with ui.row().classes("w-full items-center gap-2 no-wrap py-1.5 border-b border-gray-100") \
                .mark(f"custom-card custom-card-{custom.id}"):
            with ui.column().classes("gap-0 grow min-w-0"):
                with ui.row().classes("items-center gap-1 no-wrap min-w-0"):
                    ui.label(custom.name).classes("text-sm font-medium truncate")
                    if custom.mana_cost:
                        ui.html(fmt.symbols_html(custom.mana_cost), sanitize=False).classes("text-sm shrink-0")
                ui.label(" · ".join(filter(None, [custom.type_line, "na coleção" if custom.in_collection
                                                  else "só neste deck"]))).classes("text-xs text-gray-500 truncate")
            ui.button(icon="edit", on_click=lambda c=custom: self._edit_custom_card(c)) \
                .props("flat round dense").tooltip("Editar").mark(f"edit-custom-card-{custom.id}")
            qty = self._qty_input(f"custom-qty-{custom.id}").classes("w-16")
            ui.button(icon="add", on_click=lambda c=custom, q=qty: self._add_custom(c, q)) \
                .props("flat round dense color=primary").tooltip("Pôr no deck").mark(f"add-custom-card-{custom.id}")

    def _add_custom(self, custom: CustomCard, qty: ui.number) -> None:
        quantity = self._quantity(qty)
        if quantity and self._add(custom_card_as_card(custom), quantity):
            ui.notify(f"{quantity}x {custom.name} no deck.", type="positive")
            self.refresh()

    def _new_custom_card(self) -> None:
        def saved(custom: CustomCard, keep: bool) -> None:
            card = custom_card_as_card(custom)
            if keep:
                with database.session() as s:
                    collection.add_card(s, self.user.id, card)
            self._add(card, 1)
            ui.notify(f"{custom.name} criada e colocada no deck.", type="positive")
            self.refresh()

        open_custom_card_dialog(self.user.id, self.deck.id, None, saved)

    def _edit_custom_card(self, custom: CustomCard) -> None:
        def saved(_custom: CustomCard, _keep: bool) -> None:
            ui.notify("Carta personalizada salva.", type="positive")
            self.refresh()

        open_custom_card_dialog(self.user.id, self.deck.id, custom, saved)

    # ---------- cabeçalho ----------
    def _counts_text(self) -> str:
        counts = section_counts(self.lines)
        parts = [fmt.plural(counts["main"] + counts["commander"], "carta", "cartas")]
        parts += [f"{counts[key]} no {SECTION_TITLES[key].lower()}" for key in ("sideboard", "maybe") if counts[key]]
        return " · ".join(parts)

    def _render_header(self) -> None:
        self.header.clear()
        # no celular a capa fica em cima; da largura sm em diante, ao lado
        with self.header, ui.element("div").classes("w-full flex flex-col sm:flex-row no-wrap"):
            with ui.element("div").classes("w-full sm:w-56 shrink-0 h-28 sm:h-auto"):
                deck_cover(self.deck, height="h-full min-h-28")
            with ui.column().classes("grow gap-1 p-4 min-w-0"):
                with ui.row().classes("w-full items-start justify-between gap-2"):
                    with ui.column().classes("gap-0 min-w-0 max-w-full"):
                        ui.label(self.deck.name).classes("text-2xl font-bold break-words line-clamp-2 max-w-full") \
                            .mark("deck-name")
                        ui.label(FORMATS.get(self.deck.format, self.deck.format) if self.deck.format
                                 else "Sem formato").classes("text-sm text-gray-600").mark("deck-format-label")
                    with ui.row().classes("gap-2"):
                        with database.session() as s:
                            wins = ranking.win_count(s, self.deck.id)
                        with ui.button(icon="emoji_events", on_click=self._open_wins).props("outline no-caps") \
                                .tooltip("Vitórias").mark("deck-wins"):
                            ui.label(str(wins)).classes("ml-1").mark("deck-wins-count")
                        ui.button(icon="ios_share", on_click=lambda: open_export_dialog(self.deck, self.lines)) \
                            .props("outline").tooltip("Exportar esta versão").mark("export-deck")
                        ui.button("Editar deck", icon="edit", on_click=self._edit_deck) \
                            .props("outline no-caps").mark("edit-deck")
                        ui.button("Concluir", icon="check", on_click=self._conclude) \
                            .props("unelevated no-caps").mark("conclude")
                # observações logo abaixo do nome; longas começam recolhidas, com "... ver mais"
                expandable_text(self.deck.notes, "deck-notes")
                self._counts_label = ui.label(self._counts_text()).classes("text-sm text-gray-700") \
                    .mark("deck-counts")
                self._version_bar()
                self._command_zone_summary()

    # ---------- versões ----------
    def _version_bar(self) -> None:
        with database.session() as s:
            versions = decks.list_versions(s, self.user.id, self.deck.id)
        options = {v.id: f"{v.name} ({v.card_count})" for v in versions}
        with ui.row().classes("items-center gap-1 no-wrap mt-1"):
            select = ui.select(options, value=self.deck.version_id, label="Versão") \
                .props("outlined dense options-dense").classes("w-56 max-sm:w-44").mark("version-select")
            select.on_value_change(lambda e: self._select_version(e.value))
            self._version_select, self._version_names = select, {v.id: v.name for v in versions}
            ui.button(icon="add", on_click=self._new_version).props("flat round dense") \
                .tooltip("Nova versão (cópia desta)").mark("new-version")
            with ui.button(icon="more_vert").props("flat round dense").mark("version-menu"):
                with ui.menu():
                    ui.menu_item("Renomear versão", on_click=self._rename_version).mark("rename-version")
                    compare = ui.menu_item("Comparar versões",
                                           on_click=lambda: open_compare_dialog(self.user.id, self.deck)) \
                        .mark("compare-versions")
                    compare.enabled = len(versions) > 1
                    item = ui.menu_item("Apagar versão", on_click=self._delete_version).mark("delete-version")
                    item.enabled = len(versions) > 1

    def _select_version(self, version_id: int) -> None:
        if version_id == self.deck.version_id:
            return
        try:
            with database.session() as s:
                decks.select_version(s, self.user.id, self.deck.id, version_id)
        except decks.DeckError as e:
            ui.notify(str(e), type="negative")
        self.refresh()

    def _new_version(self) -> None:
        current = self.deck.version_name

        def create(name: str) -> str | None:
            try:
                with database.session() as s:
                    deck = decks.create_version(s, self.user.id, self.deck.id, name)
            except decks.DeckError as e:
                return str(e)
            ui.notify(f"Versão \"{deck.version_name}\" criada a partir de \"{current}\".", type="positive")
            self.refresh()
            return None

        ask_text("Nova versão", f"Nome (começa como cópia de \"{current}\")", create, ok_label="Criar",
                 max_length=config.VERSION_NAME_MAX)

    def _rename_version(self) -> None:
        def rename(name: str) -> str | None:
            try:
                with database.session() as s:
                    decks.rename_version(s, self.user.id, self.deck.id, self.deck.version_id, name)
            except decks.DeckError as e:
                return str(e)
            self.refresh()
            return None

        ask_text("Renomear versão", "Nome da versão", rename, value=self.deck.version_name,
                 max_length=config.VERSION_NAME_MAX)

    def _delete_version(self) -> None:
        def delete() -> None:
            with database.session() as s:
                deck = decks.delete_version(s, self.user.id, self.deck.id, self.deck.version_id)
            ui.notify(f"Versão apagada. Agora você está em \"{deck.version_name}\".", type="positive")
            self.refresh()

        confirm(f"Apagar a versão \"{self.deck.version_name}\"?", delete,
                detail="As cartas desta versão saem do deck. As outras versões e a coleção não mudam.")

    def _command_zone_summary(self) -> None:
        """Comandante(s) e companheiro com a arte, e o botão para trocar."""
        zone = [line for line in self.lines if line.section in ("commander", "companion")]
        has_commander = bool(commander.commander_kind(self.deck.format))
        if not zone and not has_commander:
            ui.button("Companheiro", icon="pets", on_click=self._edit_zone).props("flat dense no-caps size=sm") \
                .classes("self-start -ml-2").mark("edit-command-zone")
            return
        with ui.row().classes("w-full items-center gap-3 mt-1").mark("command-zone-summary"):
            if has_commander and not any(line.section == "commander" for line in zone):
                ui.label("Sem comandante").classes("text-sm text-amber-700 font-medium")
            for line in zone:  # no celular, dois por linha
                with ui.row().classes("items-center gap-2 no-wrap min-w-0 max-sm:w-[calc(50%-6px)]"):
                    if line.image_normal or line.image_small:
                        ui.image(line.image_normal or line.image_small).props("no-spinner") \
                            .classes("w-14 max-sm:w-10 shrink-0 rounded shadow")
                    with ui.column().classes("gap-0 min-w-0"):
                        ui.label(SECTION_TITLES[line.section]).classes("text-xs text-gray-500")
                        ui.label(line.card_name).classes("text-sm font-medium max-sm:line-clamp-2") \
                            .mark(f"zone-{line.section}")
            label = "Escolher comandante" if has_commander and not zone else "Zona de comando"
            ui.button(label, icon="military_tech", on_click=self._edit_zone).props("outline dense no-caps") \
                .classes("px-2").mark("edit-command-zone")

    def _open_wins(self) -> None:
        with database.session() as s:
            versions = decks.list_versions(s, self.user.id, self.deck.id)
        open_wins_dialog(self.user, self.deck.id, self.deck.name, versions, self.deck.version_id,
                         public=self.deck.visibility == "friends", on_change=self._render_header)

    async def _edit_zone(self) -> None:
        await open_command_zone_dialog(self.user.id, self.deck, self.lines, on_saved=self.refresh)

    def _edit_deck(self) -> None:
        with database.session() as s:
            folder_list = folders.list_folders(s, self.user.id, folders.DECKS)
        options = {NO_FOLDER: "Sem pasta", **{f.id: f.name for f in folder_list}}
        open_deck_dialog(self.user.id, self.deck, options, on_saved=lambda _: self.refresh(),
                         on_deleted=lambda: ui.navigate.to("/decks"))

    # ---------- estatísticas ----------
    def _render_stats(self) -> None:
        """Só calcula com a aba aberta (valor e fontes de mana consultam o Scryfall). Sempre da versão aberta."""
        if self.view.value not in (self.stats_tab, self.stats_tab.props.get("name")):
            return
        with database.session() as s:
            missing = sum(m.quantity for m in decks.missing_in_collection(s, self.user.id, self.deck.id))
        stats = deck_stats.compute(self.lines)
        self.stats_area.clear()
        with self.stats_area:
            value, sources = render_stats(stats, missing, self.lines)
        self._stats_loader.start(value, sources, stats, self.lines)

    # ---------- lista do deck ----------
    def _render_lines(self) -> None:
        self.deck_list.clear()
        self._qty_labels, self._group_of, self._group_totals = {}, {}, {}
        with self.deck_list:
            if not self.lines:
                with ui.column().classes("w-full items-center py-12 gap-2"):
                    ui.icon("style").classes("text-5xl text-gray-300")
                    ui.label("O deck está vazio. Adicione cartas pelo painel ao lado.").classes("text-gray-500")
            for key in SECTION_ORDER:
                lines = [line for line in self.lines if line.section == key]
                if not lines:
                    continue
                if key == "main":  # o principal vem dividido por tipo, como nos sites de deck
                    for group, title, group_lines in deck_stats.group_by_type(lines):
                        self._section(f"group-{group}", group_lines, title)
                else:
                    self._section(f"section-{key}", lines, SECTION_TITLES[key])

    def _section(self, marker: str, lines: list[DeckCard], title: str) -> None:
        with ui.card().classes("w-full gap-0 p-0").mark(marker):
            with ui.row().classes("w-full items-center justify-between px-4 py-2 bg-gray-50"):
                ui.label(title).classes("font-bold")
                self._group_totals[marker] = ui.label(str(sum(line.quantity for line in lines))) \
                    .classes("text-sm text-gray-600")
            for line in lines:
                self._group_of[line.id] = marker
                self._line(line)

    def _line(self, line: DeckCard) -> None:
        with ui.row().classes("w-full items-center gap-2 no-wrap px-1 sm:px-3 py-1.5 border-t border-gray-100 "
                              "hover:bg-gray-50").mark(f"deck-line deck-line-{line.id}"):
            with ui.row().classes("items-center gap-0 shrink-0 no-wrap"):
                ui.button(icon="remove", on_click=lambda li=line: self._change(li, -1)) \
                    .props("flat round dense size=sm").mark(f"line-minus-{line.id}")
                self._qty_labels[line.id] = ui.label(str(line.quantity)).classes("w-7 text-center font-semibold") \
                    .mark(f"line-qty-{line.id}")
                ui.button(icon="add", on_click=lambda li=line: self._change(li, +1)) \
                    .props("flat round dense size=sm").mark(f"line-plus-{line.id}")
            # no celular a miniatura sai para sobrar espaço para o nome
            if line.image_small:
                lazy_img(line.image_small).classes("w-9 shrink-0 rounded-sm max-sm:hidden")
            else:
                with ui.element("div").classes("w-9 flex justify-center shrink-0 max-sm:hidden"):
                    custom_set_icon(26)
            with ui.column().classes("gap-0 grow min-w-0"):
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    path = line_page_path(line)
                    if path:
                        ui.link(line.card_name, path).classes("font-medium truncate min-w-0 text-gray-900 "
                                                              "no-underline")
                    else:
                        ui.label(line.card_name).classes("font-medium truncate min-w-0")
                    if line.mana_cost:
                        ui.html(fmt.symbols_html(line.mana_cost), sanitize=False).classes("shrink-0 text-sm")
                with ui.row().classes("w-full items-center gap-1 no-wrap"):
                    set_icon(line.set_code, line.rarity, bool(line.custom_print_id or line.custom_card_id))
                    ui.label(line.set_name + (f" ({line.set_code})" if line.set_code else "")) \
                        .classes("text-xs text-gray-500 truncate min-w-0")
                # no celular as marcas ficam embaixo do nome; em telas maiores, à direita
                with ui.row().classes("items-center gap-1 sm:hidden"):
                    self._line_flags(line)
            with ui.row().classes("items-center gap-1 shrink-0 max-sm:hidden"):
                self._line_flags(line)
            ui.button(icon="edit", on_click=lambda lid=line.id: self.edit_line(self._current_line(lid))) \
                .props("flat round dense").tooltip("Editar").mark(f"edit-line-{line.id}")

    @staticmethod
    def _line_flags(line: DeckCard) -> None:
        line_badges(line)
        if line.notes:
            ui.icon("sticky_note_2").classes("text-gray-400 text-lg").tooltip(line.notes)

    def _current_line(self, line_id: int) -> DeckCard:
        return next(line for line in self.lines if line.id == line_id)

    def _change(self, line: DeckCard, delta: int) -> None:
        """+ e -: atualiza só a quantidade, o total do grupo e a contagem do topo. Se a linha some (chegou a
        zero), redesenha a lista toda."""
        try:
            with database.session() as s:
                updated = decks.change_quantity(s, self.user.id, self.deck.id, line.id, delta)
        except decks.DeckError as e:
            ui.notify(str(e), type="negative")
            self.refresh()
            return
        if updated is None or line.id not in self._qty_labels:
            self.refresh()
            return
        self.lines = [updated if x.id == updated.id else x for x in self.lines]
        self._qty_labels[updated.id].text = str(updated.quantity)
        group = self._group_of[updated.id]
        self._group_totals[group].text = str(sum(x.quantity for x in self.lines if self._group_of.get(x.id) == group))
        self._counts_label.text = self._counts_text()
        total = sum(x.quantity for x in self.lines if x.section in decks.DECK_SECTIONS)
        current = self.deck.version_id
        options = {**self._version_select.options, current: f"{self._version_names[current]} ({total})"}
        self._version_select.set_options(options, value=current)
        self._render_stats()
        self._render_collection()  # a coluna "no deck" da aba Coleção, se estiver aberta

    async def edit_line(self, line: DeckCard, after=None) -> None:
        """Abre a edição da linha; `after` roda depois do refresh (a revisão usa para se redesenhar)."""
        async def changed() -> None:
            self.refresh()
            if after:
                await after()

        await open_line_dialog(self.user.id, self.deck.id, line, on_change=changed)

    # ---------- concluir ----------
    async def _conclude(self) -> None:
        await ReviewDialog(self).render()


class ReviewDialog:
    """Revisão antes de concluir: todas as cartas (editar ou tirar), avisos do formato e, no fim, as cartas que
    faltam na coleção."""

    def __init__(self, builder: DeckBuilder):
        self.builder = builder
        with ui.context.client.content, ui.dialog().props("maximized-on-mobile") as self.dialog, \
                ui.card().classes("w-full max-w-3xl gap-3").mark("review"):
            with ui.row().classes("w-full items-center justify-between"):
                version = f" · {builder.deck.version_name}" if builder.deck.version_count > 1 else ""
                ui.label(f"Revisar \"{builder.deck.name}\"{version}").classes("text-lg font-bold")
                self.counts = ui.label().classes("text-sm text-gray-600")
            self.warnings = ui.column().classes("w-full gap-1").mark("review-warnings")
            self.list = ui.column().classes("w-full gap-0 max-h-[55vh] overflow-y-auto").mark("review-list")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Continuar editando", on_click=lambda: close_dialog(self.dialog)) \
                    .props("flat no-caps").mark("review-back")
                self.finish = ui.button("Concluir", icon="check", on_click=self._finish) \
                    .props("unelevated no-caps").mark("review-finish")
        self.dialog.on("hide", lambda: close_dialog(self.dialog))
        self.dialog.open()

    async def render(self) -> None:
        builder = self.builder
        lines = builder.lines
        counts = section_counts(lines)
        self.counts.text = fmt.plural(counts["main"] + counts["commander"], "carta", "cartas") + \
            (f" + {counts['sideboard']} no sideboard" if counts["sideboard"] else "")
        self.list.clear()
        with self.list:
            if not lines:
                ui.label("O deck está vazio.").classes("text-gray-500 py-4")
            for key in SECTION_ORDER:
                for line in (li for li in lines if li.section == key):
                    self._row(line)
        self.warnings.clear()
        with self.warnings:
            ui.spinner(size="sm")
        warnings = await deck_validation.check(builder.deck.format, lines)
        if self.dialog.is_deleted:  # fechado enquanto a validação consultava o Scryfall
            return
        self.warnings.clear()
        with self.warnings:
            if builder.deck.format in deck_validation.UNCHECKED:
                ui.label("Deck sem formato definido: as regras não são conferidas.").classes("text-sm text-gray-600")
            elif not warnings:
                with ui.row().classes("items-center gap-2 text-green-700"):
                    ui.icon("verified")
                    ui.label(f"Deck válido em {FORMATS.get(builder.deck.format, builder.deck.format)}.") \
                        .classes("text-sm").mark("review-valid")
            else:
                with ui.column().classes("w-full gap-1 rounded-lg bg-amber-50 border border-amber-300 p-3"):
                    ui.label(f"O deck não está válido em {FORMATS.get(builder.deck.format, builder.deck.format)}. "
                             "Dá para concluir mesmo assim.").classes("text-sm font-semibold text-amber-900")
                    for warning in warnings:
                        ui.label(f"• {warning}").classes("text-sm text-amber-900").mark("review-warning")
        self.finish.text = "Concluir mesmo assim" if warnings else "Concluir"

    def _row(self, line: DeckCard) -> None:
        with ui.row().classes("w-full items-center gap-2 no-wrap py-1 border-b border-gray-100") \
                .mark(f"review-line review-line-{line.id}"):
            ui.label(f"{line.quantity}x").classes("w-10 text-right font-semibold shrink-0")
            with ui.column().classes("gap-0 grow min-w-0"):
                ui.label(line.card_name).classes("text-sm font-medium truncate w-full")
                where = SECTION_TITLES[line.section] + " · " + line.set_name + \
                    (f" ({line.set_code})" if line.set_code else "")
                ui.label(where).classes("text-xs text-gray-500 truncate w-full")
            with ui.row().classes("items-center gap-1 shrink-0"):
                line_badges(line)
            ui.button(icon="edit", on_click=lambda li=line: self.builder.edit_line(li, after=self.render)) \
                .props("flat round dense").mark(f"review-edit-{line.id}")
            ui.button(icon="delete", on_click=lambda li=line: self._remove(li)) \
                .props("flat round dense color=negative").mark(f"review-delete-{line.id}")

    async def _remove(self, line: DeckCard) -> None:
        with database.session() as s:
            decks.remove_line(s, self.builder.user.id, self.builder.deck.id, line.id)
        self.builder.refresh()
        await self.render()

    def _finish(self) -> None:
        builder = self.builder
        with database.session() as s:
            missing = decks.missing_in_collection(s, builder.user.id, builder.deck.id)
        # abre o próximo passo antes de fechar: fechar apaga o diálogo e o contexto dele
        if missing:
            MissingDialog(builder, missing)
        else:
            ui.navigate.to(deck_path(builder.deck.id))
        close_dialog(self.dialog)


class MissingDialog:
    """Pergunta se as cartas do deck que faltam na coleção devem entrar nela."""

    def __init__(self, builder: DeckBuilder, missing: list[decks.Missing]):
        self.builder = builder
        total = sum(m.quantity for m in missing)
        with database.session() as s:
            folder_list = folders.list_folders(s, builder.user.id, folders.COLLECTION)
        with ui.context.client.content, ui.dialog() as self.dialog, \
                ui.card().classes("w-full max-w-lg gap-3").mark("missing"):
            ui.label("Adicionar à coleção?").classes("text-lg font-bold")
            ui.label(f"{fmt.plural(total, 'carta do deck não está', 'cartas do deck não estão')} na sua coleção. "
                     "Elas entram com a edição, foil, proxy, preço e observações de cada linha.") \
                .classes("text-sm text-gray-600")
            with ui.column().classes("w-full gap-0 max-h-72 overflow-y-auto"):
                for item in missing:
                    with ui.row().classes("w-full items-center gap-2 no-wrap py-1 border-b border-gray-100") \
                            .mark("missing-line"):
                        ui.label(f"{item.quantity}x").classes("w-10 text-right font-semibold shrink-0")
                        ui.label(item.line.card_name).classes("text-sm grow truncate")
                        with ui.row().classes("items-center gap-1 shrink-0"):
                            line_badges(item.line)
            self.folder = ui.select({NO_FOLDER: "Sem pasta", **{f.id: f.name for f in folder_list}},
                                    value=NO_FOLDER, label="Pasta da coleção") \
                .props("outlined dense options-dense").classes("w-full").mark("missing-folder")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Não adicionar", on_click=self._skip).props("flat no-caps").mark("missing-skip")
                ui.button(f"Adicionar {total}", icon="inventory_2", on_click=self._add) \
                    .props("unelevated no-caps").mark("missing-add")
        self.dialog.on("hide", lambda: close_dialog(self.dialog))
        self.dialog.open()

    def _skip(self) -> None:
        ui.navigate.to(deck_path(self.builder.deck.id))
        close_dialog(self.dialog)

    def _add(self) -> None:
        folder_id = None if self.folder.value == NO_FOLDER else self.folder.value
        try:
            with database.session() as s:
                added = decks.add_missing_to_collection(s, self.builder.user.id, self.builder.deck.id, folder_id)
        except (collection.CollectionError, folders.FolderError, custom_cards.CustomCardError) as e:
            ui.notify(str(e), type="negative")
            return
        ui.notify(f"{fmt.plural(added, 'carta adicionada', 'cartas adicionadas')} à coleção.", type="positive")
        ui.navigate.to(deck_path(self.builder.deck.id))
        close_dialog(self.dialog)
