import os

import httpx
import pytest
from nicegui.testing import User

from mtg_collection import config, database
from mtg_collection.models import CardSet, SearchResult
from mtg_collection.services import accounts, scryfall
from mtg_collection.services.scryfall import ScryfallClient, ScryfallError, _match_identifier, to_card, to_rulings
from mtg_collection.ui.components import card_search_input
from tests.sample_cards import BOLT, BOLT_REPRINT, DELVER, GOLD, LAND, LEGEND, LUTRI, RATS, RULINGS, THRASIOS, TYMNA

# a cópia local do Scryfall não roda nos testes de interface (baixaria da internet)
os.environ["MTG_CATALOG"] = "0"


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Cada teste usa uma pasta de dados própria, com banco novo e migrado. Nada toca ~/.mtg-collection."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "CACHE_DIR", data_dir / "cache")
    monkeypatch.setattr(config, "DATABASE_PATH", data_dir / "data.db")
    monkeypatch.setattr(config, "SECRET_PATH", data_dir / "secret.key")
    monkeypatch.setattr(config, "CUSTOM_IMAGES_DIR", data_dir / "custom-images")
    database.configure()
    database.upgrade()
    from mtg_collection.services import login_throttle
    monkeypatch.setattr(login_throttle, "throttle", login_throttle.LoginThrottle())  # tentativas não vazam
    yield data_dir
    database.engine().dispose()


@pytest.fixture
def make_client(tmp_path):
    """Cria um ScryfallClient com respostas simuladas: handler(request) -> httpx.Response."""
    def factory(handler, min_interval=0):
        return ScryfallClient(transport=httpx.MockTransport(handler), min_interval=min_interval, cache_dir=tmp_path)
    return factory


class FakeScryfall:
    """Substitui os métodos do cliente global nos testes de interface. Registra as chamadas."""

    def __init__(self):
        self.cards = {c["id"]: to_card(c) for c in (BOLT, BOLT_REPRINT, DELVER)}
        self.suggest_calls: list[str] = []
        self.prints_pages: list[int] = []
        self.card_calls: list[str] = []
        self.rulings_calls: list[str] = []
        self.search_queries: list[str] = []
        self.sets = (CardSet("m10", "Magic 2010"), CardSet("2xm", "Double Masters"))
        # só aparecem no find_cards e no suggest_where
        self.extra_cards = [to_card(c) for c in (GOLD, LAND, LEGEND, RATS, TYMNA, THRASIOS, LUTRI)]
        self.where_calls: list[tuple[str, str]] = []
        self.find_calls: list[list[dict]] = []
        self.find_error = False

    async def search(self, query: str, page: int = 1, **options) -> SearchResult:
        self.search_queries.append(query)
        if query == "erro":
            raise ScryfallError("Sintaxe inválida")
        if query == "nada":
            return SearchResult.empty()
        return SearchResult(cards=(self.cards["1"],), total=200, has_more=page == 1)

    async def suggest(self, text: str, limit: int = 8):
        self.suggest_calls.append(text)
        return (self.cards["1"], self.cards["2"]) if "e" in text.lower() or "bo" in text.lower() else ()

    async def get_card(self, card_id: str):
        self.card_calls.append(card_id)
        if card_id not in self.cards:
            raise ScryfallError("No card found with the given ID")
        return self.cards[card_id]

    async def get_prints(self, oracle_id: str, page: int = 1) -> SearchResult:
        self.prints_pages.append(page)
        prints = tuple(c for c in self.cards.values() if c.oracle_id == oracle_id)
        if page == 1:
            return SearchResult(cards=prints, total=len(prints) + 1, has_more=True)
        return SearchResult(cards=(self.cards["1"],), total=len(prints) + 1, has_more=False)

    async def get_sets(self):
        return self.sets

    async def get_type_catalogs(self):
        return {"card-types": ("Artifact", "Creature"), "supertypes": ("Legendary",),
                "creature-types": ("Dragon", "Human", "Time Lord"), "artifact-types": ("Equipment",)}

    async def suggest_where(self, text: str, query: str, limit: int = 8):
        """Ignora a sintaxe do filtro: devolve as cartas cujo nome contém o texto (o teste confere a consulta)."""
        self.where_calls.append((text, query))
        known = [*self.cards.values(), *self.extra_cards]
        return tuple(c for c in known if text.lower() in c.name.lower())[:limit]

    async def find_cards(self, identifiers: list[dict]):
        self.find_calls.append(identifiers)
        if self.find_error:
            raise ScryfallError("Falha de conexão com o Scryfall")
        known = [*self.cards.values(), *self.extra_cards]
        return [_match_identifier(identifier, known) for identifier in identifiers]

    async def get_rulings(self, card_id: str):
        self.rulings_calls.append(card_id)
        return to_rulings(RULINGS) if card_id == "1" else ()

    async def random_card(self):
        return self.cards["2"]


@pytest.fixture
def fake_api(monkeypatch) -> FakeScryfall:
    fake = FakeScryfall()
    for name in ("search", "suggest", "get_card", "get_prints", "get_rulings", "get_sets", "get_type_catalogs",
                 "find_cards", "suggest_where", "random_card"):
        monkeypatch.setattr(scryfall.client, name, getattr(fake, name))
    monkeypatch.setattr(card_search_input, "DEBOUNCE_SECONDS", 0.05)
    return fake


TEST_PASSWORD = "senha-de-teste-1"


def create_account(username: str = "marcelo", password: str = TEST_PASSWORD, display_name: str = "") -> None:
    """Cria a conta direto no banco (a primeira vira admin; as seguintes usam o convite atual)."""
    with database.session() as s:
        code = accounts.invite_code(s) if accounts.has_users(s) else ""
        accounts.register(s, username, password, display_name, code)


async def login(user: User, username: str = "marcelo", password: str = TEST_PASSWORD) -> None:
    """Entra pela tela de login, como uma pessoa faria."""
    await user.open("/login")
    user.find(marker="login-username").type(username)
    user.find(marker="login-password").type(password)
    user.find(marker="login-submit").click()
    await user.should_see(marker="user-menu", retries=30)  # argon2 é lento de propósito


@pytest.fixture
async def user(user: User, request, monkeypatch) -> User:
    """Sobrescreve a fixture do NiceGUI: o usuário simulado já entra logado.
    Testes marcados com @pytest.mark.anonymous começam deslogados e sem contas."""
    from mtg_collection.ui.pages import login as login_page
    monkeypatch.setattr(login_page, "FAILED_LOGIN_DELAY", 0)
    if request.node.get_closest_marker("anonymous") is None:
        create_account(display_name="Marcelo")
        await login(user)
    return user
