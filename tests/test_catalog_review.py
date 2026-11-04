"""Correções da revisão do catálogo local (services/catalog.py) e do uso dele no cliente do Scryfall."""
import asyncio
import json
import random
import sqlite3
import threading
from collections import Counter
from pathlib import PureWindowsPath

import httpx
import pytest

from mtg_collection.services import catalog
from mtg_collection.services.catalog import Catalog, build
from mtg_collection.services.scryfall import ScryfallError
from tests.sample_cards import BOLT, GOLD, LAND
from tests.test_catalog import CARDS, PT_BOLT


def make(tmp_path, cards, name="c.db") -> Catalog:
    source = tmp_path / "all.json"
    source.write_text(json.dumps(cards))
    build(source, tmp_path / name, "2026-10-27T10:00:00+00:00")
    return Catalog(tmp_path / name)


def card(card_id, name, **extra):
    return {**GOLD, "id": card_id, "oracle_id": f"o-{card_id}", "name": name, "collector_number": card_id, **extra}


# 1. arquivo estragado
@pytest.mark.parametrize("content", [b"", b"isto nao e um banco" * 100])
async def test_damaged_file_is_not_ready_and_update_rebuilds(tmp_path, make_client, content):
    path = tmp_path / "catalogo.db"
    path.write_bytes(content)
    cat = Catalog(path)
    assert not cat.ready and cat.updated_at() is None

    def handler(request):
        if request.url.path == "/bulk-data/all_cards":
            return httpx.Response(200, json={"updated_at": "u1", "download_uri": "https://data.scryfall.io/a.json"})
        if request.url.path == "/cards/1":
            return httpx.Response(200, json=BOLT)
        return httpx.Response(200, content=json.dumps(CARDS).encode())

    client = make_client(handler)
    client.catalog = cat
    assert (await client.get_card("1")).id == "1"  # vai à API em vez de quebrar
    assert await catalog.update(client, cat) is True
    assert cat.ready and cat.updated_at() == "u1" and cat.count() == 8


# 2. consultas locais fora do loop
async def test_client_runs_local_queries_in_a_thread(tmp_path, make_client):
    loop_thread = threading.get_ident()
    threads = []

    class Spy(Catalog):
        def _query(self, sql, params=()):
            threads.append(threading.get_ident())
            return super()._query(sql, params)

    base = make(tmp_path, [*CARDS, PT_BOLT])
    client = make_client(lambda r: httpx.Response(200, json={"data": [], "total_cards": 0, "has_more": False}))
    client.catalog = Spy(base.path)
    assert client.catalog.ready
    threads.clear()
    await client.suggest("light")
    await client.get_card("1")
    await client.get_prints("o-bolt")
    await client.find_cards([{"name": "Lightning Bolt"}])
    await client.random_card()
    await client.search("relampago")
    assert threads and loop_thread not in threads


# 3. buscas "contém" só pelo índice
def test_queries_never_scan_the_table(tmp_path, monkeypatch):
    cat = make(tmp_path, [*CARDS, PT_BOLT])
    seen = []
    original = Catalog._query

    def spy(self, sql, params=()):
        seen.append((sql, tuple(params)))
        return original(self, sql, params)

    monkeypatch.setattr(Catalog, "_query", spy)
    assert [c.id for c in cat.suggest("lampa")] == ["1-pt"]  # "contém" no nome em português
    assert [c.name for c in cat.suggest("ning")] == ["Lightning Bolt", "Lightning Helix"]
    assert [c.id for c in cat.search_printed("lâmp")] == ["1-pt"]
    assert cat.random() is not None
    with sqlite3.connect(cat.path) as db:
        for sql, params in seen:
            plan = " ".join(row[3] for row in db.execute("EXPLAIN QUERY PLAN " + sql, params))
            assert "SCAN cards" not in plan, (sql, plan)
            # percorrer todas as cartas padrão lendo cada linha também é lento (só vale pelo índice, "COVERING")
            assert "USING INDEX ix_default (is_default=?)" not in plan, (sql, plan)


# 4. caminho com caracteres especiais
def test_path_with_special_characters(tmp_path):
    folder = tmp_path / "a#b%41?"
    folder.mkdir()
    cat = make(folder, CARDS)
    assert cat.ready and cat.get("1").id == "1"


def test_readonly_uri_on_windows():
    assert catalog._readonly_uri(PureWindowsPath("C:/Users/João Silva/a#b/c.db")) == \
        "file:///C:/Users/Jo%C3%A3o%20Silva/a%23b/c.db?mode=ro"


# 5. busca com resultados em português
def _pt_client(tmp_path, make_client, handler):
    client = make_client(handler)
    client.catalog = make(tmp_path, [*CARDS, PT_BOLT])
    return client


async def test_search_dedupes_portuguese_and_api(tmp_path, make_client):
    client = _pt_client(tmp_path, make_client, lambda r: httpx.Response(
        200, json={"data": [BOLT, GOLD], "total_cards": 30, "has_more": True}))
    result = await client.search("relampago")
    assert [c.id for c in result.cards] == ["1-pt", "3"]  # o Bolt em inglês não repete
    assert result.total == 30 and result.has_more


async def test_search_keeps_portuguese_when_api_fails(tmp_path, make_client):
    client = _pt_client(tmp_path, make_client, lambda r: httpx.Response(500, json={"details": "fora do ar"}))
    result = await client.search("relampago")
    assert [c.id for c in result.cards] == ["1-pt"] and result.total == 1
    with pytest.raises(ScryfallError, match="fora do ar"):  # sem nada em português, o erro continua
        await client.search("bolt")


