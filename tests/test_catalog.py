import json

import httpx
import pytest

from mtg_collection.services import catalog
from mtg_collection.services.catalog import Catalog, build, fold
from tests.sample_cards import BOLT, BOLT_REPRINT, DELVER, GOLD, LAND

PROMO_BOLT = {**BOLT, "id": "1p", "set": "plst", "released_at": "2030-01-01", "promo": True, "games": ["paper"]}
DIGITAL_BOLT = {**BOLT, "id": "1d", "set": "prm", "released_at": "2031-01-01", "digital": True, "games": ["mtgo"]}
LIM_DUL = {**GOLD, "id": "9", "oracle_id": "o-limdul", "name": "Lim-Dûl the Necromancer", "set": "5ed"}
TOKEN = {**LAND, "id": "t1", "oracle_id": "o-token", "name": "Goblin", "layout": "token"}
CARDS = [{**BOLT, "games": ["paper"]}, {**BOLT_REPRINT, "games": ["paper"]}, PROMO_BOLT, DIGITAL_BOLT, DELVER, GOLD,
         LAND, LIM_DUL, TOKEN]


def make_catalog(tmp_path, cards=CARDS, updated="2026-10-27T10:00:00+00:00") -> Catalog:
    source = tmp_path / "default-cards.json"
    source.write_text(json.dumps(cards))
    path = tmp_path / "catalogo.db"
    assert build(source, path, updated) == len(cards) - 1  # o token fica de fora
    return Catalog(path)


def test_fold():
    assert fold("Lim-Dûl") == "lim-dul" and fold("Æther Vial") == "aether vial"


def test_lookups(tmp_path):
    cat = make_catalog(tmp_path)
    assert cat.ready and cat.updated_at() == "2026-10-27T10:00:00+00:00" and cat.count() == 8
    assert cat.get("1b").set_code == "2XM" and cat.get("nada") is None
    # impressão padrão: de papel, não promo, a mais recente (o 2XM; o promo e o digital são mais novos mas não valem)
    assert cat.find({"name": "lightning bolt"}).id == "1b"
    assert cat.find({"oracle_id": "o-bolt"}).id == "1b"
    assert cat.find({"name": "Lightning Bolt", "set": "M10"}).id == "1"
    assert cat.find({"set": "m10", "collector_number": "146"}).id == "1"
    assert cat.find({"name": "Delver of Secrets"}).id == "2"  # nome da frente da dupla face
    assert cat.find({"name": "lim-dul the necromancer"}).id == "9"  # sem acento
    assert cat.find({"name": "Não existe"}) is None
    assert [c.id for c in cat.prints("o-bolt")] == ["1d", "1p", "1b", "1"]  # mais recente primeiro


def test_suggest(tmp_path):
    cat = make_catalog(tmp_path)
    # todas começam com "li": as mais curtas primeiro
    assert [c.name for c in cat.suggest("li")] == ["Lightning Bolt", "Lightning Helix", "Lim-Dûl the Necromancer"]
    names = [c.name for c in cat.suggest("bolt")]
    assert names == ["Lightning Bolt"]  # uma por carta, não uma por impressão
    assert [c.name for c in cat.suggest("lim-dûl")] == ["Lim-Dûl the Necromancer"]
    assert cat.suggest("x") == [] and cat.suggest("%_") == []


def test_prefix_comes_first(tmp_path):
    cards = [{**GOLD, "id": "a", "oracle_id": "o-a", "name": "Burning Bolt"},
             {**GOLD, "id": "b", "oracle_id": "o-b", "name": "Bolt Bend"}]
    cat = make_catalog(tmp_path, cards + [TOKEN])
    assert [c.name for c in cat.suggest("bolt")] == ["Bolt Bend", "Burning Bolt"]


async def test_update_downloads_only_when_newer(tmp_path, make_client):
    calls = []
    payload = json.dumps(CARDS).encode()

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/bulk-data/all_cards":
            return httpx.Response(200, json={"updated_at": "2026-10-27T10:07:00+00:00",
                                             "download_uri": "https://data.scryfall.io/default-cards/x.json"})
        return httpx.Response(200, content=payload)

    client = make_client(handler)
    cat = Catalog(tmp_path / "cache" / "catalogo.db")
    assert await catalog.update(client, cat) is True
    assert cat.count() == 8 and cat.updated_at() == "2026-10-27T10:07:00+00:00"
    assert await catalog.update(client, cat) is False  # mesma data: não baixa de novo
    assert calls == ["/bulk-data/all_cards", "/default-cards/x.json", "/bulk-data/all_cards"]
    assert sorted(p.name for p in (tmp_path / "cache").iterdir()) == ["catalogo.db"]  # sem arquivos temporários


