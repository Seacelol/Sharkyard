"""Correções da revisão de segurança e desempenho da interface (redirecionamento, limite de login, sessão
derrubada, props, lista de usuários, estatísticas, ícone e consultas em lote)."""
import asyncio
import base64
import time
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest
from nicegui import Client, ui
from nicegui.testing import User

from mtg_collection import config, database
from mtg_collection.services import accounts
from tests.conftest import TEST_PASSWORD, FakeScryfall, create_account, login


def count_sessions(monkeypatch) -> list[int]:
    """Conta quantas sessões de banco são abertas (troca database.session por uma que registra)."""
    opened = [0]
    original = database.session

    @contextmanager
    def counting():
        opened[0] += 1
        with original() as s:
            yield s

    monkeypatch.setattr(database, "session", counting)
    return opened


# ---------- 2: tentativas de login em paralelo ----------
@pytest.mark.anonymous
async def test_parallel_wrong_passwords_respect_the_limit(user: User, monkeypatch):
    from mtg_collection.services import login_throttle
    from mtg_collection.ui import auth
    from mtg_collection.ui.pages import login as login_page
    create_account("marcelo")
    calls = []

    def slow_wrong(username, password):  # simula o argon2: demora e erra
        calls.append(username)
        time.sleep(0.05)
        return None

    monkeypatch.setattr(login_page, "_authenticate", slow_wrong)
    await user.open("/login")
    user.find(marker="login-username").type("marcelo")
    user.find(marker="login-password").type("senha-errada-1")
    for _ in range(login_throttle.MAX_PER_USER + 5):  # cliques seguidos, sem esperar a resposta
        user.find(marker="login-submit").click()
    await user.should_see("Muitas tentativas erradas.", retries=50)
    await asyncio.sleep(0.5)
    assert len(calls) == login_throttle.MAX_PER_USER
    assert auth.attempt_locks._entries == {}  # nenhuma trava sobra na memória


async def test_attempt_locks_serialize_same_user():
    from mtg_collection.ui.auth import AttemptLocks
    locks, running, peak = AttemptLocks(), [0], [0]

    async def attempt(name, address):
        async with locks.hold(name, address):
            running[0] += 1
            peak[0] = max(peak[0], running[0])
            await asyncio.sleep(0.01)
            running[0] -= 1

    await asyncio.gather(*(attempt("Marcelo", f"10.0.0.{i}") for i in range(5)), attempt("marcelo ", "x"))
    assert peak[0] == 1  # mesmo usuário (sem diferença de maiúscula ou espaço): uma tentativa por vez
    await asyncio.gather(*(attempt("marcelo", "1.1.1.1") for _ in range(3)), attempt("amigo", "1.1.1.1"))
    assert peak[0] == 1  # mesmo endereço também espera
    assert locks._entries == {}


# ---------- 3: sessão revogada derruba a página no servidor ----------
async def test_revoked_session_deletes_client(user: User, monkeypatch):
    from mtg_collection.ui import layout
    monkeypatch.setattr(layout, "SESSION_CHECK_SECONDS", 0.1)
    monkeypatch.setattr(layout, "SESSION_DROP_DELAY", 0.05)
    await user.open("/collection")
    await user.should_see("Minha coleção")
    page = user.client
    with database.session() as s:
        accounts.change_password(s, 1, TEST_PASSWORD, "outra-senha-forte")
    await user.should_see(marker="login-submit", retries=30)
    for _ in range(20):
        if page.id not in Client.instances:
            break
        await asyncio.sleep(0.05)
    assert page.id not in Client.instances  # os botões da página antiga não rodam mais
    assert not page.elements


async def test_admin_actions_recheck_session(user: User, fake_api: FakeScryfall):
    create_account("amigo", display_name="Amigo")
    with database.session() as s:
        code = accounts.invite_code(s)
    await user.open("/account")
    await user.should_see(marker="user-amigo")
    with database.session() as s:  # a sessão caiu antes do timer perceber
        accounts.change_password(s, 1, TEST_PASSWORD, "outra-senha-forte")
    user.find(marker="regenerate-invite").click()
    await user.should_see("Sua sessão expirou.")
    user.find(marker="user-toggle-amigo").click()
    await asyncio.sleep(0.1)
    with database.session() as s:
        assert accounts.invite_code(s) == code
        assert not next(u for u in accounts.list_users(s) if u.username == "amigo").is_disabled


# ---------- 4: dados em props vão por chave ----------
async def test_props_with_backslash_do_not_inject(user: User):
    from mtg_collection.ui.components.avatar import user_avatar
    from mtg_collection.ui.components.controls import lazy_img
    await user.open("/")
    await user.should_see(marker="user-menu")
    evil = 'x\\" :onerror="alert(1)\\'
    with user.client.content:
        img = lazy_img(evil)
        user_avatar("A", "f" * 32 + ".png\\")
    assert img.props["src"] == evil
    assert not any(key.startswith(":") for key in img.props)
    [avatar] = [e for e in user.client.elements.values() if "avatar-img" in e._markers]
    assert avatar.props["src"].endswith(".png\\")


