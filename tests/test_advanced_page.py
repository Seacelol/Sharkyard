import asyncio

from nicegui import ui
from nicegui.testing import User

from tests.conftest import FakeScryfall


def field(user: User, marker: str):
    return user.find(marker=marker).elements.pop()


def fill(user: User, **values) -> None:
    for marker, value in values.items():
        field(user, marker.replace("_", "-")).value = value


async def open_page(user: User) -> None:
    await user.open("/advanced")
    await asyncio.sleep(0.05)  # edições carregam depois da página aparecer


async def test_empty_form(user: User, fake_api: FakeScryfall):
    await open_page(user)
    await user.should_see("Preencha algum filtro")
    assert not field(user, "search").enabled


async def test_preview_updates_while_filling(user: User, fake_api: FakeScryfall):
    await open_page(user)
    fill(user, name="dragon", color_r=True, color_b=True, mv_op="<=", mv_value="5",
         format="commander", rarity_mythic=True, order="usd", direction="desc")
    field(user, "type-picker").value = "Legendary"
    field(user, "type-picker").value = "Creature"
    await user.should_see("dragon t:Legendary t:Creature c>=br mv<=5 f:commander r:mythic order:usd direction:desc")
    assert field(user, "search").enabled


async def test_identity_price_language_prints(user: User, fake_api: FakeScryfall):
    await open_page(user)
    fill(user, identity_w=True, identity_u=True, currency="eur", price_op="<", price_value="2",
         language="pt", all_prints=True, legality="banned", format="modern", pow_value="4", mana_cost="2RR")
    await user.should_see("id<=wu m:2RR pow>=4 banned:modern eur<2 lang:pt unique:prints")


async def test_sets_loaded_and_selectable(user: User, fake_api: FakeScryfall):
    await open_page(user)
    sets = field(user, "sets")
    assert sets.options == {"m10": "Magic 2010 (M10)", "2xm": "Double Masters (2XM)"}
    sets.value = ["m10", "2xm"]
    await user.should_see("(s:m10 OR s:2xm)")


async def test_search_opens_results_with_query(user: User, fake_api: FakeScryfall):
    await open_page(user)
    fill(user, oracle="draw a card", color_u=True)
    user.find(marker="search").click()
    await user.should_see("200 cartas encontradas")
    assert fake_api.search_queries[-1] == 'o:"draw a card" c>=u'
    assert user.find(ui.input).elements.pop().value == 'o:"draw a card" c>=u'  # consulta visível para ajustar


async def test_enter_in_text_field_searches(user: User, fake_api: FakeScryfall):
    await open_page(user)
    user.find(marker="artist").type("Rebecca Guay").trigger("keydown.enter")
    await user.should_see("200 cartas encontradas")
    assert fake_api.search_queries[-1] == 'a:"Rebecca Guay"'


async def test_clear_resets_everything(user: User, fake_api: FakeScryfall):
    await open_page(user)
    fill(user, name="bolt", color_r=True, color_mode="=", sets=["m10"], price_value="5", all_prints=True,
         order="usd", mv_op="<")
    await user.should_not_see("Preencha algum filtro")
    user.find(marker="clear").click()
    await user.should_see("Preencha algum filtro")
    assert field(user, "color-mode").value == ">=" and field(user, "sets").value == []
    assert field(user, "price-op").value == "<=" and field(user, "mv-op").value == ">="
    assert field(user, "color-r").value is False and field(user, "name").value == ""


async def test_search_page_has_shortcut_to_advanced(user: User, fake_api: FakeScryfall):
    await user.open("/search")
    user.find(marker="advanced-button").click()
    await user.should_see("Preencha algum filtro")


async def test_type_picker_options_grouped(user: User, fake_api: FakeScryfall):
    await open_page(user)
    picker = field(user, "type-picker")
    assert picker.options == {
        "Artifact": "Artifact · tipo", "Creature": "Creature · tipo", "Legendary": "Legendary · supertipo",
        "Dragon": "Dragon · tipo de criatura", "Human": "Human · tipo de criatura",
        "Time Lord": "Time Lord · tipo de criatura", "Equipment": "Equipment · tipo de artefato"}


async def test_type_picker_add_toggle_remove(user: User, fake_api: FakeScryfall):
    await open_page(user)
    picker = field(user, "type-picker")
    picker.value = "Creature"
    picker.value = "Human"
    picker.value = "Human"  # repetido não duplica
    assert picker.value is None  # campo limpa para o próximo
    assert len(user.find(marker="type-chip").elements) == 2
    await user.should_see("t:Creature t:Human")

    user.find(marker="type-toggle-Human").click()
    await user.should_see("t:Creature -t:Human")
    await user.should_see("NÃO")

    user.find(marker="type-toggle-Human").click()
    await user.should_see("t:Creature t:Human")

    user.find(marker="type-remove-Creature").click()
    await user.should_see("t:Human")
    assert len(user.find(marker="type-chip").elements) == 1

    picker.value = "Time Lord"
    await user.should_see('t:Human t:"Time Lord"')


async def test_clear_removes_types(user: User, fake_api: FakeScryfall):
    await open_page(user)
    field(user, "type-picker").value = "Dragon"
    await user.should_see("t:Dragon")
    user.find(marker="clear").click()
    await user.should_see("Preencha algum filtro")
    await user.should_not_see(marker="type-chip")


async def test_back_from_results_keeps_fields(user: User, fake_api: FakeScryfall):
    await open_page(user)
    fill(user, name="dragon", color_r=True, mv_op="<=", mv_value="5", rarity_mythic=True)
    field(user, "sets").value = ["m10"]
    field(user, "type-picker").value = "Creature"
    field(user, "type-picker").value = "Legendary"
    user.find(marker="type-toggle-Legendary").click()  # NÃO lendária
    user.find(marker="search").click()
    await user.should_see("200 cartas encontradas")
    user.find(marker="back-advanced").click()
    await asyncio.sleep(0.1)
    await user.should_see("dragon t:Creature -t:Legendary c>=r mv<=5 s:m10 r:mythic")
    assert field(user, "name").value == "dragon" and field(user, "rarity-mythic").value is True
    user.find(marker="clear").click()
    await user.should_see("Preencha algum filtro")
    await open_page(user)
    await user.should_see("Preencha algum filtro")  # limpar também esquece o formulário guardado


async def test_plain_search_has_no_back_button(user: User, fake_api: FakeScryfall):
    await user.open("/?q=bolt")
    await user.should_see("200 cartas encontradas")
    await user.should_not_see(marker="back-advanced")
