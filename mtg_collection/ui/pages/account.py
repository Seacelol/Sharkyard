"""Minha conta: perfil, senha e, para o administrador, convite e contas (senha temporária, desativar, apagar)."""
from nicegui import run, ui

from mtg_collection import config, database
from mtg_collection.services import accounts, login_throttle
from mtg_collection.ui import auth
from mtg_collection.ui.components.avatar import install_crop_script, open_avatar_dialog, user_avatar
from mtg_collection.ui.components.dialogs import close_dialog, confirm, limit
from mtg_collection.ui.custom_images import discard_unused
from mtg_collection.ui.layout import frame
from mtg_collection.ui.pages.login import blocked_message
from mtg_collection.ui.theme import theme_picker


def _change_password(user_id: int, current: str, new: str) -> str:
    with database.session() as s:  # fora do loop da interface: argon2 é lento de propósito
        return accounts.change_password(s, user_id, current, new)


def _section(title: str):
    card = ui.card().classes("w-full gap-3")
    with card:
        ui.label(title).classes("text-xs font-bold uppercase tracking-wider text-gray-500")
    return card


def _date(value) -> str:
    return value.astimezone().strftime("%d/%m/%Y %H:%M") if value else "-"


@ui.page("/account")
def account_page() -> None:
    user = auth.current_user()

    with frame("Minha conta"), ui.column().classes("w-full max-w-2xl mx-auto gap-5"):
        ui.label("Minha conta").classes("text-2xl font-bold")

        with _section("Perfil"):
            install_crop_script()
            # ícone à esquerda (clicar troca); nome e bio ao lado
            with ui.row().classes("w-full items-start gap-4 no-wrap"):
                avatar_area = ui.element("div").classes("relative shrink-0 cursor-pointer group rounded-full") \
                    .mark("profile-avatar").tooltip("Trocar ícone")
                avatar_area.on("click", lambda: open_avatar_dialog(user.id, user.display_name, current_avatar(),
                                                                   on_saved=avatar_saved))

                def show_avatar(filename: str | None) -> None:
                    avatar_area.clear()
                    with avatar_area:
                        user_avatar(display_name.value or user.display_name, filename, 88)
                        with ui.element("div").classes(
                                "absolute inset-0 rounded-full bg-black/45 flex items-center justify-center "
                                "opacity-0 group-hover:opacity-100 transition-opacity"):
                            ui.icon("photo_camera").classes("text-white text-2xl")
                        ui.icon("photo_camera").classes(  # no celular não existe "passar o mouse": selo fixo
                            "absolute -bottom-0.5 -right-0.5 text-sm mtg-on-primary bg-primary rounded-full p-1 "
                            "shadow sm:hidden")

                with ui.column().classes("gap-2 grow min-w-0"):
                    display_name = ui.input("Nome de exibição", value=user.display_name) \
                        .props(f"outlined dense {limit(config.DISPLAY_NAME_MAX)}").classes("w-full") \
                        .mark("display-name")
                    bio = ui.input("Bio", value=user.bio, placeholder="ex: só jogo de Boros") \
                        .props(f"outlined dense {limit(accounts.BIO_MAX)} "
                               'hint="Aparece no ranking"') \
                        .classes("w-full").mark("bio")
            ui.label(f"Usuário: {user.username}" + (" · administrador" if user.is_admin else "")) \
                .classes("text-sm text-gray-500")

            def current_avatar() -> str | None:
                with database.session() as s:
                    return accounts.get_user(s, user.id).avatar_filename

            def avatar_saved(filename: str | None) -> None:
                show_avatar(filename)
                ui.navigate.reload()  # o ícone do topo da página também muda

            def save_profile() -> None:
                try:
                    with database.session() as s:
                        updated = accounts.update_profile(s, user.id, display_name.value or "", bio.value or "")
                except accounts.AccountError as e:
                    ui.notify(str(e), type="negative")
                    return
                display_name.value, bio.value = updated.display_name, updated.bio
                ui.notify("Perfil salvo.", type="positive")

            ui.button("Salvar perfil", on_click=save_profile).props("unelevated no-caps").classes("self-end") \
                .mark("save-profile")
            show_avatar(user.avatar_filename)

        with ui.element("div").classes("w-full scroll-mt-20").props('id="aparencia"'), _section("Aparência"):
            theme_picker(user)

        with _section("Trocar senha"):
            current = ui.input("Senha atual", password=True, password_toggle_button=True) \
                .props('outlined dense autocomplete="current-password"').classes("w-full").mark("current-password")
            new = ui.input("Nova senha", password=True, password_toggle_button=True) \
                .props('outlined dense autocomplete="new-password"').classes("w-full").mark("new-password")
            confirm = ui.input("Confirmar nova senha", password=True, password_toggle_button=True) \
                .props('outlined dense autocomplete="new-password"').classes("w-full").mark("confirm-password")

            async def change_password() -> None:
                if new.value != confirm.value:
                    ui.notify("As senhas novas não conferem.", type="warning")
                    return
                address = auth.client_address()
                # mesma fila do login: trocas mandadas em paralelo não furam o limite de tentativas
                async with auth.attempt_locks.hold(user.username, address):
                    if wait := login_throttle.throttle.wait_seconds(user.username, address):
                        ui.notify(blocked_message(wait), type="negative")
                        return
                    try:
                        token = await run.io_bound(_change_password, user.id, current.value or "", new.value or "")
                    except accounts.AccountError as e:
                        if "atual" in str(e):  # senha atual errada conta como tentativa
                            login_throttle.throttle.failed(user.username, address)
                        ui.notify(str(e), type="negative")
                        return
                auth.start_session(user, token)  # este navegador continua logado; os outros saem
                for field in (current, new, confirm):
                    field.value = ""
                ui.notify("Senha alterada. Outros navegadores foram desconectados.", type="positive")

            ui.button("Trocar senha", on_click=change_password).props("unelevated no-caps").classes("self-start") \
                .mark("change-password")

        if user.is_admin:
            _admin_section(user.id)


