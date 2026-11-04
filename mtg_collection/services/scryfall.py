"""Cliente assíncrono da API do Scryfall.

Reaproveita a conexão HTTP e respeita o intervalo mínimo entre requisições.
Converte o JSON do Scryfall para os modelos do app, então o resto do código
nunca lida com o formato da API diretamente.
"""
import asyncio
import re
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

from mtg_collection import config
from mtg_collection.models import Card, CardFace, CardSet, Prices, Ruling, SearchResult


class ScryfallError(Exception):
    pass


COLLECTION_BATCH = 75  # limite do /cards/collection

# Catálogos de tipos do Scryfall, na ordem em que aparecem no seletor
TYPE_CATALOGS = ("card-types", "supertypes", "artifact-types", "battle-types", "creature-types",
                 "enchantment-types", "land-types", "planeswalker-types", "spell-types")
# Reserva caso /catalog/card-types não responda: o seletor nunca fica sem os tipos principais
DEFAULT_CARD_TYPES = ("Artifact", "Battle", "Conspiracy", "Creature", "Dungeon", "Emblem", "Enchantment", "Hero",
                      "Instant", "Kindred", "Land", "Phenomenon", "Plane", "Planeswalker", "Scheme", "Sorcery",
                      "Tribal", "Vanguard")


