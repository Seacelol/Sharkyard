"""Modelos de domínio. Não dependem de API nem de interface."""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CardFace:
    """Uma face da carta. Cartas normais têm uma; dupla face, split e aventura têm duas."""
    name: str
    mana_cost: str = ""
    type_line: str = ""
    oracle_text: str = ""
    flavor_text: str = ""
    power: str | None = None
    toughness: str | None = None
    loyalty: str | None = None
    defense: str | None = None
    artist: str = ""
    image_normal: str | None = None
    image_large: str | None = None
    # como está impresso na carta (impressões em outro idioma, ex.: português); vazio nas em inglês
    printed_name: str = ""
    printed_type_line: str = ""
    printed_text: str = ""


@dataclass(frozen=True, slots=True)
class Prices:
    """Preços de mercado do Scryfall por acabamento; None quando o Scryfall não informa. tix = MTGO."""
    usd: Decimal | None = None
    usd_foil: Decimal | None = None
    usd_etched: Decimal | None = None
    eur: Decimal | None = None
    eur_foil: Decimal | None = None
    tix: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Card:
    """Uma impressão de carta (id = id do Scryfall). Também representa versões e cartas personalizadas,
    para que a interface mostre tudo do mesmo jeito."""
    id: str
    name: str
    set_code: str
    set_name: str
    collector_number: str
    rarity: str
    type_line: str
    mana_cost: str
    oracle_text: str
    oracle_id: str | None = None
    released_at: date | None = None
    artist: str = ""
    lang: str = "en"
    faces: tuple[CardFace, ...] = ()
    legalities: dict[str, str] = field(default_factory=dict)
    finishes: tuple[str, ...] = ()
    image_small: str | None = None
    image_normal: str | None = None
    image_large: str | None = None
    prices: Prices = field(default_factory=Prices)
    scryfall_uri: str | None = None
    custom_print_id: int | None = None  # preenchido quando é uma versão personalizada do usuário
    color_identity: tuple[str, ...] = ()  # letras WUBRG, como o Scryfall devolve
    image_art_crop: str | None = None  # só a arte, sem moldura: boa para capa de deck
    custom_card_id: int | None = None  # carta criada pelo usuário, que não existe no Magic
    printed_name: str = ""  # nome impresso, nas impressões em outro idioma (ex.: "Relâmpago")

    @property
    def display_name(self) -> str:
        """Nome como está na impressão: em português nas impressões em português, senão o nome em inglês."""
        return self.printed_name or self.name

    @property
    def is_custom(self) -> bool:
        """Edição personalizada de uma carta real."""
        return self.custom_print_id is not None

    @property
    def is_custom_card(self) -> bool:
        """Carta que não existe no Magic."""
        return self.custom_card_id is not None

    @property
    def price_usd(self) -> Decimal | None:
        return self.prices.usd

    @property
    def price_eur(self) -> Decimal | None:
        return self.prices.eur


@dataclass(frozen=True, slots=True)
class User:
    """Conta de usuário, sem a senha. theme é o nome do tema e theme_mode é "auto", "light" ou "dark"."""
    id: int
    username: str
    display_name: str
    is_admin: bool = False
    created_at: datetime | None = None
    last_login_at: datetime | None = None
    avatar_filename: str | None = None
    bio: str = ""
    must_change_password: bool = False
    is_disabled: bool = False
    theme: str = "tubarao"
    theme_mode: str = "auto"


@dataclass(frozen=True, slots=True)
class CustomPrint:
    """Versão da carta criada pelo usuário (alter, proxy próprio, arte personalizada...). Só o dono vê."""
    id: int
    oracle_id: str
    card_name: str
    name: str
    code: str = ""
    artist: str = ""
    notes: str = ""
    image_filename: str | None = None
    base_scryfall_id: str | None = None  # impressão do Scryfall usada como base (texto, imagem padrão)
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CollectionEntry:
    """Um lote de cartas iguais na coleção: mesma impressão, mesmo foil/proxy, mesmo preço e observação."""
    id: int
    oracle_id: str
    card_name: str
    quantity: int
    foil: bool = False
    is_proxy: bool = False
    price_paid_cents: int | None = None  # por unidade, em centavos de real
    notes: str = ""
    scryfall_id: str | None = None
    custom_print_id: int | None = None
    custom_card_id: int | None = None
    base_scryfall_id: str | None = None  # impressão do Scryfall para abrir a página da carta
    set_code: str = ""
    set_name: str = ""
    collector_number: str = ""
    rarity: str = ""
    type_line: str = ""
    lang: str = "en"  # idioma da impressão (ex.: "pt")
    image_small: str | None = None
    image_normal: str | None = None
    folder_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def price_paid(self) -> Decimal | None:
        return None if self.price_paid_cents is None else Decimal(self.price_paid_cents) / 100

    @property
    def total_paid_cents(self) -> int:
        return (self.price_paid_cents or 0) * self.quantity