def _still_admin(admin_id: int) -> bool:
    """Reconfere a sessão antes de cada ação de administrador. A página pode estar aberta há horas: se a sessão
    caiu (senha trocada, saiu em outra aba) ou a pessoa deixou de ser admin, a ação não roda."""
    user = auth.current_user()
    if user is None or user.id != admin_id or not user.is_admin:
        ui.notify("Sua sessão expirou. Entre de novo.", type="negative")
        return False
    return True


def _admin_section(user_id: int) -> None:
    with _section("Convidar amigos"):
        ui.label("Quem for criar conta precisa deste código. Gere um novo para invalidar o anterior.") \
            .classes("text-sm text-gray-600")
        with database.session() as s:
            code = accounts.invite_code(s)
        with ui.row().classes("items-center gap-3"):
            code_label = ui.label(code).classes("font-mono text-2xl tracking-widest").mark("invite-code")
            ui.button(icon="content_copy", on_click=lambda: ui.clipboard.write(code_label.text)) \
                .props("flat round").tooltip("Copiar")

            def regenerate() -> None:
                if not _still_admin(user_id):
                    return
                with database.session() as s:
                    code_label.text = accounts.new_invite_code(s, user_id)
                ui.notify("Novo código gerado. O anterior não vale mais.", type="positive")

            ui.button("Gerar novo código", icon="refresh", on_click=regenerate).props("flat no-caps") \
                .mark("regenerate-invite")

    with _section("Usuários"):
        ui.label("Quem esquecer a senha recebe uma senha temporária sua e cria uma nova no primeiro acesso.") \
            .classes("text-sm text-gray-600")
        UsersList(user_id)


def _reset_password(admin_id: int, target_id: int) -> str:
    with database.session() as s:  # fora do loop da interface: argon2 é lento de propósito
        return accounts.reset_password(s, admin_id, target_id)


