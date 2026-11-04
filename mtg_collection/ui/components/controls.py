"""Peças repetidas pelas páginas, para terem sempre a mesma cara."""
from collections.abc import Callable

from nicegui import ui

# seletor de opções lado a lado (modo de exibição, capa do deck, claro/escuro...)
SEGMENTED = "no-caps unelevated dense toggle-color=primary"


def back_button(label: str, on_click: Callable[[], object]) -> ui.button:
    """Botão de voltar no topo da página, alinhado com a borda do conteúdo."""
    return ui.button(label, icon="arrow_back", on_click=on_click).props("flat no-caps dense") \
        .classes("self-start px-2").mark("back-button")


def lazy_img(src: str) -> ui.element:
    """<img> com carregamento sob demanda. O endereço vai por chave em props, nunca dentro do texto de props:
    um valor terminado em barra invertida quebraria o parser do NiceGUI e deixaria injetar props ":" (JS)."""
    img = ui.element("img").props('loading="lazy" alt=""')
    img.props["src"] = src
    return img
