"""Página de uma carta: imagem, versões (oficiais e personalizadas), texto, preços, coleção, legalidade e rulings."""
import json

from nicegui import ui

from mtg_collection import config, database
from mtg_collection.models import Card, CardFace, User
from mtg_collection.services import collection, scryfall
from mtg_collection.ui import auth
from mtg_collection.ui import formatting as fmt
from mtg_collection.ui.components.controls import back_button
from mtg_collection.ui.components.custom_print_dialog import open_custom_print_dialog
from mtg_collection.ui.components.entry_dialog import open_entry_dialog
from mtg_collection.ui.layout import frame
from mtg_collection.ui.pages.collection import entry_icon
from mtg_collection.ui.printings import CUSTOM_PREFIX, custom_card, load_custom_card, user_custom_cards
from mtg_collection.ui.routes import card_path
from mtg_collection.ui.set_icons import custom_set_icon, set_icon_url

LEGALITY_STYLES = {
    "legal": "bg-green-600 text-white",
    "restricted": "bg-amber-500 text-white",
    "banned": "bg-red-600 text-white",
    "not_legal": "bg-gray-200 text-gray-500",
}


def section_title(text: str) -> None:
    ui.label(text).classes("text-xs font-bold uppercase tracking-wider text-gray-500")


class CardView:
    """Ao trocar de versão, só as áreas que dependem dela são redesenhadas, sem recarregar a página."""

    CURRENT_PRINT = "bg-blue-100 ring-2 ring-blue-400"
    OTHER_PRINT = "hover:bg-gray-200"

    def __init__(self, card: Card, user: User, base: Card | None = None):
        self.card = card
        self.user = user
        # última impressão oficial: base para criar versões personalizadas e para buscar os rulings
        self.official = base if card.is_custom else card
        self.official_by_id: dict[str, Card] = {self.official.id: self.official}
        self.prints_page = 1
        self.print_items: dict[str, ui.element] = {}
        self.images: list[str] = []
        self.face_index = 0
        self._build()
        self._render_card()

    # ---------- estrutura fixa ----------
    def _build(self) -> None:
        with ui.column().classes("w-full max-w-6xl mx-auto gap-6"):
            back_button("Voltar", ui.navigate.back)
            with ui.element("div").classes("grid gap-8 w-full grid-cols-1 md:grid-cols-[minmax(280px,400px)_1fr]"):
                with ui.column().classes("gap-4 w-full max-w-sm mx-auto md:max-w-none"):
                    with ui.row().classes("w-full no-wrap gap-2 items-stretch"):
                        self._prints_column()
                        with ui.column().classes("grow min-w-0 gap-2"):
                            self.image = ui.element("img").classes("card-image w-full").mark("main-image")
                            # legenda: mostra a versão sob o mouse; fora da lista, volta para a versão aberta
                            self.caption = ui.label().mark("print-caption") \
                                .classes("w-full text-center text-sm text-gray-600 leading-5 min-h-[2.5rem]")
                            self.image_actions = ui.column().classes("w-full gap-2")
                    self.collection_area = ui.column().classes("w-full")
                    self.prices_area = ui.column().classes("w-full")
                self.info_area = ui.column().classes("gap-5 w-full min-w-0")
            self._rulings_section()

    def _prints_column(self) -> None:
        # a lista fica absoluta dentro de um wrapper para ter a altura da imagem e rolar
        with ui.element("div").classes("relative w-14 shrink-0"):
            # flex-nowrap é necessário: a classe "flex" do Quasar liga flex-wrap e quebraria a lista em colunas
            self.prints_list = ui.element("div").classes(
                "absolute inset-0 overflow-y-auto overflow-x-hidden flex flex-col flex-nowrap items-center gap-1 p-1 "
                "prints-scroll").mark("prints-list")
        with self.prints_list:
            # versões personalizadas ficam num bloco próprio no topo: dá para refazer só ele
            self.custom_list = ui.element("div").classes("w-full flex flex-col flex-nowrap items-center gap-1")
            self.official_list = ui.element("div").classes("w-full flex flex-col flex-nowrap items-center gap-1")
            with self.official_list:
                ui.spinner().classes("mt-4")

    # ---------- partes que dependem da versão ----------
    def _render_card(self) -> None:
        card = self.card
        self.images = [f.image_large for f in card.faces if f.image_large] or (
            [card.image_large] if card.image_large else [])
        self.face_index = 0
        self.image.visible = bool(self.images)
        if self.images:
            self._show_image(self.images[0])
        text = self._print_text(card)
        self.caption.text = text
        self.caption.props["data-current"] = text  # por chave: o texto vai como dado, sem passar pelo parser

        self.image_actions.clear()
        with self.image_actions:
            if not self.images:
                ui.label("Sem imagem").classes("text-gray-400 self-center")
            elif len(self.images) > 1:
                ui.button("Virar carta", icon="flip", on_click=self._flip).props("outline no-caps").classes("w-full")

        self._render_collection()
        self.prices_area.clear()
        with self.prices_area:
            self._prices()

        self.info_area.clear()
        with self.info_area:
            self._header()
            for face in card.faces:
                self._face(face, show_title=len(card.faces) > 1)
            self._legalities()

    def select_print(self, printing: Card) -> None:
        """Mostra outra versão na mesma página. Os dados já vieram na lista de versões: nenhuma requisição."""
        if printing.id == self.card.id:
            return
        if old := self.print_items.get(self.card.id):
            old.classes(remove=self.CURRENT_PRINT, add=self.OTHER_PRINT)
        if new := self.print_items.get(printing.id):
            new.classes(remove=self.OTHER_PRINT, add=self.CURRENT_PRINT)
        self.card = printing
        if not printing.is_custom:
            self.official = printing
        self._render_card()
        ui.navigate.history.replace(card_path(printing.id))  # recarregar ou compartilhar abre esta versão
        ui.page_title(f"{printing.name} | {config.APP_NAME}")

    def _flip(self) -> None:
        self.face_index = (self.face_index + 1) % len(self.images)
        self._show_image(self.images[self.face_index])

    def _show_image(self, url: str) -> None:
        # data-current guarda a imagem "oficial"; o hover nas versões troca só o src e volta para ela.
        # Ao trocar o src, o navegador mantém a imagem anterior na tela até a nova carregar (sem piscar).
        self.image.props.update({"src": url, "data-current": url, "alt": self.card.name})

    # ---------- coleção ----------
    def _render_collection(self) -> None:
        with database.session() as s:
            entries = collection.list_entries(s, self.user.id, self.card.oracle_id)
        self.collection_area.clear()
        with self.collection_area, ui.card().classes("w-full gap-2").mark("my-collection"):
            section_title("Na sua coleção")
            if entries:
                summary = collection.summarize(entries)
                proxies = f" ({fmt.plural(summary.proxies, 'proxy', 'proxies')})" if summary.proxies else ""
                ui.label(f"Você tem {summary.cards}{proxies}").classes("text-sm font-medium") \
                    .mark("collection-count")
                for entry in entries:
                    with ui.row().classes("w-full items-center gap-2 no-wrap text-sm").mark(f"owned-{entry.id}"):
                        entry_icon(entry)
                        if entry.custom_print_id:
                            code = f" ({entry.set_code})" if entry.set_code else ""
                            text = f"{entry.set_name}{code}"
                        else:
                            text = f"{entry.set_code} #{entry.collector_number}"
                        ui.label(text).classes("truncate grow min-w-0")
                        if entry.foil:
                            ui.badge("Foil").props("color=amber-7")
                        if entry.is_proxy:
                            ui.badge("Proxy").props("color=grey-6")
                        ui.label(f"{entry.quantity}x").classes("font-semibold")
                        ui.button(icon="edit", on_click=lambda e=entry: open_entry_dialog(
                            self.user.id, e, on_change=self._render_collection)) \
                            .props("flat round dense size=sm").mark(f"edit-owned-{entry.id}")
            else:
                ui.label("Você ainda não tem esta carta.").classes("text-sm text-gray-500")
            label = "Adicionar esta versão" if not self.card.is_custom else "Adicionar esta versão personalizada"
            ui.button(label, icon="add", on_click=self._add_current).props("unelevated no-caps") \
                .classes("w-full").mark("add-to-collection")
            with ui.row().classes("w-full gap-1 no-wrap"):
                ui.button("Nova versão personalizada", icon="auto_awesome", on_click=self._new_custom) \
                    .props("flat dense no-caps size=sm").mark("new-custom")
                if self.card.is_custom:
                    ui.button("Editar versão", icon="edit", on_click=self._edit_custom) \
                        .props("flat dense no-caps size=sm").mark("edit-custom")

    def _add_current(self) -> None:
        try:
            with database.session() as s:
                entry = collection.add_card(s, self.user.id, self.card)
        except collection.CollectionError as e:
            ui.notify(str(e), type="negative")
            return
        ui.notify(f"Adicionada à coleção. Agora você tem {entry.quantity} nesse item.", type="positive")
        self._render_collection()

    def _new_custom(self) -> None:
        open_custom_print_dialog(self.user.id, self.official, None, on_saved=self._custom_saved)

    def _edit_custom(self) -> None:
        with database.session() as s:
            existing = collection.get_custom_print(s, self.user.id, self.card.custom_print_id)
        open_custom_print_dialog(self.user.id, self.official, existing, on_saved=self._custom_saved,
                                 on_deleted=self._custom_deleted)

    def _custom_saved(self, custom) -> None:
        base = self.official_by_id.get(custom.base_scryfall_id) or self.official
        card = custom_card(custom, base)
        self._render_custom_icons()
        if self.card.is_custom and self.card.custom_print_id == custom.id:
            self.card = card  # editou a versão aberta: redesenha com os dados novos
            self._render_card()
        else:
            self.select_print(card)

    def _custom_deleted(self, custom_id: int) -> None:
        self._render_custom_icons()
        if self.card.custom_print_id == custom_id:
            self.select_print(self.official)
        else:
            self._render_collection()

    # ---------- coluna de versões ----------
    async def load_extras(self) -> None:
        """Versões e rulings, carregados depois que a carta já está na tela."""
        await self.load_prints()
        await self.load_rulings()

    async def load_prints(self) -> None:
        """Carrega a próxima página de impressões oficiais na coluna (o botão "+" chama de novo)."""
        if not self.card.oracle_id:
            self.official_list.clear()
            return
        try:
            result = await scryfall.client.get_prints(self.card.oracle_id, self.prints_page)
        except scryfall.ScryfallError as e:
            ui.notify(f"Não foi possível carregar as versões: {e}", type="warning")
            return
        self.official_by_id.update({c.id: c for c in result.cards})
        if self.prints_page == 1:
            self.official_list.clear()
            # ao sair da lista, volta para a imagem e a legenda da versão aberta
            restore = "if (i.dataset.current) i.src = i.dataset.current; c.textContent = c.dataset.current;"
            self.prints_list.on("mouseleave", js_handler=f"() => {{ {self._hover_js} {restore} }}")
            self._render_custom_icons()
        else:
            self.more_prints.delete()
        with self.official_list:
            for printing in result.cards:
                item = self._print_icon(printing)
                if printing.id == self.card.id:
                    self._scroll_list_to(item)
            if result.has_more:
                self.more_prints = ui.button(icon="add", on_click=self.load_prints) \
                    .props("flat round dense size=sm").tooltip("Carregar mais versões").mark("more-prints")
        self.prints_page += 1

    def _render_custom_icons(self) -> None:
        for key in [k for k in self.print_items if k.startswith(CUSTOM_PREFIX)]:
            del self.print_items[key]
        self.custom_list.clear()
        customs = user_custom_cards(self.user.id, self.card.oracle_id, list(self.official_by_id.values()),
                                    self.official)
        with self.custom_list:
            for card in customs:
                item = self._print_icon(card)
                if card.id == self.card.id:
                    self._scroll_list_to(item)
            if customs:
                ui.separator().classes("w-8 my-1")

    @staticmethod
    def _scroll_list_to(item: ui.element) -> None:
        """Rola só a lista (não a página) até a versão aberta. Espera o elemento existir no navegador."""
        ui.run_javascript(f"""(function scroll(tries) {{
            const el = document.getElementById('c{item.id}');
            if (!el) {{ if (tries > 0) requestAnimationFrame(() => scroll(tries - 1)); return; }}
            const box = el.closest('.prints-scroll');
            box.scrollTop = el.offsetTop - box.clientHeight / 2 + el.clientHeight / 2;
        }})(120);""")

    @property
    def _hover_js(self) -> str:
        return (f"const i = document.getElementById('c{self.image.id}'); "
                f"const c = document.getElementById('c{self.caption.id}');")

    @staticmethod
    def _print_text(printing: Card) -> str:
        if printing.is_custom:
            code = f" ({printing.set_code})" if printing.set_code else ""
            return f"★ {printing.set_name}{code} · versão personalizada"
        details = [f"{printing.set_name} ({printing.set_code})", f"#{printing.collector_number}",
                   fmt.RARITY_LABELS.get(printing.rarity, printing.rarity.title())]
        if printing.released_at:
            details.append(str(printing.released_at.year))
        if printing.lang != "en":
            details.append(fmt.LANG_LABELS.get(printing.lang, printing.lang.upper()))
        price = printing.prices.usd or printing.prices.usd_foil
        if price is not None:
            details.append(fmt.price(price, "US$"))
        return " · ".join(details)

    def _print_icon(self, printing: Card) -> ui.element:
        state = self.CURRENT_PRINT if printing.id == self.card.id else self.OTHER_PRINT
        classes = f"relative w-11 h-11 shrink-0 flex items-center justify-center rounded-lg cursor-pointer {state}"
        with ui.element("div").mark(f"print print-{printing.id}").classes(classes) as item:
            if printing.is_custom:
                custom_set_icon()
            else:
                ui.element("div").classes(f"set-icon rarity-{printing.rarity}") \
                    .style(f"--icon: url('{set_icon_url(printing.set_code)}')")
            if printing.lang != "en":  # mesma edição em outro idioma: a etiqueta diferencia do ícone em inglês
                ui.label(printing.lang.upper()).classes(
                    "absolute -bottom-1 -right-1 text-[9px] font-bold leading-none px-1 py-0.5 rounded "
                    "bg-primary mtg-on-primary").mark(f"print-lang-{printing.id}")
        self.print_items[printing.id] = item
        item.on("click", lambda: self.select_print(printing))
        # tamanho "normal" (488px): leve o bastante para trocar rápido ao passar por várias versões
        hover_image = (printing.faces[0].image_normal if printing.faces else None) or printing.image_normal
        set_src = f"i.src = {json.dumps(hover_image)};" if hover_image else ""
        text = json.dumps(self._print_text(printing), ensure_ascii=False)
        # troca imagem e legenda direto no navegador, sem ida ao servidor
        item.on("mouseenter", js_handler=f"() => {{ {self._hover_js} {set_src} c.textContent = {text}; }}")
        return item

    # ---------- preços, texto, legalidade, rulings ----------
    def _prices(self) -> None:
        p = self.card.prices
        rows = [("Normal", p.usd, p.eur), ("Foil", p.usd_foil, p.eur_foil), ("Etched", p.usd_etched, None)]
        rows = [r for r in rows if r[1] is not None or r[2] is not None]
        with ui.card().classes("w-full gap-2"):
            section_title("Preços")
            if self.card.is_custom:
                ui.label("Versão personalizada: sem preço de mercado.").classes("text-sm text-gray-500")
            elif not rows and p.tix is None:
                ui.label("Sem preço disponível").classes("text-sm text-gray-500")
            for label, usd, eur in rows:
                with ui.row().classes("w-full justify-between text-sm"):
                    ui.label(label).classes("text-gray-600")
                    ui.label(f"{fmt.price(usd, 'US$')}  ·  {fmt.price(eur, '€')}").classes("font-medium tabular-nums")
            if p.tix is not None:
                with ui.row().classes("w-full justify-between text-sm"):
                    ui.label("MTGO").classes("text-gray-600")
                    ui.label(f"{p.tix:.2f} tix").classes("font-medium tabular-nums")
            if self.card.scryfall_uri:
                ui.link("Ver no Scryfall", self.card.scryfall_uri, new_tab=True).classes("text-sm mt-1")

    def _header(self) -> None:
        card = self.card
        with ui.column().classes("gap-1 w-full"):
            with ui.row().classes("w-full items-start justify-between no-wrap gap-4"):
                with ui.column().classes("gap-0 min-w-0"):
                    ui.label(card.display_name).classes("text-3xl font-bold leading-tight").mark("card-title")
                    if card.printed_name and card.printed_name != card.name:  # impressão em português
                        ui.label(card.name).classes("text-sm text-gray-500").mark("card-english-name")
                if len(card.faces) == 1 and card.mana_cost:
                    ui.html(fmt.symbols_html(card.mana_cost), sanitize=False).classes("mana-cost shrink-0 mt-1")
            with ui.row().classes("items-center gap-x-3 gap-y-1 text-sm text-gray-600"):
                if card.is_custom:
                    ui.badge("Versão personalizada").props("color=primary").mark("custom-badge")
                    code = f" ({card.set_code})" if card.set_code else ""
                    ui.label(f"{card.set_name}{code}").classes("font-medium text-gray-800")
                    if card.artist:
                        ui.label(f"por {card.artist}")
                    return
                ui.label(f"{card.set_name} ({card.set_code})").classes("font-medium text-gray-800")
                ui.label(f"#{card.collector_number}")
                ui.label(fmt.RARITY_LABELS.get(card.rarity, card.rarity.title())) \
                    .classes(f"font-semibold rarity-text-{card.rarity}") \
                    .style(f"color: {fmt.RARITY_COLORS.get(card.rarity, '#374151')}")
                ui.label(fmt.date_br(card.released_at))
                ui.label(fmt.LANG_LABELS.get(card.lang, card.lang.upper()))
                if card.finishes:
                    ui.label(" / ".join(f.title() for f in card.finishes))

    def _face(self, face: CardFace, show_title: bool) -> None:
        with ui.card().classes("w-full gap-3"):
            printed = bool(face.printed_type_line or face.printed_text)  # impressão em português
            if show_title:
                with ui.row().classes("w-full items-start justify-between no-wrap gap-4"):
                    ui.label(face.printed_name or face.name).classes("text-lg font-bold")
                    if face.mana_cost:
                        ui.html(fmt.symbols_html(face.mana_cost), sanitize=False).classes("mana-cost shrink-0")
            ui.label(face.printed_type_line or face.type_line).classes("font-semibold text-gray-800")
            text = face.printed_text if printed else face.oracle_text
            if text:
                ui.separator()
                ui.html(fmt.rules_text_html(text), sanitize=False) \
                    .classes("whitespace-pre-line leading-relaxed").mark("face-text")
            if face.flavor_text:
                ui.label(face.flavor_text).classes("italic text-gray-500 whitespace-pre-line border-l-4 pl-3")
            stats = fmt.stats(face.power, face.toughness, face.loyalty, face.defense)
            footer_artist = face.artist or self.card.artist
            if stats or footer_artist:
                with ui.row().classes("w-full items-center justify-between text-sm"):
                    ui.label(f"Ilustração: {footer_artist}" if footer_artist else "").classes("text-gray-500")
                    if stats:
                        ui.label(stats).classes("px-3 py-1 rounded-lg bg-slate-900 text-white font-bold")
            if printed and face.oracle_text:  # o texto impresso pode estar desatualizado: o Oracle vale nas regras
                with ui.expansion("Texto Oracle (inglês)").props("dense").classes("w-full text-sm text-gray-600") \
                        .mark("oracle-english"):
                    ui.label(face.type_line).classes("font-semibold")
                    ui.html(fmt.rules_text_html(face.oracle_text), sanitize=False) \
                        .classes("whitespace-pre-line leading-relaxed")

    def _legalities(self) -> None:
        items = fmt.sorted_legalities(self.card.legalities)
        if not items:
            return
        with ui.card().classes("w-full gap-3"):
            section_title("Legalidade")
            with ui.element("div").classes("grid gap-x-3 sm:gap-x-6 gap-y-2 w-full grid-cols-2 lg:grid-cols-3"):
                for fmt_label, status, status_label in items:
                    with ui.row().classes("items-center gap-2 no-wrap min-w-0"):
                        ui.label(status_label).classes(
                            f"w-20 max-sm:w-16 shrink-0 text-center text-xs max-sm:text-[11px] font-semibold rounded "
                            f"py-0.5 {LEGALITY_STYLES.get(status, LEGALITY_STYLES['not_legal'])}")
                        ui.label(fmt_label).classes("text-sm truncate min-w-0")

    def _rulings_section(self) -> None:
        with ui.card().classes("w-full gap-4"):
            self.rulings_title = ui.label("Rulings").classes("text-xs font-bold uppercase tracking-wider text-gray-500")
            self.rulings_list = ui.column().classes("w-full gap-4")
            with self.rulings_list:
                ui.spinner()

    async def load_rulings(self) -> None:
        try:  # rulings valem para todas as versões da carta: carrega uma vez só (pela impressão oficial)
            rulings = await scryfall.client.get_rulings(self.official.id)
        except scryfall.ScryfallError as e:
            ui.notify(f"Não foi possível carregar os rulings: {e}", type="warning")
            return
        self.rulings_title.text = f"Rulings ({len(rulings)})"
        self.rulings_list.clear()
        with self.rulings_list:
            if not rulings:
                ui.label("Nenhum ruling para esta carta.").classes("text-gray-500")
            for ruling in rulings:
                with ui.column().classes("gap-1"):
                    ui.label(fmt.date_br(ruling.published_at)).classes("text-xs font-semibold text-gray-500")
                    ui.html(fmt.rules_text_html(ruling.text), sanitize=False).classes("leading-relaxed")