class ScryfallClient:
    """Cliente compartilhado pelo app inteiro. Um lock espaça as chamadas à API no intervalo mínimo
    pedido pelo Scryfall; edições e catálogos de tipos ficam em memória depois da primeira busca.
    `transport` existe para os testes trocarem a rede por respostas falsas."""

    def __init__(
        self,
        base_url: str = config.SCRYFALL_BASE_URL,
        min_interval: float = config.SCRYFALL_MIN_INTERVAL,
        transport: httpx.AsyncBaseTransport | None = None,
        cache_dir: Path = config.CACHE_DIR,
    ):
        self._base_url = base_url
        self._min_interval = min_interval
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._cache_dir = cache_dir
        self._sets: tuple[CardSet, ...] | None = None
        self._sets_lock = asyncio.Lock()
        self._type_catalogs: dict[str, tuple[str, ...]] | None = None
        self._catalogs_lock = asyncio.Lock()
        # cópia local das cartas (services/catalog.py). Com ela, sugestões, cartas e impressões são lidas daqui
        # e só o que faltar vai à API. O main() liga; sem ela (testes, primeiro uso) tudo vai à API.
        # As consultas nela rodam numa thread (asyncio.to_thread) para não travar o loop da interface.
        self.catalog = None

    def _local(self):
        return self.catalog if self.catalog is not None and self.catalog.ready else None

    @property
    def http(self) -> httpx.AsyncClient:
        # Criado sob demanda para nascer dentro do event loop em uso
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={"User-Agent": config.SCRYFALL_USER_AGENT, "Accept": "application/json"},
                timeout=config.HTTP_TIMEOUT,
                transport=self._transport,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def search(self, query: str, page: int = 1, **options) -> SearchResult:
        """Busca com a sintaxe completa do Scryfall (até 175 cartas por página).
        `options` vai direto para a API (ex: unique="prints", order="released", dir="desc")."""
        # Nome em português ("raio"): o Scryfall só procura nomes em inglês. A cópia local tem os nomes impressos das
        # cartas em português; elas vêm primeiro (uma impressão PT por carta) e o resultado da API depois.
        # Uma carta que aparece nas duas listas fica só na portuguesa (e sai da conta do total). Se a API falhar,
        # o que achou em português ainda serve.
        portuguese = []
        if page == 1 and not options and _plain_text(query) and (local := self._local()):
            portuguese = await asyncio.to_thread(local.search_printed, query)
        try:
            response = await self._get("/cards/search", q=query, page=page, **options)
            if response.status_code == 404:  # o Scryfall responde 404 quando nada é encontrado
                return SearchResult(cards=tuple(portuguese), total=len(portuguese), has_more=False)
            data = self._json(response)
        except ScryfallError:
            if not portuguese:
                raise
            return SearchResult(cards=tuple(portuguese), total=len(portuguese), has_more=False)
        seen = {card.oracle_id for card in portuguese}
        cards = [to_card(c) for c in data["data"]]
        api_cards = [card for card in cards if card.oracle_id not in seen]
        return SearchResult(
            cards=(*portuguese, *api_cards),
            total=data.get("total_cards", 0) - (len(cards) - len(api_cards)) + len(portuguese),
            has_more=data.get("has_more", False),
        )

    async def find_cards(self, identifiers: list[dict]) -> list[Card | None]:
        """Várias cartas de uma vez pelo /cards/collection (até 75 por requisição).
        Identificadores: {"name"}, {"name", "set"}, {"set", "collector_number"}, {"oracle_id"} ou {"id"}.
        Devolve uma carta (ou None se não achou) para cada identificador, na mesma ordem."""
        results: list[Card | None] = [None] * len(identifiers)
        pending = list(range(len(identifiers)))
        if local := self._local():
            found = await asyncio.to_thread(lambda: [local.find(identifiers[i]) for i in pending])
            for i, card in zip(pending, found, strict=True):
                results[i] = card
            pending = [i for i in pending if results[i] is None]  # o que não está na cópia local vai à API
        for start in range(0, len(pending), COLLECTION_BATCH):
            batch = pending[start:start + COLLECTION_BATCH]
            body = {"identifiers": [identifiers[i] for i in batch]}
            data = self._json(await self._request("POST", "/cards/collection", json=body))
            found = [to_card(c) for c in data["data"]]
            for i in batch:
                results[i] = _match_identifier(identifiers[i], found)
        return results

    async def get_card(self, card_id: str) -> Card:
        if (local := self._local()) and (card := await asyncio.to_thread(local.get, card_id)):
            return card
        return to_card(self._json(await self._get(f"/cards/{card_id}")))

    async def random_card(self) -> Card:
        """Uma carta qualquer (o "Carta aleatória" da página inicial)."""
        if (local := self._local()) and (card := await asyncio.to_thread(local.random)):
            return card
        return to_card(self._json(await self._get("/cards/random")))

    async def get_prints(self, oracle_id: str, page: int = 1) -> SearchResult:
        """Todas as impressões da carta, da mais recente para a mais antiga."""
        if page == 1 and (local := self._local()) and (prints := await asyncio.to_thread(local.prints, oracle_id)):
            return SearchResult(cards=tuple(prints), total=len(prints), has_more=False)
        return await self.search(f"oracleid:{oracle_id}", page, unique="prints", order="released", dir="desc",
                                 include_extras="true", include_variations="true")

    async def get_rulings(self, card_id: str) -> tuple[Ruling, ...]:
        return to_rulings(self._json(await self._get(f"/cards/{card_id}/rulings")))

    async def suggest_where(self, text: str, query: str, limit: int = 8) -> tuple[Card, ...]:
        """Sugestões de cartas para o texto digitado, só entre as que atendem a `query` (sintaxe do Scryfall,
        ex: "is:commander"). Uma requisição; as mais jogadas primeiro."""
        words = " ".join(re.sub(r"[^\w\s'’-]", " ", text).split())
        if len(words) < 2:
            return ()
        result = await self.search(f"({query}) {words}", order="edhrec")
        return result.cards[:limit]

    async def suggest(self, text: str, limit: int = 8) -> tuple[Card, ...]:
        """Sugestões de cartas para o texto digitado, com imagem. Usa 2 requisições leves:
        /cards/autocomplete (só nomes) e /cards/collection (dados de até 75 cartas de uma vez)."""
        if len(text.strip()) < 2:  # o Scryfall não sugere nada abaixo de 2 caracteres
            return ()
        if local := self._local():
            return tuple(await asyncio.to_thread(local.suggest, text, limit))
        names = self._json(await self._request("GET", "/cards/autocomplete", params={"q": text}))["data"][:limit]
        if not names:
            return ()
        body = {"identifiers": [{"name": name} for name in names]}
        cards = [to_card(c) for c in self._json(await self._request("POST", "/cards/collection", json=body))["data"]]
        # Mapeia por nome (e pela face da frente, em cartas dupla face) para manter a ordem do autocomplete
        by_name = {}
        for card in cards:
            by_name.setdefault(card.name, card)
            by_name.setdefault(card.name.split(" // ")[0], card)
        return tuple(by_name[name] for name in names if name in by_name)

    async def get_type_catalogs(self) -> dict[str, tuple[str, ...]]:
        """Listas de tipos (catálogo -> nomes). Um catálogo que falhar fica vazio em vez de derrubar tudo.
        Só guarda em memória se ao menos um respondeu, para não fixar uma lista vazia se estiver offline."""
        async with self._catalogs_lock:
            if self._type_catalogs is not None:
                return self._type_catalogs
            catalogs: dict[str, tuple[str, ...]] = {}
            for key in TYPE_CATALOGS:
                try:
                    catalogs[key] = tuple(self._json(await self._get(f"/catalog/{key}"))["data"])
                except (ScryfallError, KeyError):
                    catalogs[key] = ()
            loaded_any = any(catalogs.values())
            catalogs["card-types"] = catalogs["card-types"] or DEFAULT_CARD_TYPES
            if loaded_any:
                self._type_catalogs = catalogs
            return catalogs

    async def get_set_icon(self, code: str) -> bytes | None:
        """SVG do símbolo da coleção. Baixa uma vez e guarda em disco, como o Scryfall recomenda."""
        code = code.lower()
        cached = self._cache_dir / "set-icons" / f"{code}.svg"
        if cached.exists():
            return cached.read_bytes()
        uri = next((s.icon_svg_uri for s in await self.get_sets() if s.code == code), None)
        if not uri:
            return None
        response = await self._request("GET", uri)
        if response.status_code != 200:
            return None
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(response.content)
        return response.content

    async def get_sets(self) -> tuple[CardSet, ...]:
        """Todas as edições, da mais nova para a mais antiga. Busca uma vez por execução e guarda em memória.
        Edições promocionais já trazem o símbolo da edição principal em icon_svg_uri."""
        async with self._sets_lock:  # várias telas e imagens pedem ao mesmo tempo; busca /sets uma vez só
            if self._sets is None:
                self._sets = tuple(to_set(s) for s in self._json(await self._get("/sets"))["data"])
        return self._sets

    async def _get(self, path: str, **params) -> httpx.Response:
        return await self._request("GET", path, params=params)

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if not path.startswith("http"):  # só a API tem limite; os arquivos em *.scryfall.io não
            async with self._lock:
                wait = self._min_interval - (time.monotonic() - self._last_request)
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last_request = time.monotonic()
        try:
            return await self.http.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise ScryfallError(f"Falha de conexão com o Scryfall: {e}") from e

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        try:
            data = response.json()
        except ValueError:
            raise ScryfallError(f"Resposta inválida do Scryfall (HTTP {response.status_code})") from None
        if response.status_code != 200:
            raise ScryfallError(data.get("details") or f"Erro {response.status_code} no Scryfall")
        return data


