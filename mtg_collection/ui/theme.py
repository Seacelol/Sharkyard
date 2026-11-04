"""Temas da interface: a cor de cada um (inspirada nos cinco terrenos básicos, mais o do tubarão) e o modo
claro, escuro ou automático (segue o aparelho). A escolha fica na conta da pessoa."""
from dataclasses import dataclass

from nicegui import ui

from mtg_collection import database
from mtg_collection.models import User
from mtg_collection.services import accounts


@dataclass(frozen=True, slots=True)
class Theme:
    """Paleta de um tema. `name` é o nome mostrado; a chave em THEMES é o que fica gravado na conta."""
    name: str
    primary: str  # botões, links, destaques
    primary_dark: str  # a mesma cor mais clara, para ler bem no fundo escuro
    header: str  # barra do topo


DEFAULT = "tubarao"
THEMES = {
    "tubarao": Theme("Tubarão", "#1f6fb2", "#5aa7ea", "#13263b"),
    "ilha": Theme("Ilha", "#0284c7", "#38bdf8", "#0c4a6e"),
    "planicie": Theme("Planície", "#a16207", "#e0b23c", "#6b5426"),
    "pantano": Theme("Pântano", "#7e57c2", "#b39dfa", "#221a2e"),
    "montanha": Theme("Montanha", "#c2410c", "#fb8a4c", "#5b1b0c"),
    "floresta": Theme("Floresta", "#15803d", "#3fcf78", "#123d26"),
}
assert tuple(THEMES) == accounts.THEMES  # a lista válida mora em services (sem depender da interface)
MODES = {"auto": "Automático", "light": "Claro", "dark": "Escuro"}