@dataclass(frozen=True, slots=True)
class CollectionSummary:
    """Totais da coleção (ou de uma pasta). entries conta lotes; cards soma as quantidades."""
    entries: int = 0
    cards: int = 0
    real_cards: int = 0
    proxies: int = 0
    unique_cards: int = 0
    total_paid_cents: int = 0


@dataclass(frozen=True, slots=True)
class Folder:
    """Pasta para organizar a coleção ou os decks (kind = "collection" ou "decks")."""
    id: int
    kind: str
    name: str
    item_count: int = 0


@dataclass(frozen=True, slots=True)
class DeckCard:
    """Uma linha do deck: N cópias de uma impressão numa seção (ver services.decks.SECTIONS).
    Os campos depois de notes são cópia dos dados da carta, para mostrar o deck sem consultar o catálogo."""
    id: int
    deck_id: int
    oracle_id: str
    card_name: str
    quantity: int
    section: str = "main"
    scryfall_id: str | None = None
    custom_print_id: int | None = None
    custom_card_id: int | None = None
    foil: bool = False
    is_proxy: bool = False
    price_paid_cents: int | None = None
    notes: str = ""
    set_code: str = ""
    set_name: str = ""
    collector_number: str = ""
    rarity: str = ""
    color_identity: str = ""
    type_line: str = ""
    mana_cost: str = ""
    lang: str = "en"  # idioma da impressão (ex.: "pt")
    image_small: str | None = None
    image_normal: str | None = None
    image_art_crop: str | None = None


@dataclass(frozen=True, slots=True)
class CustomCard:
    """Carta criada pelo usuário (não existe no Magic). Fica só no deck em que nasceu (deck_id) até ir para a
    coleção; aí deck_id fica vazio e ela pode ser usada em qualquer deck."""
    id: int
    name: str
    mana_cost: str = ""
    type_line: str = ""
    oracle_text: str = ""
    power: str = ""
    toughness: str = ""
    loyalty: str = ""
    colors: str = ""  # letras WUBRG
    image_filename: str | None = None
    deck_id: int | None = None
    created_at: datetime | None = None

    @property
    def in_collection(self) -> bool:
        return self.deck_id is None


@dataclass(frozen=True, slots=True)
class Deck:
    """Deck do usuário. Contagem, cores e nome da versão vêm da versão atual, já prontos para a grade de decks."""
    id: int
    user_id: int
    name: str
    format: str = ""
    notes: str = ""
    visibility: str = "private"  # "private" ou "friends"
    folder_id: int | None = None
    colors: tuple[str, ...] = ()  # identidade de cor somada das cartas, na ordem WUBRG
    card_count: int = 0
    cover_filename: str | None = None  # capa enviada pelo usuário (tem prioridade)
    cover_art_url: str | None = None  # capa escolhida entre as cartas do deck
    cover_card_name: str = ""
    version_id: int | None = None  # versão atual (a que a grade mostra e a montagem edita)
    version_name: str = ""
    version_count: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DeckVersion:
    """Versão nomeada de um deck. Cada versão tem a própria lista de cartas."""
    id: int
    deck_id: int
    name: str
    card_count: int = 0  # principal + comandante, como no deck
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CardSet:
    """Edição (coleção) de Magic, como o Scryfall descreve."""
    code: str
    name: str
    set_type: str = ""
    released_at: date | None = None
    icon_svg_uri: str | None = None
    digital: bool = False


@dataclass(frozen=True, slots=True)
class Ruling:
    published_at: date
    text: str
    source: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Uma página de resultados de busca. total conta todas as páginas da busca, não só esta."""
    cards: tuple[Card, ...]
    total: int
    has_more: bool

    @classmethod
    def empty(cls) -> "SearchResult":
        return cls(cards=(), total=0, has_more=False)


@dataclass(frozen=True, slots=True)
class Season:
    """Temporada do ranking. Só uma fica ativa por vez (ended_at vazio)."""
    id: int
    name: str
    started_at: date
    ended_at: date | None = None

    @property
    def active(self) -> bool:
        return self.ended_at is None


@dataclass(frozen=True, slots=True)
class Win:
    """Vitória registrada para um deck. Guarda a versão usada para o histórico continuar certo se o deck mudar."""
    id: int
    deck_id: int
    played_on: date
    notes: str = ""
    version_id: int | None = None
    version_name: str = ""  # vazio se a versão foi apagada
    season_id: int | None = None
    season_name: str = ""


@dataclass(frozen=True, slots=True)
class RankedDeck:
    """Linha do ranking de decks, já com a posição calculada."""
    position: int
    deck_id: int
    name: str
    owner_id: int
    owner_name: str
    format: str
    wins: int
    last_win: date
    hidden: bool = False  # oculto pelo admin (só o admin vê)


@dataclass(frozen=True, slots=True)
class RankedPlayer:
    """Linha do ranking de jogadores. best_deck é o deck com mais vitórias do jogador no filtro escolhido."""
    position: int
    user_id: int
    name: str
    wins: int
    decks: int  # decks com vitória
    best_deck: str
    last_win: date
    hidden: bool = False
    avatar_filename: str | None = None
    bio: str = ""
