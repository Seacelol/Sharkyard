"""Entrar e criar conta."""
import asyncio
from urllib.parse import quote

from nicegui import run, ui

from mtg_collection import config, database
from mtg_collection.services import accounts, login_throttle
from mtg_collection.ui import auth
from mtg_collection.ui.layout import public_frame

FAILED_LOGIN_DELAY = 1.0  # segundos de espera após senha errada: atrasa tentativas em massa


def _authenticate(username: str, password: str):
    """Roda fora do loop da interface (argon2 é lento de propósito e travaria a página de todo mundo)."""
    with database.session() as s:
        return accounts.authenticate(s, username, password)


def _set_new_password(user_id: int, new: str) -> str:
    """Também roda fora do loop (argon2). Devolve o token novo da sessão."""
    with database.session() as s:
        return accounts.set_new_password(s, user_id, new)


def _register(username: str, password: str, display_name: str, invite: str):
    """Cadastra e já autentica na mesma sessão, para entrar direto. Fora do loop, como _authenticate."""
    with database.session() as s:
        accounts.register(s, username, password, display_name, invite)
        return accounts.authenticate(s, username, password)


def blocked_message(seconds: int) -> str:
    """Aviso de bloqueio arredondado em minutos (no mínimo 1)."""
    minutes = max(1, round(seconds / 60))
    return f"Muitas tentativas erradas. Tente de novo em {minutes} minuto{'s' if minutes > 1 else ''}."


def _card():
    return ui.card().classes("w-full max-w-sm mx-auto mt-12 gap-4 p-6")


def _field(label: str, marker: str, password: bool = False, autocomplete: str = "") -> ui.input:
    field = ui.input(label, password=password, password_toggle_button=password) \
        .props(f'outlined autocomplete="{autocomplete}"').classes("w-full").mark(marker)
    return field


async def _try_login(name: str, password: str, address: str) -> tuple | str:
    """Confere o limite, a senha e conta o erro. Roda com a trava da tentativa: (usuário, token) ou o erro."""
    throttle = login_throttle.throttle
    if wait := throttle.wait_seconds(name, address):
        return blocked_message(wait)
    try:
        result = await run.io_bound(_authenticate, name, password)
    except accounts.AccountError as e:  # senha certa, mas a conta está desativada
        return str(e)
    if result is None:
        throttle.failed(name, address)
        await asyncio.sleep(FAILED_LOGIN_DELAY)  # ainda com a trava: atrasa também quem tenta em paralelo
        wait = throttle.wait_seconds(name, address)
        return blocked_message(wait) if wait else "Usuário ou senha incorretos."
    throttle.succeeded(name)
    return result


@ui.page("/login")
def login_page(redirect_to: str = "") -> None:
    """Tela de login. `redirect_to` é a página pedida antes do login; passa por safe_redirect para não virar
    um redirecionamento para outro site."""
    with database.session() as s:
        first_run = not accounts.has_users(s)
    if first_run:  # ninguém cadastrado ainda: o primeiro cadastro vira administrador
        ui.navigate.to("/register")
        return
    if auth.current_user():
        ui.navigate.to(auth.safe_redirect(redirect_to))
        return

    async def submit() -> None:
        name, address = username.value or "", auth.client_address()
        async with auth.attempt_locks.hold(name, address):
            result = await _try_login(name, password.value or "", address)
        if isinstance(result, str):
            error.text, error.visible = result, True
            password.value = ""
            return
        auth.start_session(*result)
        ui.navigate.to(auth.safe_redirect(redirect_to))

    with public_frame("Entrar"), _card():
        ui.label("Entrar").classes("text-2xl font-bold")
        username = _field("Usuário", "login-username", autocomplete="username")
        password = _field("Senha", "login-password", password=True, autocomplete="current-password")
        error = ui.label().classes("text-sm text-red-600").mark("login-error")
        error.visible = False
        for field in (username, password):
            field.on("keydown.enter", submit)
        ui.button("Entrar", on_click=submit).props("unelevated no-caps").classes("w-full").mark("login-submit")
        with ui.row().classes("w-full justify-center gap-1 text-sm"):
            ui.label("Não tem conta?").classes("text-gray-600")
            ui.link("Criar conta", f"/register?redirect_to={quote(redirect_to)}" if redirect_to else "/register")


