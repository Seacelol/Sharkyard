import asyncio

import pytest
from nicegui.testing import User

from mtg_collection import database
from mtg_collection.services import accounts
from mtg_collection.ui.auth import safe_redirect
from tests.conftest import TEST_PASSWORD, FakeScryfall, create_account, login

anonymous = pytest.mark.anonymous


def fill(user: User, **fields) -> None:
    for marker, value in fields.items():
        user.find(marker=marker.replace("_", "-")).type(value)


def test_safe_redirect():
    assert safe_redirect("/card/1?x=2") == "/card/1?x=2"
    for bad in ("", None, "//evil.com", "https://evil.com", "evil", "/login", "/register?x=1"):
        assert safe_redirect(bad) == "/"
    # o navegador lê barra invertida como barra: "/\\site.com" seria outro site
    for bad in ("/\\evil.com", "/\\/evil.com", "/\tx", "/\x7fx"):
        assert safe_redirect(bad) == "/", bad
    # com três barras ou mais o urlsplit não vê o host, mas o navegador vai para outro site do mesmo jeito
    for bad in ("///evil.com", "////evil.com", "///evil.com/card/1?x=1"):
        assert safe_redirect(bad) == "/", bad


@anonymous
async def test_first_run_goes_to_register_and_creates_admin(user: User, fake_api: FakeScryfall):
    await user.open("/")
    await user.should_see("Primeiro acesso")
    await user.should_not_see(marker="register-invite")  # o primeiro não precisa de convite
    fill(user, register_username="Marcelo", register_display_name="Marcelo A.",
         register_password=TEST_PASSWORD, register_confirm=TEST_PASSWORD)
    user.find(marker="register-submit").click()
    await user.should_see(marker="user-menu", retries=30)
    await user.should_see("Marcelo A.")
    with database.session() as s:
        [admin] = accounts.list_users(s)
    assert admin.username == "marcelo" and admin.is_admin


@anonymous
async def test_register_errors(user: User):
    await user.open("/register")
    fill(user, register_username="marcelo", register_password=TEST_PASSWORD, register_confirm="outra-senha-1")
    user.find(marker="register-submit").click()
    await user.should_see("As senhas não conferem.")
    user.find(marker="register-username").clear().type("x")
    user.find(marker="register-confirm").clear().type(TEST_PASSWORD)
    user.find(marker="register-submit").click()
    await user.should_see("O usuário deve ter de 3 a 20 caracteres")


@anonymous
async def test_register_with_invite(user: User):
    create_account("admin")
    with database.session() as s:
        code = accounts.invite_code(s)
    await user.open("/register")
    fill(user, register_username="amigo", register_password=TEST_PASSWORD, register_confirm=TEST_PASSWORD,
         register_invite="ERRADO99")
    user.find(marker="register-submit").click()
    await user.should_see("Código de convite inválido", retries=30)
    user.find(marker="register-invite").clear().type(code.lower())
    user.find(marker="register-submit").click()
    await user.should_see(marker="user-menu", retries=30)
    await user.should_see("amigo")


@anonymous
async def test_protected_pages_redirect_to_login(user: User):
    create_account()
    for path in ("/", "/advanced", "/account", "/card/1"):
        await user.open(path)
        await user.should_see(marker="login-submit")


@anonymous
async def test_wrong_password_then_login(user: User, fake_api: FakeScryfall):
    create_account()
    await user.open("/login")
    fill(user, login_username="marcelo", login_password="senha-errada")
    user.find(marker="login-submit").click()
    await user.should_see("Usuário ou senha incorretos.", retries=30)
    await user.should_see(marker="login-submit")
    user.find(marker="login-password").type(TEST_PASSWORD)  # o campo foi limpo após o erro
    user.find(marker="login-submit").click()
    await user.should_see(marker="user-menu", retries=30)


@anonymous
async def test_login_returns_to_requested_page(user: User, fake_api: FakeScryfall):
    create_account()
    await user.open("/card/1?x=1")
    await user.should_see(marker="login-submit")
    fill(user, login_username="MARCELO", login_password=TEST_PASSWORD)
    user.find(marker="login-submit").click()
    await user.should_see("Lightning Bolt", retries=30)  # argon2 é lento de propósito
    await user.should_see("Magic 2010 (M10)")