def _plain_text(query: str) -> bool:
    """Texto simples (só palavras), sem a sintaxe de busca do Scryfall (t:dragon, "frase", -palavra...)."""
    return bool(query.strip()) and not any(c in query for c in ':<>=!"()') and not query.strip().startswith("-")


def to_card(data: dict) -> Card:
    """Converte o JSON de uma carta do Scryfall. Cartas de várias faces não têm custo nem texto no topo, então
    vêm da primeira face (texto: todas, separadas por "//"). Os campos de Prices têm o nome das chaves do Scryfall."""
    raw_faces = data.get("card_faces") or [data]
    faces = tuple(_to_face(face, data) for face in raw_faces)
    prices = data.get("prices") or {}
    released = data.get("released_at")
    return Card(
        id=data["id"],
        name=data["name"],
        set_code=data.get("set", "").upper(),
        set_name=data.get("set_name", ""),
        collector_number=data.get("collector_number", ""),
        rarity=data.get("rarity", ""),
        type_line=data.get("type_line", ""),
        mana_cost=data.get("mana_cost") or faces[0].mana_cost,
        oracle_text=data.get("oracle_text") or "\n//\n".join(f.oracle_text for f in faces),
        oracle_id=data.get("oracle_id") or raw_faces[0].get("oracle_id"),
        released_at=date.fromisoformat(released) if released else None,
        artist=data.get("artist", ""),
        lang=data.get("lang", "en"),
        faces=faces,
        legalities=dict(data.get("legalities") or {}),
        finishes=tuple(data.get("finishes") or ()),
        image_small=_image(data, "small"),
        image_normal=_image(data, "normal"),
        image_large=_image(data, "large"),
        prices=Prices(**{key: _decimal(prices.get(key)) for key in Prices.__slots__}),
        scryfall_uri=data.get("scryfall_uri"),
        color_identity=tuple(data.get("color_identity") or ()),
        image_art_crop=_image(data, "art_crop"),
        printed_name=_printed_name(data) if data.get("lang", "en") != "en" else "",
    )


