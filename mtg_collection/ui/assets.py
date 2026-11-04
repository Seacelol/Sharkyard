"""Arquivos fixos (logo, ícones) e o necessário para instalar o app pelo navegador (PWA): manifesto e
service worker. Ficam abertos sem login: o navegador busca o manifesto sem o cookie da sessão."""
import json
from pathlib import Path

from fastapi import Response
from nicegui import app

from mtg_collection import config

STATIC_DIR = Path(__file__).parent / "static"
FAVICON = STATIC_DIR / "favicon.png"
PUBLIC_PREFIXES = ("/static/",)
PUBLIC_FILES = {"/manifest.webmanifest", "/sw.js"}

HEAD_HTML = """
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<script>if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});</script>
"""

# Sem cache offline de propósito: o app depende do servidor (banco e sessão). O service worker existe só porque
# alguns navegadores pedem um para oferecer "Instalar app".
SERVICE_WORKER = "self.addEventListener('fetch', () => {});\n"


def manifest() -> dict:
    return {
        "name": config.APP_NAME,
        "short_name": config.APP_NAME,
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#13263b",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/static/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }


async def _manifest() -> Response:
    return Response(json.dumps(manifest()), media_type="application/manifest+json")


async def _service_worker() -> Response:
    return Response(SERVICE_WORKER, media_type="text/javascript", headers={"Cache-Control": "no-cache"})


def is_public(path: str) -> bool:
    return path in PUBLIC_FILES or path.startswith(PUBLIC_PREFIXES)


def install() -> None:
    """Chamado pelo main() antes de subir o servidor."""
    if any(getattr(r, "path", None) == "/manifest.webmanifest" for r in app.routes):
        return
    app.add_static_files("/static", STATIC_DIR)
    app.add_api_route("/manifest.webmanifest", _manifest, methods=["GET"])
    app.add_api_route("/sw.js", _service_worker, methods=["GET"])