async def test_logged_in_user_skips_login_page(user: User, fake_api: FakeScryfall):
    await user.open("/login")
    await user.should_see(marker="user-menu", retries=30)
    await user.should_not_see(marker="login-submit")


async def test_logout(user: User, fake_api: FakeScryfall):
    await user.open("/")
    user.find(marker="menu-logout").click()
    await user.should_see(marker="login-submit")
    await user.open("/")
    await user.should_see(marker="login-submit")


async def test_change_display_name(user: User, fake_api: FakeScryfall):
    await user.open("/account")
    await user.should_see("Usuário: marcelo · administrador")
    user.find(marker="display-name").clear().type("Marcelo Mello")
    user.find(marker="save-profile").click()
    await user.should_see("Perfil salvo.")
    await user.open("/")
    await user.should_see("Marcelo Mello")  # menu do usuário


async def test_change_password(user: User, fake_api: FakeScryfall):
    await user.open("/account")
    fill(user, current_password="errada", new_password="nova-senha-123", confirm_password="nova-senha-123")
    user.find(marker="change-password").click()
    await user.should_see("A senha atual está incorreta.", retries=30)

    user.find(marker="current-password").clear().type(TEST_PASSWORD)
    user.find(marker="confirm-password").clear().type("diferente-123")
    user.find(marker="change-password").click()
    await user.should_see("As senhas novas não conferem.")

    user.find(marker="confirm-password").clear().type("nova-senha-123")
    user.find(marker="change-password").click()
    await user.should_see("Senha alterada.", retries=30)
    await user.open("/")  # este navegador continua logado
    await user.should_see(marker="user-menu", retries=30)
    with database.session() as s:
        assert accounts.authenticate(s, "marcelo", "nova-senha-123") is not None


async def test_password_change_logs_out_other_browsers(user: User, create_user, fake_api: FakeScryfall):
    other: User = create_user()
    await login(other)
    await other.open("/")
    await other.should_see(marker="user-menu", retries=30)

    await user.open("/account")
    fill(user, current_password=TEST_PASSWORD, new_password="nova-senha-123", confirm_password="nova-senha-123")
    user.find(marker="change-password").click()
    await user.should_see("Senha alterada.", retries=30)

    await other.open("/")
    await other.should_see(marker="login-submit", retries=30)  # sessão antiga caiu


async def test_admin_section(user: User, fake_api: FakeScryfall):
    create_account("amigo", display_name="Amigo")
    with database.session() as s:
        code = accounts.invite_code(s)
    await user.open("/account")
    await user.should_see(code)
    await user.should_see(marker="user-marcelo")
    await user.should_see(marker="user-amigo")
    await user.should_see("Admin")
    await user.should_not_see(marker="user-actions-marcelo")  # nada de se desativar ou apagar
    await user.should_see(marker="user-actions-amigo")
    user.find(marker="regenerate-invite").click()
    await user.should_see("Novo código gerado.")
    with database.session() as s:
        assert accounts.invite_code(s) != code
    await user.should_not_see(code)


async def test_temporary_password_flow(user: User, create_user, fake_api: FakeScryfall):
    create_account("amigo", display_name="Amigo")
    await user.open("/account")
    user.find(marker="user-reset-amigo").click()
    await user.should_see("Gerar uma senha temporária para Amigo?")
    user.find(marker="confirm-ok").click()
    await user.should_see(marker="temp-password", retries=30)
    await user.should_see("Senha temporária")  # selo na lista
    temporary = user.find(marker="temp-password").elements.pop().text

    friend: User = create_user()
    await friend.open("/login")
    friend.find(marker="login-username").type("amigo")
    friend.find(marker="login-password").type(TEST_PASSWORD)  # a antiga não vale mais
    friend.find(marker="login-submit").click()
    await friend.should_see("Usuário ou senha incorretos.", retries=30)
    friend.find(marker="login-password").type(temporary)
    friend.find(marker="login-submit").click()
    await friend.should_see("Criar nova senha", retries=30)
    await friend.open("/collection")  # não passa daqui sem criar a senha
    await friend.should_see("Criar nova senha")
    await friend.should_not_see(marker="user-menu")
    friend.find(marker="new-password").type(temporary)
    friend.find(marker="new-password-confirm").type(temporary)
    friend.find(marker="new-password-submit").click()
    await friend.should_see("diferente da temporária", retries=30)
    friend.find(marker="new-password").clear().type("senha-do-amigo-1")
    friend.find(marker="new-password-confirm").clear().type("senha-do-amigo-1")
    friend.find(marker="new-password-submit").click()
    await friend.should_see(marker="user-menu", retries=30)
    await friend.open("/collection")
    await friend.should_see("Minha coleção")
    with database.session() as s:
        assert accounts.authenticate(s, "amigo", "senha-do-amigo-1") is not None


