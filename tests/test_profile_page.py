import base64

from nicegui.testing import User

from mtg_collection import config, database
from mtg_collection.services import accounts, decks, ranking
from tests.conftest import FakeScryfall, create_account

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def png_data_url(data: bytes = PNG) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode()


async def test_bio_saved_and_shown_in_ranking(user: User, fake_api: FakeScryfall):
    await user.open("/account")
    user.find(marker="bio").type("Só jogo de Boros")
    user.find(marker="save-profile").click()
    await user.should_see("Perfil salvo.")
    with database.session() as s:
        assert accounts.get_user(s, 1).bio == "Só jogo de Boros"
        deck = decks.create_deck(s, 1, "Boros", visibility="friends")
        from datetime import date
        ranking.add_win(s, 1, deck.id, date.today())
    await user.open("/ranking")
    user.find(marker="tab-players").click()
    await user.should_see(marker="player-bio-1")
    await user.should_see("Só jogo de Boros")


async def test_bio_too_long(user: User, fake_api: FakeScryfall):
    await user.open("/account")
    user.find(marker="bio").elements.pop().value = "x" * 25  # o campo limita a 20, mas o servidor também confere
    user.find(marker="save-profile").click()
    await user.should_see("A bio pode ter até 20 caracteres.")


async def test_avatar_saved_served_and_replaced(user: User, fake_api: FakeScryfall):
    from mtg_collection.ui.components.avatar import save_avatar_png
    await user.open("/account")
    await user.should_see(marker="avatar-initial")  # sem ícone: inicial do nome
    user.find(marker="profile-avatar").click()
    await user.should_see(marker="avatar-crop")
    first = save_avatar_png(1, png_data_url())
    assert (await user.http_client.get(f"/avatar/{first}")).status_code == 200
    second = save_avatar_png(1, png_data_url(PNG + b"1"))
    assert not (config.CUSTOM_IMAGES_DIR / first).exists()  # o antigo é apagado
    assert (await user.http_client.get(f"/avatar/{first}")).status_code == 404
    await user.open("/account")
    await user.should_see(marker="avatar-img")
    # outro usuário logado também vê (o ícone aparece no ranking)
    create_account("amigo")
    assert (await user.http_client.get(f"/avatar/{second}")).status_code == 200
    assert (await user.http_client.get(f"/avatar/{'f' * 32}.png")).status_code == 404


def test_save_avatar_rejects_other_formats():
    import pytest

    from mtg_collection.ui.components.avatar import save_avatar_png
    from mtg_collection.ui.custom_images import ImageError
    with pytest.raises(ImageError):
        save_avatar_png(1, "data:text/plain;base64,aGk=")
