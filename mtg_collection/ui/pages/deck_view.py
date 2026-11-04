"""Decks dos amigos: a lista (/decks/friends) e a página de um deck de outro usuário, só para ver.

As rotas /deck/<id> (ver) e /deck/<id>/edit (montar) também ficam aqui. Ver: o dono e os amigos (se o deck estiver
visível) abrem a mesma página, com quatro jeitos de mostrar as cartas; só o dono tem o botão de editar. Quem vê
escolhe a versão (começa na versão atual) sem mudar nada no deck."""
from dataclasses import replace

from nicegui import app, ui

from mtg_collection import database
from mtg_collection.models import Deck, DeckCard, User
from mtg_collection.services import deck_stats, decks, ranking
from mtg_collection.ui import auth
from mtg_collection.ui import formatting as fmt
from mtg_collection.ui.components.avatar import user_avatar
from mtg_collection.ui.components.controls import SEGMENTED, back_button, lazy_img
from mtg_collection.ui.components.deck_dialog import FORMATS
from mtg_collection.ui.components.deck_stats_view import StatsLoader, render_stats
from mtg_collection.ui.components.expandable_text import expandable_text
from mtg_collection.ui.components.export_dialog import open_export_dialog
from mtg_collection.ui.components.wins_dialog import open_wins_dialog
from mtg_collection.ui.layout import frame
from mtg_collection.ui.pages.deck_builder import (
    SECTION_ORDER,
    SECTION_TITLES,
    DeckBuilder,
    line_badges,
    section_counts,
    set_icon,
)
from mtg_collection.ui.pages.decks import deck_cover
from mtg_collection.ui.routes import card_path, deck_edit_path, deck_path

FRIENDS_PATH = "/decks/friends"


def format_label(deck: Deck) -> str:
    return FORMATS.get(deck.format, deck.format) if deck.format else "Sem formato"


# ---------- lista ----------
class FriendsDecksPage:
    def __init__(self, user: User):
        with database.session() as s:
            self.shared = decks.list_shared_decks(s, user.id)
        with ui.column().classes("w-full max-w-6xl mx-auto gap-4"):
            back_button("Meus decks", lambda: ui.navigate.to("/decks"))
            with ui.row().classes("w-full items-end justify-between"):
                with ui.column().classes("gap-0"):
                    ui.label("Decks dos amigos").classes("text-2xl font-bold")
                    ui.label("Decks que outras pessoas deixaram visíveis para os amigos.") \
                        .classes("text-sm text-gray-600")
            with ui.row().classes("w-full items-center gap-3"):
                self.filter = ui.input(placeholder="Filtrar por deck, pessoa ou formato") \
                    .props("outlined dense clearable").classes("grow").mark("friends-filter")
                owners = sorted({item.owner_name for item in self.shared})
                self.owner = ui.select({"": "Todas as pessoas", **{o: o for o in owners}}, value="") \
                    .props("outlined dense options-dense").classes("w-48").mark("friends-owner")
            self.grid = ui.element("div").classes(
                "grid gap-3 sm:gap-4 w-full grid-cols-2 "
                "sm:[grid-template-columns:repeat(auto-fill,minmax(230px,1fr))]").mark("friends-grid")
        self.filter.on_value_change(self.render)
        self.owner.on_value_change(self.render)
        self.render()

    def render(self) -> None:
        needle = (self.filter.value or "").strip().lower()
        def text(item: decks.SharedDeck) -> str:
            return f"{item.deck.name} {item.owner_name} {format_label(item.deck)}".lower()

        visible = [item for item in self.shared if (not self.owner.value or item.owner_name == self.owner.value)
                   and (not needle or needle in text(item))]
        self.grid.clear()
        with self.grid:
            if not self.shared:
                ui.label("Ninguém deixou decks visíveis ainda. Na edição do deck, \"Visível para os amigos\" "
                         "mostra ele aqui para os outros.").classes("col-span-full text-gray-500 py-8 text-center")
            elif not visible:
                ui.label("Nenhum deck com esse filtro.").classes("col-span-full text-gray-500 py-8 text-center")
            for item in visible:
                self._tile(item)

    @staticmethod
    def _tile(item: decks.SharedDeck) -> None:
        deck = item.deck
        with ui.card().tight().classes("cursor-pointer hover:shadow-xl transition-shadow overflow-hidden min-w-0") \
                .mark(f"friend-deck friend-deck-{deck.id}") as tile:
            tile.on("click", lambda d=deck: ui.navigate.to(deck_path(d.id)))
            deck_cover(deck, height="h-24 sm:h-40")
            with ui.column().classes("gap-0 px-3 py-2 w-full"):
                ui.label(deck.name).classes("font-semibold truncate w-full")
                with ui.row().classes("items-center gap-1 no-wrap"):
                    user_avatar(item.owner_name, item.owner_avatar, 18)
                    ui.label(f"de {item.owner_name}").classes("text-xs text-gray-600")
                details = [format_label(deck), fmt.plural(deck.card_count, "carta", "cartas")]
                if deck.version_count > 1:
                    details.append(fmt.plural(deck.version_count, "versão", "versões"))
                ui.label(" · ".join(details)).classes("text-xs text-gray-500")


