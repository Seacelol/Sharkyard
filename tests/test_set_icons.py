from mtg_collection.services import scryfall
from mtg_collection.ui import set_icons


async def test_route_serves_icon(monkeypatch):
    async def fake(code):
        return b"<svg>ok</svg>" if code == "m10" else None
    monkeypatch.setattr(scryfall.client, "get_set_icon", fake)

    response = await set_icons.set_icon("m10")
    assert response.body == b"<svg>ok</svg>" and response.media_type == "image/svg+xml"
    assert "max-age" in response.headers["cache-control"]


async def test_route_fallback_for_unknown_invalid_or_error(monkeypatch):
    calls = []

    async def fake(code):
        calls.append(code)
        if code == "boom":
            raise scryfall.ScryfallError("offline")
        return None
    monkeypatch.setattr(scryfall.client, "get_set_icon", fake)

    for code in ("zzz", "boom", "../etc", "A"):
        response = await set_icons.set_icon(code)
        assert response.body == set_icons.FALLBACK_SVG
        assert "cache-control" not in response.headers  # não fixa o fallback no cache do navegador
    assert calls == ["zzz", "boom"]  # códigos inválidos nem chegam ao serviço


def test_set_icon_url():
    assert set_icons.set_icon_url("M10") == "/set-icon/m10.svg"


async def test_route_is_served_over_http(user, monkeypatch):
    async def fake(code):
        return b"<svg>http</svg>"
    monkeypatch.setattr(scryfall.client, "get_set_icon", fake)
    await user.open("/")
    response = await user.http_client.get("/set-icon/m10.svg")
    assert response.status_code == 200 and response.content == b"<svg>http</svg>"
