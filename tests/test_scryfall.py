import asyncio
import json
import time
from decimal import Decimal

import httpx
import pytest

from mtg_collection import config
from mtg_collection.services.scryfall import ScryfallClient, ScryfallError, to_card
from tests.sample_cards import BOLT, DELVER, RULINGS


def test_to_card_normal():
    card = to_card(BOLT)
    assert card.name == "Lightning Bolt"
    assert card.set_code == "M10"
    assert card.image_normal == "https://img/bolt-n.jpg"
    assert card.price_usd == Decimal("1.25")
    assert card.price_eur is None


def test_to_card_double_faced():
    card = to_card(DELVER)
    assert card.image_normal == "https://img/d-n.jpg"
    assert card.mana_cost == "{U}"
    assert card.oracle_text.endswith("(Reminder.)\n//\nFlying")


async def test_search_ok_and_headers(make_client):
    seen = {}

    def handler(request):
        seen.update(request.headers, **request.url.params)
        return httpx.Response(200, json={"data": [BOLT, DELVER], "total_cards": 2, "has_more": False})

    result = await make_client(handler).search("bolt", page=2)
    assert result.total == 2 and len(result.cards) == 2
    assert seen["q"] == "bolt" and seen["page"] == "2"
    assert seen["user-agent"] == config.SCRYFALL_USER_AGENT


async def test_search_no_results(make_client):
    client = make_client(lambda r: httpx.Response(404, json={"object": "error", "details": "No cards"}))
    result = await client.search("x")
    assert result.cards == () and result.total == 0


async def test_search_api_error(make_client):
    client = make_client(lambda r: httpx.Response(400, json={"object": "error", "details": "Sintaxe inválida"}))
    with pytest.raises(ScryfallError, match="Sintaxe inválida"):
        await client.search("t:")


async def test_search_non_json_error(make_client):
    client = make_client(lambda r: httpx.Response(503, text="<html>down</html>"))
    with pytest.raises(ScryfallError, match="503"):
        await client.search("bolt")


async def test_connection_error(make_client):
    def handler(request):
        raise httpx.ConnectError("offline")
    with pytest.raises(ScryfallError, match="conexão"):
        await make_client(handler).search("bolt")


async def test_rate_limit():
    def ok(request):
        return httpx.Response(200, json={"data": [], "total_cards": 0, "has_more": False})

    client = ScryfallClient(transport=httpx.MockTransport(ok), min_interval=0.1)
    start = time.monotonic()
    for _ in range(3):
        await client.search("x")
    assert time.monotonic() - start >= 0.2
    await client.close()


async def test_suggest_keeps_autocomplete_order_and_handles_double_faced(make_client):
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/cards/autocomplete":
            names = ["Lightning Bolt", "Delver of Secrets", "Sumiu"]
            return httpx.Response(200, json={"object": "catalog", "data": names})
        # o Scryfall devolve em outra ordem, com nome completo da dupla face e o não encontrado em not_found
        return httpx.Response(200, json={"data": [DELVER, BOLT], "not_found": [{"name": "Sumiu"}]})

    cards = await make_client(handler).suggest("bo")
    assert [c.name for c in cards] == ["Lightning Bolt", "Delver of Secrets // Insectile Aberration"]
    assert calls == [("GET", "/cards/autocomplete"), ("POST", "/cards/collection")]
    assert cards[0].image_small == "https://img/bolt-s.jpg"


async def test_suggest_sends_identifiers_and_limit(make_client):
    sent = {}

    def handler(request):
        if request.url.path == "/cards/autocomplete":
            sent["q"] = request.url.params["q"]
            return httpx.Response(200, json={"data": [f"Card {i}" for i in range(20)]})
        sent["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": []})

    await make_client(handler).suggest("card", limit=5)
    assert sent["q"] == "card"
    assert sent["body"] == {"identifiers": [{"name": f"Card {i}"} for i in range(5)]}


async def test_suggest_short_or_empty_makes_no_extra_requests(make_client):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"data": []})

    client = make_client(handler)
    assert await client.suggest("a") == ()
    assert calls == []
    assert await client.suggest("zzzz") == ()
    assert calls == ["/cards/autocomplete"]  # sem nomes, não chama /cards/collection


