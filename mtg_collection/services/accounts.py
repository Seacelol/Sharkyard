"""Contas de usuário: cadastro, login, senha, perfil e convite. Sem interface.

Regras:
- o primeiro cadastro vira administrador e não precisa de convite;
- os seguintes precisam do código de convite (o admin vê e pode trocar);
- nome de usuário é único sem diferenciar maiúsculas e minúsculas;
- senha guardada só como hash argon2;
- sem e-mail: quem esquece a senha pede ao admin uma senha temporária, que precisa ser trocada no primeiro acesso.
"""
import re
import secrets
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mtg_collection import config
from mtg_collection.database.tables import CustomCardRow, CustomPrintRow, DeckRow, SettingRow, UserRow
from mtg_collection.models import User

INVITE_KEY = "invite_code"
INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O, 1/I: fácil de ditar
TEMP_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # minúsculas sem l/1, o/0: fácil de ditar e digitar no celular
TEMP_LENGTH = 10
_USERNAME = re.compile(rf"[a-z0-9_.\-]{{{config.USERNAME_MIN},{config.USERNAME_MAX}}}")

_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("senha-que-nao-existe")  # iguala o tempo de resposta para usuário inexistente


class AccountError(Exception):
    """Erro com mensagem pronta para mostrar ao usuário."""


def to_user(row: UserRow) -> User:
    return User(id=row.id, username=row.username, display_name=row.display_name, is_admin=row.is_admin,
                created_at=row.created_at, last_login_at=row.last_login_at, avatar_filename=row.avatar_filename,
                bio=row.bio, must_change_password=row.must_change_password, is_disabled=row.is_disabled,
                theme=row.theme, theme_mode=row.theme_mode)


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_password(password: str) -> None:
    if len(password) < config.PASSWORD_MIN:
        raise AccountError(f"A senha precisa ter pelo menos {config.PASSWORD_MIN} caracteres.")


def has_users(s: Session) -> bool:
    return s.scalar(select(func.count()).select_from(UserRow)) > 0


def register(s: Session, username: str, password: str, display_name: str = "", invite_code: str = "") -> User:
    """Cria a conta. A primeira do banco vira admin sem convite; as demais precisam do código de convite atual."""
    username = normalize_username(username)
    if not _USERNAME.fullmatch(username):
        raise AccountError(f"O usuário deve ter de {config.USERNAME_MIN} a {config.USERNAME_MAX} caracteres: "
                           "letras, números, ponto, hífen ou sublinhado.")
    validate_password(password)
    first_user = not has_users(s)
    if not first_user and not _invite_matches(s, invite_code):
        raise AccountError("Código de convite inválido. Peça o código atual ao administrador.")
    if _username_taken(s, username):
        raise AccountError(TAKEN)
    row = UserRow(username=username, display_name=display_name.strip()[:config.DISPLAY_NAME_MAX] or username,
                  password_hash=_hasher.hash(password), is_admin=first_user, session_token=_new_token())
    s.add(row)
    try:
        s.flush()
    except IntegrityError:  # o mesmo nome cadastrado ao mesmo tempo em outra aba: o índice único barra
        raise AccountError(TAKEN) from None
    # Dois cadastros ao mesmo tempo no banco vazio leem "não há usuários" e os dois virariam admin. A gravação
    # acima espera a do outro terminar, então agora a contagem já inclui o outro: se não for só esta conta, ela
    # não era a primeira (e não tinha convite). O erro desfaz o cadastro.
    if first_user and s.scalar(select(func.count()).select_from(UserRow)) > 1:
        raise AccountError("Outra conta acabou de ser criada. Peça o código de convite ao administrador.")
    if first_user:
        regenerate_invite_code(s)
    return to_user(row)


TAKEN = "Esse nome de usuário já está em uso."


def _username_taken(s: Session, username: str) -> bool:
    return s.scalar(select(UserRow.id).where(UserRow.username == username)) is not None


