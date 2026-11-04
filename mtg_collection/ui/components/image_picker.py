"""Botão "Escolher imagem": abre o seletor de arquivos, valida e entrega os bytes (gravar é com quem chama)."""
import base64
from collections.abc import Callable

from nicegui import events, ui

from mtg_collection.ui.custom_images import MAX_IMAGE_BYTES, ImageError, image_extension


def data_url(data: bytes) -> str:
    extension = image_extension(data)
    mime = "jpeg" if extension == "jpg" else extension
    return f"data:image/{mime};base64,{base64.b64encode(data).decode()}"


class ImagePicker:
    def __init__(self, on_pick: Callable[[bytes, str], None], marker: str, label: str = "Escolher imagem"):
        self._on_pick = on_pick

        async def handle(e: events.UploadEventArguments) -> None:
            data = await e.file.read()
            try:
                url = data_url(data)
            except ImageError as err:
                ui.notify(str(err), type="negative")
                return
            self.chosen.text = f"{e.file.name}: pronta para salvar"
            self.upload.reset()
            self._on_pick(data, url)

        # o seletor de arquivo do Quasar fica escondido; o botão abre ele direto no navegador
        # (abrir o seletor exige o clique do usuário, então não pode passar pelo servidor)
        self.upload = ui.upload(on_upload=handle, auto_upload=True, max_file_size=MAX_IMAGE_BYTES,
                                on_rejected=lambda: ui.notify("A imagem passa de 8 MB.", type="negative")) \
            .props('accept="image/png,image/jpeg,image/webp"').classes("hidden").mark(f"{marker}-upload")
        ui.button(label, icon="image").props("outline no-caps") \
            .on("click", js_handler=f"() => runMethod({self.upload.id}, 'pickFiles', [])").mark(f"{marker}-pick")
        self.chosen = ui.label().classes("text-xs text-gray-600").mark(f"{marker}-chosen")
