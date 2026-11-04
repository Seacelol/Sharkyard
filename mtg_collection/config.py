"""Configurações centrais do app."""
import os
from pathlib import Path

APP_NAME = "Sharkyard"
VERSION = "0.1.0"

PORT = 8080
WINDOW_SIZE = (1280, 820)

SCRYFALL_BASE_URL = "https://api.scryfall.com"
SCRYFALL_USER_AGENT = f"Sharkyard/{VERSION}"
SCRYFALL_MIN_INTERVAL = 0.1  # segundos entre requisições, conforme pedido pelo Scryfall
HTTP_TIMEOUT = 15

# Tudo que é do usuário fica aqui: banco, chave de sessão e cache. MTG_DATA_DIR permite trocar (ex: testes).
DATA_DIR = Path(os.environ.get("MTG_DATA_DIR", Path.home() / ".mtg-collection"))
CACHE_DIR = DATA_DIR / "cache"
CATALOG_PATH = CACHE_DIR / "catalogo.db"  # cópia local das cartas do Scryfall (services/catalog.py)
DATABASE_PATH = DATA_DIR / "data.db"
SECRET_PATH = DATA_DIR / "secret.key"
CUSTOM_IMAGES_DIR = DATA_DIR / "custom-images"  # imagens das versões personalizadas

USERNAME_MIN, USERNAME_MAX = 3, 20
# Limites de tamanho dos nomes: o campo não deixa passar e o servidor corta (nomes enormes quebram o layout)
DISPLAY_NAME_MAX = 20
BIO_MAX = 20
FOLDER_NAME_MAX = 30
DECK_NAME_MAX = 40
VERSION_NAME_MAX = 30
SEASON_NAME_MAX = 40
CUSTOM_PRINT_NAME_MAX = 40
CUSTOM_CARD_NAME_MAX = 60
PASSWORD_MIN = 8