async def test_client_reads_local_first(tmp_path, make_client):
    requests = []

    def handler(request):
        requests.append(request.url.path)
        body = json.loads(request.content) if request.content else {}
        return httpx.Response(200, json={"data": [DELVER] if body else [], "not_found": []})

    client = make_client(handler)
    client.catalog = make_catalog(tmp_path, [c for c in CARDS if c is not DELVER])
    assert [c.name for c in await client.suggest("light")] == ["Lightning Bolt", "Lightning Helix"]
    assert (await client.get_card("1")).set_code == "M10"
    assert len((await client.get_prints("o-bolt")).cards) == 4
    found = await client.find_cards([{"name": "Lightning Bolt"}, {"name": "Delver of Secrets"}])
    assert [c.id for c in found] == ["1b", "2"]
    assert requests == ["/cards/collection"]  # só o Delver, que não está na cópia local, foi à API


async def test_update_finds_link_in_listing(tmp_path, make_client):
    payload = json.dumps(CARDS).encode()

    def handler(request):
        if request.url.path == "/bulk-data/all_cards":
            return httpx.Response(200, json={"updated_at": "2026-10-27T09:05:57+00:00"})
        if request.url.path == "/bulk-data":
            return httpx.Response(200, json={"data": [
                {"type": "oracle_cards", "download_uri": "https://data.scryfall.io/oracle/x.json"},
                {"type": "all_cards", "download_uri": "https://data.scryfall.io/default-cards/y.json"}]})
        assert request.url.path == "/default-cards/y.json"
        return httpx.Response(200, content=payload)

    cat = Catalog(tmp_path / "catalogo.db")
    assert await catalog.update(make_client(handler), cat) is True and cat.count() == 8


async def test_update_without_link_says_which_fields(tmp_path, make_client):
    def handler(request):
        if request.url.path == "/bulk-data":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, json={"updated_at": "x", "uri": "y"})

    with pytest.raises(RuntimeError, match="updated_at"):
        await catalog.update(make_client(handler), Catalog(tmp_path / "catalogo.db"))
    assert not (tmp_path / "catalogo.db").exists()


@pytest.mark.parametrize("kind", ["jsonl.gz", "jsonl", "json.gz"])
def test_build_reads_gzip_and_jsonl(tmp_path, kind):
    import gzip
    text = "\n".join(json.dumps(card) for card in CARDS) + "\n" if "jsonl" in kind else json.dumps(CARDS, indent=1)
    raw = text.encode()
    path = tmp_path / f"cards.{kind}"
    path.write_bytes(gzip.compress(raw) if kind.endswith(".gz") else raw)
    assert catalog.build(path, tmp_path / "c.db", "x") == 8
    assert Catalog(tmp_path / "c.db").find({"name": "Delver of Secrets"}) is not None


async def test_stalled_download_gives_up_and_cleans_up(tmp_path, make_client, monkeypatch):
    """Conexão que para de mandar dados: desiste (em vez de esperar para sempre) e não deixa arquivo pela metade."""
    def handler(request):
        if request.url.path == "/bulk-data/all_cards":
            return httpx.Response(200, json={"updated_at": "x", "download_uri": "https://data.scryfall.io/y.json"})
        assert request.extensions["timeout"]["read"] == catalog.DOWNLOAD_TIMEOUT.read  # tem limite de espera
        raise httpx.ReadTimeout("parou de responder", request=request)

    cat = Catalog(tmp_path / "cache" / "catalogo.db")
    with pytest.raises(httpx.ReadTimeout):
        await catalog.update(make_client(handler), cat)
    assert not cat.ready and list((tmp_path / "cache").iterdir()) == []


