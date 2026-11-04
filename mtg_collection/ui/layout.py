"""Moldura comum a todas as páginas: cabeçalho, navegação, tema, estilos e área de conteúdo."""
import asyncio
from contextlib import contextmanager

from nicegui import Client, background_tasks, ui

from mtg_collection import config
from mtg_collection.ui import assets, auth, theme
from mtg_collection.ui.components.avatar import user_avatar
from mtg_collection.ui.components.card_search_input import CardSearchInput
from mtg_collection.ui.routes import card_path, search_path

# (rótulo, rota, ícone, caminhos em que o item fica destacado). Cada página nova entra aqui para aparecer no menu.
# "Buscar" não navega: abre o campo de busca no próprio cabeçalho.
SEARCH_PREFIXES = ("/search", "/card")
NAV_ITEMS = [
    ("Busca avançada", "/advanced", "tune", ("/advanced",)),
    ("Coleção", "/collection", "collections_bookmark", ("/collection",)),
    ("Decks", "/decks", "style", ("/deck",)),
    ("Ranking", "/ranking", "leaderboard", ("/ranking",)),
]
# barra de baixo no celular: início e as mesmas páginas, com rótulos curtos
MOBILE_ITEMS = [("Início", "/", "home", ("/",)), ("Avançada", "/advanced", "tune", ("/advanced",)),
                ("Coleção", "/collection", "collections_bookmark", ("/collection",)),
                ("Decks", "/decks", "style", ("/deck",)), ("Ranking", "/ranking", "leaderboard", ("/ranking",))]

STYLES = """
.mana-symbol { display: inline-block; height: 1.05em; width: 1.05em; vertical-align: -0.15em; margin: 0 1px; }
.mana-cost .mana-symbol { height: 1.6rem; width: 1.6rem; filter: drop-shadow(-1px 1px 0 rgba(0,0,0,.35)); }
.reminder { font-style: italic; color: #6b7280; }
.card-image { border-radius: 4.75% / 3.5%; box-shadow: 0 10px 30px rgba(0,0,0,.25); aspect-ratio: 488 / 680; }
.set-icon { width: 28px; height: 28px; background: #1f2937;
            -webkit-mask: var(--icon) center / contain no-repeat; mask: var(--icon) center / contain no-repeat; }
.set-icon.rarity-uncommon { background: linear-gradient(135deg, #4b5a63, #c9d7e0 50%, #4b5a63); }
.set-icon.rarity-rare { background: linear-gradient(135deg, #85651a, #f0d98c 50%, #85651a); }
.set-icon.rarity-mythic { background: linear-gradient(135deg, #b3260e, #f7a63a 50%, #b3260e); }
.set-icon.rarity-special, .set-icon.rarity-bonus { background: linear-gradient(135deg, #5b21b6, #c4a6f5 50%, #5b21b6); }
.prints-scroll { scrollbar-width: thin; scrollbar-color: #cbd5e1 transparent; }
/* cabeçalho que se recolhe ao rolar para baixo (prop "reveal" do Quasar): só no celular */
@media (min-width: 640px) { .q-header--hidden { transform: none !important; } }
"""


SESSION_CHECK_SECONDS = 10.0
SESSION_DROP_DELAY = 1.0  # tempo para a ordem de ir ao login chegar ao navegador antes de fechar a conexão


def _check_session() -> None:
    """Página aberta de uma sessão que deixou de valer (senha trocada em outro lugar, saiu em outra aba):
    vai para o login e derruba a página no servidor. Só mandar para o login não basta: os botões da página
    continuam ligados no servidor com o usuário de antes, e quem manda eventos pela conexão aberta (sem
    obedecer ao redirecionamento) continuaria mexendo nos dados."""
    if auth.current_user() is not None:
        return
    client = ui.context.client
    ui.navigate.to("/login")
    # sem os elementos, eventos que ainda chegarem são ignorados (não acham o elemento); a fila de mensagens
    # continua de pé para levar o redirecionamento. O timer some junto, por isso o resto vai em outra tarefa.
    client.remove_all_elements()
    background_tasks.create(_drop_client(client), name="sessao-revogada")


async def _drop_client(client: Client) -> None:
    await asyncio.sleep(SESSION_DROP_DELAY)
    if client.id in Client.instances:  # o navegador pode já ter saído e o NiceGUI apagado sozinho
        client.delete()


def _current_path() -> str:
    request = ui.context.client.request
    return request.url.path if request is not None else ""


def _is_active(prefixes: tuple[str, ...], path: str) -> bool:
    return any(path == p if p == "/" else path.startswith(p) for p in prefixes)


def _page_setup(title: str, user) -> None:
    ui.page_title(f"{title} | {config.APP_NAME}")
    theme.apply(user)
    ui.add_css(STYLES)
    ui.add_head_html(assets.HEAD_HTML)


def _brand() -> None:
    with ui.link(target="/").classes("flex items-center gap-2 no-underline text-white shrink-0").mark("brand"):
        ui.element("div").classes("app-logo w-8 h-8")
        ui.label(config.APP_NAME).classes("text-lg font-bold tracking-tight whitespace-nowrap")


