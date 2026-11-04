"""Busca simples (/search): campo com sugestões, grade de resultados e "Carregar mais".

Também mostra os resultados da busca avançada, que chega com adv=1 para oferecer o caminho de volta ao formulário.
"""
from nicegui import ui

from mtg_collection.models import Card, SearchResult
from mtg_collection.services import scryfall
from mtg_collection.ui.components.card_search_input import CardSearchInput
from mtg_collection.ui.components.card_tile import card_tile
from mtg_collection.ui.layout import frame
from mtg_collection.ui.routes import card_path, search_path


def open_card(card: Card) -> None:
    """Abre a página da carta (clique na grade ou numa sugestão)."""
    ui.navigate.to(card_path(card.id))


class SearchPage:
    """Estado da busca na página: consulta atual, página carregada e trava contra cliques repetidos (busy)."""
    def __init__(self, initial_query: str = "", from_advanced: bool = False):
        self.from_advanced = from_advanced
        self.initial_query = initial_query.strip()
        self.query = ""
        self.page = 1
        self.busy = False
        self._build(initial_query)

    def _build(self, initial_query: str) -> None:
        with ui.row().classes("w-full items-start gap-2 no-wrap"):
            self.search_input = CardSearchInput(
                on_submit=self.search,
                on_select=open_card,
                placeholder="Buscar carta (ex: lightning bolt, t:dragon c:r)",
                value=initial_query,
            )
            # no celular os botões ficam só com o ícone, para sobrar espaço para o campo
            self.search_button = ui.button(
                icon="search", on_click=lambda: self.search(self.search_input.value)) \
                .tooltip("Pesquisar").mark("search-button")
            with self.search_button:
                ui.label("Pesquisar").classes("ml-2 max-sm:hidden")
            if self.from_advanced:  # a busca avançada abre com os campos que geraram esta busca
                with ui.button(icon="tune", on_click=lambda: ui.navigate.to("/advanced")) \
                        .props("flat no-caps").tooltip("Editar os filtros").mark("back-advanced"):
                    ui.label("Voltar à avançada").classes("ml-2 max-sm:hidden")
            else:
                with ui.button(icon="tune", on_click=lambda: ui.navigate.to("/advanced")) \
                        .props("flat no-caps").tooltip("Busca avançada").mark("advanced-button"):
                    ui.label("Avançada").classes("ml-2 max-sm:hidden")
        self.status = ui.label().classes("text-gray-500")
        # duas cartas por linha no celular; nas telas maiores, quantas couberem
        self.grid = ui.element("div").classes(
            "grid gap-3 sm:gap-4 w-full grid-cols-2 sm:[grid-template-columns:repeat(auto-fill,minmax(190px,1fr))]")
        self.more_button = ui.button("Carregar mais", on_click=self.load_more) \
            .props("outline").classes("self-center")
        self.more_button.visible = False

    async def search(self, query: str) -> None:
        if not query or self.busy:
            return
        self.search_input.hide()
        self.query, self.page = query, 1
        result = await self._fetch()
        if result is not None:
            # Voltar da página da carta refaz esta busca (e mantém o caminho de volta para a avançada)
            same = self.from_advanced and query == self.initial_query
            ui.navigate.history.replace(search_path(query) + ("&adv=1" if same else ""))
            self.grid.clear()
            self._show(result)

    async def load_more(self) -> None:
        if self.busy:
            return
        self.page += 1
        result = await self._fetch()
        if result is None:
            self.page -= 1
        else:
            self._show(result)

    async def _fetch(self) -> SearchResult | None:
        self._set_busy(True)
        try:
            return await scryfall.client.search(self.query, self.page)
        except scryfall.ScryfallError as e:
            ui.notify(str(e), type="negative")
            return None
        finally:
            self._set_busy(False)

    def _show(self, result: SearchResult) -> None:
        with self.grid:
            for card in result.cards:
                card_tile(card, on_click=open_card)
        self.status.text = f"{result.total} cartas encontradas" if result.total else "Nenhuma carta encontrada"
        self.more_button.visible = result.has_more

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        for button in (self.search_button, self.more_button):
            if busy:
                button.props("loading")
            else:
                button.props(remove="loading")


@ui.page("/search")
async def search_page(q: str = "", adv: str = "") -> None:
    with frame("Buscar"):
        page = SearchPage(initial_query=q, from_advanced=adv == "1")
    if q:
        # espera o websocket: a busca usa ui.notify e history.replace, que só funcionam com a página conectada
        await ui.context.client.connected()
        await page.search(q.strip())