@ui.page("/card/{card_id}")
async def card_page(card_id: str) -> None:
    """Página da carta. `card_id` é o id do Scryfall ou, numa versão personalizada, CUSTOM_PREFIX + id.
    Mostra um spinner e só busca depois que o navegador conecta, para a página abrir na hora."""
    user = auth.current_user()
    with frame("Carta"):
        content = ui.column().classes("w-full")
        with content:
            ui.spinner(size="xl").classes("self-center mt-24")
    await ui.context.client.connected()
    base = None
    try:
        if card_id.startswith(CUSTOM_PREFIX):
            card, base = await load_custom_card(user.id, card_id)
        else:
            card = await scryfall.client.get_card(card_id)
    except (scryfall.ScryfallError, collection.CollectionError) as e:
        content.clear()
        with content.classes("items-center mt-24 gap-4"):
            ui.icon("error_outline", size="xl").classes("text-gray-400")
            ui.label(f"Não foi possível abrir a carta: {e}").classes("text-gray-600")
            ui.button("Voltar", icon="arrow_back", on_click=ui.navigate.back).props("outline no-caps")
        return
    ui.page_title(f"{card.display_name} | {config.APP_NAME}")
    content.clear()
    with content:
        view = CardView(card, user, base)
    await view.load_extras()
