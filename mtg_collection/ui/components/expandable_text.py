"""Texto longo mostrado em poucas linhas, com "... ver mais" para abrir tudo (e "ver menos" para fechar)."""
from nicegui import ui

LONG_CHARS = 160  # acima disso (ou com muitas quebras de linha) o texto começa recolhido


def is_long(text: str, lines: int) -> bool:
    """Estimativa do servidor; o navegador confirma depois (ver hide_if_fits)."""
    return len(text) > LONG_CHARS or text.count("\n") >= lines


def expandable_text(text: str, marker: str, lines: int = 3, classes: str = "text-sm text-gray-600") -> None:
    """Mostra `text` cortado em `lines` linhas, com botão para abrir. Texto vazio não desenha nada."""
    if not text:
        return
    clamp = f"line-clamp-{lines}"
    long = is_long(text, lines)
    with ui.column().classes("w-full gap-0").mark(marker):
        label = ui.label(text).classes(f"w-full whitespace-pre-line break-words {classes} {clamp if long else ''}") \
            .mark(f"{marker}-text")
        if not long:
            return
        toggle = ui.button("... ver mais").props("flat dense no-caps size=sm").classes("self-start -ml-1 px-1") \
            .mark(f"{marker}-toggle")

        def flip() -> None:
            opened = clamp not in label.classes
            label.classes(add=clamp) if opened else label.classes(remove=clamp)
            toggle.text = "... ver mais" if opened else "ver menos"

        toggle.on_click(flip)

        def hide_if_fits() -> None:
            # o servidor estima pelo tamanho do texto; no navegador dá para ver se ele realmente passou das linhas
            ui.run_javascript(f"""setTimeout(() => {{
                const t = getHtmlElement({label.id}), b = getHtmlElement({toggle.id});
                if (t && b && t.scrollHeight <= t.clientHeight + 1) b.style.display = 'none';
            }}, 50)""")

        # adiado: o elemento precisa estar no navegador e com tamanho calculado antes da medição
        ui.timer(0.1, hide_if_fits, once=True)