class UsersList:
    """Lista de contas do admin. Uma por página aberta: um @ui.refreshable no módulo seria um só para todos os
    navegadores, e atualizar a lista numa aba mexeria na de outra pessoa."""

    def __init__(self, admin_id: int):
        self.admin_id = admin_id
        self.show()

    @ui.refreshable_method
    def show(self) -> None:
        with database.session() as s:
            users = accounts.list_users(s)
        with ui.column().classes("w-full gap-0").mark("users-list"):
            for u in users:
                self._row(u)

    def _row(self, u) -> None:
        with ui.row().classes("w-full items-center gap-3 no-wrap py-2 border-b border-gray-100") \
                .mark(f"user-{u.username}"):
            user_avatar(u.display_name, u.avatar_filename, 36)
            with ui.column().classes("gap-0 grow min-w-0"):
                with ui.row().classes("items-center gap-x-2 gap-y-0"):
                    ui.label(u.display_name).classes("font-medium")
                    ui.label(f"@{u.username}").classes("text-sm text-gray-500")
                    if u.is_admin:
                        ui.badge("Admin").props("color=primary")
                    if u.is_disabled:
                        ui.badge("Desativada").props("color=negative")
                    if u.must_change_password:
                        ui.badge("Senha temporária").props("color=warning text-color=black")
                ui.label(f"Criada em {_date(u.created_at)} · último acesso {_date(u.last_login_at)}") \
                    .classes("text-xs text-gray-500")
            if u.id == self.admin_id:
                return
            with ui.button(icon="more_vert").props("flat round dense").mark(f"user-actions-{u.username}"):
                with ui.menu():
                    ui.menu_item("Gerar senha temporária", on_click=lambda: self._ask_reset(u)) \
                        .mark(f"user-reset-{u.username}")
                    ui.menu_item("Reativar conta" if u.is_disabled else "Desativar conta",
                                 on_click=lambda: self._toggle_disabled(u)).mark(f"user-toggle-{u.username}")
                    ui.menu_item("Apagar conta", on_click=lambda: self._ask_delete(u)).classes("text-red-700") \
                        .mark(f"user-delete-{u.username}")

    def _ask_reset(self, u) -> None:
        async def reset() -> None:
            if not _still_admin(self.admin_id):
                return
            try:
                password = await run.io_bound(_reset_password, self.admin_id, u.id)
            except accounts.AccountError as e:
                ui.notify(str(e), type="negative")
                return
            self.show.refresh()
            _show_temporary(u, password)

        confirm(f"Gerar uma senha temporária para {u.display_name}?", reset, ok_label="Gerar senha",
                detail="A senha atual deixa de valer e a pessoa sai de onde estiver logada. No próximo acesso, "
                       "ela entra com a senha temporária e o app pede para criar uma nova.")

    def _toggle_disabled(self, u) -> None:
        if not _still_admin(self.admin_id):
            return
        try:
            with database.session() as s:
                updated = accounts.set_disabled(s, self.admin_id, u.id, not u.is_disabled)
        except accounts.AccountError as e:
            ui.notify(str(e), type="negative")
            return
        ui.notify(f"Conta de {u.display_name} desativada: não consegue entrar até você reativar."
                  if updated.is_disabled else f"Conta de {u.display_name} reativada.", type="positive")
        self.show.refresh()

    def _ask_delete(self, u) -> None:
        with ui.context.client.content, ui.dialog() as dialog, ui.card().classes("w-full max-w-sm gap-3"):
            ui.label(f"Apagar a conta de {u.display_name}?").classes("text-lg font-bold")
            ui.label("Apaga também a coleção, as pastas, os decks, as vitórias no ranking e as imagens dessa "
                     "pessoa. Não dá para desfazer. Se for só para bloquear o acesso, use Desativar conta.") \
                .classes("text-sm text-gray-600")
            typed = ui.input(f"Digite {u.username} para confirmar").props("outlined dense autocomplete=off") \
                .classes("w-full").mark("delete-confirm-name")

            def delete() -> None:
                if not _still_admin(self.admin_id):
                    close_dialog(dialog)
                    return
                try:
                    with database.session() as s:
                        files = accounts.delete_user(s, self.admin_id, u.id)
                except accounts.AccountError as e:
                    ui.notify(str(e), type="negative")
                    return
                discard_unused(files)  # depois de gravar: só apaga o arquivo se nada mais usa
                ui.notify(f"Conta de {u.display_name} apagada.", type="positive")
                close_dialog(dialog)
                self.show.refresh()

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancelar", on_click=lambda: close_dialog(dialog)).props("flat no-caps")
                button = ui.button("Apagar conta", on_click=delete).props("unelevated no-caps color=negative") \
                    .mark("delete-account-ok")
                button.bind_enabled_from(typed, "value", backward=lambda v: (v or "").strip().lower() == u.username)
        dialog.on("hide", lambda: close_dialog(dialog))
        dialog.open()


def _show_temporary(u, password: str) -> None:
    with ui.context.client.content, ui.dialog() as dialog, ui.card().classes("w-full max-w-sm gap-3"):
        ui.label(f"Senha temporária de {u.display_name}").classes("text-lg font-bold")
        with ui.row().classes("items-center gap-2"):
            ui.label(password).classes("font-mono text-2xl tracking-widest select-all").mark("temp-password")
            ui.button(icon="content_copy", on_click=lambda: ui.clipboard.write(password)) \
                .props("flat round").tooltip("Copiar")
        ui.label(f"Passe para a pessoa: usuário {u.username} e esta senha. Ela não aparece de novo depois de "
                 "fechar; se perder, gere outra.").classes("text-sm text-gray-600")
        ui.button("Fechar", on_click=lambda: close_dialog(dialog)).props("unelevated no-caps").classes("self-end")
    dialog.props("persistent")
    dialog.open()