# ---------- 5: página pedida volta inteira depois do login ----------
@pytest.mark.anonymous
async def test_redirect_keeps_all_query_parameters(user: User):
    create_account()
    response = await user.http_client.get("/advanced?q=bolt&adv=1", follow_redirects=False)
    assert response.headers["location"] == "/login?redirect_to=/advanced%3Fq%3Dbolt%26adv%3D1"


@pytest.mark.anonymous
async def test_login_returns_with_all_parameters(user: User, fake_api: FakeScryfall, monkeypatch):
    from mtg_collection.ui import auth
    create_account()
    targets, original = [], auth.safe_redirect
    monkeypatch.setattr(auth, "safe_redirect", lambda target: targets.append(target) or original(target))
    await user.open("/card/1?x=1&y=2")
    user.find(marker="login-username").type("marcelo")
    user.find(marker="login-password").type(TEST_PASSWORD)
    user.find(marker="login-submit").click()
    await user.should_see("Lightning Bolt", retries=30)
    assert "/card/1?x=1&y=2" in targets  # o "&y=2" não se perdeu no caminho


# ---------- 6: lista de usuários é de cada página ----------
async def test_users_list_is_per_page(user: User, create_user, fake_api: FakeScryfall):
    create_account("amigo", display_name="Amigo")
    other: User = create_user()
    await login(other)
    await other.open("/account")
    await other.should_see(marker="user-amigo")
    create_account("terceiro", display_name="Terceiro")
    await user.open("/account")
    await user.should_see(marker="user-terceiro")
    user.find(marker="user-toggle-amigo").click()
    await user.should_see("Conta de Amigo desativada")
    await other.should_not_see(marker="user-terceiro")  # a outra aba não foi refeita pela atualização desta


# ---------- 7: estatísticas fora de ordem ----------
async def test_stats_loader_drops_stale_results(user: User, monkeypatch):
    from mtg_collection.ui.components import deck_stats_view
    old_lines, new_lines, rendered = ["velha"], ["nova"], []

    async def fake_fetch(lines):
        await asyncio.sleep(0.2 if lines is old_lines else 0)  # a primeira termina depois da segunda
        return {}

    monkeypatch.setattr(deck_stats_view, "fetch_cards", fake_fetch)
    monkeypatch.setattr(deck_stats_view, "estimated_value",
                        lambda lines, cards: (Decimal(1 if lines is old_lines else 2), 0))
    monkeypatch.setattr(deck_stats_view, "render_sources", lambda box, stats, lines, cards: rendered.append(lines))
    await user.open("/")
    await user.should_see(marker="user-menu")
    loader = deck_stats_view.StatsLoader()
    with user.client.content:
        value, sources = ui.label(), ui.element("div")
    loader.start(value, sources, None, old_lines)
    loader.start(value, sources, None, new_lines)
    await asyncio.sleep(0.4)
    assert value.text == "US$ 2,00"
    assert rendered == [new_lines]


# ---------- 8: ícone grande demais ----------
def test_avatar_too_big_is_rejected_before_decoding():
    from mtg_collection.ui.components.avatar import MAX_AVATAR_BYTES, save_avatar_png
    from mtg_collection.ui.custom_images import ImageError
    big = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * MAX_AVATAR_BYTES).decode()
    with pytest.raises(ImageError, match="grande demais"):
        save_avatar_png(1, big)
    assert not config.CUSTOM_IMAGES_DIR.exists() or not any(config.CUSTOM_IMAGES_DIR.iterdir())


# ---------- 9: usuário da requisição consultado uma vez ----------
async def test_image_routes_reuse_user_from_middleware(user: User, monkeypatch):
    from mtg_collection.ui import auth
    calls = []
    original = auth.current_user
    monkeypatch.setattr(auth, "current_user", lambda: calls.append(1) or original())
    for path in ("/avatar/", "/custom-image/", "/deck-cover/"):
        calls.clear()
        assert (await user.http_client.get(f"{path}{'a' * 32}.png")).status_code == 404
        assert len(calls) == 1, path  # só o middleware consultou


# ---------- 10 e consultas em lote ----------
async def test_command_zone_custom_cards_in_one_session(monkeypatch):
    from mtg_collection.ui.components import command_zone
    opened = count_sessions(monkeypatch)
    monkeypatch.setattr(command_zone.custom_cards, "get", lambda s, user_id, custom_id: custom_id)
    monkeypatch.setattr(command_zone, "custom_card_as_card", lambda custom: f"carta-{custom}")
    lines = [SimpleNamespace(custom_card_id=i, oracle_id=None) for i in (1, 2, 3)]
    assert await command_zone._full_cards(1, lines) == ["carta-1", "carta-2", "carta-3"]
    assert opened[0] == 1


def test_discard_unused_uses_one_session(monkeypatch):
    from mtg_collection.ui.custom_images import discard_unused
    config.CUSTOM_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    names = [f"{c * 32}.png" for c in "abc"]
    for name in names:
        (config.CUSTOM_IMAGES_DIR / name).write_bytes(b"x")
    opened = count_sessions(monkeypatch)
    discard_unused([*names, None, "../fora.png", names[0]])
    assert opened[0] == 1
    assert not any(config.CUSTOM_IMAGES_DIR.iterdir())
