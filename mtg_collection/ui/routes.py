"""Caminhos das páginas, para nenhum componente montar URL na mão."""
from urllib.parse import quote


def search_path(query: str = "") -> str:
    return f"/search?q={quote(query)}" if query else "/search"


def card_path(card_id: str) -> str:
    return f"/card/{card_id}"


def deck_path(deck_id: int) -> str:
    return f"/deck/{deck_id}"


def deck_edit_path(deck_id: int) -> str:
    return f"/deck/{deck_id}/edit"
