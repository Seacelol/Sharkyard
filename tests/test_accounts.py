import pytest
from sqlalchemy import func, select

from mtg_collection import database
from mtg_collection.database.tables import UserRow
from mtg_collection.services import accounts
from mtg_collection.services.accounts import AccountError


def register(username="marcelo", password="senha-forte-1", **kwargs):
    with database.session() as s:
        return accounts.register(s, username, password, **kwargs)


def invite() -> str:
    with database.session() as s:
        return accounts.invite_code(s)


def test_first_user_is_admin_and_needs_no_invite():
    user = register("Marcelo", display_name="  Marcelo A.  ")
    assert user.username == "marcelo" and user.display_name == "Marcelo A." and user.is_admin
    assert len(invite()) == 8


def test_password_stored_as_argon2_hash():
    register(password="senha-forte-1")
    with database.session() as s:
        row = s.scalar(select(UserRow))
    assert row.password_hash.startswith("$argon2") and "senha-forte-1" not in row.password_hash


def test_next_users_need_valid_invite():
    register()
    with pytest.raises(AccountError, match="convite"):
        register("amigo")
    with pytest.raises(AccountError, match="convite"):
        register("amigo", invite_code="ERRADO12")
    code = invite()
    friend = register("amigo", invite_code=f" {code[:4].lower()}-{code[4:].lower()} ")  # tolera formatação
    assert not friend.is_admin and friend.display_name == "amigo"


def test_regenerated_invite_invalidates_old():
    register()
    old = invite()
    with database.session() as s:
        new = accounts.regenerate_invite_code(s)
    assert new != old
    with pytest.raises(AccountError, match="convite"):
        register("amigo", invite_code=old)
    assert register("amigo", invite_code=new).username == "amigo"


def test_username_rules_and_uniqueness():
    for bad in ("ab", "a" * 21, "com espaço", "acentuação", "x@y"):
        with pytest.raises(AccountError, match="caracteres"):
            register(bad)
    register("Marcelo")
    with pytest.raises(AccountError, match="em uso"):
        register("MARCELO", invite_code=invite())


def test_password_min_length():
    with pytest.raises(AccountError, match="8 caracteres"):
        register(password="curta")


def test_authenticate():
    register("marcelo", "senha-forte-1")
    with database.session() as s:
        result = accounts.authenticate(s, " MARCELO ", "senha-forte-1")
        assert result is not None
        user, token = result
        assert user.username == "marcelo" and len(token) == 64
        assert accounts.authenticate(s, "marcelo", "errada") is None
        assert accounts.authenticate(s, "ninguem", "senha-forte-1") is None
    with database.session() as s:
        assert accounts.list_users(s)[0].last_login_at is not None


def test_session_token_and_password_change_invalidates_other_sessions():
    user = register()
    with database.session() as s:
        _, token = accounts.authenticate(s, "marcelo", "senha-forte-1")
        assert accounts.user_for_session(s, user.id, token).id == user.id
        assert accounts.user_for_session(s, user.id, "falso") is None
        assert accounts.user_for_session(s, 999, token) is None
        with pytest.raises(AccountError, match="atual está incorreta"):
            accounts.change_password(s, user.id, "errada", "nova-senha-123")
        with pytest.raises(AccountError, match="8 caracteres"):
            accounts.change_password(s, user.id, "senha-forte-1", "curta")
        new_token = accounts.change_password(s, user.id, "senha-forte-1", "nova-senha-123")
        assert new_token != token
        assert accounts.user_for_session(s, user.id, token) is None  # sessões antigas caem
        assert accounts.user_for_session(s, user.id, new_token) is not None
        assert accounts.authenticate(s, "marcelo", "nova-senha-123") is not None
        assert accounts.authenticate(s, "marcelo", "senha-forte-1") is None


def test_update_display_name():
    user = register()
    with database.session() as s:
        assert accounts.update_display_name(s, user.id, "  Marcelo Mello ").display_name == "Marcelo Mello"
        assert accounts.update_display_name(s, user.id, "   ").display_name == "marcelo"  # vazio volta ao usuário


def test_list_users_in_signup_order():
    register("primeiro")
    register("segundo", invite_code=invite())
    with database.session() as s:
        assert [u.username for u in accounts.list_users(s)] == ["primeiro", "segundo"]


def test_failed_register_leaves_no_trace():
    register()
    with pytest.raises(AccountError):
        register("amigo", invite_code="ERRADO12")
    with database.session() as s:
        assert len(accounts.list_users(s)) == 1


def test_profile_bio_and_avatar():
    from mtg_collection.services import accounts as acc
    with database.session() as s:
        acc.register(s, "marcelo", "senha-forte-1")
        user = acc.update_profile(s, 1, "  Marcelo  ", "  mono   red   ")
        assert (user.display_name, user.bio) == ("Marcelo", "mono red")
        with pytest.raises(acc.AccountError, match="20"):
            acc.update_profile(s, 1, "Marcelo", "x" * 21)
        assert acc.update_profile(s, 1, "Marcelo", "x" * 20).bio == "x" * 20
        assert acc.set_avatar(s, 1, "a.png") is None
        assert acc.avatar_in_use(s, "a.png")
        assert acc.set_avatar(s, 1, "b.png") == "a.png"
        assert not acc.avatar_in_use(s, "a.png")
        assert acc.update_display_name(s, 1, "Outro").bio == "x" * 20  # mudar só o nome mantém a bio


