"""Vitórias de um deck: registrar (data, versão, observação), ver o histórico, editar e apagar.
O dono mexe nas do próprio deck; o admin, nas de qualquer deck (e também muda a temporada)."""
from collections.abc import Callable
from datetime import date

from nicegui import ui

from mtg_collection import database
from mtg_collection.models import DeckVersion, User, Win
from mtg_collection.services import ranking
from mtg_collection.ui import formatting as fmt
from mtg_collection.ui.components.dialogs import close_dialog, maybe_await

NO_SEASON = "__none__"  # opção "Sem temporada" no select: None ali significa "nada escolhido"


def parse_date(text: str | None) -> date:
    """Data do campo (formato ISO do input type=date); vazio ou inválido vira erro para o usuário."""
    try:
        return date.fromisoformat(text or "")
    except ValueError:
        raise ranking.RankingError("Escolha a data da vitória.") from None


def open_wins_dialog(user: User, deck_id: int, deck_name: str, versions: list[DeckVersion], current_version: int | None,
                     public: bool, on_change: Callable[[], object] | None = None) -> None:
    """Histórico de vitórias do deck. Quem não pode editar só vê a lista. `public` diz se o deck está visível
    para os amigos (senão as vitórias não entram no ranking, e o diálogo avisa)."""
    with database.session() as s:
        editable = ranking.can_edit_wins(s, user.id, deck_id)
        seasons = ranking.list_seasons(s)
        active = ranking.active_season(s)
    version_options = {v.id: v.name for v in versions}

    with ui.context.client.content, ui.dialog() as dialog, ui.card().classes("w-full max-w-xl gap-3"):
        title = ui.label().classes("text-lg font-bold").mark("wins-title")
        if not public:
            ui.label("Este deck é privado: as vitórias só contam no ranking quando ele estiver visível para os "
                     "amigos.").classes("text-sm text-amber-800").mark("wins-private")
        if editable:
            with ui.element("div").classes("w-full grid gap-2 grid-cols-1 sm:grid-cols-2"):
                day = ui.input("Data", value=date.today().isoformat()).props("outlined dense type=date") \
                    .mark("win-date")
                version = ui.select(version_options, value=current_version, label="Versão") \
                    .props("outlined dense options-dense").mark("win-version")
            notes = ui.input("Observação (opcional)", placeholder="ex: mesa de 4, final do torneio") \
                .props("outlined dense").classes("w-full").mark("win-notes")
            hint = f"Entra na temporada \"{active.name}\"." if active else "Nenhuma temporada aberta: conta no geral."
            with ui.row().classes("w-full items-center justify-between gap-2"):
                ui.label(hint).classes("text-xs text-gray-500")
                # lambda porque add só é definida mais abaixo, depois de montar o diálogo
                ui.button("Registrar vitória", icon="emoji_events", on_click=lambda: add()) \
                    .props("unelevated no-caps").mark("win-add")
        history = ui.column().classes("w-full gap-0 max-h-[50vh] overflow-y-auto").mark("wins-list")
        with ui.row().classes("w-full justify-end"):
            ui.button("Fechar", on_click=lambda: close_dialog(dialog)).props("flat no-caps")

    async def changed() -> None:
        render()
        if on_change:
            await maybe_await(on_change())

    async def add() -> None:
        try:
            with database.session() as s:
                ranking.add_win(s, user.id, deck_id, parse_date(day.value), notes.value or "", version.value)
        except ranking.RankingError as e:
            ui.notify(str(e), type="negative")
            return
        notes.value = ""
        ui.notify("Vitória registrada.", type="positive")
        await changed()

    async def remove(win: Win) -> None:
        with database.session() as s:
            ranking.delete_win(s, user.id, win.id)
        ui.notify("Vitória apagada.", type="positive")
        await changed()

    def edit(win: Win) -> None:
        with ui.context.client.content, ui.dialog() as editor, ui.card().classes("w-full max-w-md gap-3"):
            ui.label("Editar vitória").classes("text-lg font-bold")
            edit_day = ui.input("Data", value=win.played_on.isoformat()).props("outlined dense type=date") \
                .classes("w-full").mark("win-edit-date")
            edit_version = ui.select(version_options, value=win.version_id, label="Versão") \
                .props("outlined dense options-dense").classes("w-full").mark("win-edit-version")
            edit_notes = ui.input("Observação", value=win.notes).props("outlined dense").classes("w-full") \
                .mark("win-edit-notes")
            season = None
            if user.is_admin:
                season = ui.select({NO_SEASON: "Sem temporada", **{x.id: x.name for x in seasons}},
                                   value=win.season_id or NO_SEASON, label="Temporada") \
                    .props("outlined dense options-dense").classes("w-full").mark("win-edit-season")

            async def save() -> None:
                extra = {}  # season_id só vai quando é o admin: para os outros, update_win recusa
                if season is not None:
                    extra["season_id"] = None if season.value == NO_SEASON else season.value
                try:
                    with database.session() as s:
                        ranking.update_win(s, user.id, win.id, played_on=parse_date(edit_day.value),
                                           notes=edit_notes.value or "", version_id=edit_version.value, **extra)
                except ranking.RankingError as e:
                    ui.notify(str(e), type="negative")
                    return
                ui.notify("Vitória salva.", type="positive")
                await changed()
                close_dialog(editor)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancelar", on_click=lambda: close_dialog(editor)).props("flat no-caps")
                ui.button("Salvar", on_click=save).props("unelevated no-caps").mark("win-edit-save")
        editor.on("hide", lambda: close_dialog(editor))
        editor.open()

    def render() -> None:
        with database.session() as s:
            wins = ranking.list_wins(s, user.id, deck_id)
        title.text = f"Vitórias de \"{deck_name}\": {len(wins)}"
        history.clear()
        with history:
            if not wins:
                ui.label("Nenhuma vitória registrada ainda.").classes("text-sm text-gray-500 py-2")
            for win in wins:
                with ui.row().classes("w-full items-center gap-2 no-wrap py-1.5 border-b border-gray-100") \
                        .mark(f"win win-{win.id}"):
                    ui.icon("emoji_events").classes("text-amber-600 text-lg shrink-0")
                    with ui.column().classes("gap-0 grow min-w-0"):
                        details = [fmt.date_br(win.played_on), win.version_name or "versão apagada"]
                        if win.season_name:
                            details.append(win.season_name)
                        ui.label(" · ".join(details)).classes("text-sm text-gray-800 truncate w-full")
                        if win.notes:
                            ui.label(win.notes).classes("text-xs text-gray-500 truncate w-full")
                    if editable:
                        ui.button(icon="edit", on_click=lambda w=win: edit(w)).props("flat round dense") \
                            .mark(f"win-edit-{win.id}")
                        ui.button(icon="delete", on_click=lambda w=win: remove(w)) \
                            .props("flat round dense color=negative").mark(f"win-delete-{win.id}")

    render()
    dialog.on("hide", lambda: close_dialog(dialog))
    dialog.open()