# ---------- um deck ----------
VIEW_MODES = {"list": ("Lista", "view_list"), "compact": ("Texto", "notes"), "images": ("Imagens", "grid_view"),
              "stacks": ("Pilhas", "view_column")}
VIEW_KEY = "deck_view_mode"  # lembrado neste navegador
# Carta grande ao lado do mouse: um só <img> fixo na página; qualquer elemento com data-preview mostra a imagem
# dele. Fica à direita do cursor e passa para a esquerda se não couber. Só onde existe mouse (no toque não aparece).
PREVIEW_JS = """
(() => {
  if (window.mtgPreview || !matchMedia('(hover: hover) and (pointer: fine)').matches) return;
  const box = document.createElement('img');
  box.id = 'deck-preview'; box.alt = ''; box.decoding = 'async';
  document.body.appendChild(box);
  const W = 260, H = Math.round(W * 680 / 488), GAP = 18, EDGE = 8;
  const ready = new Set();     // imagens grandes já baixadas (trocar o src é instantâneo)
  const loading = new Map();   // url -> Promise do download em andamento
  let current = null;
  const load = url => {
    if (ready.has(url)) return Promise.resolve();
    if (!loading.has(url)) {
      loading.set(url, new Promise(done => {
        const img = new Image(); img.decoding = 'async';
        img.onload = () => { ready.add(url); loading.delete(url); done(); };
        img.onerror = () => { loading.delete(url); done(); };
        img.src = url;
      }));
    }
    return loading.get(url);
  };
  // baixa as imagens grandes das cartas da página aos poucos (4 por vez), sem atrapalhar o resto
  let preloading = false;
  const preloadAll = async () => {
    if (preloading) return;
    preloading = true;
    const urls = [...new Set([...document.querySelectorAll('[data-preview]')].map(el => el.dataset.preview))]
      .filter(url => !ready.has(url));
    const next = async () => { while (urls.length) await load(urls.shift()); };
    await Promise.all([next(), next(), next(), next()]);
    preloading = false;
  };
  const idle = window.requestIdleCallback || (fn => setTimeout(fn, 300));
  idle(preloadAll);
  new MutationObserver(() => idle(preloadAll))  // trocou o modo de exibição ou a versão: novas cartas
    .observe(document.body, {childList: true, subtree: true});
  const place = e => {
    let x = e.clientX + GAP;
    if (x + W > innerWidth - EDGE) x = e.clientX - GAP - W;  // sem espaço à direita: vai para a esquerda
    const y = Math.min(Math.max(EDGE, e.clientY - H / 2), innerHeight - H - EDGE);
    box.style.transform = `translate(${Math.max(EDGE, x)}px, ${y}px)`;
  };
  document.addEventListener('mouseover', e => {
    const el = e.target.closest('[data-preview]');
    if (el === current) return;
    current = el;
    if (!el) { box.classList.remove('show'); return; }
    const big = el.dataset.preview, small = el.dataset.previewSmall;
    place(e);
    if (ready.has(big)) { box.src = big; box.classList.add('show'); return; }
    // ainda não baixou a grande: mostra na hora a pequena (já está na página) e troca quando a grande chegar
    if (small) { box.src = small; box.classList.add('show'); } else { box.classList.remove('show'); }
    load(big).then(() => { if (current === el) { box.src = big; box.classList.add('show'); } });
  });
  document.addEventListener('mousemove', e => { if (current) place(e); });
  const hide = () => { current = null; box.classList.remove('show'); };
  document.addEventListener('click', hide, true);
  window.addEventListener('scroll', hide, {passive: true});
  window.mtgPreview = true;
})();
"""
VIEW_CSS = """
#deck-preview { position: fixed; left: 0; top: 0; width: 260px; aspect-ratio: 488 / 680; z-index: 9999;
                border-radius: 4.75% / 3.5%; box-shadow: 0 12px 32px rgba(0,0,0,.45); pointer-events: none;
                opacity: 0; transition: opacity .12s; background: #111; }
#deck-preview.show { opacity: 1; }
.deck-card-img { width: 100%; aspect-ratio: 488 / 680; border-radius: 4.75% / 3.5%; display: block;
                 box-shadow: 0 2px 6px rgba(0,0,0,.25); object-fit: cover; }
.deck-card { position: relative; transition: transform .12s ease; }
.deck-card.clickable { cursor: pointer; }
.deck-card.clickable:hover { transform: translateY(-3px); }
.deck-stack .deck-card + .deck-card { margin-top: -118%; }  /* % da largura: mostra só a faixa do nome */
.deck-stack .deck-card:hover { z-index: 10; transform: translateY(-6px); }
.deck-qty { position: absolute; top: 7%; right: 6%; background: rgba(15,23,42,.85); color: #fff; font-weight: 700;
            font-size: .75rem; line-height: 1; padding: .25rem .4rem; border-radius: 6px; }
.deck-compact { columns: 1; column-gap: 2rem; }
@media (min-width: 640px) { .deck-compact { columns: 2; } }
@media (min-width: 1024px) { .deck-compact { columns: 3; } }
.deck-compact > div { break-inside: avoid; }
/* lista em duas colunas que se encaixam (cada uma segue logo abaixo da anterior, sem esperar a do lado) */
.deck-columns { columns: 1; column-gap: 1rem; }
@media (min-width: 1024px) { .deck-columns { columns: 2; } }
.deck-columns > * { break-inside: avoid; margin-bottom: 1rem; }
"""