def _printed_name(data: dict) -> str:
    """Nome impresso da carta inteira; nas de duas faces, as faces juntas como no nome em inglês ("A // B")."""
    if data.get("printed_name"):
        return data["printed_name"]
    faces = [face.get("printed_name") for face in data.get("card_faces") or []]
    return " // ".join(faces) if faces and all(faces) else ""


def to_set(data: dict) -> CardSet:
    released = data.get("released_at")
    return CardSet(
        code=data["code"],
        name=data.get("name", data["code"].upper()),
        set_type=data.get("set_type", ""),
        released_at=date.fromisoformat(released) if released else None,
        icon_svg_uri=data.get("icon_svg_uri"),
        digital=data.get("digital", False),
    )


def to_rulings(payload: dict) -> tuple[Ruling, ...]:
    return tuple(
        Ruling(published_at=date.fromisoformat(r["published_at"]), text=r["comment"], source=r.get("source", ""))
        for r in payload["data"]
    )


def _match_identifier(identifier: dict, cards: list[Card]) -> Card | None:
    """Acha, entre as cartas devolvidas, a que corresponde ao identificador (o Scryfall não diz qual é qual)."""
    def same_name(card: Card, name: str) -> bool:
        name = name.strip().lower()
        return name in (card.name.lower(), card.name.split(" // ")[0].lower())

    for card in cards:
        if "id" in identifier and card.id == identifier["id"]:
            return card
        if "oracle_id" in identifier and card.oracle_id == identifier["oracle_id"]:
            return card
        if "collector_number" in identifier and card.set_code.lower() == identifier["set"].lower() \
                and card.collector_number == identifier["collector_number"]:
            return card
        if "name" in identifier and same_name(card, identifier["name"]) and (
                "set" not in identifier or card.set_code.lower() == identifier["set"].lower()):
            return card
    return None


def _to_face(face: dict, card: dict) -> CardFace:
    images = face.get("image_uris") or {}
    return CardFace(
        name=face.get("name", card.get("name", "")),
        mana_cost=face.get("mana_cost", ""),
        type_line=face.get("type_line", ""),
        oracle_text=face.get("oracle_text", ""),
        flavor_text=face.get("flavor_text", ""),
        power=face.get("power"),
        toughness=face.get("toughness"),
        loyalty=face.get("loyalty"),
        defense=face.get("defense"),
        artist=face.get("artist") or card.get("artist", ""),
        image_normal=images.get("normal"),
        image_large=images.get("large"),
        printed_name=face.get("printed_name", "") if card.get("lang", "en") != "en" else "",
        printed_type_line=face.get("printed_type_line", "") if card.get("lang", "en") != "en" else "",
        printed_text=face.get("printed_text", "") if card.get("lang", "en") != "en" else "",
    )


def _image(data: dict, size: str) -> str | None:
    if "image_uris" in data:
        return data["image_uris"].get(size)
    for face in data.get("card_faces") or []:  # cartas dupla face
        if "image_uris" in face:
            return face["image_uris"].get(size)
    return None


def _decimal(value: str | None) -> Decimal | None:
    try:
        return Decimal(value) if value else None
    except InvalidOperation:
        return None


client = ScryfallClient()
