"""Diálogo para criar, editar ou apagar uma versão personalizada (com imagem opcional)."""
import base64
from collections.abc import Callable

from nicegui import events, ui

from mtg_collection import config, database
from mtg_collection.models import Card, CustomPrint
from mtg_collection.services import collection
from mtg_collection.ui.components.dialogs import close_dialog, confirm, limit
from mtg_collection.ui.custom_images import (
    MAX_IMAGE_BYTES,
    ImageError,
    custom_image_url,
    discard_if_unused,
    image_extension,
    save_image,
)


def delete_warning(usage: collection.CustomPrintUsage) -> str:
    """O que acontece ao apagar a versão: as cópias da coleção vão junto; os decks não perdem a carta."""
    parts = []
    if usage.copies:
        parts.append(f"{usage.copies} cópia(s) na coleção serão apagadas")
    if usage.deck_lines:
        parts.append(f"{usage.deck_lines} linha(s) de deck voltam para a edição oficial")
    return "; ".join(parts) + "." if parts else ""


def open_custom_print_dialog(user_id: int, base: Card, existing: CustomPrint | None,
                             on_saved: Callable[[CustomPrint], None],
                             on_deleted: Callable[[int], None] | None = None) -> None:
    """Cria (existing=None) ou edita uma versão personalizada de `base`. A imagem escolhida só vai para o disco
    ao salvar; se salvar falhar, o arquivo novo é descartado."""
    pending: dict[str, bytes] = {}  # imagem enviada, só gravada em disco ao salvar

    # criado na raiz da página: se ficasse dentro da área que o abriu, seria apagado quando ela é redesenhada
    with ui.context.client.content, ui.dialog() as dialog, ui.card().classes("w-full max-w-lg gap-3"):
        ui.label("Editar versão personalizada" if existing else "Nova versão personalizada") \
            .classes("text-lg font-bold")
        ui.label(f"{base.name}: só você vê esta versão. O texto da carta continua o original.") \
            .classes("text-sm text-gray-500")
        name = ui.input("Nome da versão", value=existing.name if existing else "",
                        placeholder="ex: Alter pintado, Proxy arte alternativa") \
            .props(f"outlined dense {limit(config.CUSTOM_PRINT_NAME_MAX)}").classes("w-full").mark("custom-name")
        with ui.row().classes("w-full gap-3 no-wrap"):
            code = ui.input("Código (opcional)", value=existing.code if existing else "", placeholder="ex: ALT") \
                .props("outlined dense maxlength=8").classes("w-40").mark("custom-code")
            artist = ui.input("Autor / artista (opcional)", value=existing.artist if existing else "") \
                .props("outlined dense").classes("grow").mark("custom-artist")
        notes = ui.textarea("Observações (opcional)", value=existing.notes if existing else "") \
            .props("outlined dense autogrow").classes("w-full").mark("custom-notes")

        with ui.row().classes("w-full items-start gap-4 no-wrap"):
            preview = ui.image(custom_image_url(existing.image_filename) if existing and existing.image_filename
                               else base.image_normal or "").props("no-spinner").classes("w-28 shrink-0 rounded-lg")
            with ui.column().classes("grow gap-2"):
                ui.label("Imagem (opcional): PNG, JPG ou WebP até 8 MB. Sem imagem, usa a da carta.") \
                    .classes("text-xs text-gray-500")

                async def handle_upload(e: events.UploadEventArguments) -> None:
                    data = await e.file.read()
                    try:
                        extension = image_extension(data)
                    except ImageError as err:
                        ui.notify(str(err), type="negative")
                        return
                    pending["data"] = data
                    chosen.text = f"{e.file.name}: pronta para salvar"
                    mime = "jpeg" if extension == "jpg" else extension
                    preview.set_source(f"data:image/{mime};base64,{base64.b64encode(data).decode()}")
                    if remove_image is not None:
                        remove_image.value = False
                    upload.reset()

                # o seletor de arquivo do Quasar fica escondido; o botão abre ele direto no navegador
                # (abrir o seletor exige o clique do usuário, então não pode passar pelo servidor)
                upload = ui.upload(on_upload=handle_upload, auto_upload=True, max_file_size=MAX_IMAGE_BYTES,
                                   on_rejected=lambda: ui.notify("A imagem passa de 8 MB.", type="negative")) \
                    .props('accept="image/png,image/jpeg,image/webp"').classes("hidden").mark("custom-upload")
                ui.button("Escolher imagem", icon="image").props("outline no-caps") \
                    .on("click", js_handler=f"() => runMethod({upload.id}, 'pickFiles', [])").mark("custom-pick")
                chosen = ui.label().classes("text-xs text-gray-600").mark("custom-chosen")
                remove_image = None
                if existing and existing.image_filename:
                    remove_image = ui.checkbox("Remover imagem (voltar para a da carta)").mark("custom-remove-image")
                    remove_image.on_value_change(
                        lambda e: preview.set_source(base.image_normal or "") if e.value else
                        preview.set_source(custom_image_url(existing.image_filename)))
        error = ui.label().classes("text-sm text-red-600").mark("custom-error")
        error.visible = False

        def save() -> None:
            new_file = None
            try:
                if not (name.value or "").strip():
                    raise collection.CollectionError("Dê um nome para a versão.")
                if "data" in pending:
                    new_file = save_image(pending["data"])
                with database.session() as s:
                    if existing:
                        saved = collection.update_custom_print(
                            s, user_id, existing.id, name.value, code.value or "", artist.value or "",
                            notes.value or "", image_filename=new_file,
                            remove_image=bool(remove_image and remove_image.value),
                            image_url=custom_image_url(new_file), base=base)
                    else:
                        saved = collection.create_custom_print(
                            s, user_id, base, name.value, code.value or "", artist.value or "", notes.value or "",
                            image_filename=new_file)
            except (collection.CollectionError, ImageError) as e:
                discard_if_unused(new_file)
                error.text = str(e)
                error.visible = True
                return
            if existing:
                discard_if_unused(existing.image_filename)  # se a imagem foi trocada ou removida
            ui.notify("Versão salva.", type="positive")
            on_saved(saved)  # antes de fechar: fechar apaga o diálogo e o contexto dele
            close_dialog(dialog)

        def ask_delete() -> None:
            with database.session() as s:
                usage = collection.custom_print_usage(s, user_id, existing.id)

            def delete() -> None:
                with database.session() as s:
                    collection.delete_custom_print(s, user_id, existing.id, base)
                discard_if_unused(existing.image_filename)
                ui.notify("Versão apagada.", type="positive")
                if on_deleted:
                    on_deleted(existing.id)
                close_dialog(dialog)

            confirm(f"Apagar a versão \"{existing.name}\"?", delete, detail=delete_warning(usage))

        with ui.row().classes("w-full items-center justify-between mt-2"):
            if existing:
                ui.button("Apagar versão", icon="delete", on_click=ask_delete) \
                    .props("flat no-caps color=negative").mark("custom-delete")
            else:
                ui.element("div")
            with ui.row().classes("gap-2"):
                ui.button("Cancelar", on_click=lambda: close_dialog(dialog)).props("flat no-caps")
                ui.button("Salvar", on_click=save).props("unelevated no-caps").mark("custom-save")

    dialog.on("hide", lambda: close_dialog(dialog))  # fechar clicando fora ou com Esc
    dialog.open()