PT_BOLT = {**BOLT, "id": "1-pt", "lang": "pt", "printed_name": "Relâmpago", "printed_type_line": "Mágica Instantânea",
           "printed_text": "Relâmpago causa 3 pontos de dano a qualquer alvo.", "games": ["paper"]}
DE_BOLT = {**BOLT, "id": "1-de", "lang": "de", "printed_name": "Blitzschlag", "games": ["paper"]}
JA_ONLY = {**LAND, "id": "ja1", "oracle_id": "o-ja", "name": "Promo Japonesa", "set": "pjp", "collector_number": "1★",
           "lang": "ja"}
KO_SAME = {**JA_ONLY, "id": "ko1", "lang": "ko"}  # mesma edição e número, outro idioma: só a primeira fica


@pytest.mark.parametrize("jsonl", [True, False])
def test_keeps_english_portuguese_and_single_language(tmp_path, jsonl):
    cards = [PT_BOLT, DE_BOLT, *CARDS, JA_ONLY, KO_SAME]  # a versão PT vem antes da inglesa no arquivo
    source = tmp_path / "all-cards.json"
    source.write_text("\n".join(json.dumps(c) for c in cards) if jsonl else json.dumps(cards))
    assert build(source, tmp_path / "c.db", "x") == len(CARDS) - 1 + 2  # + PT e a japonesa; sem alemão e coreano
    cat = Catalog(tmp_path / "c.db")
    assert cat.ready
    assert {c.lang for c in cat.prints("o-bolt")} == {"en", "pt"}
    assert cat.find({"set": "m10", "collector_number": "146"}).lang == "en"  # PT tem o mesmo número
    assert cat.find({"name": "Lightning Bolt", "set": "m10"}).lang == "en"
    assert all(c.lang == "en" for c in cat.suggest("bolt"))
    pt = cat.get("1-pt")
    assert (pt.display_name, pt.name, pt.faces[0].printed_text.startswith("Relâmpago")) == \
        ("Relâmpago", "Lightning Bolt", True)
    assert cat.find({"oracle_id": "o-ja"}).id == "ja1"


def test_old_default_cards_copy_is_ignored_until_rebuilt(tmp_path):
    cat = make_catalog(tmp_path)
    import sqlite3
    with sqlite3.connect(cat.path) as db:  # cópia montada antes, do "Default Cards"
        db.execute("UPDATE meta SET value = 'default_cards' WHERE key = 'bulk_type'")
    cat = Catalog(cat.path)
    assert not cat.ready and cat.updated_at() is None  # cliente usa a API e o próximo update baixa de novo


def test_portuguese_names_in_suggestions_and_search(tmp_path):
    cards = [*CARDS, PT_BOLT, {**PT_BOLT, "id": "1-pt-old", "set": "4ed", "released_at": "1995-01-01"}]
    source = tmp_path / "all.json"
    source.write_text(json.dumps(cards))
    build(source, tmp_path / "c.db", "x")
    cat = Catalog(tmp_path / "c.db")
    [suggestion] = cat.suggest("relamp")  # sem acento também acha; uma sugestão por carta
    assert (suggestion.id, suggestion.display_name) == ("1-pt", "Relâmpago")  # a impressão PT mais recente
    assert [c.name for c in cat.suggest("bolt")][0] == "Lightning Bolt"  # em inglês continua igual
    assert [c.id for c in cat.search_printed("relâmpago")] == ["1-pt"]
    assert cat.search_printed("raio") == []


async def test_search_puts_portuguese_matches_first(tmp_path, make_client):
    def handler(request):
        if request.url.params["q"] == "relampago":
            return httpx.Response(404, json={"object": "error", "details": "no cards"})
        return httpx.Response(200, json={"data": [GOLD], "total_cards": 1, "has_more": False})

    client = make_client(handler)
    source = tmp_path / "all.json"
    source.write_text(json.dumps([*CARDS, PT_BOLT]))
    build(source, tmp_path / "c.db", "x")
    client.catalog = Catalog(tmp_path / "c.db")
    result = await client.search("relampago")  # o Scryfall não acha nada pelo nome em português
    assert [c.display_name for c in result.cards] == ["Relâmpago"] and result.total == 1
    result = await client.search("relâmpago t:instant")  # com sintaxe: só a API
    assert [c.name for c in result.cards] == ["Lightning Helix"]
