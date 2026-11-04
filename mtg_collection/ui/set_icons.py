"""Serve os símbolos de coleção pelo próprio app (mesma origem), a partir do cache local."""
import re

from fastapi import Response
from nicegui import app, ui

from mtg_collection.services import scryfall

_VALID_CODE = re.compile(r"[a-z0-9]{2,8}")
# Símbolo neutro quando a coleção não tem ícone; sem ele a máscara CSS deixaria o espaço vazio
FALLBACK_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="11"/></svg>'


def set_icon_url(set_code: str) -> str:
    return f"/set-icon/{set_code.lower()}.svg"


def custom_set_icon(size: int = 28):
    """Símbolo das versões e cartas personalizadas: o tubarão do app, na cor do tema."""
    return ui.element("div").classes("set-icon custom-set shrink-0") \
        .style(f"--icon: url('/static/shark.svg'); width: {size}px; height: {size}px").mark("custom-set-icon")


async def set_icon(code: str) -> Response:
    """Rota do símbolo da coleção. O código é validado antes de virar nome de arquivo no cache. Sem ícone,
    devolve o símbolo neutro sem cache no navegador, para tentar de novo na próxima visita."""
    svg = None
    if _VALID_CODE.fullmatch(code):
        try:
            svg = await scryfall.client.get_set_icon(code)
        except scryfall.ScryfallError:
            pass
    headers = {"Cache-Control": "public, max-age=604800"} if svg else {}
    return Response(svg or FALLBACK_SVG, media_type="image/svg+xml", headers=headers)


def install() -> None:
    """Registra a rota /set-icon. Chamado pelo main() antes de subir o servidor."""
    if not any(getattr(r, "path", None) == "/set-icon/{code}.svg" for r in app.routes):
        app.add_api_route("/set-icon/{code}.svg", set_icon, methods=["GET"])