def test_only_admin_changes_invite_code():
    register("admin")
    with database.session() as s:
        code = accounts.invite_code(s)
    register("amigo", invite_code=code)
    with database.session() as s:
        with pytest.raises(AccountError, match="administrador"):
            accounts.new_invite_code(s, 2)
        assert accounts.new_invite_code(s, 1) != code


def _two_accounts():
    admin = register("admin")
    friend = register("amigo", invite_code=invite())
    return admin, friend


def test_reset_password_forces_new_one():
    admin, friend = _two_accounts()
    with database.session() as s:
        old_token = accounts.authenticate(s, "amigo", "senha-forte-1")[1]
        temporary = accounts.reset_password(s, admin.id, friend.id)
    assert len(temporary) == accounts.TEMP_LENGTH and set(temporary) <= set(accounts.TEMP_ALPHABET)
    with database.session() as s:
        assert accounts.user_for_session(s, friend.id, old_token) is None  # sessão aberta caiu
        assert accounts.authenticate(s, "amigo", "senha-forte-1") is None  # senha antiga não vale
        logged, token = accounts.authenticate(s, "amigo", temporary)
        assert logged.must_change_password
        with pytest.raises(AccountError, match="diferente da temporária"):
            accounts.set_new_password(s, friend.id, temporary)
        with pytest.raises(AccountError, match="pelo menos"):
            accounts.set_new_password(s, friend.id, "curta")
        new_token = accounts.set_new_password(s, friend.id, "minha-nova-senha")
        assert new_token != token and not accounts.get_user(s, friend.id).must_change_password
        with pytest.raises(AccountError, match="Minha conta"):  # sem senha temporária, precisa da atual
            accounts.set_new_password(s, friend.id, "outra-senha-qualquer")
    with database.session() as s:
        assert accounts.authenticate(s, "amigo", "minha-nova-senha") is not None


def test_only_admin_manages_accounts_and_not_own():
    admin, friend = _two_accounts()
    with database.session() as s:
        for action in (lambda: accounts.reset_password(s, friend.id, admin.id),
                       lambda: accounts.set_disabled(s, friend.id, admin.id, True),
                       lambda: accounts.delete_user(s, friend.id, admin.id)):
            with pytest.raises(AccountError, match="Só o administrador"):
                action()
        for action in (lambda: accounts.reset_password(s, admin.id, admin.id),
                       lambda: accounts.delete_user(s, admin.id, admin.id)):
            with pytest.raises(AccountError, match="própria conta"):
                action()


def test_disabled_account_cannot_log_in():
    admin, friend = _two_accounts()
    with database.session() as s:
        token = accounts.authenticate(s, "amigo", "senha-forte-1")[1]
        accounts.set_disabled(s, admin.id, friend.id, True)
    with database.session() as s:
        assert accounts.user_for_session(s, friend.id, token) is None
        assert accounts.authenticate(s, "amigo", "errada-123") is None  # senha errada: não diz que existe
        with pytest.raises(AccountError, match="desativada"):
            accounts.authenticate(s, "amigo", "senha-forte-1")
        assert accounts.set_disabled(s, admin.id, friend.id, False).is_disabled is False
    with database.session() as s:
        assert accounts.authenticate(s, "amigo", "senha-forte-1") is not None


def test_delete_user_removes_everything():
    from datetime import date

    from mtg_collection.database.tables import CollectionEntryRow, DeckRow, WinRow
    from mtg_collection.services import collection, decks, ranking
    from mtg_collection.services.scryfall import to_card
    from tests.sample_cards import BOLT as BOLT_JSON
    BOLT = to_card(BOLT_JSON)
    admin, friend = _two_accounts()
    with database.session() as s:
        collection.add_card(s, friend.id, BOLT, 4)
        collection.add_card(s, admin.id, BOLT, 1)
        deck = decks.create_deck(s, friend.id, "Burn")
        decks.add_card(s, friend.id, deck.id, BOLT, 4)
        decks.set_cover_image(s, friend.id, deck.id, "capa.png")
        accounts.set_avatar(s, friend.id, "icone.png")
        ranking.add_win(s, friend.id, deck.id, date(2026, 10, 1))
    with database.session() as s:
        assert sorted(accounts.delete_user(s, admin.id, friend.id)) == ["capa.png", "icone.png"]
    with database.session() as s:
        assert [u.username for u in accounts.list_users(s)] == ["admin"]
        assert s.scalar(select(func.count()).select_from(DeckRow)) == 0
        assert s.scalar(select(func.count()).select_from(WinRow)) == 0
        assert [r.user_id for r in s.scalars(select(CollectionEntryRow))] == [admin.id]  # a do admin fica