def authenticate(s: Session, username: str, password: str) -> tuple[User, str] | None:
    """Confere usuário e senha. Devolve (usuário, token da sessão) ou None, sem dizer qual dos dois errou."""
    row = s.scalar(select(UserRow).where(UserRow.username == normalize_username(username)))
    if row is None:
        _verify(_DUMMY_HASH, password)
        return None
    if not _verify(row.password_hash, password):
        return None
    if row.is_disabled:  # só avisa depois da senha certa: não revela a quem chuta senhas que a conta existe
        raise AccountError("Esta conta está desativada. Fale com o administrador.")
    if _hasher.check_needs_rehash(row.password_hash):  # parâmetros do argon2 mudaram desde o cadastro
        row.password_hash = _hasher.hash(password)
    row.last_login_at = datetime.now(UTC)
    return to_user(row), row.session_token


def user_for_session(s: Session, user_id: int, token: str) -> User | None:
    """Usuário da sessão, se o token ainda valer (troca de senha invalida as outras sessões)."""
    row = s.get(UserRow, user_id)
    if row is None or row.is_disabled or not token or not secrets.compare_digest(row.session_token, token):
        return None
    return to_user(row)


def change_password(s: Session, user_id: int, current: str, new: str) -> str:
    """Troca a senha e devolve o novo token: as sessões em outros navegadores deixam de valer."""
    row = _get(s, user_id)
    if not _verify(row.password_hash, current):
        raise AccountError("A senha atual está incorreta.")
    return _set_password(row, new)


def set_new_password(s: Session, user_id: int, new: str) -> str:
    """Primeiro acesso com a senha temporária: cria a senha nova sem pedir a atual (a pessoa acabou de entrar)."""
    row = _get(s, user_id)
    if not row.must_change_password:
        raise AccountError("Para trocar a senha, use Minha conta.")
    validate_password(new)
    if _verify(row.password_hash, new):
        raise AccountError("Escolha uma senha diferente da temporária.")
    return _set_password(row, new)


def _set_password(row: UserRow, new: str) -> str:
    validate_password(new)
    row.password_hash = _hasher.hash(new)
    row.must_change_password = False
    row.session_token = _new_token()
    return row.session_token


# ---------- administração das contas ----------
def _target(s: Session, actor_id: int, target_id: int) -> UserRow:
    if not _get(s, actor_id).is_admin:
        raise AccountError("Só o administrador pode fazer isso.")
    if actor_id == target_id:
        raise AccountError("Isso não vale para a sua própria conta.")
    return _get(s, target_id)


def reset_password(s: Session, actor_id: int, target_id: int) -> str:
    """Senha temporária para quem esqueceu a sua. A antiga e as sessões abertas deixam de valer.
    Devolve a senha para o admin passar à pessoa (só existe em texto neste momento)."""
    row = _target(s, actor_id, target_id)
    temporary = "".join(secrets.choice(TEMP_ALPHABET) for _ in range(TEMP_LENGTH))
    row.password_hash = _hasher.hash(temporary)
    row.must_change_password = True
    row.session_token = _new_token()
    return temporary


def set_disabled(s: Session, actor_id: int, target_id: int, disabled: bool) -> User:
    """Desativada, a conta não entra e as sessões abertas caem. Os dados continuam lá."""
    row = _target(s, actor_id, target_id)
    row.is_disabled = disabled
    if disabled:
        row.session_token = _new_token()
    return to_user(row)


def delete_user(s: Session, actor_id: int, target_id: int) -> list[str]:
    """Apaga a conta e tudo dela (coleção, pastas, decks, vitórias, versões e cartas personalizadas).
    Devolve as imagens que podem ter ficado sem uso, para apagar depois de gravar."""
    row = _target(s, actor_id, target_id)
    files = [row.avatar_filename] if row.avatar_filename else []
    for column, owner in ((CustomPrintRow.image_filename, CustomPrintRow.user_id),
                          (CustomCardRow.image_filename, CustomCardRow.user_id),
                          (DeckRow.cover_filename, DeckRow.user_id)):
        files += s.scalars(select(column).where(owner == target_id, column.is_not(None))).all()
    s.delete(row)  # o resto sai junto pelas chaves estrangeiras (ON DELETE CASCADE)
    s.flush()
    return files