class DeckViewer:
    """Página de um deck só para ver. O dono tem o botão de editar (abre a montagem); um amigo só vê.
    A versão escolhida aqui não muda a versão atual do deck (só ao clicar em Editar, para editar a que está vendo)."""

    def __init__(self, user: User, shared: decks.SharedDeck, owned: bool = False):
        self.user, self.deck, self.owner_name = user, shared.deck, shared.owner_name
        self.owner_avatar = shared.owner_avatar
        self.owned = owned
        self.version_id = self.deck.version_id
        self._stats_loader = StatsLoader()
        with database.session() as s:
            self.versions = decks.list_versions(s, user.id, self.deck.id) if owned \
                else decks.shared_versions(s, user.id, self.deck.id)
        self.lines: list[DeckCard] = []
        try:
            self.mode = app.storage.user.get(VIEW_KEY, "list")
        except RuntimeError:  # sem armazenamento do navegador (não acontece numa página normal)
            self.mode = "list"
        if self.mode not in VIEW_MODES:
            self.mode = "list"
        ui.add_css(VIEW_CSS)
        ui.add_body_html(f"<script>{PREVIEW_JS}</script>")
        with ui.column().classes("w-full max-w-6xl mx-auto gap-4"):
            back = ("Meus decks", "/decks") if owned else ("Decks dos amigos", FRIENDS_PATH)
            back_button(back[0], lambda: ui.navigate.to(back[1]))
            self.header = ui.card().tight().classes("w-full overflow-hidden")
            with ui.row().classes("w-full items-center justify-between gap-2"):
                with ui.tabs().props("dense no-caps align=left").classes("text-gray-700") as self.view:
                    cards_tab = ui.tab("Cartas", icon="style").mark("view-cards")
                    self.stats_tab = ui.tab("Estatísticas", icon="insights").mark("view-stats")
                self.mode_toggle = ui.toggle({key: label for key, (label, _) in VIEW_MODES.items()},
                                             value=self.mode, on_change=lambda e: self._set_mode(e.value)) \
                    .props(SEGMENTED).mark("view-mode")
            with ui.tab_panels(self.view, value=cards_tab).props("animated=false").classes("w-full bg-transparent"):
                with ui.tab_panel(cards_tab).classes("p-0"):
                    self.list = ui.element("div").classes("w-full p-1").mark("deck-list")
                with ui.tab_panel(self.stats_tab).classes("p-0"):
                    self.stats_area = ui.card().classes("w-full gap-3").mark("deck-stats")
            self.view.on_value_change(self._on_tab)
        self.load()

    def load(self) -> None:
        with database.session() as s:
            self.lines = decks.list_cards(s, self.user.id, self.deck.id, self.version_id) if self.owned \
                else decks.shared_cards(s, self.user.id, self.deck.id, self.version_id)
        self._render_header()
        self._render_lines()
        self._render_stats()

    @property
    def version_name(self) -> str:
        return next((v.name for v in self.versions if v.id == self.version_id), "")

    def _choose_version(self, version_id: int) -> None:
        self.version_id = version_id
        self.load()

    def _on_tab(self) -> None:
        self.mode_toggle.visible = not self._stats_open()
        self._render_stats()

    def _stats_open(self) -> bool:
        return self.view.value in (self.stats_tab, self.stats_tab.props.get("name"))

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        app.storage.user[VIEW_KEY] = mode
        self._render_lines()

    def _edit(self) -> None:
        """Edita a versão que está na tela (vira a versão atual do deck, como no seletor da montagem)."""
        if self.version_id and self.version_id != self.deck.version_id:
            with database.session() as s:
                decks.select_version(s, self.user.id, self.deck.id, self.version_id)
        ui.navigate.to(deck_edit_path(self.deck.id))

    def _render_header(self) -> None:
        counts = section_counts(self.lines)
        self.header.clear()
        with self.header, ui.element("div").classes("w-full flex flex-col sm:flex-row no-wrap"):
            with ui.element("div").classes("w-full sm:w-56 shrink-0 h-28 sm:h-auto"):
                deck_cover(self.deck, height="h-full min-h-28")
            with ui.column().classes("grow gap-1 p-4 min-w-0"):
                with ui.row().classes("w-full items-start justify-between gap-2"):
                    with ui.column().classes("gap-0 min-w-0 max-w-full"):
                        ui.label(self.deck.name).classes("text-2xl font-bold break-words line-clamp-2 max-w-full") \
                            .mark("deck-name")
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            if self.owned:
                                ui.label(format_label(self.deck)).classes("text-sm text-gray-600").mark("deck-owner")
                            else:
                                user_avatar(self.owner_name, self.owner_avatar, 20)
                                ui.label(f"de {self.owner_name} · {format_label(self.deck)}") \
                                    .classes("text-sm text-gray-600").mark("deck-owner")
                    with ui.row().classes("gap-2"):
                        with database.session() as s:
                            wins = ranking.win_count(s, self.deck.id)
                        with ui.button(icon="emoji_events", on_click=self._open_wins).props("outline no-caps") \
                                .tooltip("Vitórias").mark("deck-wins"):
                            ui.label(str(wins)).classes("ml-1").mark("deck-wins-count")
                        ui.button(icon="ios_share", on_click=self._export).props("outline") \
                            .tooltip("Exportar esta versão").mark("export-deck")
                        if self.owned:
                            ui.button("Editar", icon="edit", on_click=self._edit).props("unelevated no-caps") \
                                .mark("open-builder")
                expandable_text(self.deck.notes, "deck-notes")
                parts = [fmt.plural(counts["main"] + counts["commander"], "carta", "cartas")]
                parts += [f"{counts[key]} no {SECTION_TITLES[key].lower()}" for key in ("sideboard", "maybe")
                          if counts[key]]
                ui.label(" · ".join(parts)).classes("text-sm text-gray-700").mark("deck-counts")
                if len(self.versions) > 1:
                    options = {v.id: f"{v.name} ({v.card_count})" for v in self.versions}
                    select = ui.select(options, value=self.version_id, label="Versão") \
                        .props("outlined dense options-dense").classes("w-56 max-sm:w-44 mt-1") \
                        .mark("version-select")
                    select.on_value_change(lambda e: self._choose_version(e.value))
                zone = [line for line in self.lines if line.section in ("commander", "companion")]
                if zone:
                    with ui.row().classes("w-full items-center gap-3 mt-1"):
                        for line in zone:  # no celular, dois por linha
                            with ui.row().classes("items-center gap-2 no-wrap min-w-0 max-sm:w-[calc(50%-6px)]"):
                                if line.image_normal or line.image_small:
                                    ui.image(line.image_normal or line.image_small).props("no-spinner") \
                                        .classes("w-14 max-sm:w-10 shrink-0 rounded shadow")
                                with ui.column().classes("gap-0 min-w-0"):
                                    ui.label(SECTION_TITLES[line.section]).classes("text-xs text-gray-500")
                                    ui.label(line.card_name).classes("text-sm font-medium max-sm:line-clamp-2")

    def _open_wins(self) -> None:
        # o dono registra as próprias vitórias; para o amigo é só leitura (o admin pode corrigir)
        open_wins_dialog(self.user, self.deck.id, self.deck.name, self.versions, self.version_id,
                         public=not self.owned or self.deck.visibility == "friends", on_change=self._render_header)

    def _export(self) -> None:
        open_export_dialog(replace(self.deck, version_name=self.version_name), self.lines)

    def _groups(self) -> list[tuple[str, str, list[DeckCard]]]:
        """(marcador, título, linhas): seções na ordem do deck e o principal dividido por tipo."""
        groups = []
        for key in SECTION_ORDER:
            lines = [line for line in self.lines if line.section == key]
            if not lines:
                continue
            if key == "main":
                groups += [(f"group-{group}", title, group_lines)
                           for group, title, group_lines in deck_stats.group_by_type(lines)]
            else:
                groups.append((f"section-{key}", SECTION_TITLES[key], lines))
        return groups

    def _render_lines(self) -> None:
        self.list.clear()
        groups = self._groups()
        with self.list:
            if not groups:
                message = "O deck está vazio. Clique em Editar para adicionar cartas." if self.owned \
                    else "Esta versão está vazia."
                ui.label(message).classes("text-gray-500 py-8 w-full text-center")
                return
            render = {"list": self._as_list, "compact": self._as_compact, "images": self._as_images,
                      "stacks": self._as_stacks}[self.mode]
            render(groups)

    # ----- modos de exibição -----
    def _as_list(self, groups) -> None:
        with ui.element("div").classes("deck-columns w-full").mark("mode-list"):
            for marker, title, lines in groups:
                self._section(marker, title, lines)

    @staticmethod
    def _as_compact(groups) -> None:
        """Como uma lista de texto: quantidade, nome e custo, em colunas."""
        with ui.card().classes("w-full p-4"), ui.element("div").classes("deck-compact w-full").mark("mode-compact"):
            for marker, title, lines in groups:
                with ui.element("div").classes("mb-4").mark(marker):
                    ui.label(f"{title} ({sum(line.quantity for line in lines)})") \
                        .classes("font-bold text-sm mb-1")
                    for line in lines:
                        with _preview(ui.row().classes("items-center gap-2 no-wrap text-sm py-0.5"), line) \
                                .mark(f"view-line view-line-{line.id}"):
                            ui.label(str(line.quantity)).classes("w-5 text-right text-gray-500 shrink-0")
                            _card_name(line, "truncate min-w-0")
                            if line.mana_cost:
                                ui.html(fmt.symbols_html(line.mana_cost), sanitize=False) \
                                    .classes("shrink-0 text-xs ml-auto")

    @staticmethod
    def _as_images(groups) -> None:
        with ui.column().classes("w-full gap-5").mark("mode-images"):
            for marker, title, lines in groups:
                with ui.column().classes("w-full gap-2").mark(marker):
                    ui.label(f"{title} ({sum(line.quantity for line in lines)})").classes("font-bold")
                    with ui.element("div").classes("grid gap-3 w-full") \
                            .style("grid-template-columns: repeat(auto-fill, minmax(130px, 1fr))"):
                        for line in lines:
                            _card_picture(line)

    @staticmethod
    def _as_stacks(groups) -> None:
        """Uma coluna por tipo com as cartas empilhadas (aparece a faixa do nome; passar o mouse mostra a carta)."""
        with ui.element("div").classes("flex flex-wrap gap-4 w-full items-start").mark("mode-stacks"):
            for marker, title, lines in groups:
                with ui.column().classes("gap-2 w-[150px] sm:w-[170px]").mark(marker):
                    ui.label(f"{title} ({sum(line.quantity for line in lines)})").classes("font-bold text-sm")
                    with ui.element("div").classes("deck-stack w-full pb-2"):
                        for line in lines:
                            _card_picture(line)

    @staticmethod
    def _section(marker: str, title: str, lines: list[DeckCard]) -> None:
        with ui.card().classes("w-full gap-0 p-0").mark(marker):
            with ui.row().classes("w-full items-center justify-between px-4 py-2 bg-gray-50"):
                ui.label(title).classes("font-bold")
                ui.label(str(sum(line.quantity for line in lines))).classes("text-sm text-gray-600")
            for line in lines:
                row = ui.row().classes("w-full items-center gap-2 no-wrap px-3 py-1.5 border-t border-gray-100")
                with _preview(row, line).mark(f"view-line view-line-{line.id}"):
                    ui.label(str(line.quantity)).classes("w-7 text-right font-semibold shrink-0")
                    if line.image_small:
                        lazy_img(line.image_small).classes("w-9 shrink-0 rounded-sm max-sm:hidden")
                    else:  # mantém o alinhamento com as linhas que têm imagem
                        ui.icon("style").classes("w-9 text-2xl text-gray-300 shrink-0 max-sm:hidden")
                    with ui.column().classes("gap-0 grow min-w-0"):
                        with ui.row().classes("w-full items-center gap-2 no-wrap"):
                            _card_name(line, "font-medium truncate min-w-0")
                            if line.mana_cost:
                                ui.html(fmt.symbols_html(line.mana_cost), sanitize=False) \
                                    .classes("shrink-0 text-sm")
                        with ui.row().classes("w-full items-center gap-1 no-wrap"):
                            set_icon(line.set_code, line.rarity, bool(line.custom_print_id or line.custom_card_id))
                            ui.label(line.set_name + (f" ({line.set_code})" if line.set_code else "")) \
                                .classes("text-xs text-gray-500 truncate min-w-0")
                    with ui.row().classes("items-center gap-1 shrink-0"):
                        line_badges(line)

    def _render_stats(self) -> None:
        if not self._stats_open():
            return
        with database.session() as s:  # o que falta na coleção de quem está vendo
            missing = sum(m.quantity for m in decks.missing_against(s, self.user.id, self.lines))
        stats = deck_stats.compute(self.lines)
        self.stats_area.clear()
        with self.stats_area:
            value, sources = render_stats(stats, missing, self.lines)
        self._stats_loader.start(value, sources, stats, self.lines)