def test_to_card_full_fields():
    card = to_card(BOLT)
    assert card.oracle_id == "o-bolt"
    assert card.released_at.isoformat() == "2009-07-17"
    assert card.prices.usd_foil == Decimal("4.00") and card.prices.tix == Decimal("0.03")
    assert card.legalities["vintage"] == "restricted"
    assert card.finishes == ("nonfoil", "foil")
    assert len(card.faces) == 1
    face = card.faces[0]
    assert face.name == "Lightning Bolt" and face.flavor_text == "The sparkmage shrieked."
    assert face.artist == "Christopher Moeller" and face.image_large == "https://img/bolt-l.jpg"


def test_to_card_faces_of_double_faced():
    card = to_card(DELVER)
    assert [f.name for f in card.faces] == ["Delver of Secrets", "Insectile Aberration"]
    assert (card.faces[1].power, card.faces[1].toughness) == ("3", "2")
    assert card.faces[1].image_large == "https://img/d2-l.jpg"


async def test_get_card(make_client):
    def handler(request):
        assert request.url.path == "/cards/1"
        return httpx.Response(200, json=BOLT)
    assert (await make_client(handler).get_card("1")).name == "Lightning Bolt"


async def test_get_card_not_found(make_client):
    client = make_client(lambda r: httpx.Response(404, json={"object": "error", "details": "No card found"}))
    with pytest.raises(ScryfallError, match="No card found"):
        await client.get_card("x")


async def test_get_prints_params(make_client):
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json={"data": [BOLT], "total_cards": 1, "has_more": False})

    result = await make_client(handler).get_prints("o-bolt", page=2)
    assert len(result.cards) == 1
    assert seen == {"q": "oracleid:o-bolt", "page": "2", "unique": "prints", "order": "released", "dir": "desc",
                    "include_extras": "true", "include_variations": "true"}


async def test_get_rulings(make_client):
    def handler(request):
        assert request.url.path == "/cards/1/rulings"
        return httpx.Response(200, json=RULINGS)
    rulings = await make_client(handler).get_rulings("1")
    assert len(rulings) == 1 and rulings[0].published_at.isoformat() == "2020-08-07"
    assert rulings[0].source == "wotc" and "planeswalker" in rulings[0].text


SETS = {"data": [
    {"code": "m10", "name": "Magic 2010", "set_type": "core", "released_at": "2009-07-17", "digital": False,
     "icon_svg_uri": "https://svgs.scryfall.io/sets/m10.svg?123"},
    {"code": "pm10", "name": "Magic 2010 Promos", "set_type": "promo",
     "icon_svg_uri": "https://svgs.scryfall.io/sets/m10.svg?123"}]}


async def test_get_sets_parsed_and_cached(make_client):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=SETS)

    client = make_client(handler)
    sets = await client.get_sets()
    assert [s.code for s in sets] == ["m10", "pm10"]
    assert sets[0].name == "Magic 2010" and sets[0].released_at.isoformat() == "2009-07-17"
    assert sets[1].released_at is None and sets[1].set_type == "promo"
    await client.get_sets()
    assert calls == ["/sets"]


