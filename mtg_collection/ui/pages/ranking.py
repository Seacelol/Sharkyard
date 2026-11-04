"""Ranking (/ranking): decks e jogadores por vitórias, com filtro de temporada, formato e período.
O admin abre e encerra temporadas, tira decks ou jogadores do ranking, corrige vitórias e zera o ranking."""
from nicegui import ui

from mtg_collection import config, database
from mtg_collection.models import RankedDeck, RankedPlayer, User
from mtg_collection.services import decks, ranking
from mtg_collection.services.ranking import PERIODS, Filters, period_start
from mtg_collection.ui import auth
from mtg_collection.ui import formatting as fmt
from mtg_collection.ui.components.avatar import user_avatar
from mtg_collection.ui.components.deck_dialog import FORMATS
from mtg_collection.ui.components.dialogs import ask_text, confirm
from mtg_collection.ui.components.wins_dialog import open_wins_dialog
from mtg_collection.ui.layout import frame
from mtg_collection.ui.routes import deck_path

ALL_SEASONS = "geral"  # opção "Geral" do select (None ali significaria "nada escolhido")
MEDALS = {1: "text-amber-500", 2: "text-slate-400", 3: "text-orange-700"}  # ouro, prata, bronze


class RankingPage:
    """Rankings de decks e jogadores com os mesmos filtros. Admin vê também os ocultos (se pedir) e a área de
    temporadas. Cada mudança de filtro relê os rankings do banco."""
    def __init__(self, user: User):
        self.user = user
        self.admin = user.is_admin
        with ui.column().classes("w-full max-w-4xl mx-auto gap-4"):
            with ui.column().classes("gap-0"):
                ui.label("Ranking").classes("text-2xl font-bold")
                ui.label("Vitórias dos decks visíveis para os amigos.").classes("text-sm text-gray-600")
            self.filters_row = ui.element("div").classes("w-full grid gap-2 grid-cols-1 sm:grid-cols-3")
            if self.admin:
                self.show_hidden = ui.checkbox("Mostrar decks e jogadores tirados do ranking") \
                    .props("dense").mark("show-hidden")
                self.show_hidden.on_value_change(self.render)
            with ui.tabs().props("dense no-caps align=left").classes("text-gray-700") as self.tabs:
                decks_tab = ui.tab("Decks", icon="style").mark("tab-decks")
                players_tab = ui.tab("Jogadores", icon="person").mark("tab-players")
            with ui.tab_panels(self.tabs, value=decks_tab).props("animated=false").classes("w-full bg-transparent"):
                with ui.tab_panel(decks_tab).classes("p-0"):
                    self.decks_list = ui.card().classes("w-full gap-0 p-0").mark("ranking-decks")
                with ui.tab_panel(players_tab).classes("p-0"):
                    self.players_list = ui.card().classes("w-full gap-0 p-0").mark("ranking-players")
            if self.admin:
                self.admin_area = ui.card().classes("w-full gap-3").mark("ranking-admin")
        self.build_filters()
        self.render()

    # ---------- filtros ----------
    def build_filters(self, keep: dict | None = None) -> None:
        """(Re)monta os filtros com as temporadas e formatos atuais. `keep` preserva a escolha anterior quando a
        opção ainda existe; sem ela, a temporada aberta vem selecionada."""
        with database.session() as s:
            seasons = ranking.list_seasons(s)
            active = ranking.active_season(s)
            formats = ranking.ranking_formats(s)
        keep = keep or {}
        season_options = {ALL_SEASONS: "Geral (todas as temporadas)",
                          **{x.id: x.name + (" (atual)" if x.active else "") for x in seasons}}
        season_value = keep.get("season", active.id if active else ALL_SEASONS)
        format_options = {"": "Todos os formatos", **{f: FORMATS.get(f, f) for f in formats}}
        self.filters_row.clear()
        with self.filters_row:
            self.season = ui.select(season_options, value=season_value if season_value in season_options
                                    else ALL_SEASONS, label="Temporada") \
                .props("outlined dense options-dense").mark("filter-season")
            self.format = ui.select(format_options, value=keep.get("format", "") if keep.get("format", "")
                                    in format_options else "", label="Formato") \
                .props("outlined dense options-dense").mark("filter-format")
            self.period = ui.select(PERIODS, value=keep.get("period", ""), label="Período") \
                .props("outlined dense options-dense").mark("filter-period")
        for widget in (self.season, self.format, self.period):
            widget.on_value_change(self.render)

    def filters(self) -> Filters:
        return Filters(season_id=None if self.season.value == ALL_SEASONS else self.season.value,
                       format=self.format.value or "", since=period_start(self.period.value or ""),
                       include_hidden=self.admin and self.show_hidden.value)

    # ---------- listas ----------
    def render(self) -> None:
        filters = self.filters()
        with database.session() as s:
            ranked_decks = ranking.deck_ranking(s, filters)
            players = ranking.player_ranking(s, filters)
        self._render_decks(ranked_decks)
        self._render_players(players)
        if self.admin:
            self._render_admin()

    @staticmethod
    def _position(position: int) -> None:
        with ui.element("div").classes("w-10 shrink-0 flex items-center justify-center"):
            if position in MEDALS:
                ui.icon("emoji_events").classes(f"text-2xl {MEDALS[position]}").tooltip(f"{position}º")
            else:
                ui.label(f"{position}º").classes("font-semibold text-gray-600")

    @staticmethod
    def _empty(container: ui.element, text: str) -> None:
        with container:
            ui.label(text).classes("text-gray-500 py-8 self-center text-center px-4")

    def _render_decks(self, items: list[RankedDeck]) -> None:
        self.decks_list.clear()
        if not items:
            self._empty(self.decks_list, "Nenhuma vitória com esses filtros. Decks visíveis para os amigos entram "
                                         "aqui quando ganham.")
            return
        with self.decks_list:
            for item in items:
                faded = " opacity-50" if item.hidden else ""
                with ui.row().classes(f"w-full items-center gap-2 no-wrap px-2 sm:px-4 py-2 border-b "
                                      f"border-gray-100 last:border-b-0{faded}").mark(f"ranked-deck-{item.deck_id}"):
                    self._position(item.position)
                    with ui.column().classes("gap-0 grow min-w-0"):
                        ui.link(item.name, deck_path(item.deck_id)) \
                            .classes("font-medium truncate w-full text-gray-900 no-underline")
                        details = [f"de {item.owner_name}", FORMATS.get(item.format, item.format) or "Sem formato",
                                   f"última em {fmt.date_br(item.last_win)}"]
                        ui.label(" · ".join(details)).classes("text-xs text-gray-500 truncate w-full")
                    if item.hidden:
                        ui.badge("Fora do ranking").props("color=grey-6")
                    with ui.column().classes("gap-0 items-end shrink-0"):
                        ui.label(str(item.wins)).classes("text-lg font-bold leading-none")
                        ui.label("vitória" if item.wins == 1 else "vitórias").classes("text-xs text-gray-500")
                    if self.admin:
                        self._deck_admin_menu(item)

    def _render_players(self, items: list[RankedPlayer]) -> None:
        self.players_list.clear()
        if not items:
            self._empty(self.players_list, "Nenhum jogador com vitórias com esses filtros.")
            return
        with self.players_list:
            for item in items:
                faded = " opacity-50" if item.hidden else ""
                with ui.row().classes(f"w-full items-center gap-2 no-wrap px-2 sm:px-4 py-2 border-b "
                                      f"border-gray-100 last:border-b-0{faded}").mark(f"ranked-player-{item.user_id}"):
                    self._position(item.position)
                    user_avatar(item.name, item.avatar_filename, 40)
                    with ui.column().classes("gap-0 grow min-w-0"):
                        ui.label(item.name).classes("font-medium truncate w-full")
                        if item.bio:
                            ui.label(item.bio).classes("text-xs italic text-gray-600 truncate w-full") \
                                .mark(f"player-bio-{item.user_id}")
                        decks_text = fmt.plural(item.decks, "deck", "decks")
                        ui.label(f"{decks_text} · melhor: {item.best_deck}").classes("text-xs text-gray-500 truncate "
                                                                                     "w-full")
                    if item.hidden:
                        ui.badge("Fora do ranking").props("color=grey-6")
                    with ui.column().classes("gap-0 items-end shrink-0"):
                        ui.label(str(item.wins)).classes("text-lg font-bold leading-none")
                        ui.label("vitória" if item.wins == 1 else "vitórias").classes("text-xs text-gray-500")
                    if self.admin:
                        hide = not item.hidden
                        ui.button(icon="visibility_off" if hide else "visibility",
                                  on_click=lambda i=item, h=hide: self._hide_player(i, h)) \
                            .props("flat round dense").tooltip("Tirar do ranking" if hide else "Voltar ao ranking") \
                            .mark(f"hide-player-{item.user_id}")

    # ---------- admin ----------
    def _deck_admin_menu(self, item: RankedDeck) -> None:
        with ui.button(icon="more_vert").props("flat round dense").mark(f"deck-admin-{item.deck_id}"):
            with ui.menu():
                ui.menu_item("Ver e corrigir vitórias", on_click=lambda i=item: self._wins(i)) \
                    .mark(f"deck-admin-wins-{item.deck_id}")
                label = "Voltar ao ranking" if item.hidden else "Tirar do ranking"
                ui.menu_item(label, on_click=lambda i=item: self._hide_deck(i, not i.hidden)) \
                    .mark(f"hide-deck-{item.deck_id}")

    def _wins(self, item: RankedDeck) -> None:
        # lido com o id do dono: o serviço de decks só entrega decks do próprio usuário, e quem chega aqui é o admin
        with database.session() as s:
            versions = decks.list_versions(s, item.owner_id, item.deck_id)
            current = decks.get_deck(s, item.owner_id, item.deck_id).version_id
        open_wins_dialog(self.user, item.deck_id, item.name, versions, current, public=True, on_change=self.render)

    def _hide_deck(self, item: RankedDeck, hidden: bool) -> None:
        with database.session() as s:
            ranking.set_deck_hidden(s, self.user.id, item.deck_id, hidden)
        ui.notify(f"\"{item.name}\" {'saiu do' if hidden else 'voltou ao'} ranking.", type="positive")
        self.render()

    def _hide_player(self, item: RankedPlayer, hidden: bool) -> None:
        with database.session() as s:
            ranking.set_player_hidden(s, self.user.id, item.user_id, hidden)
        ui.notify(f"{item.name} {'saiu do' if hidden else 'voltou ao'} ranking.", type="positive")
        self.render()

    def _render_admin(self) -> None:
        with database.session() as s:
            active = ranking.active_season(s)
            seasons = ranking.list_seasons(s)
        self.admin_area.clear()
        with self.admin_area:
            ui.label("Administração").classes("text-xs font-bold uppercase tracking-wider text-gray-500")
            ui.label(f"Temporada atual: {active.name} (desde {fmt.date_br(active.started_at)})" if active
                     else "Nenhuma temporada aberta: as vitórias novas contam só no geral.") \
                .classes("text-sm text-gray-700").mark("current-season")
            with ui.row().classes("gap-2"):
                ui.button("Abrir nova temporada", icon="flag", on_click=self._start_season) \
                    .props("outline no-caps").mark("start-season")
                if active:
                    ui.button("Encerrar temporada", icon="stop_circle", on_click=self._end_season) \
                        .props("flat no-caps").mark("end-season")
            if seasons:
                with ui.column().classes("w-full gap-0"):
                    for season in seasons:
                        period = f"{fmt.date_br(season.started_at)} a " + \
                            (fmt.date_br(season.ended_at) if season.ended_at else "hoje")
                        with ui.row().classes("w-full items-center gap-2 no-wrap py-1 border-b border-gray-100"):
                            ui.label(season.name).classes("text-sm grow truncate")
                            ui.label(period).classes("text-xs text-gray-500 shrink-0")
                            ui.button(icon="delete", on_click=lambda x=season: self._delete_season(x)) \
                                .props("flat round dense color=negative").tooltip("Apagar temporada") \
                                .mark(f"delete-season-{season.id}")
            scope = "da temporada escolhida no filtro" if self.season.value != ALL_SEASONS else "de todas as temporadas"
            ui.button("Zerar ranking", icon="restart_alt", on_click=self._reset) \
                .props("flat no-caps color=negative").classes("self-start").tooltip(f"Apaga as vitórias {scope}") \
                .mark("reset-ranking")

    def _keep(self) -> dict:
        return {"season": self.season.value, "format": self.format.value, "period": self.period.value}

    def _start_season(self) -> None:
        def start(name: str) -> str | None:
            try:
                with database.session() as s:
                    season = ranking.start_season(s, self.user.id, name)
            except ranking.RankingError as e:
                return str(e)
            ui.notify(f"Temporada \"{season.name}\" aberta. As próximas vitórias entram nela.", type="positive")
            self.build_filters({**self._keep(), "season": season.id})
            self.render()
            return None

        ask_text("Nova temporada", "Nome (a temporada atual é encerrada)", start, ok_label="Abrir",
                 max_length=config.SEASON_NAME_MAX)

    def _end_season(self) -> None:
        def end() -> None:
            with database.session() as s:
                ranking.end_season(s, self.user.id)
            ui.notify("Temporada encerrada.", type="positive")
            self.build_filters(self._keep())
            self.render()

        confirm("Encerrar a temporada atual?", end, ok_label="Encerrar",
                detail="As vitórias dela ficam guardadas. Até abrir outra, as novas contam só no geral.")

    def _delete_season(self, season) -> None:
        def delete() -> None:
            with database.session() as s:
                ranking.delete_season(s, self.user.id, season.id)
            ui.notify(f"Temporada \"{season.name}\" apagada.", type="positive")
            keep = self._keep()
            if keep["season"] == season.id:
                keep["season"] = ALL_SEASONS
            self.build_filters(keep)
            self.render()

        confirm(f"Apagar a temporada \"{season.name}\"?", delete,
                detail="As vitórias dela não são apagadas: continuam valendo no ranking geral.")

    def _reset(self) -> None:
        season_id = None if self.season.value == ALL_SEASONS else self.season.value
        scope = f"da temporada \"{self.season.options[season_id]}\"" if season_id else "de todas as temporadas"

        def reset() -> None:
            with database.session() as s:
                removed = ranking.reset(s, self.user.id, season_id)
            ui.notify(f"{fmt.plural(removed, 'vitória apagada', 'vitórias apagadas')}.", type="positive")
            self.build_filters(self._keep())
            self.render()

        confirm(f"Zerar o ranking {scope}?", reset, ok_label="Zerar",
                detail="Apaga as vitórias de todos os decks. Não dá para desfazer.")


@ui.page("/ranking")
def ranking_page() -> None:
    with frame("Ranking"):
        RankingPage(auth.current_user())