# Fundo, superfícies e as classes de cinza do Tailwind no modo escuro. O Tailwind fica numa camada (@layer) de
# prioridade menor, então estas regras valem sem precisar de !important.
CSS = """
/* fundo e superfícies levam um pouco da cor do tema (--mtg-header), no claro e no escuro */
body { --mtg-bg: color-mix(in srgb, var(--mtg-header, #13263b) 6%, #f4f6f9); --mtg-surface: #ffffff;
       --mtg-border: color-mix(in srgb, var(--mtg-header, #13263b) 10%, #e4e8ef);
       --mtg-soft: color-mix(in srgb, var(--mtg-header, #13263b) 5%, #f6f7f9);
       background: var(--mtg-bg) !important; -webkit-font-smoothing: antialiased;
       font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
body.body--dark { --mtg-bg: color-mix(in srgb, var(--mtg-header) 30%, #07090d);
                  --mtg-surface: color-mix(in srgb, var(--mtg-header) 28%, #121821);
                  --mtg-border: color-mix(in srgb, var(--mtg-header) 35%, #27313f);
                  --mtg-soft: color-mix(in srgb, var(--mtg-header) 30%, #19202b);
                  --q-dark: var(--mtg-surface) !important; --q-dark-page: var(--mtg-bg) !important; color: #e6eaf0; }
/* texto escuro sobre a cor do tema no escuro (a cor fica clara para ler no fundo escuro; branco sumiria nela).
   O ".text-white" do Quasar tem !important numa camada que ganha de qualquer regra nossa no próprio botão, então
   a cor vai no conteúdo de dentro, que herda dele. */
body { --mtg-on-primary: #ffffff; }
body.body--dark { --mtg-on-primary: #0b1016; }
.q-btn.bg-primary > .q-btn__content, .q-badge.bg-primary, .mtg-on-primary { color: var(--mtg-on-primary); }
/* barras presas (rodapé da busca avançada): fundo da página meio transparente, em vez de branco */
.mtg-sticky { background: color-mix(in srgb, var(--mtg-bg) 88%, transparent); backdrop-filter: blur(6px); }
@media (max-width: 639px) { .mtg-sticky { bottom: calc(58px + env(safe-area-inset-bottom)) !important; } }
.bg-gray-50 { background-color: var(--mtg-soft) !important; }
.q-card { border-radius: 14px; box-shadow: 0 1px 2px rgba(15,23,42,.05), 0 2px 8px rgba(15,23,42,.06); }
body.body--dark .q-card { background: var(--mtg-surface); box-shadow: 0 0 0 1px var(--mtg-border); }
.q-btn { border-radius: 10px; }
/* texto sem espaços (ex: "aaaa...") também quebra em vez de estourar a caixa */
.break-words { overflow-wrap: anywhere; }
/* quantidade sem as setinhas de subir e descer */
input[type=number]::-webkit-outer-spin-button, input[type=number]::-webkit-inner-spin-button { -webkit-appearance: none;
  margin: 0; }
input[type=number] { -moz-appearance: textfield; appearance: textfield; }
.q-btn--round { border-radius: 50%; }
.q-field--outlined .q-field__control { border-radius: 10px; }
.app-header { background: var(--mtg-header) !important; box-shadow: 0 1px 0 rgba(255,255,255,.06); }
.nav-btn { opacity: .82; }
/* barra de baixo no celular */
.app-footer { background: var(--mtg-surface) !important; color: #4b5563; border-top: 1px solid var(--mtg-border);
              padding-bottom: env(safe-area-inset-bottom); }
body.body--dark .app-footer { color: #9aa5b5; }
.bottom-item { flex: 1 1 0; display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 8px 0 7px;
               cursor: pointer; -webkit-tap-highlight-color: transparent; }
.bottom-item.bottom-active { color: var(--q-primary); font-weight: 600; }
.nav-btn.nav-active { opacity: 1; background: rgba(255,255,255,.13); }
.app-logo { background: currentColor; -webkit-mask: url('/static/shark.svg') center / contain no-repeat;
            mask: url('/static/shark.svg') center / contain no-repeat; }
.app-logo-full { background: var(--q-primary); -webkit-mask: url('/static/logo.svg') center / contain no-repeat;
                 mask: url('/static/logo.svg') center / contain no-repeat; }
.set-icon.custom-set { background: var(--q-primary);
                       --icon: url('/static/shark.svg') !important; }

body.body--dark .text-gray-900, body.body--dark .text-gray-800 { color: #e6eaf0; }
body.body--dark .text-gray-700 { color: #cdd5e0; }
body.body--dark .text-gray-600 { color: #aab4c3; }
body.body--dark .text-gray-500 { color: #8e9aab; }
body.body--dark .text-gray-400 { color: #6c788a; }
body.body--dark .text-gray-300 { color: #4b5566; }
body.body--dark .bg-white { background-color: var(--mtg-surface); }
body.body--dark .bg-gray-100 { background-color: color-mix(in srgb, var(--mtg-soft), white 4%); }
body.body--dark .bg-gray-200 { background-color: color-mix(in srgb, var(--mtg-soft), white 9%); }
body.body--dark .hover\\:bg-gray-50:hover { background-color: color-mix(in srgb, var(--mtg-soft), white 3%); }
body.body--dark .hover\\:bg-gray-100:hover { background-color: color-mix(in srgb, var(--mtg-soft), white 6%); }
body.body--dark .hover\\:bg-gray-200:hover { background-color: color-mix(in srgb, var(--mtg-soft), white 10%); }
body.body--dark .border-gray-100 { border-color: var(--mtg-border); }
body.body--dark .border-gray-200 { border-color: var(--mtg-border); }
body.body--dark .border-gray-300 { border-color: #364152; }
body.body--dark .text-red-600 { color: #f87171; }
body.body--dark .text-red-700 { color: #fca5a5; }
body.body--dark .text-green-700 { color: #4ade80; }
body.body--dark .text-amber-700, body.body--dark .text-amber-800, body.body--dark .text-amber-900 { color: #fcd34d; }
body.body--dark .text-orange-600, body.body--dark .text-orange-700 { color: #fdba74; }
body.body--dark .text-purple-600, body.body--dark .text-purple-400 { color: #c4b5fd; }
body.body--dark .bg-blue-50 { background-color: #122235; }
body.body--dark .bg-blue-100 { background-color: #16304b; }
body.body--dark .bg-amber-50 { background-color: #2a2110; }
body.body--dark .border-blue-200 { border-color: #1e3a5f; }
body.body--dark .border-amber-300 { border-color: #6b5313; }
body.body--dark .set-icon { background: #cfd6df; }
body.body--dark .rarity-text-common, body.body--dark .rarity-text-uncommon { color: #cbd3dd !important; }
body.body--dark .reminder { color: #8e9aab; }
body.body--dark .set-icon.custom-set { background: var(--q-primary); }
"""


def theme_of(user: User | None) -> Theme:
    return THEMES.get(user.theme if user else DEFAULT, THEMES[DEFAULT])


def _vars(theme: Theme) -> str:
    # !important: o Quasar grava as cores no próprio <body>, e isso ganharia de uma regra comum
    return (f"body{{--q-primary:{theme.primary} !important;--mtg-header:{theme.header}}}"
            f"body.body--dark{{--q-primary:{theme.primary_dark} !important}}")


