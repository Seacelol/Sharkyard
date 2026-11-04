"""Ponto de entrada. Desktop: python main.py | Web: python main.py --web"""
import argparse
import logging
import os
import sys

from mtg_collection import config

# sessões do NiceGUI na pasta de dados (o padrão é ".nicegui" na pasta onde o comando foi rodado).
# Precisa vir antes de importar o nicegui, que lê a variável ao carregar.
os.environ.setdefault("NICEGUI_STORAGE_PATH", str(config.DATA_DIR / "sessions"))

from nicegui import app, background_tasks, ui  # noqa: E402

import mtg_collection.ui.pages  # noqa: E402, F401  registra as rotas
from mtg_collection import database  # noqa: E402
from mtg_collection.services import catalog, scryfall
from mtg_collection.ui import assets, auth, custom_images, set_icons


def main() -> None:
    parser = argparse.ArgumentParser(description=config.APP_NAME)
    parser.add_argument("--web", action="store_true", help="roda no navegador em vez de janela desktop")
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--host", default=None,
                        help="endereço onde escutar. Com o túnel da Cloudflare use 127.0.0.1 (só o próprio PC); "
                             "sem informar, a rede local também acessa no modo --web")
    args, _ = parser.parse_known_args()

    database.configure()
    database.upgrade()  # cria o banco na primeira vez e aplica migrações novas
    auth.install()  # páginas exigem login
    set_icons.install()
    assets.install()
    custom_images.install()
    app.on_shutdown(scryfall.client.close)
    if os.environ.get("MTG_CATALOG", "1") != "0":  # MTG_CATALOG=0 desliga a cópia local (os testes desligam)
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
        local = catalog.Catalog(config.CATALOG_PATH)
        scryfall.client.catalog = local
        app.on_startup(lambda: background_tasks.create(catalog.keep_updated(scryfall.client, local),
                                                       name="catalogo-scryfall"))
    if not args.web:
        if sys.platform == "win32":
            # identidade própria na barra de tarefas: sem isso o Windows agrupa a janela com o Python e usa o ícone dele
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(config.APP_NAME)
        # a janela desktop guarda o cookie de sessão entre execuções (não precisa entrar toda vez).
        # icon: ícone da janela e da barra de tarefas (no Windows, a partir do pywebview 6)
        app.native.start_args.update(private_mode=False, storage_path=str(config.DATA_DIR / "webview"),
                                     icon=str(assets.STATIC_DIR / "icon.ico"))
        app.native.settings["ALLOW_DOWNLOADS"] = True  # "Baixar arquivo" (exportar deck) na janela desktop
    ui.run(
        title=config.APP_NAME,
        favicon=assets.FAVICON,
        native=not args.web,
        window_size=None if args.web else config.WINDOW_SIZE,
        port=args.port,
        host=args.host,
        reload=False,
        storage_secret=auth.storage_secret(),
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
