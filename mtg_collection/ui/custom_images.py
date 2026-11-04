"""Imagens enviadas pelos usuários (versões personalizadas e capas de deck): validação, gravação em disco e
rotas que só entregam a quem pode ver."""
import re
import secrets
from collections.abc import Iterable

from fastapi import Request, Response
from fastapi.responses import FileResponse
from nicegui import app

from mtg_collection import config, database
from mtg_collection.services import accounts, collection, custom_cards, decks
from mtg_collection.ui import auth

MAX_IMAGE_BYTES = 8 * 1024 * 1024
# confere o conteúdo do arquivo, não o que o navegador diz que ele é
_SIGNATURES = {b"\x89PNG\r\n\x1a\n": "png", b"\xff\xd8\xff": "jpg"}
_VALID_NAME = re.compile(r"[a-f0-9]{32}\.(png|jpg|webp)")
_MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


class ImageError(Exception):
    pass


def image_extension(data: bytes) -> str:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    for signature, extension in _SIGNATURES.items():
        if data.startswith(signature):
            return extension
    raise ImageError("Envie uma imagem PNG, JPG ou WebP.")


def save_image(data: bytes) -> str:
    """Valida e grava a imagem. Devolve o nome do arquivo (aleatório, nunca o nome original)."""
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError("A imagem passa de 8 MB.")
    filename = f"{secrets.token_hex(16)}.{image_extension(data)}"
    config.CUSTOM_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    (config.CUSTOM_IMAGES_DIR / filename).write_bytes(data)
    return filename


def discard_if_unused(filename: str | None) -> None:
    """Apaga o arquivo se nada usa mais ele (imagem trocada, versão ou deck apagado)."""
    discard_unused([filename])


def discard_unused(filenames: Iterable[str | None]) -> None:
    """Igual ao discard_if_unused para vários arquivos (conta ou decks apagados): uma sessão só para todos."""
    names = [f for f in dict.fromkeys(filenames) if f and _VALID_NAME.fullmatch(f)]
    if not names:
        return
    with database.session() as s:
        unused = [f for f in names if not (
            collection.custom_print_image_in_use(s, f) or decks.cover_image_in_use(s, f)
            or custom_cards.image_in_use(s, f) or accounts.avatar_in_use(s, f))]
    for filename in unused:
        (config.CUSTOM_IMAGES_DIR / filename).unlink(missing_ok=True)


def custom_image_url(filename: str | None) -> str | None:
    return f"/custom-image/{filename}" if filename else None


def deck_cover_url(filename: str | None) -> str | None:
    return f"/deck-cover/{filename}" if filename else None


def avatar_url(filename: str | None) -> str | None:
    return f"/avatar/{filename}" if filename else None


async def custom_image(filename: str, request: Request) -> Response:  # async: a sessão só é lida no loop principal
    """Imagem de versão ou carta personalizada: o dono vê; amigos veem se ela estiver num deck visível para eles.
    O nome é conferido contra _VALID_NAME antes de tocar no disco (sem "../")."""
    user = auth.request_user(request)
    if user is None or not _VALID_NAME.fullmatch(filename):
        return Response(status_code=404)
    with database.session() as s:
        owner = collection.custom_print_owner(s, filename) or custom_cards.image_owner(s, filename)
        # também vale para quem vê um deck de amigo em que a carta aparece
        allowed = owner == user.id or decks.can_view_card_image(s, user.id, custom_image_url(filename))
    # imagem de outro usuário: mesma resposta de inexistente
    return _file_response(filename) if allowed else Response(status_code=404)


async def deck_cover(filename: str, request: Request) -> Response:
    """Capa de deck: o dono sempre vê; amigos veem se o deck estiver visível para eles."""
    user = auth.request_user(request)
    if user is None or not _VALID_NAME.fullmatch(filename):
        return Response(status_code=404)
    with database.session() as s:
        allowed = decks.can_view_cover(s, user.id, filename)
    return _file_response(filename) if allowed else Response(status_code=404)


async def avatar(filename: str, request: Request) -> Response:
    """Ícone de usuário: qualquer pessoa logada vê (aparece no ranking e nos decks dos amigos)."""
    if auth.request_user(request) is None or not _VALID_NAME.fullmatch(filename):
        return Response(status_code=404)
    with database.session() as s:
        used = accounts.avatar_in_use(s, filename)
    return _file_response(filename) if used else Response(status_code=404)


def _file_response(filename: str) -> Response:
    path = config.CUSTOM_IMAGES_DIR / filename
    if not path.exists():
        return Response(status_code=404)
    return FileResponse(path, media_type=_MEDIA_TYPES[filename.rsplit(".", 1)[1]],
                        headers={"Cache-Control": "private, max-age=86400"})


_ROUTES = {"/custom-image/{filename}": custom_image, "/deck-cover/{filename}": deck_cover,
           "/avatar/{filename}": avatar}


def install() -> None:
    """Registra as rotas de imagem. Chamado pelo main() antes de subir o servidor."""
    existing = {getattr(r, "path", None) for r in app.routes}
    for path, handler in _ROUTES.items():
        if path not in existing:
            app.add_api_route(path, handler, methods=["GET"])
