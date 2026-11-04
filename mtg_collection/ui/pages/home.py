"""Página inicial: o logo no meio e o campo de busca, como a do Scryfall. Pesquisar leva para /search."""
from nicegui import ui

from mtg_collection import config, database
from mtg_collection.models import Card
from mtg_collection.services import collection, decks, scryfall
from mtg_collection.ui import auth, formatting
from mtg_collection.ui.components.card_search_input import CardSearchInput
from mtg_collection.ui.layout import frame
from mtg_collection.ui.routes import card_path, search_path

LINKS = [("Busca avançada", "/advanced", "tune"), ("Coleção", "/collection", "collections_bookmark"),
         ("Decks", "/decks", "style")]


@ui.page("/")
async def home_page(q: str = "", adv: str = "") -> None:
    """Página inicial com a busca e um resumo da coleção. `q`/`adv` só existem para redirecionar links antigos."""
    if q:  # endereço antigo da busca ("/?q=..."): continua funcionando
        ui.navigate.to(search_path(q) + ("&adv=1" if adv == "1" else ""))
        return
    user = auth.current_user()
    with database.session() as s:
        cards, deck_count = collection.count_cards(s, user.id), decks.count_decks(s, user.id)

    async def submit(query: str) -> None:
        if query:
            ui.navigate.to(search_path(query))

    def open_card(card: Card) -> None:
        ui.navigate.to(card_path(card.id))

    async def random_card() -> None:
        try:
            card = await scryfall.client.random_card()
        except scryfall.ScryfallError as e:
            ui.notify(str(e), type="negative")
            return
        open_card(card)

    with frame("Início"), ui.column().classes("w-full max-w-2xl mx-auto items-center gap-6 pt-6 sm:pt-16 pb-10"):
        ui.element("div").classes("app-logo-full w-36 h-36 sm:w-48 sm:h-48").mark("home-logo")
        with ui.column().classes("items-center gap-1"):
            ui.label(config.APP_NAME).classes("text-3xl sm:text-4xl font-bold tracking-tight")
            ui.label("Busque cartas, organize a coleção e monte decks com os amigos.") \
                .classes("text-gray-500 text-center")
        with ui.row().classes("w-full no-wrap gap-2 items-start"):
            search = CardSearchInput(on_submit=submit, on_select=open_card,
                                     placeholder="Buscar carta (ex: lightning bolt, t:dragon)")
            search.input.props("rounded").classes("text-lg")
            ui.button(icon="search", on_click=lambda: submit(search.value)).props("round unelevated") \
                .classes("mt-0.5").tooltip("Pesquisar").mark("home-search")
        with ui.row().classes("justify-center gap-x-1 gap-y-1"):
            ui.button("Carta aleatória", icon="casino", on_click=random_card) \
                .props("flat no-caps color=primary").mark("random-card")
            for label, path, icon in LINKS:
                ui.button(label, icon=icon, on_click=lambda p=path: ui.navigate.to(p)) \
                    .props("flat no-caps color=primary")
        ui.label(f"Sua coleção: {formatting.plural(cards, 'carta', 'cartas')} · "
                 f"{formatting.plural(deck_count, 'deck', 'decks')}").classes("text-sm text-gray-500") \
            .mark("home-stats")