# 6 e 7. idiomas guardados e nomes em português
def test_portuguese_key_blocks_other_languages_and_only_pt_is_searchable(tmp_path):
    pt_only = {**LAND, "id": "p1", "oracle_id": "o-p", "name": "Promo PT", "set": "pxx", "collector_number": "7",
               "lang": "pt", "printed_name": "Promoção"}
    ja_same = {**pt_only, "id": "j1", "lang": "ja", "printed_name": "Rarojapa"}
    ja_alone = {**pt_only, "id": "j2", "oracle_id": "o-j", "name": "Japan Only", "collector_number": "8",
                "lang": "ja", "printed_name": "Rarojapa"}
    cat = make(tmp_path, [ja_same, pt_only, ja_alone, *CARDS])
    assert cat.get("j1") is None and cat.get("p1") and cat.get("j2")  # a japonesa só fica se não houver en nem pt
    assert cat.search_printed("rarojapa") == [] and cat.suggest("rarojapa") == []
    assert [c.id for c in cat.suggest("promoc")] == ["p1"]


def test_schema_bump_rebuilds_old_copies(tmp_path):
    cat = make(tmp_path, CARDS)
    with sqlite3.connect(cat.path) as db:
        db.execute("UPDATE meta SET value = '2' WHERE key = 'schema'")
    assert catalog.SCHEMA_VERSION != "2" and not Catalog(cat.path).ready


# 8. nome exato primeiro
def test_exact_name_comes_first(tmp_path):
    cards = [card("fi", "Fire // Ice"), card("fb", "Fireball"), *(card(f"f{i}", f"Fire{i}") for i in range(9)),
             {**PT_BOLT, "id": "pt1", "printed_name": "Fogoso"},
             {**GOLD, "id": "pt2", "lang": "pt", "printed_name": "Fogo // Gelo"}]
    cat = make(tmp_path, cards)
    assert [c.name for c in cat.suggest("fire")][:2] == ["Fire // Ice", "Fire0"]
    assert [c.display_name for c in cat.suggest("fogo")] == ["Fogo // Gelo", "Fogoso"]


# 9. impressão que representa a carta
def test_default_print_skips_alternate_treatments(tmp_path):
    regular = {**BOLT, "games": ["paper"], "released_at": "2020-01-01", "frame_effects": ["legendary"]}
    newer = {**regular, "released_at": "2025-01-01"}
    odd = [{**newer, "id": "v", "variation": True}, {**newer, "id": "b", "border_color": "borderless"},
           {**newer, "id": "s", "frame_effects": ["showcase"]}, {**newer, "id": "f", "full_art": True},
           {**newer, "id": "o", "oversized": True}, {**newer, "id": "u", "set_type": "funny"}]
    for alternate in odd:
        cat = make(tmp_path, [regular, alternate], f"{alternate['id']}.db")
        assert cat.find({"name": "Lightning Bolt"}).id == "1", alternate["id"]
    lands = [{**LAND, "games": ["paper"], "released_at": "2015-01-01"},
             {**LAND, "id": "4f", "games": ["paper"], "released_at": "2024-01-01", "full_art": True}]
    assert make(tmp_path, lands, "land.db").find({"name": "Wastes"}).id == "4f"  # básico de arte inteira vale


@pytest.mark.parametrize("order", [1, -1])
def test_collector_number_breaks_ties(tmp_path, order):
    prints = [{**BOLT, "id": "n10", "collector_number": "10"}, {**BOLT, "id": "n2", "collector_number": "2"}]
    assert make(tmp_path, prints[::order]).find({"name": "Lightning Bolt"}).id == "n2"


# 10. sorteio uniforme
def test_random_is_uniform(tmp_path, monkeypatch):
    many = [{**BOLT, "id": f"r{i}", "collector_number": str(i), "released_at": "1990-01-01"} for i in range(40)]
    cat = make(tmp_path, [GOLD, *many, LAND, BOLT])  # o Wastes vem logo depois de um buraco de 40 linhas
    monkeypatch.setattr(catalog.random, "randrange", random.Random(0).randrange)
    counts = Counter(cat.random().id for _ in range(3000))
    assert set(counts) == {"1", "3", "4"} and all(800 < n < 1200 for n in counts.values()), counts


# 11. nova tentativa mais cedo depois de uma falha
async def test_keep_updated_retries_sooner_after_failure(tmp_path, monkeypatch):
    results = iter([RuntimeError("offline"), False])
    delays = []

    async def fake_update(client, cat):
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    async def fake_sleep(seconds):
        delays.append(seconds)
        if len(delays) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(catalog, "update", fake_update)
    monkeypatch.setattr(catalog.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await catalog.keep_updated(None, Catalog(tmp_path / "c.db"))
    assert delays == [catalog.RETRY_MINUTES * 60, catalog.CHECK_HOURS * 3600]


# 12. troca do arquivo fora do loop e sem estragar o atual
async def test_replace_runs_in_thread_and_failure_keeps_current(tmp_path, make_client, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    cat = make(cache, CARDS, "catalogo.db")
    (cache / "all.json").unlink()
    threads = []

    def locked(source, target, attempts=25):
        threads.append(threading.get_ident())
        raise PermissionError("arquivo em uso")

    monkeypatch.setattr(catalog, "_replace", locked)

    def handler(request):
        if request.url.path == "/bulk-data/all_cards":
            return httpx.Response(200, json={"updated_at": "novo", "download_uri": "https://data.scryfall.io/a.json"})
        return httpx.Response(200, content=json.dumps(CARDS).encode())

    with pytest.raises(PermissionError):
        await catalog.update(make_client(handler), cat)
    assert threads and threading.get_ident() not in threads
    assert cat.ready and cat.updated_at() == "2026-10-27T10:00:00+00:00"  # o atual continua valendo
    assert [p.name for p in cache.iterdir()] == ["catalogo.db"]  # sem arquivos temporários