def _official_path(line: DeckCard) -> str | None:
    """Carta oficial abre a página dela; as personalizadas só existem no deck."""
    return card_path(line.scryfall_id) if line.scryfall_id and not line.custom_print_id else None


def _card_name(line: DeckCard, classes: str) -> None:
    path = _official_path(line)
    if path:
        ui.link(line.card_name, path).classes(f"{classes} text-gray-900 no-underline")
    else:
        ui.label(line.card_name).classes(classes)


def _preview(element: ui.element, line: DeckCard) -> ui.element:
    """Marca o elemento para mostrar a carta grande ao passar o mouse (se a carta tiver imagem)."""
    src = line.image_normal or line.image_small
    if src:
        element.props["data-preview"] = src
        if line.image_small and line.image_small != src:  # a miniatura já carregada, para mostrar na hora
            element.props["data-preview-small"] = line.image_small
    return element


def _card_picture(line: DeckCard) -> None:
    """Imagem da carta com a quantidade no canto. Sem imagem (carta personalizada): um cartão com o nome."""
    path = _official_path(line)
    with _preview(ui.element("div").classes("deck-card" + (" clickable" if path else "")), line) \
            .mark(f"view-card view-card-{line.id}") as box:
        src = line.image_normal or line.image_small
        if src:
            lazy_img(src).classes("deck-card-img")
        else:
            with ui.element("div").classes("deck-card-img bg-gray-200 flex items-start p-2"):
                ui.label(line.card_name).classes("text-xs font-bold")
        if line.quantity > 1:
            ui.label(f"{line.quantity}x").classes("deck-qty")
        if path:
            box.on("click", lambda p=path: ui.navigate.to(p))


