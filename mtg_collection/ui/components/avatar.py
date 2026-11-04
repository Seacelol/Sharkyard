"""Ícone redondo do usuário: exibição (imagem ou inicial) e o editor que recorta a imagem dentro do círculo.

Tudo acontece no navegador: a imagem escolhida nem sobe para o servidor (a prévia sai direto do arquivo). A pessoa
arrasta e ajusta o zoom; ao salvar, o navegador desenha o círculo num quadrado de 256 px e manda só esse PNG."""
import base64
import hashlib
from collections.abc import Callable

from nicegui import run, ui

from mtg_collection import database
from mtg_collection.services import accounts
from mtg_collection.ui.components.dialogs import close_dialog, maybe_await
from mtg_collection.ui.custom_images import ImageError, avatar_url, discard_if_unused, save_image

CROP_SIZE = 240  # px do círculo no editor
OUTPUT_SIZE = 256  # px do ícone salvo
# um PNG de 256 x 256 nem sem compressão chega a 270 KB; bem acima disso não veio do recorte do app
MAX_AVATAR_BYTES = 512 * 1024
_COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#c98500", "#d55181", "#008300", "#7c3aed", "#0e7490")

CROP_JS = rf"""
window.mtgAvatarCrop = window.mtgAvatarCrop || (() => {{
  const SIZE = {CROP_SIZE}, OUT = {OUTPUT_SIZE};
  const state = new WeakMap();
  function clamp(s) {{
    const w = s.img.naturalWidth * s.scale, h = s.img.naturalHeight * s.scale;
    s.x = Math.min(0, Math.max(SIZE - w, s.x));
    s.y = Math.min(0, Math.max(SIZE - h, s.y));
  }}
  function draw(s) {{
    clamp(s);
    s.img.style.width = (s.img.naturalWidth * s.scale) + 'px';
    s.img.style.height = (s.img.naturalHeight * s.scale) + 'px';
    s.img.style.transform = `translate(${{s.x}}px, ${{s.y}}px)`;
  }}
  function setup(box) {{
    const img = box.querySelector('img');
    const s = {{img, x: 0, y: 0, scale: 1, base: 1, zoom: 1}};
    state.set(box, s);
    const start = () => {{
      s.base = Math.max(SIZE / img.naturalWidth, SIZE / img.naturalHeight);  // cobre o círculo
      s.zoom = 1; s.scale = s.base;
      s.x = (SIZE - img.naturalWidth * s.scale) / 2; s.y = (SIZE - img.naturalHeight * s.scale) / 2;
      draw(s);
    }};
    img.addEventListener('load', start);
    if (img.complete && img.naturalWidth) start();
    let drag = null;
    box.addEventListener('pointerdown', e => {{ drag = {{px: e.clientX, py: e.clientY, x: s.x, y: s.y}};
      box.setPointerCapture(e.pointerId); box.style.cursor = 'grabbing'; }});
    box.addEventListener('pointermove', e => {{ if (!drag) return;
      s.x = drag.x + e.clientX - drag.px; s.y = drag.y + e.clientY - drag.py; draw(s); }});
    const stop = () => {{ drag = null; box.style.cursor = 'grab'; }};
    box.addEventListener('pointerup', stop); box.addEventListener('pointercancel', stop);
    box.addEventListener('wheel', e => {{ e.preventDefault();
      api.zoom(box, Math.min(4, Math.max(1, s.zoom * (e.deltaY < 0 ? 1.08 : 0.92)))); }}, {{passive: false}});
    return s;
  }}
  const api = {{
    init(box) {{ return setup(box); }},
    bind(box, input) {{  // arquivo escolhido: prévia local, sem enviar nada
      if (!box || !input || input.dataset.bound) return;
      input.dataset.bound = '1';
      input.addEventListener('change', () => {{
        const file = input.files && input.files[0];
        input.value = '';
        if (!file || !/^image\/(png|jpeg|webp)$/.test(file.type)) return;
        const img = box.querySelector('img');
        if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
        img.dataset.url = URL.createObjectURL(file);
        if (!state.get(box)) setup(box);
        img.src = img.dataset.url;
        const placeholder = box.querySelector('.avatar-placeholder');
        if (placeholder) placeholder.style.display = 'none';
      }});
    }},
    zoom(box, value) {{
      const s = state.get(box) || setup(box);
      if (!s.img.naturalWidth) return;
      const cx = SIZE / 2, cy = SIZE / 2, old = s.scale;  // o zoom mantém o centro do círculo no lugar
      s.zoom = value; s.scale = s.base * value;
      s.x = cx - (cx - s.x) * s.scale / old; s.y = cy - (cy - s.y) * s.scale / old;
      draw(s);
    }},
    export(box) {{
      const s = state.get(box); if (!s || !s.img.naturalWidth) return null;
      const canvas = document.createElement('canvas'); canvas.width = canvas.height = OUT;
      const k = OUT / SIZE, ctx = canvas.getContext('2d');
      ctx.drawImage(s.img, s.x * k, s.y * k, s.img.naturalWidth * s.scale * k, s.img.naturalHeight * s.scale * k);
      return canvas.toDataURL('image/png');
    }},
  }};
  return api;
}})();
"""


def install_crop_script() -> None:
    """Coloca o script do recorte na página. Chamar ao montar a página que abre o editor."""
    ui.add_head_html(f"<script>{CROP_JS}</script>")


