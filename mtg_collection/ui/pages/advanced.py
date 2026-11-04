"""Busca avançada: formulário que monta a consulta na sintaxe do Scryfall e abre a busca normal."""
from contextlib import contextmanager

from nicegui import app, ui

from mtg_collection.services import scryfall
from mtg_collection.services.search_query import Comparison, SearchFilters, build_query
from mtg_collection.ui import formatting as fmt
from mtg_collection.ui.components.type_picker import TypePicker
from mtg_collection.ui.layout import frame
from mtg_collection.ui.routes import search_path

COLORS = [("w", "Branco"), ("u", "Azul"), ("b", "Preto"), ("r", "Vermelho"), ("g", "Verde"), ("c", "Incolor")]
COLOR_MODES = {">=": "Incluindo estas cores", "=": "Exatamente estas cores", "<=": "No máximo estas cores"}
OPERATORS = {"=": "=", "!=": "≠", "<": "<", "<=": "≤", ">": ">", ">=": "≥"}
LEGALITIES = {"legal": "Legal em", "banned": "Banida em", "restricted": "Restrita em"}
RARITIES = [("common", "Comum"), ("uncommon", "Incomum"), ("rare", "Rara"), ("mythic", "Mítica"),
            ("special", "Especial")]
CURRENCIES = {"usd": "US$", "eur": "€", "tix": "tix"}
LANGUAGES = {"": "Inglês (padrão)", "any": "Qualquer idioma", **{k: v for k, v in fmt.LANG_LABELS.items() if k != "en"}}
ORDERS = {"": "Nome (padrão)", "released": "Data de lançamento", "set": "Edição", "rarity": "Raridade",
          "color": "Cor", "cmc": "Valor de mana", "power": "Poder", "toughness": "Resistência",
          "usd": "Preço (US$)", "eur": "Preço (€)", "edhrec": "Popularidade no EDHREC", "artist": "Artista"}
DIRECTIONS = {"": "Automática", "asc": "Crescente", "desc": "Decrescente"}
STORAGE_KEY = "advanced_form"  # último formulário buscado, para voltar dos resultados com tudo preenchido


@contextmanager
def field_row(label: str, hint: str = ""):
    """Linha do formulário: rótulo à esquerda, controles à direita (empilha no celular)."""
    with ui.element("div").classes("grid grid-cols-1 sm:grid-cols-[11rem_1fr] gap-x-6 gap-y-1 w-full py-3 "
                                   "border-b border-gray-100 last:border-b-0"):
        with ui.column().classes("gap-0"):
            ui.label(label).classes("text-sm font-semibold text-gray-800")
            if hint:
                ui.label(hint).classes("text-xs text-gray-500")
        with ui.row().classes("w-full items-center gap-3"):
            yield


def section(title: str):
    """Cartão de um grupo de campos, com título. Usar com `with`."""
    card = ui.card().classes("w-full gap-0")
    with card:
        ui.label(title).classes("text-xs font-bold uppercase tracking-wider text-gray-500 mb-1")
    return card