async def test_disable_and_delete_account(user: User, create_user, fake_api: FakeScryfall):
    create_account("amigo", display_name="Amigo")
    await user.open("/account")
    user.find(marker="user-toggle-amigo").click()
    await user.should_see("Conta de Amigo desativada")
    await user.should_see("Desativada")

    friend: User = create_user()
    await friend.open("/login")
    friend.find(marker="login-username").type("amigo")
    friend.find(marker="login-password").type(TEST_PASSWORD)
    friend.find(marker="login-submit").click()
    await friend.should_see("Esta conta está desativada.", retries=30)

    # no teste, o clique simulado usa a sessão da última página aberta (a do amigo); no navegador de verdade
    # cada evento leva a sessão de quem abriu a página. Reabrir devolve a sessão do admin.
    await user.open("/account")
    user.find(marker="user-toggle-amigo").click()
    await user.should_see("Conta de Amigo reativada.")
    user.find(marker="user-delete-amigo").click()
    await user.should_see("Apagar a conta de Amigo?")
    ok = user.find(marker="delete-account-ok").elements.pop()
    assert not ok.enabled
    user.find(marker="delete-confirm-name").type("amig")
    assert not ok.enabled
    user.find(marker="delete-confirm-name").type("o")
    assert ok.enabled
    user.find(marker="delete-account-ok").click()
    await user.should_see("Conta de Amigo apagada.")
    await user.should_not_see(marker="user-amigo")
    with database.session() as s:
        assert [u.username for u in accounts.list_users(s)] == ["marcelo"]


@anonymous
async def test_non_admin_has_no_admin_section(user: User, fake_api: FakeScryfall):
    create_account("admin")
    create_account("amigo")
    await login(user, "amigo")
    await user.open("/account")
    await user.should_see("Usuário: amigo")
    await user.should_not_see("Convidar amigos")
    await user.should_not_see(marker="users-list")


async def test_open_page_leaves_when_session_is_revoked(user: User, monkeypatch):
    from mtg_collection.ui import layout
    monkeypatch.setattr(layout, "SESSION_CHECK_SECONDS", 0.1)
    await user.open("/collection")
    await user.should_see("Minha coleção")
    with database.session() as s:  # outra aba trocou a senha: o token antigo deixa de valer
        accounts.change_password(s, 1, TEST_PASSWORD, "outra-senha-forte")
    await user.should_see(marker="login-submit", retries=30)


@pytest.mark.anonymous
async def test_login_blocked_after_many_wrong_passwords(user: User, monkeypatch):
    from mtg_collection.services import login_throttle
    monkeypatch.setattr(login_throttle, "throttle", login_throttle.LoginThrottle())
    create_account("marcelo")
    await user.open("/login")
    for _ in range(login_throttle.MAX_PER_USER):
        user.find(marker="login-username").clear().type("marcelo")
        user.find(marker="login-password").clear().type("senha-errada-1")
        user.find(marker="login-submit").click()
        await asyncio.sleep(0.3)
    await user.should_see("Muitas tentativas erradas.")
    # nem a senha certa entra enquanto estiver bloqueado
    user.find(marker="login-password").clear().type(TEST_PASSWORD)
    user.find(marker="login-submit").click()
    await asyncio.sleep(0.3)
    await user.should_not_see(marker="user-menu")