def initials_color(name: str) -> str:
    return _COLORS[int(hashlib.md5(name.encode()).hexdigest(), 16) % len(_COLORS)]


def user_avatar(name: str, filename: str | None, size: int = 32) -> None:
    """Ícone redondo: a imagem da pessoa ou a inicial do nome sobre uma cor fixa para ela."""
    style = f"width:{size}px;height:{size}px;min-width:{size}px"
    if filename:
        img = ui.element("img").props('alt=""')
        img.props["src"] = avatar_url(filename)  # dado vai por chave, nunca dentro do texto de props
        img.classes("rounded-full object-cover shrink-0").style(style).mark("avatar-img")
        return
    with ui.element("div").classes("rounded-full shrink-0 flex items-center justify-center text-white font-bold") \
            .style(f"{style};background:{initials_color(name)};font-size:{max(10, size * 0.45):.0f}px") \
            .mark("avatar-initial"):
        ui.label((name.strip()[:1] or "?").upper())


def save_avatar_png(user_id: int, data_url: str) -> str:
    """Grava o PNG recortado que veio do navegador e troca o ícone. Devolve o nome do arquivo."""
    prefix = "data:image/png;base64,"
    if not data_url.startswith(prefix):
        raise ImageError("Não deu para recortar a imagem. Tente de novo.")
    encoded = data_url[len(prefix):]
    # confere o tamanho antes de decodificar: cada 4 caracteres de base64 viram 3 bytes
    if len(encoded) * 3 // 4 > MAX_AVATAR_BYTES:
        raise ImageError("A imagem do ícone ficou grande demais. Escolha outra imagem.")
    filename = save_image(base64.b64decode(encoded))
    with database.session() as s:
        old = accounts.set_avatar(s, user_id, filename)
    discard_if_unused(old)
    return filename


def open_avatar_dialog(user_id: int, name: str, current: str | None,
                       on_saved: Callable[[str | None], object]) -> None:
    """Editor do ícone. `on_saved` recebe o novo nome de arquivo (None quando a pessoa apaga o ícone)."""
    with ui.context.client.content, ui.dialog() as dialog, ui.card().classes("w-full max-w-sm gap-3 items-center"):
        ui.label("Ícone da conta").classes("text-lg font-bold self-start")
        ui.label("Escolha uma imagem, arraste para posicionar dentro do círculo e ajuste o zoom.") \
            .classes("text-sm text-gray-500 self-start")
        with ui.element("div").classes("relative rounded-full overflow-hidden bg-gray-100 select-none") \
                .style(f"width:{CROP_SIZE}px;height:{CROP_SIZE}px;touch-action:none;cursor:grab") \
                .mark("avatar-crop") as box:
            ui.element("img").props('draggable="false" alt=""') \
                .classes("absolute top-0 left-0 max-w-none pointer-events-none").style("transform-origin:0 0")
            with ui.element("div").classes("avatar-placeholder absolute inset-0 flex items-center justify-center"):
                user_avatar(name, current, CROP_SIZE)
        zoom = ui.slider(min=1, max=4, step=0.01, value=1).classes("w-full").mark("avatar-zoom")
        zoom.on("update:model-value", js_handler=f"(v) => mtgAvatarCrop.zoom(getHtmlElement({box.id}), v)")
        # seletor de arquivo do próprio navegador: o arquivo fica no aparelho, só a prévia aparece
        file_input = ui.element("input").props('type="file" accept="image/png,image/jpeg,image/webp"') \
            .classes("hidden").mark("avatar-file")
        ui.button("Escolher imagem", icon="image").props("outline no-caps") \
            .on("click", js_handler=f"() => getHtmlElement({file_input.id}).click()").mark("avatar-pick")

        async def save() -> None:
            data_url = await ui.run_javascript(f"mtgAvatarCrop.export(getHtmlElement({box.id}))", timeout=10)
            if not data_url:
                ui.notify("Escolha uma imagem primeiro.", type="warning")
                return
            try:
                # decodificar e gravar fora do loop da interface: não trava a página dos outros enquanto isso
                filename = await run.io_bound(save_avatar_png, user_id, str(data_url))
            except ImageError as e:
                ui.notify(str(e), type="negative")
                return
            ui.notify("Ícone salvo.", type="positive")
            await maybe_await(on_saved(filename))
            close_dialog(dialog)

        async def remove() -> None:
            with database.session() as s:
                old = accounts.set_avatar(s, user_id, None)
            discard_if_unused(old)
            ui.notify("Ícone removido.", type="positive")
            await maybe_await(on_saved(None))
            close_dialog(dialog)

        with ui.row().classes("w-full items-center justify-between"):
            if current:
                ui.button("Apagar ícone", icon="delete", on_click=remove).props("flat no-caps color=negative") \
                    .mark("avatar-remove")
            else:
                ui.element("div")
            with ui.row().classes("gap-2"):
                ui.button("Cancelar", on_click=lambda: close_dialog(dialog)).props("flat no-caps")
                ui.button("Salvar", on_click=save).props("unelevated no-caps").mark("avatar-save")
    dialog.on("hide", lambda: close_dialog(dialog))
    dialog.open()
    # o diálogo só entra no DOM depois de aberto: o atraso garante que caixa e campo de arquivo já existem
    ui.run_javascript(f"setTimeout(() => mtgAvatarCrop.bind(getHtmlElement({box.id}), "
                      f"getHtmlElement({file_input.id})), 50)")