class AdvancedSearchPage:
    """Formulário da busca avançada. Cada mudança atualiza a prévia da consulta; buscar guarda o formulário em
    app.storage.user e abre a busca normal, para que voltar dos resultados traga tudo preenchido."""

    def __init__(self):
        self._text_inputs: list[ui.input] = []
        self._build()
        for widget in self._all_widgets():
            widget.on_value_change(self._update_preview)
        for text_input in self._text_inputs:
            text_input.on("keydown.enter", self.search)
        self._update_preview()

    # ---------- formulário ----------
    def _input(self, placeholder: str, marker: str, width: str = "grow") -> ui.input:
        widget = ui.input(placeholder=placeholder).props("outlined dense clearable").classes(width).mark(marker)
        self._text_inputs.append(widget)
        return widget

    @staticmethod
    def _select(options: dict, value, width: str, marker: str) -> ui.select:
        return ui.select(options, value=value).props("outlined dense options-dense").classes(width).mark(marker)

    def _comparison(self, label: str, marker: str) -> tuple[ui.select, ui.input]:
        with ui.row().classes("items-center gap-2 no-wrap"):
            if label:
                ui.label(label).classes("text-sm text-gray-600 w-20 sm:w-auto")
            op = self._select(OPERATORS, ">=", "w-20", f"{marker}-op")
            value = self._input("", f"{marker}-value", "w-20")
        return op, value

    def _color_checkboxes(self, marker: str) -> dict[str, ui.checkbox]:
        boxes = {}
        for code, label in COLORS:
            with ui.row().classes("items-center gap-0 no-wrap"):
                boxes[code] = ui.checkbox().props("dense").mark(f"{marker}-{code}")
                ui.html(fmt.symbols_html("{" + code.upper() + "}"), sanitize=False).classes("ml-1 text-lg leading-none")
                ui.label(label).classes("text-sm ml-1 cursor-pointer") \
                    .on("click", lambda b=boxes[code]: b.set_value(not b.value))
        return boxes

    def _build(self) -> None:
        with ui.column().classes("w-full max-w-5xl mx-auto gap-5"):
            with ui.row().classes("w-full items-end justify-between"):
                with ui.column().classes("gap-0"):
                    ui.label("Busca avançada").classes("text-2xl font-bold")
                    ui.label("Preencha só o que importa. Os filtros se somam.").classes("text-sm text-gray-500")
                ui.link("Guia de sintaxe do Scryfall", "https://scryfall.com/docs/syntax", new_tab=True) \
                    .classes("text-sm")

            with section("Carta"):
                with field_row("Nome", "Palavras do nome"):
                    self.name = self._input("ex: dragon", "name")
                with field_row("Texto", "Trecho do texto de regras"):
                    self.oracle = self._input("ex: draw a card", "oracle")
                with field_row("Tipo", "Clique em É / NÃO para incluir ou excluir"):
                    self.types = TypePicker(on_change=self._update_preview)
                with field_row("Texto de sabor"):
                    self.flavor = self._input("ex: mishra", "flavor")
                with field_row("Artista"):
                    self.artist = self._input("ex: Rebecca Guay", "artist")

            with section("Cores e custo"):
                with field_row("Cores"):
                    self.colors = self._color_checkboxes("color")
                    self.color_mode = self._select(COLOR_MODES, ">=", "w-56", "color-mode")
                with field_row("Identidade de cor", "Cabe num deck de Commander destas cores"):
                    self.identity = self._color_checkboxes("identity")
                with field_row("Custo de mana", "Símbolos exatos do custo"):
                    self.mana_cost = self._input("ex: {2}{R}{R} ou 2RR", "mana-cost", "w-64")
                with field_row("Valor de mana"):
                    self.mv_op, self.mv_value = self._comparison("", "mv")
                with field_row("Atributos"):
                    self.pow_op, self.pow_value = self._comparison("Poder", "pow")
                    self.tou_op, self.tou_value = self._comparison("Resistência", "tou")
                    self.loy_op, self.loy_value = self._comparison("Lealdade", "loy")

            with section("Formato, edição e raridade"):
                with field_row("Formato"):
                    self.legality = self._select(LEGALITIES, "legal", "w-40", "legality")
                    self.format = self._select({"": "Qualquer formato", **fmt.FORMAT_LABELS}, "", "w-56", "format")
                with field_row("Edição", "Pode escolher várias"):
                    self.sets = ui.select({}, multiple=True, with_input=True, label="Carregando edições...") \
                        .props("outlined dense use-chips options-dense clearable") \
                        .classes("grow min-w-[16rem]").mark("sets")
                with field_row("Raridade"):
                    self.rarities = {code: ui.checkbox(label).props("dense").mark(f"rarity-{code}")
                                     for code, label in RARITIES}

            with section("Preço, idioma e exibição"):
                with field_row("Preço"):
                    self.currency = self._select(CURRENCIES, "usd", "w-24", "currency")
                    self.price_op = self._select(OPERATORS, "<=", "w-20", "price-op")
                    self.price_value = self._input("ex: 5", "price-value", "w-28")
                with field_row("Idioma"):
                    self.language = self._select(LANGUAGES, "", "w-56", "language")
                with field_row("Ordenar por"):
                    self.order = self._select(ORDERS, "", "w-56", "order")
                    self.direction = self._select(DIRECTIONS, "", "w-40", "direction")
                with field_row("Impressões"):
                    self.all_prints = ui.checkbox("Mostrar todas as impressões de cada carta") \
                        .props("dense").mark("all-prints")

            # barra presa ao rodapé da tela com a consulta montada e as ações
            with ui.element("div").classes("sticky bottom-0 z-10 w-full -mt-2 pb-4 pt-2 mtg-sticky"):
                # no celular a consulta fica numa linha e os botões embaixo; no desktop, lado a lado
                with ui.card().classes("w-full"), ui.element("div") \
                        .classes("w-full flex flex-col flex-nowrap sm:flex-row sm:items-center gap-2 sm:gap-4"):
                    with ui.column().classes("gap-0 grow min-w-0"):
                        ui.label("Consulta").classes("text-xs font-bold uppercase tracking-wider text-gray-500")
                        self.preview = ui.label().classes("font-mono text-sm break-words w-full").mark("query-preview")
                    with ui.row().classes("gap-2 no-wrap justify-end shrink-0"):
                        ui.button("Limpar", icon="restart_alt", on_click=self.clear) \
                            .props("flat no-caps").mark("clear")
                        self.search_button = ui.button("Buscar", icon="search", on_click=self.search) \
                            .props("no-caps").mark("search")

    def _all_widgets(self) -> list:
        return [
            self.name, self.oracle, self.flavor, self.artist, *self.colors.values(), self.color_mode,
            *self.identity.values(), self.mana_cost, self.mv_op, self.mv_value, self.pow_op, self.pow_value,
            self.tou_op, self.tou_value, self.loy_op, self.loy_value, self.legality, self.format, self.sets,
            *self.rarities.values(), self.currency, self.price_op, self.price_value, self.language, self.order,
            self.direction, self.all_prints,
        ]

    async def load_lists(self) -> None:
        """Tipos e edições vêm do Scryfall (guardados em memória depois da primeira vez)."""
        self.types.set_catalogs(await scryfall.client.get_type_catalogs())
        try:
            sets = await scryfall.client.get_sets()
        except scryfall.ScryfallError as e:
            self.sets.props["label"] = f"Edições indisponíveis: {e}"
            return
        self.sets.set_options({s.code: f"{s.name} ({s.code.upper()})" for s in sets})
        self.sets.props('label="Digite para procurar uma edição"')

    # ---------- consulta ----------
    def filters(self) -> SearchFilters:
        def text(widget) -> str:
            return (widget.value or "").strip()

        return SearchFilters(
            name=text(self.name),
            oracle_text=text(self.oracle),
            types=list(self.types.selected),
            colors={code for code, box in self.colors.items() if box.value},
            color_mode=self.color_mode.value,
            identity={code for code, box in self.identity.items() if box.value},
            mana_cost=text(self.mana_cost),
            mana_value=Comparison(self.mv_op.value, text(self.mv_value)),
            power=Comparison(self.pow_op.value, text(self.pow_value)),
            toughness=Comparison(self.tou_op.value, text(self.tou_value)),
            loyalty=Comparison(self.loy_op.value, text(self.loy_value)),
            format=self.format.value or "",
            legality=self.legality.value,
            sets=list(self.sets.value or []),
            rarities=[code for code, box in self.rarities.items() if box.value],
            artist=text(self.artist),
            flavor_text=text(self.flavor),
            price_currency=self.currency.value,
            price=Comparison(self.price_op.value, text(self.price_value)),
            language=self.language.value or "",
            order=self.order.value or "",
            direction=self.direction.value or "",
            all_prints=self.all_prints.value,
        )

    def query(self) -> str:
        return build_query(self.filters())

    def _update_preview(self) -> None:
        query = self.query()
        self.preview.text = query or "Preencha algum filtro"
        self.preview.classes(remove="text-gray-400" if query else "", add="" if query else "text-gray-400")
        self.search_button.set_enabled(bool(query))

    def search(self) -> None:
        query = self.query()
        if not query:
            ui.notify("Preencha pelo menos um filtro", type="warning")
            return
        app.storage.user[STORAGE_KEY] = self.state()
        ui.navigate.to(search_path(query) + "&adv=1")

    # ---------- guardar e restaurar ----------
    def _named(self) -> dict:
        """Cada campo com um nome estável (é o que fica guardado entre as páginas)."""
        named = {"name": self.name, "oracle": self.oracle, "flavor": self.flavor, "artist": self.artist,
                 "color_mode": self.color_mode, "mana_cost": self.mana_cost, "mv_op": self.mv_op,
                 "mv_value": self.mv_value, "pow_op": self.pow_op, "pow_value": self.pow_value,
                 "tou_op": self.tou_op, "tou_value": self.tou_value, "loy_op": self.loy_op,
                 "loy_value": self.loy_value, "legality": self.legality, "format": self.format, "sets": self.sets,
                 "currency": self.currency, "price_op": self.price_op, "price_value": self.price_value,
                 "language": self.language, "order": self.order, "direction": self.direction,
                 "all_prints": self.all_prints}
        named |= {f"color_{c}": box for c, box in self.colors.items()}
        named |= {f"identity_{c}": box for c, box in self.identity.items()}
        named |= {f"rarity_{c}": box for c, box in self.rarities.items()}
        return named

    def state(self) -> dict:
        state = {key: widget.value for key, widget in self._named().items()}
        state["types"] = [[name, include] for name, include in self.types.selected]
        return state

    def restore(self, state: dict) -> None:
        for key, widget in self._named().items():
            if key not in state:
                continue
            value = state[key]
            if widget is self.sets:  # edição que não veio na lista (Scryfall fora do ar) fica de fora
                value = [code for code in value or [] if code in self.sets.options]
            elif isinstance(widget, ui.select) and value not in widget.options:
                continue
            widget.value = value
        # guardado como lista de listas (JSON do storage); volta a ser tupla
        self.types.selected = [(name, bool(include)) for name, include in state.get("types", [])]
        self.types._changed()

    def clear(self) -> None:
        app.storage.user.pop(STORAGE_KEY, None)
        defaults = {self.color_mode: ">=", self.legality: "legal", self.format: "", self.currency: "usd",
                    self.price_op: "<=", self.language: "", self.order: "", self.direction: ""}
        for op in (self.mv_op, self.pow_op, self.tou_op, self.loy_op):
            defaults[op] = ">="
        self.types.clear()
        for widget in self._all_widgets():
            if widget in defaults:
                widget.value = defaults[widget]
            elif isinstance(widget, ui.checkbox):
                widget.value = False
            elif widget is self.sets:
                widget.value = []
            else:
                widget.value = ""


@ui.page("/advanced")
async def advanced_page() -> None:
    """Monta o formulário na hora; listas e formulário salvo chegam depois que o navegador conecta."""
    with frame("Busca avançada"):
        page = AdvancedSearchPage()
    await ui.context.client.connected()
    await page.load_lists()
    if saved := app.storage.user.get(STORAGE_KEY):
        page.restore(saved)  # depois das listas: as edições escolhidas precisam estar entre as opções
