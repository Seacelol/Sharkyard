"""Sessão do usuário na interface: quem está logado, login/logout e proteção das páginas."""
import asyncio
import secrets
from contextlib import asynccontextmanager
from urllib.parse import quote, urlsplit

from fastapi import Request
from fastapi.responses import RedirectResponse
from nicegui import app, ui
from starlette.middleware.base import BaseHTTPMiddleware

from mtg_collection import config, database
from mtg_collection.models import User
from mtg_collection.services import accounts
from mtg_collection.ui import assets

PUBLIC_PATHS = {"/login", "/register", "/favicon.ico"}
NEW_PASSWORD_PATH = "/new-password"  # quem entrou com senha temporária só passa daqui depois de criar a sua


def storage_secret() -> str:
    """Chave que assina o cookie de sessão. Criada uma vez e guardada na pasta de dados."""
    if config.SECRET_PATH.exists():
        return config.SECRET_PATH.read_text().strip()
    config.SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    config.SECRET_PATH.write_text(secret)
    config.SECRET_PATH.chmod(0o600)
    return secret


def current_user() -> User | None:
    """Usuário logado neste navegador, ou None. Confere no banco se a sessão ainda vale."""
    user_id, token = app.storage.user.get("user_id"), app.storage.user.get("token")
    if not user_id or not token:
        return None
    with database.session() as s:
        return accounts.user_for_session(s, user_id, token)


_NOT_CHECKED = object()


def request_user(request: Request) -> User | None:
    """Usuário da requisição HTTP. O AuthMiddleware já consultou o banco e guardou o resultado em request.state:
    as rotas de imagem reaproveitam em vez de repetir a consulta a cada imagem da página."""
    user = getattr(request.state, "user", _NOT_CHECKED)
    return current_user() if user is _NOT_CHECKED else user


def start_session(user: User, token: str) -> None:
    """Grava a sessão no cookie assinado. O token é conferido a cada página: trocar a senha derruba as outras."""
    app.storage.user.update(user_id=user.id, token=token)


def end_session() -> None:
    app.storage.user.clear()


def safe_redirect(target: str | None) -> str:
    """Só aceita caminhos internos (evita mandar o usuário para outro site depois do login).
    O navegador lê "\\" como "/", então "/\\site.com" também seria outro site: barra invertida é recusada.
    "//site.com", "///site.com" e afins o navegador também resolve para outro site (o urlsplit não vê o host
    quando há três barras ou mais), por isso qualquer caminho que começa com duas barras é recusado."""
    if (not target or not target.startswith("/") or target.startswith("//") or "\\" in target
            or any(ord(c) < 32 or ord(c) == 127 for c in target)):
        return "/"
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.path in PUBLIC_PATHS or parsed.path == NEW_PASSWORD_PATH:
        return "/"
    return target


class AttemptLocks:
    """Uma tentativa de senha por vez para cada usuário e para cada endereço.

    O limite de tentativas só conta o erro depois que o argon2 responde. Sem esta fila, várias tentativas
    mandadas ao mesmo tempo passariam todas pela conferência do limite antes de o primeiro erro ser contado.
    Cada trava some quando ninguém mais a usa: nomes inventados por um robô não acumulam na memória."""

    def __init__(self):
        self._entries: dict[str, list] = {}  # chave -> [trava, quantas tentativas usam ou esperam]

    def _release(self, key: str) -> None:
        entry = self._entries[key]
        entry[1] -= 1
        if entry[1] == 0:
            del self._entries[key]

    @asynccontextmanager
    async def hold(self, username: str, address: str):
        """Segura as duas travas (usuário e endereço) durante uma tentativa de login."""
        held = []
        try:
            # sempre na mesma ordem (usuário, depois endereço): duas tentativas nunca ficam presas uma esperando a outra
            for key in (f"user:{username.strip().lower()}", f"addr:{address}"):
                entry = self._entries.setdefault(key, [asyncio.Lock(), 0])
                entry[1] += 1
                try:
                    await entry[0].acquire()
                except BaseException:  # cancelada na fila: não chegou a pegar a trava
                    self._release(key)
                    raise
                held.append(key)
            yield
        finally:
            for key in reversed(held):
                self._entries[key][0].release()
                self._release(key)


attempt_locks = AttemptLocks()


LOCAL_ADDRESSES = {"127.0.0.1", "::1", "localhost"}


def client_address() -> str:
    """Endereço de quem está acessando. Atrás do túnel da Cloudflare a conexão chega do próprio PC, e o
    endereço real vem no cabeçalho CF-Connecting-IP (só é aceito quando a conexão é local)."""
    request = ui.context.client.request
    host = request.client.host if request and request.client else ""
    if host in LOCAL_ADDRESSES and request is not None:
        return request.headers.get("cf-connecting-ip") or host
    return host or "desconhecido"


class AuthMiddleware(BaseHTTPMiddleware):
    """Quem não está logado vai para /login, guardando a página pedida para voltar depois.
    Quem entrou com senha temporária vai para a tela de criar a senha nova, seja qual for a página pedida."""

    async def dispatch(self, request: Request, call_next):
        """Arquivos internos do NiceGUI (/_nicegui) e caminhos públicos passam direto; o resto exige sessão válida."""
        path = request.url.path
        if path.startswith("/_nicegui") or path in PUBLIC_PATHS or assets.is_public(path):
            return await call_next(request)
        user = request.state.user = current_user()  # guardado para as rotas não consultarem de novo
        if user is None:
            if request.url.query:
                path = f"{path}?{request.url.query}"
            # codificado: sem isso o "&" da página pedida viraria outro parâmetro do /login e se perderia
            return RedirectResponse(f"/login?redirect_to={quote(path, safe='/')}" if path != "/" else "/login")
        if user.must_change_password and path != NEW_PASSWORD_PATH:
            return RedirectResponse(NEW_PASSWORD_PATH)
        return await call_next(request)


def install() -> None:
    """Liga a proteção de login. Chamado pelo main() antes de subir o servidor."""
    if not any(m.cls is AuthMiddleware for m in app.user_middleware):
        app.add_middleware(AuthMiddleware)
