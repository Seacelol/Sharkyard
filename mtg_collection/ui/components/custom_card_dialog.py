"""Diálogo para criar ou editar uma carta personalizada (que não existe no Magic)."""
from collections.abc import Callable

from nicegui import ui

from mtg_collection import config, database
from mtg_collection.models import CustomCard
from mtg_collection.services import custom_cards
from mtg_collection.ui.components.dialogs import close_dialog, limit, maybe_await
from mtg_collection.ui.components.image_picker import ImagePicker
from mtg_collection.ui.custom_images import ImageError, custom_image_url, discard_if_unused, save_image
from mtg_collection.ui.printings import custom_card_as_card


def open_custom_card_dialog(user_id: int, deck_id: int | None, existing: CustomCard | None,
                            on_saved: Callable[[CustomCard, bool], object]) -> None:
    """`on_saved(carta, guardar_na_coleção)`. Na criação, a carta nasce só no deck, a não ser que o usuário
    marque para guardar na coleção (aí ela pode ser usada em qualquer deck)."""
    pending: dict[str, bytes] = {}
    value = (lambda attr: getattr(existing, attr)) if existing else (lambda attr: "")

    with ui.context.client.content, ui.dialog() as dialog, ui.card().classes("w-full max-w-lg gap-3"):
        ui.label("Editar carta personalizada" if existing else "Nova carta personalizada").classes("text-lg font-bold")
        ui.label("Carta que não existe no Magic. Ela aparece marcada como personalizada e não vale em formatos "
                 "oficiais.").classes("text-sm text-gray-500")
        name = ui.input("Nome", value=value("name")) \
            .props(f"outlined dense autofocus {limit(config.CUSTOM_CARD_NAME_MAX)}").classes("w-full").mark("cc-name")
        with ui.row().classes("w-full gap-3 no-wrap"):
            cost = ui.input("Custo de mana", value=value("mana_cost"), placeholder="{2}{R}{R}") \
                .props("outlined dense").classes("w-40").mark("cc-cost")
            type_line = ui.input("Tipo", value=value("type_line"), placeholder="Criatura Lendária — Dragão") \
                .props("outlined dense").classes("grow").mark("cc-type")
        text = ui.textarea("Texto", value=value("oracle_text")).props("outlined dense autogrow") \
            .classes("w-full").mark("cc-text")
        with ui.row().classes("w-full gap-3 no-wrap"):
            power = ui.input("Poder", value=value("power")).props("outlined dense").classes("w-24").mark("cc-power")
            toughness = ui.input("Resistência", value=value("toughness")).props("outlined dense").classes("w-28") \
                .mark("cc-toughness")
            loyalty = ui.input("Lealdade", value=value("loyalty")).props("outlined dense").classes("w-24") \
                .mark("cc-loyalty")
        with ui.row().classes("w-full items-start gap-4 no-wrap"):
            current = custom_image_url(existing.image_filename) if existing else None
            preview = ui.image(current or "").props("no-spinner").classes("w-28 shrink-0 rounded-lg")
            preview.visible = bool(current)
            with ui.column().classes("grow gap-2"):
                ui.label("Imagem (opcional): PNG, JPG ou WebP até 8 MB.").classes("text-xs text-gray-500")

                def picked(data: bytes, url: str) -> None:
                    pending["data"] = data
                    preview.set_source(url)
                    preview.visible = True

                ImagePicker(picked, marker="cc")
                remove_image = ui.checkbox("Remover imagem").mark("cc-remove-image") if current else None
        keep = None
        if existing is None and deck_id is not None:
            keep = ui.checkbox("Guardar também na coleção (para usar em outros decks)").mark("cc-keep")
        error = ui.label().classes("text-sm text-red-600").mark("cc-error")
        error.visible = False

        async def save() -> None:
            new_file = None
            fields = dict(name=name.value or "", mana_cost=cost.value or "", type_line=type_line.value or "",
                          oracle_text=text.value or "", power=power.value or "", toughness=toughness.value or "",
                          loyalty=loyalty.value or "")
            try:
                if not fields["name"].strip():
                    raise custom_cards.CustomCardError("Dê um nome para a carta.")
                if "data" in pending:
                    new_file = save_image(pending["data"])
                with database.session() as s:
                    if existing:
                        saved, old = custom_cards.update(
                            s, user_id, existing.id, **fields, image_filename=new_file,
                            remove_image=bool(remove_image and remove_image.value))
                        custom_cards.sync_snapshots(s, user_id, custom_card_as_card(saved))
                    else:
                        saved, old = custom_cards.create(s, user_id, **fields, image_filename=new_file,
                                                         deck_id=deck_id), None
            except (custom_cards.CustomCardError, ImageError) as e:
                discard_if_unused(new_file)
                error.text, error.visible = str(e), True
                return
            discard_if_unused(old)
            await maybe_await(on_saved(saved, bool(keep and keep.value)))  # antes de fechar (apaga o contexto)
            close_dialog(dialog)

        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button("Cancelar", on_click=lambda: close_dialog(dialog)).props("flat no-caps")
            ui.button("Salvar", on_click=save).props("unelevated no-caps").mark("cc-save")

    dialog.on("hide", lambda: close_dialog(dialog))
    dialog.open()