BIO_MAX = config.BIO_MAX


def update_display_name(s: Session, user_id: int, display_name: str) -> User:
    row = _get(s, user_id)
    return update_profile(s, user_id, display_name, row.bio)


def update_profile(s: Session, user_id: int, display_name: str, bio: str = "") -> User:
    """Nome de exibição e bio (frase curta que aparece embaixo do nome no ranking)."""
    row = _get(s, user_id)
    bio = " ".join(bio.split())
    if len(bio) > BIO_MAX:
        raise AccountError(f"A bio pode ter até {BIO_MAX} caracteres.")
    if len(display_name.strip()) > config.DISPLAY_NAME_MAX:
        raise AccountError(f"O nome de exibição pode ter até {config.DISPLAY_NAME_MAX} caracteres.")
    row.display_name = display_name.strip() or row.username
    row.bio = bio
    return to_user(row)


THEMES = ("tubarao", "ilha", "planicie", "pantano", "montanha", "floresta")  # cores de cada um: ui/theme.py
THEME_MODES = ("auto", "light", "dark")


def set_theme(s: Session, user_id: int, theme: str, mode: str) -> User:
    """Tema da interface (cores) e modo claro/escuro/automático. Fica na conta: vale em qualquer aparelho."""
    if theme not in THEMES or mode not in THEME_MODES:
        raise AccountError("Tema desconhecido.")
    row = _get(s, user_id)
    row.theme, row.theme_mode = theme, mode
    return to_user(row)


def set_avatar(s: Session, user_id: int, filename: str | None) -> str | None:
    """Troca (ou tira, com None) o ícone. Devolve o arquivo antigo, que pode ter ficado sem uso."""
    row = _get(s, user_id)
    old, row.avatar_filename = row.avatar_filename, filename
    return old


def avatar_in_use(s: Session, filename: str) -> bool:
    return s.scalar(select(UserRow.id).where(UserRow.avatar_filename == filename)) is not None


def get_user(s: Session, user_id: int) -> User:
    return to_user(_get(s, user_id))


def list_users(s: Session) -> list[User]:
    return [to_user(r) for r in s.scalars(select(UserRow).order_by(UserRow.created_at))]


def invite_code(s: Session) -> str:
    row = s.get(SettingRow, INVITE_KEY)
    return row.value if row else regenerate_invite_code(s)


def new_invite_code(s: Session, actor_id: int) -> str:
    """Troca o código de convite (o anterior deixa de valer). Só o admin."""
    if not _get(s, actor_id).is_admin:
        raise AccountError("Só o administrador pode trocar o código de convite.")
    return regenerate_invite_code(s)


def regenerate_invite_code(s: Session) -> str:
    """Gera e grava um código novo, sem conferir permissão (uso interno; a tela usa new_invite_code)."""
    code = "".join(secrets.choice(INVITE_ALPHABET) for _ in range(8))
    row = s.get(SettingRow, INVITE_KEY)
    if row:
        row.value = code
    else:
        s.add(SettingRow(key=INVITE_KEY, value=code))
    return code


def _invite_matches(s: Session, code: str) -> bool:
    row = s.get(SettingRow, INVITE_KEY)
    cleaned = code.strip().upper().replace("-", "").replace(" ", "")
    return bool(row and cleaned and secrets.compare_digest(row.value, cleaned))


def _get(s: Session, user_id: int) -> UserRow:
    row = s.get(UserRow, user_id)
    if row is None:
        raise AccountError("Usuário não encontrado.")
    return row


def _verify(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _new_token() -> str:
    return secrets.token_hex(32)