def not_found(message: str) -> None:
    with ui.column().classes("w-full items-center mt-12 gap-3"):
        ui.label(message).classes("text-gray-600")
        ui.button("Voltar para os decks", on_click=lambda: ui.navigate.to("/decks")).props("outline no-caps")


@ui.page(FRIENDS_PATH)
def friends_decks_page() -> None:
    with frame("Decks dos amigos"):
        FriendsDecksPage(auth.current_user())


@ui.page("/deck/{deck_id}")
def deck_page(deck_id: int) -> None:
    """Abre o deck para ver: o dono tem o botão de editar; um amigo vê se o deck estiver visível.
    Deck privado de outro: "não encontrado"."""
    user = auth.current_user()
    with frame("Deck"):
        with database.session() as s:
            try:
                deck = decks.get_deck(s, user.id, deck_id)
            except decks.DeckError:
                deck = None
            try:
                shared = decks.SharedDeck(deck, user.display_name, user.avatar_filename) if deck \
                    else decks.get_shared_deck(s, user.id, deck_id)
            except decks.DeckError as e:
                not_found(str(e))
                return
        ui.page_title(f"{shared.deck.name} | " + ("Decks" if deck else "Decks dos amigos"))
        DeckViewer(user, shared, owned=deck is not None)


@ui.page("/deck/{deck_id}/edit")
def deck_edit_page(deck_id: int) -> None:
    """Montagem do deck (só o dono). Quem não é dono volta para a página de ver."""
    user = auth.current_user()
    with frame("Deck"):
        with database.session() as s:
            try:
                deck = decks.get_deck(s, user.id, deck_id)
            except decks.DeckError:
                ui.navigate.to(deck_path(deck_id))
                return
        ui.page_title(f"{deck.name} | Editando")
        DeckBuilder(user, deck)