@ui.page("/register")
def register_page(redirect_to: str = "") -> None:
    """Cadastro. No banco vazio não pede convite (a conta vira admin); depois, o código de convite é obrigatório."""
    with database.session() as s:
        first_run = not accounts.has_users(s)
    if auth.current_user():
        ui.navigate.to("/")
        return

    async def submit() -> None:
        if password.value != confirm.value:
            error.text = "As senhas não conferem."
            error.visible = True
            return
        try:
            user, token = await run.io_bound(_register, username.value or "", password.value or "",
                                             display_name.value or "", (invite.value or "") if invite else "")
        except accounts.AccountError as e:
            error.text = str(e)
            error.visible = True
            return
        auth.start_session(user, token)
        ui.notify(f"Bem-vindo, {user.display_name}!", type="positive")
        ui.navigate.to(auth.safe_redirect(redirect_to))

    with public_frame("Criar conta"), _card():
        ui.label("Criar conta").classes("text-2xl font-bold")
        if first_run:
            ui.label("Primeiro acesso: esta conta será a de administrador. Depois você convida seus amigos "
                     "com o código que aparece em Minha conta.").classes("text-sm text-gray-600")
        username = _field("Usuário", "register-username", autocomplete="username")
        ui.label(f"{config.USERNAME_MIN} a {config.USERNAME_MAX} caracteres: letras, números, ponto, hífen ou "
                 "sublinhado").classes("text-xs text-gray-500 -mt-3")
        display_name = _field("Nome de exibição (opcional)", "register-display-name", autocomplete="nickname") \
            .props(f"maxlength={config.DISPLAY_NAME_MAX}")
        password = _field("Senha", "register-password", password=True, autocomplete="new-password")
        ui.label(f"Mínimo de {config.PASSWORD_MIN} caracteres").classes("text-xs text-gray-500 -mt-3")
        confirm = _field("Confirmar senha", "register-confirm", password=True, autocomplete="new-password")
        invite = None if first_run else _field("Código de convite", "register-invite", autocomplete="off")
        error = ui.label().classes("text-sm text-red-600").mark("register-error")
        error.visible = False
        ui.button("Criar conta", on_click=submit).props("unelevated no-caps").classes("w-full") \
            .mark("register-submit")
        if not first_run:
            with ui.row().classes("w-full justify-center gap-1 text-sm"):
                ui.label("Já tem conta?").classes("text-gray-600")
                ui.link("Entrar", "/login")


@ui.page(auth.NEW_PASSWORD_PATH)
def new_password_page() -> None:
    """Primeiro acesso depois que o admin gerou uma senha temporária: a pessoa cria a sua antes de seguir."""
    user = auth.current_user()
    if user is None or not user.must_change_password:
        ui.navigate.to("/")
        return

    async def submit() -> None:
        if password.value != confirm.value:
            error.text, error.visible = "As senhas não conferem.", True
            return
        try:
            token = await run.io_bound(_set_new_password, user.id, password.value or "")
        except accounts.AccountError as e:
            error.text, error.visible = str(e), True
            return
        auth.start_session(user, token)
        ui.notify("Senha criada. Pronto!", type="positive")
        ui.navigate.to("/")

    def leave() -> None:
        auth.end_session()
        ui.navigate.to("/login")

    with public_frame("Criar nova senha"), _card():
        ui.label("Criar nova senha").classes("text-2xl font-bold")
        ui.label(f"Olá, {user.display_name}. Você entrou com uma senha temporária; crie a sua para continuar.") \
            .classes("text-sm text-gray-600")
        password = _field("Nova senha", "new-password", password=True, autocomplete="new-password")
        ui.label(f"Mínimo de {config.PASSWORD_MIN} caracteres").classes("text-xs text-gray-500 -mt-3")
        confirm = _field("Confirmar nova senha", "new-password-confirm", password=True, autocomplete="new-password")
        error = ui.label().classes("text-sm text-red-600").mark("new-password-error")
        error.visible = False
        confirm.on("keydown.enter", submit)
        ui.button("Salvar senha", on_click=submit).props("unelevated no-caps").classes("w-full") \
            .mark("new-password-submit")
        ui.button("Sair", on_click=leave).props("flat no-caps").classes("w-full")