class HeaderSearch:
    """Busca no cabeçalho: "Buscar" (ou a lupa, no celular) abre o campo ali mesmo, com as sugestões; Enter leva
    aos resultados e escolher uma sugestão abre a carta. Esc ou o X fecham e o menu volta."""

    def __init__(self, hide_when_open: list[tuple[ui.element, str]]):
        self.hide_when_open = hide_when_open  # (elemento, classe que esconde: "hidden" ou só no celular)
        with ui.row().classes("grow no-wrap items-center gap-1 min-w-0").mark("header-search-box") as self.box:
            self.field = CardSearchInput(on_submit=self._submit, on_select=self._open_card, autofocus=False,
                                         placeholder="Buscar carta (ex: lightning bolt, t:dragon)",
                                         marker="header-search")
            self.field.input.props("dark standout dense rounded clearable=false").classes("min-w-0")
            self.field.input.on("keydown.esc", self.close)
            ui.button(icon="close", on_click=self.close).props("flat round dense color=white") \
                .mark("header-search-close")
        self.box.visible = False

    def open(self) -> None:
        for element, hide in self.hide_when_open:
            element.classes(add=hide)
        self.box.visible = True
        self.field.input.run_method("focus")

    def close(self) -> None:
        self.field.hide()
        self.box.visible = False
        for element, hide in self.hide_when_open:
            element.classes(remove=hide)

    async def _submit(self, query: str) -> None:
        if query:
            ui.navigate.to(search_path(query))

    @staticmethod
    def _open_card(card) -> None:
        ui.navigate.to(card_path(card.id))


@contextmanager
def frame(title: str):
    """Moldura das páginas de quem está logado. Desktop: menu no cabeçalho. Celular: cabeçalho com logo, busca e
    conta, e as páginas numa barra embaixo (como um app)."""
    user = auth.current_user()
    _page_setup(title, user)
    path = _current_path()
    # reveal: some ao rolar para baixo e volta assim que rola para cima (no desktop o CSS mantém fixo)
    with ui.header().props("reveal reveal-offset=56") \
            .classes("app-header items-center gap-2 sm:gap-4 px-3 sm:px-6 no-wrap"):
        brand = ui.element("div").classes("shrink-0")
        with brand:
            _brand()
        nav = ui.row().classes("gap-1 no-wrap max-sm:hidden ml-2")
        spacer = ui.element("div").classes("grow")
        search = HeaderSearch([(brand, "max-sm:hidden"), (nav, "hidden"), (spacer, "hidden")])
        with nav:
            searching = any(path.startswith(p) for p in SEARCH_PREFIXES)
            ui.button("Buscar", icon="search", on_click=search.open).props("flat color=white no-caps") \
                .classes("nav-btn" + (" nav-active" if searching else "")).mark("nav-search")
            for label, target, icon, prefixes in NAV_ITEMS:
                ui.button(label, icon=icon, on_click=lambda p=target: ui.navigate.to(p)) \
                    .props("flat color=white no-caps") \
                    .classes("nav-btn" + (" nav-active" if _is_active(prefixes, path) else ""))
        with ui.element("div").classes("shrink-0 sm:hidden") as mobile_search:
            ui.button(icon="search", on_click=search.open).props("flat round color=white").mark("nav-search-mobile")
        search.hide_when_open.append((mobile_search, "hidden"))
        if user:
            with ui.element("div").classes("shrink-0 flex items-center") as quick_mode:
                theme.mode_switch(lambda: theme.toggle_mode(user)).mark("header-mode-switch")
            search.hide_when_open.append((quick_mode, "max-sm:hidden"))
            with ui.button().props("flat color=white no-caps").classes("px-1 sm:px-2 shrink-0").mark("user-menu"):
                user_avatar(user.display_name, user.avatar_filename, 28)
                ui.label(user.display_name).classes("ml-2 max-sm:hidden max-w-40 truncate")
                with ui.menu():
                    ui.menu_item(user.display_name).props("disable").classes("sm:hidden")
                    ui.menu_item("Minha conta", on_click=lambda: ui.navigate.to("/account")).mark("menu-account")
                    # computador: a janela de Aparência; celular: a seção em Minha conta
                    ui.menu_item("Aparência", on_click=lambda: theme.open_theme_dialog(user)) \
                        .classes("max-sm:hidden").mark("menu-theme")
                    ui.menu_item("Aparência", on_click=lambda: ui.navigate.to("/account#aparencia")) \
                        .classes("sm:hidden").mark("menu-theme-mobile")
                    ui.menu_item("Sair", on_click=_logout).mark("menu-logout")
    with ui.footer().classes("app-footer sm:hidden p-0").mark("bottom-nav"):
        with ui.row().classes("w-full no-wrap justify-around gap-0"):
            for label, target, icon, prefixes in MOBILE_ITEMS:
                active = _is_active(prefixes, path)
                with ui.element("div").classes("bottom-item" + (" bottom-active" if active else "")) \
                        .on("click", lambda p=target: ui.navigate.to(p)).mark(f"bottom-{target}"):
                    ui.icon(icon).classes("text-[22px]")
                    ui.label(label).classes("text-[11px] leading-none")
    ui.timer(SESSION_CHECK_SECONDS, _check_session)
    with ui.column().classes("w-full max-w-screen-2xl mx-auto p-3 sm:p-6 gap-4"):
        yield


@contextmanager
def public_frame(title: str):
    """Moldura das páginas abertas (entrar, criar conta): sem navegação."""
    _page_setup(title, None)
    with ui.header().classes("app-header items-center px-3 sm:px-6"):
        _brand()
    with ui.column().classes("w-full p-3 sm:p-6"):
        yield


def _logout() -> None:
    auth.end_session()
    ui.navigate.to("/login")