def _dark_value(mode: str) -> bool | None:
    return {"light": False, "dark": True}.get(mode)  # None: segue o claro/escuro do aparelho


BOOT_CSS = """<style>
html[data-boot=dark] body:not(.body--light):not(.body--dark) { --mtg-bg: #0b1016; background: #0b1016; }
@media (prefers-color-scheme: dark) {
  html[data-boot=auto] body:not(.body--light):not(.body--dark) { --mtg-bg: #0b1016; background: #0b1016; } }
</style>"""


def _patch_initial_dark() -> None:
    """Faz a página já nascer no modo certo, sem piscar claro antes de ficar escura ao trocar de página.

    O NiceGUI escreve o modo inicial no HTML a partir da configuração da rota (a mesma para todo mundo); o modo de
    cada pessoa só era aplicado depois, quando a página conectava. Aqui o HTML de cada pessoa sai com o modo dela.
    A troca vale só durante a montagem do HTML, que é síncrona: duas pessoas nunca se misturam."""
    from nicegui.client import Client
    if getattr(Client, "_mtg_dark_patch", False):
        return
    original = Client.build_response

    def build_response(self, request, status_code: int = 200):
        if not hasattr(self, "mtg_dark"):
            return original(self, request, status_code)
        saved = self.page.dark
        self.page.dark = self.mtg_dark
        try:
            return original(self, request, status_code)
        finally:
            self.page.dark = saved

    Client.build_response = build_response
    Client._mtg_dark_patch = True


def apply(user: User | None) -> None:
    """Aplica as cores e o modo na página que está sendo montada. Sem usuário (login): tema padrão, automático."""
    _patch_initial_dark()
    dark = _dark_value(user.theme_mode if user else "auto")
    ui.context.client.mtg_dark = dark
    # antes do Quasar iniciar o <body> ainda não tem body--dark nem body--light: o fundo já sai escuro quando
    # for o caso (escolha da pessoa ou, no automático, o aparelho), em vez de piscar o fundo claro
    boot = {True: "dark", False: "light"}.get(dark, "auto")
    ui.add_head_html(f"<script>document.documentElement.dataset.boot = '{boot}';</script>" + BOOT_CSS)
    theme = theme_of(user)
    # guardado no cliente para a escolha de aparência trocar o modo sem recarregar a página
    ui.context.client.mtg_dark_mode = ui.dark_mode(_dark_value(user.theme_mode if user else "auto"))
    ui.add_css(CSS + SWITCH_CSS)
    ui.add_head_html(f'<meta name="theme-color" content="{theme.header}"><style id="mtg-theme">{_vars(theme)}</style>')


def _show(theme_key: str, mode: str) -> None:
    """Troca as cores e o modo da página aberta, na hora."""
    theme = THEMES[theme_key]
    dark = getattr(ui.context.client, "mtg_dark_mode", None)
    if dark is not None:
        dark.value = _dark_value(mode)
    ui.run_javascript(f"document.getElementById('mtg-theme').textContent = {_vars(theme)!r};"
                      f"document.querySelector('meta[name=theme-color]')?.setAttribute('content', '{theme.header}');")


# ---------- chave claro/escuro ----------
SWITCH_CSS = """
.mode-switch { position: relative; width: 56px; height: 30px; border-radius: 999px; background: #b4b4b4; border: 0;
               padding: 0; cursor: pointer; flex-shrink: 0; transition: background .2s;
               box-shadow: inset 0 0 0 1px rgba(255,255,255,.18); -webkit-tap-highlight-color: transparent; }
.mode-switch .mode-knob { position: absolute; top: 3px; left: 3px; width: 24px; height: 24px; border-radius: 50%;
                          background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.3); transition: transform .2s; }
.mode-switch .mode-sun, .mode-switch .mode-moon { position: absolute; top: 50%; font-size: 17px; color: #fff;
                                                  transform: translateY(-50%); transition: opacity .2s; }
.mode-switch .mode-sun { right: 7px; }
.mode-switch .mode-moon { left: 7px; opacity: 0; }
body.body--dark .mode-switch { background: #2c2c2c; }
body.body--dark .mode-switch .mode-knob { transform: translateX(26px); }
body.body--dark .mode-switch .mode-sun { opacity: 0; }
body.body--dark .mode-switch .mode-moon { opacity: 1; }
.mode-switch.mode-switch-lg { transform: scale(1.2); transform-origin: left center; margin-right: 12px; }
"""