async def test_set_icon_downloads_once_and_caches_on_disk(make_client, tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if request.url.path == "/sets":
            return httpx.Response(200, json=SETS)
        return httpx.Response(200, content=b"<svg>m10</svg>")

    client = make_client(handler)
    assert await client.get_set_icon("PM10") == b"<svg>m10</svg>"  # promo usa o símbolo da principal
    assert (tmp_path / "set-icons" / "pm10.svg").read_bytes() == b"<svg>m10</svg>"
    assert await client.get_set_icon("pm10") == b"<svg>m10</svg>"
    assert len(calls) == 2  # /sets + svg; a segunda vez vem do disco
    assert await client.get_set_icon("zzz") is None
    assert len(calls) == 2  # lista de coleções já está em memória


async def test_set_list_fetched_once_with_concurrent_requests(make_client):
    sets_calls = []

    def handler(request):
        if request.url.path == "/sets":
            sets_calls.append(1)
            return httpx.Response(200, json=SETS)
        return httpx.Response(200, content=b"<svg/>")

    client = make_client(handler)
    await asyncio.gather(client.get_set_icon("m10"), client.get_set_icon("pm10"), client.get_set_icon("x"))
    assert len(sets_calls) == 1


async def test_cdn_files_skip_rate_limit(make_client):
    def handler(request):
        if request.url.path == "/sets":
            return httpx.Response(200, json={"data": [
                {"code": f"s{i}", "icon_svg_uri": f"https://svgs.scryfall.io/sets/s{i}.svg"} for i in range(5)]})
        return httpx.Response(200, content=b"<svg/>")

    client = make_client(handler, min_interval=0.2)
    start = time.monotonic()
    for i in range(5):
        await client.get_set_icon(f"s{i}")
    assert time.monotonic() - start < 0.2  # só /sets passou pelo limite


async def test_type_catalogs_with_failures_and_fallback(make_client):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        key = request.url.path.rsplit("/", 1)[1]
        if key in ("card-types", "battle-types"):
            return httpx.Response(404, json={"object": "error", "details": "Not found"})
        return httpx.Response(200, json={"object": "catalog", "data": [f"{key}-a", f"{key}-b"]})

    client = make_client(handler)
    catalogs = await client.get_type_catalogs()
    assert catalogs["supertypes"] == ("supertypes-a", "supertypes-b")
    assert catalogs["battle-types"] == ()
    assert "Creature" in catalogs["card-types"]  # reserva embutida
    await client.get_type_catalogs()
    assert len(calls) == 9  # guardado em memória


async def test_type_catalogs_not_cached_when_offline(make_client):
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("offline")

    client = make_client(handler)
    catalogs = await client.get_type_catalogs()
    assert "Creature" in catalogs["card-types"] and catalogs["creature-types"] == ()
    await client.get_type_catalogs()
    assert len(calls) == 18  # tenta de novo na próxima vez


async def test_find_cards_batches_and_matches(make_client):
    from tests.sample_cards import GOLD
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body["identifiers"])
        # devolve só o que conhece, fora de ordem, como o Scryfall pode fazer
        known = {"lightning bolt": BOLT, "delver of secrets": DELVER, "lightning helix": GOLD}
        data = [known[i["name"].lower()] for i in reversed(body["identifiers"])
                if "name" in i and i["name"].lower() in known]
        data += [BOLT for i in body["identifiers"] if i.get("oracle_id") == "o-bolt" or i.get("set") == "m10"]
        return httpx.Response(200, json={"data": data, "not_found": []})

    client = make_client(handler)
    names = [{"name": "Lightning Bolt"}, {"name": "Não Existe"}, {"name": "delver of secrets"}]
    names += [{"name": f"Filler {i}"} for i in range(80)] + [{"name": "LIGHTNING HELIX"}]
    cards = await client.find_cards(names)
    assert len(bodies) == 2 and len(bodies[0]) == 75 and len(bodies[1]) == 9  # 84 identificadores em 2 lotes
    assert cards[0].name == "Lightning Bolt" and cards[1] is None
    assert cards[2].name.startswith("Delver")  # nome da frente de dupla face
    assert cards[-1].name == "Lightning Helix" and all(c is None for c in cards[3:-1])
    by_set = await client.find_cards([
        {"set": "m10", "collector_number": "146"}, {"set": "m10", "collector_number": "1"},
        {"oracle_id": "o-bolt"}, {"name": "Lightning Bolt", "set": "2xm"}])
    assert by_set[0].name == "Lightning Bolt" and by_set[1] is None and by_set[2].oracle_id == "o-bolt"
    assert by_set[3] is None  # edição pedida não bate
    assert await client.find_cards([]) == []


async def test_suggest_where_adds_filter_and_cleans_text(make_client):
    queries = []

    def handler(request):
        queries.append((request.url.params["q"], request.url.params["order"]))
        return httpx.Response(200, json={"data": [BOLT, DELVER], "total_cards": 2, "has_more": False})

    client = make_client(handler)
    cards = await client.suggest_where('kren"ko (o:x)', "is:commander", limit=1)
    assert queries == [("(is:commander) kren ko o x", "edhrec")] and [c.id for c in cards] == ["1"]
    assert await client.suggest_where("k", "is:commander") == () and len(queries) == 1
