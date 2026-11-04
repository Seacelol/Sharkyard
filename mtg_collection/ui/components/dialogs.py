"""Utilidades para diálogos: fechar com segurança, pedir um texto, confirmar uma ação."""
import inspect
from collections.abc import Callable

from nicegui import ui


async def maybe_await(result) -> None:
    """Callbacks dos diálogos podem ser síncronos ou assíncronos."""
    if inspect.isawaitable(result):
        await result


def close_dialog(dialog: ui.dialog) -> None:
    """Fecha e remove o diálogo da página. Não depende do evento de fechar do navegador para limpar."""
    if not dialog.is_deleted:
        dialog.close()
        dialog.delete()


def limit(max_length: int) -> str:
    """Props de um campo com limite de caracteres: não deixa digitar além e mostra o contador."""
    return f"maxlength={max_length} counter"


def ask_text(title: str, label: str, on_ok: Callable[[str], str | None], value: str = "",
             ok_label: str = "Salvar", max_length: int | None = None) -> None:
    """Pede um texto. `on_ok` devolve uma mensagem de erro (fica aberto) ou None (fecha)."""
    # criado na raiz da página (client.content), não onde o código está: se o elemento que abriu o diálogo for
    # recriado (ex.: ui.refreshable), o diálogo não é apagado junto. Os outros diálogos do app seguem o mesmo padrão.
    with ui.context.client.content, ui.dialog() as dialog, ui.card().classes("w-full max-w-sm gap-3"):
        ui.label(title).classes("text-lg font-bold")
        field = ui.input(label, value=value).props("outlined dense autofocus " + (limit(max_length) if max_length
                                                                                else "")) \
            .classes("w-full").mark("ask-text")
        error = ui.label().classes("text-sm text-red-600")
        error.visible = False

        def submit() -> None:
            message = on_ok(field.value or "")
            if message:
                error.text, error.visible = message, True
            else:
                close_dialog(dialog)

        field.on("keydown.enter", submit)
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=lambda: close_dialog(dialog)).props("flat no-caps")
            ui.button(ok_label, on_click=submit).props("unelevated no-caps").mark("ask-ok")
    dialog.on("hide", lambda: close_dialog(dialog))
    dialog.open()


def confirm(message: str, on_ok: Callable[[], object], ok_label: str = "Apagar", detail: str = "") -> None:
    """Confirmação de ação. Todas do mesmo tamanho; apagar sempre com "Apagar" em vermelho."""
    with ui.context.client.content, ui.dialog() as dialog, ui.card().classes("w-full max-w-sm gap-3"):
        ui.label(message).classes("text-lg font-bold break-words")
        if detail:
            ui.label(detail).classes("text-sm text-gray-600 break-words")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=lambda: close_dialog(dialog)).props("flat no-caps")

            async def ok() -> None:
                await maybe_await(on_ok())
                close_dialog(dialog)

            ui.button(ok_label, on_click=ok).props("unelevated no-caps color=negative").mark("confirm-ok")
    dialog.on("hide", lambda: close_dialog(dialog))
    dialog.open()