def mode_switch(on_click, large: bool = False) -> ui.element:
    """Chave no estilo sol/lua. A posição vem do CSS (segue o claro/escuro real da página, inclusive no automático),
    então todas as chaves da tela ficam iguais sem precisar avisar umas às outras."""
    with ui.element("button").classes("mode-switch" + (" mode-switch-lg" if large else "")) \
            .props('type="button" aria-label="Alternar entre claro e escuro"') as switch:
        ui.element("span").classes("mode-knob")
        ui.icon("light_mode").classes("mode-sun")
        ui.icon("dark_mode").classes("mode-moon")
    switch.on("click", on_click)
    return switch


async def _is_dark_now() -> bool:
    return bool(await ui.run_javascript("document.body.classList.contains('body--dark')", timeout=5))


def _save(user_id: int, theme: str | None = None, mode: str | None = None) -> User:
    """Grava o que mudou, aplica na página e atualiza as outras escolhas de aparência abertas nela."""
    with database.session() as s:
        current = accounts.get_user(s, user_id)
        updated = accounts.set_theme(s, user_id, theme or current.theme, mode or current.theme_mode)
    _show(updated.theme, updated.theme_mode)
    for refresh in getattr(ui.context.client, "mtg_theme_refresh", []):
        refresh()
    return updated


async def toggle_mode(user: User) -> None:
    """Troca rápida entre claro e escuro (sai do automático)."""
    _save(user.id, mode="light" if await _is_dark_now() else "dark")


def theme_picker(user: User) -> None:
    """Aparência: chave claro/escuro, "automático" e os temas. Cada clique salva e já mostra, sem recarregar."""
    def current() -> User:
        with database.session() as s:  # o usuário da página pode estar desatualizado (escolha feita há pouco)
            return accounts.get_user(s, user.id)

    async def set_auto(value: bool) -> None:
        if value != (current().theme_mode == "auto"):
            _save(user.id, mode="auto" if value else ("dark" if await _is_dark_now() else "light"))

    @ui.refreshable
    def controls() -> None:
        me = current()
        with ui.row().classes("w-full items-center gap-3 no-wrap"):
            mode_switch(lambda: toggle_mode(user), large=True).mark("theme-switch")
            ui.label("Claro / escuro").classes("text-sm")
        ui.checkbox("Automático (segue o claro/escuro do aparelho)", value=me.theme_mode == "auto",
                    on_change=lambda e: set_auto(e.value)).props("dense").classes("text-sm").mark("theme-auto")
        with ui.element("div").classes("grid grid-cols-3 gap-2 w-full"):
            for key, theme in THEMES.items():
                selected = key == me.theme
                with ui.element("div").classes(
                        "flex flex-col items-center gap-1 p-2 rounded-xl cursor-pointer border-2 "
                        + ("border-[var(--q-primary)]" if selected else "border-transparent hover:bg-gray-100")) \
                        .on("click", lambda k=key: _save(user.id, theme=k)).mark(f"theme-{key}"):
                    with ui.element("div").classes("relative w-10 h-10 rounded-full overflow-hidden shadow") \
                            .style(f"background:{theme.header}"):
                        ui.element("div").classes("absolute right-0 bottom-0 w-5 h-5 rounded-tl-full") \
                            .style(f"background:{theme.primary}")
                    ui.label(theme.name).classes("text-xs" + (" font-bold" if selected else ""))

    client = ui.context.client
    if not hasattr(client, "mtg_theme_refresh"):
        client.mtg_theme_refresh = []
    with ui.column().classes("w-full gap-3"):
        controls()
    client.mtg_theme_refresh.append(controls.refresh)


def open_theme_dialog(user: User) -> None:
    """Janela de Aparência (computador). Uma só por página: abrir de novo só mostra a mesma."""
    client = ui.context.client
    dialog = getattr(client, "mtg_theme_dialog", None)
    if dialog is not None and not dialog.is_deleted:
        dialog.open()
        return
    with client.content, ui.dialog() as dialog, ui.card().classes("w-80 max-w-[90vw] gap-4 m-3 shadow-2xl"):
        ui.label("Aparência").classes("text-lg font-bold")
        theme_picker(user)
        ui.button("Fechar", on_click=dialog.close).props("flat no-caps").classes("self-end").mark("theme-close")
    # sem escurecer a página e no canto: dá para ver as cores mudando; fecha só no botão
    dialog.props("seamless position=right").mark("theme-dialog")
    client.mtg_theme_dialog = dialog
    dialog.open()
