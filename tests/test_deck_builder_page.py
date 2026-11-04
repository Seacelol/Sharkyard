import asyncio

from nicegui.testing import User

from mtg_collection import database
from mtg_collection.services import collection as col
from mtg_collection.services import custom_cards as cc
from mtg_collection.services import decks, folders
from mtg_collection.services.scryfall import to_card
from tests.conftest import FakeScryfall, create_account
from tests.sample_cards import BOLT, BOLT_REPRINT, DELVER, LAND, LEGEND
from tests.sample_cards import GOLD as GOLD_HELIX


def run(fn, *args, **kwargs):
    with database.session() as s:
        return fn(s, *args, **kwargs)


def lines(deck_id: int):
    return [(c.card_name, c.quantity, c.section) for c in run(decks.list_cards, 1, deck_id)]


def set_value(user: User, marker: str, value) -> None:
    user.find(marker=marker).elements.pop().value = value


async def open_deck(user: User, name="Burn", fmt="modern"):
    deck = run(decks.create_deck, 1, name, format=fmt)
    await user.open(f"/deck/{deck.id}/edit")
    await user.should_see(marker="deck-name")
    return deck


async def test_empty_deck_and_other_users_deck(user: User, fake_api: FakeScryfall):
    deck = await open_deck(user)
    await user.should_see("O deck está vazio. Adicione cartas pelo painel ao lado.")
    await user.should_see("Modern")
    create_account("amigo")
    theirs = run(decks.create_deck, 2, "Do amigo")
    await user.open(f"/deck/{theirs.id}/edit")
    await user.should_see("Deck não encontrado.")
    assert deck.id != theirs.id


async def test_add_by_search_into_chosen_section(user: User, fake_api: FakeScryfall):
    deck = await open_deck(user)
    set_value(user, "search-qty", 3)
    user.find(marker="card-search").type("bo")
    await asyncio.sleep(0.2)
    user.find(marker="suggestion-1").trigger("mousedown.prevent")
    await user.should_see("3x Lightning Bolt no deck (principal).")
    set_value(user, "add-section", "sideboard")
    user.find(marker="card-search").type("bo")
    await asyncio.sleep(0.2)
    user.find(marker="suggestion-1").trigger("mousedown.prevent")
    await user.should_see(marker="section-sideboard")
    assert lines(deck.id) == [("Lightning Bolt", 3, "main"), ("Lightning Bolt", 1, "sideboard")]
    await user.should_see("3 cartas · 1 no sideboard")


async def test_plus_minus_and_remove_at_zero(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Burn")
    line = run(decks.add_card, 1, deck.id, to_card(BOLT), 2)
    await user.open(f"/deck/{deck.id}/edit")
    user.find(marker=f"line-plus-{line.id}").click()
    await user.should_see("3 cartas")
    user.find(marker=f"line-minus-{line.id}").click()
    user.find(marker=f"line-minus-{line.id}").click()
    user.find(marker=f"line-minus-{line.id}").click()
    await user.should_see("O deck está vazio.")
    assert lines(deck.id) == []


async def test_text_list_import(user: User, fake_api: FakeScryfall):
    deck = await open_deck(user)
    user.find(marker="tab-text").click()
    user.find(marker="decklist-text").type(
        "4 Lightning Bolt\n2x Wastes (OGW) 183\n1 Delver of Secrets\n0 Ponder\n1 Carta Que Nao Existe\n"
        "Sideboard\n2 Krenko, Mob Boss\n1 Outra Inexistente")
    user.find(marker="decklist-import").click()
    await user.should_see("9 cartas adicionadas.")
    await user.should_see("3 linhas não reconhecidas: ficaram na caixa acima para corrigir e adicionar de novo.")
    assert lines(deck.id) == [("Delver of Secrets // Insectile Aberration", 1, "main"),
                              ("Lightning Bolt", 4, "main"), ("Wastes", 2, "main"),
                              ("Krenko, Mob Boss", 2, "sideboard")]
    box = user.find(marker="decklist-text").elements.pop()
    assert box.value == "1 Carta Que Nao Existe\nSideboard\n1 Outra Inexistente\n0 Ponder"
    # identificadores em lote: edição e número quando vierem na lista
    assert {"set": "ogw", "collector_number": "183"} in fake_api.find_calls[0]


async def test_text_list_with_wrong_set_falls_back_to_name(user: User, fake_api: FakeScryfall):
    deck = await open_deck(user)
    user.find(marker="decklist-text").type("4 Lightning Bolt (XXX) 999")
    user.find(marker="decklist-import").click()
    await user.should_see("4 cartas adicionadas.")
    assert lines(deck.id) == [("Lightning Bolt", 4, "main")]


async def test_text_list_scryfall_down(user: User, fake_api: FakeScryfall):
    deck = await open_deck(user)
    fake_api.find_error = True
    user.find(marker="decklist-text").type("4 Lightning Bolt")
    user.find(marker="decklist-import").click()
    await user.should_see("Não deu para consultar o Scryfall")
    assert lines(deck.id) == []


async def test_add_from_collection_keeps_edition_and_flags(user: User, fake_api: FakeScryfall):
    entry = run(col.add_card, 1, fake_api.cards["1b"], 3, is_proxy=True, foil=True)
    deck = await open_deck(user)
    user.find(marker="tab-collection").click()
    await user.should_see(marker=f"collection-entry-{entry.id}")
    set_value(user, f"collection-qty-{entry.id}", 2)
    user.find(marker=f"add-entry-{entry.id}").click()
    await user.should_see("2x Lightning Bolt no deck.")
    [line] = run(decks.list_cards, 1, deck.id)
    assert (line.scryfall_id, line.quantity, line.is_proxy, line.foil) == ("1b", 2, True, True)
    await user.should_see(marker="badge-proxy")
    await user.should_see("tem 3 · 2 no deck · proxy · foil")


async def test_create_custom_card_only_in_deck_or_in_collection(user: User, fake_api: FakeScryfall):
    deck = await open_deck(user)
    user.find(marker="tab-custom").click()
    user.find(marker="new-custom-card").click()
    user.find(marker="cc-save").click()
    await user.should_see("Dê um nome para a carta.")
    user.find(marker="cc-name").type("Dragão do Marcelo")
    user.find(marker="cc-cost").type("{3}{R}")
    user.find(marker="cc-save").click()
    await user.should_see("Dragão do Marcelo criada e colocada no deck.")
    await user.should_see(marker="badge-custom-card")
    await user.should_see("só neste deck")
    user.find(marker="new-custom-card").click()
    user.find(marker="cc-name").type("Elfo Guardado")
    user.find(marker="cc-keep").click()
    user.find(marker="cc-save").click()
    await user.should_see("Elfo Guardado criada e colocada no deck.")
    assert [(e.card_name, e.custom_card_id is not None) for e in run(col.list_entries, 1)] == [("Elfo Guardado", True)]
    customs = {c.name: c for c in run(cc.available_for_deck, 1, deck.id)}
    assert not customs["Dragão do Marcelo"].in_collection and customs["Elfo Guardado"].in_collection
    assert sorted(lines(deck.id)) == [("Dragão do Marcelo", 1, "main"), ("Elfo Guardado", 1, "main")]
    assert run(decks.get_deck, 1, deck.id).colors == ("R",)


async def test_edit_line_dialog(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Burn")
    line = run(decks.add_card, 1, deck.id, to_card(BOLT), 4)
    await user.open(f"/deck/{deck.id}/edit")
    user.find(marker=f"edit-line-{line.id}").click()
    await user.should_see(marker="line-printing")
    await asyncio.sleep(0.1)  # edições carregam com o diálogo aberto
    set_value(user, "line-printing", "1b")
    set_value(user, "line-quantity", 2)
    set_value(user, "line-section", "sideboard")
    user.find(marker="line-proxy").click()
    user.find(marker="line-price").type("1,50")
    user.find(marker="line-save").click()
    await user.should_see(marker="badge-proxy")
    [saved] = run(decks.list_cards, 1, deck.id)
    assert (saved.scryfall_id, saved.quantity, saved.section, saved.is_proxy, saved.price_paid_cents) == (
        "1b", 2, "sideboard", True, 150)


async def test_custom_print_line_has_badge(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Burn")
    custom = run(col.create_custom_print, 1, fake_api.cards["1"], "Alter pintado")
    run(decks.add_card, 1, deck.id, col.as_card(custom, fake_api.cards["1"]))
    await user.open(f"/deck/{deck.id}/edit")
    await user.should_see(marker="badge-custom-print")
    await user.should_see("Alter pintado")


async def test_conclude_valid_deck_without_missing_cards(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Burn", format="modern")
    run(decks.add_card, 1, deck.id, to_card(BOLT), 4)
    run(decks.add_card, 1, deck.id, to_card(LAND), 56)
    run(col.add_card, 1, to_card(BOLT), 4)
    run(col.add_card, 1, to_card(LAND), 56)
    await user.open(f"/deck/{deck.id}/edit")
    user.find(marker="conclude").click()
    await user.should_see(marker="review-valid")
    await user.should_see("Deck válido em Modern.")
    user.find(marker="review-finish").click()
    await user.should_see("Meus decks")


async def test_conclude_with_warnings_and_add_missing(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Rakdos", format="commander")
    run(decks.add_card, 1, deck.id, to_card(LEGEND), 1, section="commander")
    bolt = run(decks.add_card, 1, deck.id, to_card(BOLT), 2)
    delver = run(decks.add_card, 1, deck.id, to_card(DELVER), 1, is_proxy=True)
    run(col.add_card, 1, to_card(BOLT_REPRINT), 1)
    binder = run(folders.create_folder, 1, folders.COLLECTION, "Commander")
    await user.open(f"/deck/{deck.id}/edit")
    user.find(marker="conclude").click()
    await user.should_see("O deck não está válido em Commander. Dá para concluir mesmo assim.")
    await user.should_see("• O deck tem 4 cartas; o formato pede exatamente 100.")
    await user.should_see("• Lightning Bolt: 2 cópias; o máximo é 1 cópia.")
    await user.should_see("• Fora da identidade de cor do comandante: Delver of Secrets // Insectile Aberration.")
    # corrige na própria revisão: tira o Delver e o aviso some
    user.find(marker=f"review-delete-{delver.id}").click()
    await user.should_not_see("Fora da identidade de cor")
    user.find(marker="review-finish").click()
    await user.should_see("Adicionar à coleção?")
    await user.should_see("2 cartas do deck não estão na sua coleção.")
    set_value(user, "missing-folder", binder.id)
    user.find(marker="missing-add").click()
    await user.should_see("Meus decks")
    entries = {(e.card_name, e.folder_id): e.quantity for e in run(col.list_entries, 1)}
    assert entries == {("Lightning Bolt", None): 1, ("Lightning Bolt", binder.id): 1,
                       ("Krenko, Mob Boss", binder.id): 1}
    assert bolt.id


async def test_conclude_skip_missing(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Casual", format="casual")
    run(decks.add_card, 1, deck.id, to_card(BOLT), 9)
    await user.open(f"/deck/{deck.id}/edit")
    user.find(marker="conclude").click()
    await user.should_see("Deck sem formato definido: as regras não são conferidas.")
    user.find(marker="review-finish").click()
    user.find(marker="missing-skip").click()
    await user.should_see("Meus decks")
    assert run(col.list_entries, 1) == []


async def test_new_custom_version_from_line_dialog(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Burn")
    line = run(decks.add_card, 1, deck.id, to_card(BOLT), 4)
    await user.open(f"/deck/{deck.id}/edit")
    user.find(marker=f"edit-line-{line.id}").click()
    await asyncio.sleep(0.1)
    user.find(marker="line-new-version").click()
    user.find(marker="custom-name").type("Arte do amigo")
    user.find(marker="custom-save").click()
    await user.should_see("Versão salva.")
    [custom] = run(col.list_custom_prints, 1, "o-bolt")
    assert user.find(marker="line-printing").elements.pop().value == f"custom-{custom.id}"
    user.find(marker="line-save").click()
    await user.should_see(marker="badge-custom-print")
    [saved] = run(decks.list_cards, 1, deck.id)
    assert (saved.custom_print_id, saved.set_name, saved.quantity) == (custom.id, "Arte do amigo", 4)


async def test_edit_custom_card_updates_deck_line(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Burn")
    custom = run(cc.create, 1, name="Rascunho", deck_id=deck.id)
    line = run(decks.add_card, 1, deck.id, cc.as_card(custom), 2)
    await user.open(f"/deck/{deck.id}/edit")
    user.find(marker=f"edit-line-{line.id}").click()
    await user.should_see(marker="line-edit-custom")
    user.find(marker="line-edit-custom").click()
    user.find(marker="cc-name").clear().type("Versão final")
    user.find(marker="cc-cost").type("{G}")
    user.find(marker="cc-save").click()
    await user.should_see("Carta personalizada salva.")
    await user.should_see("Versão final")
    [saved] = run(decks.list_cards, 1, deck.id)
    assert (saved.card_name, saved.mana_cost, saved.color_identity, saved.quantity) == ("Versão final", "{G}", "G", 2)


# ---------- zona de comando ----------
async def pick(user: User, marker: str, text: str, card_id: str) -> None:
    user.find(marker=marker).type(text)
    await asyncio.sleep(0.2)
    user.find(marker=f"{marker}-suggestion-{card_id}").trigger("mousedown.prevent")
    await asyncio.sleep(0.05)


async def test_create_commander_deck_with_partners_and_companion(user: User, fake_api: FakeScryfall):
    await user.open("/decks")
    user.find(marker="new-deck").click()
    user.find(marker="deck-name").type("Partners")
    await user.should_not_see("Comandante")  # sem formato: não tem comandante
    user.find(marker="deck-format").elements.pop().value = "commander"
    await user.should_see("Comandante")
    await pick(user, "commander-pick", "Krenko", "5")
    assert fake_api.where_calls[-1] == ("Krenko", "is:commander")
    await user.should_see("Krenko, Mob Boss não tem parceiro.")
    user.find(marker="commander-pick-clear").click()
    await pick(user, "commander-pick", "ty", "7")  # Tymna
    # parceiro: só sugere quem pode ser par (Thrasios), mesmo com o texto batendo em outras
    user.find(marker="partner-pick").type("os")  # bate em Thrasios e em Krenko, Mob Boss
    await asyncio.sleep(0.2)
    await user.should_see(marker="partner-pick-suggestion-8")
    await user.should_not_see(marker="partner-pick-suggestion-5")
    user.find(marker="partner-pick-suggestion-8").trigger("mousedown.prevent")
    await asyncio.sleep(0.05)
    await pick(user, "companion-pick", "Lutri", "9")
    assert fake_api.where_calls[-1] == ("Lutri", "is:companion")
    user.find(marker="deck-save").click()
    await user.should_see("Deck \"Partners\" criado.")
    [deck] = run(decks.list_decks, 1)
    assert lines(deck.id) == [("Thrasios, Triton Hero", 1, "commander"), ("Tymna the Weaver", 1, "commander"),
                              ("Lutri, the Spellchaser", 1, "companion")]
    assert deck.colors == ("W", "U", "B", "G") and deck.card_count == 2


async def test_edit_command_zone_in_builder_and_identity_search(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Goblins", format="commander")
    await user.open(f"/deck/{deck.id}/edit")
    await user.should_see("Sem comandante")
    await user.should_not_see(marker="identity-filter")
    user.find(marker="edit-command-zone").click()
    await user.should_see(marker="commander-pick")
    await pick(user, "commander-pick", "Krenko", "5")
    user.find(marker="zone-save").click()
    await user.should_see("Zona de comando salva.")
    await user.should_see(marker="zone-commander")
    assert lines(deck.id) == [("Krenko, Mob Boss", 1, "commander")]
    # a busca do deck passa a sugerir só cartas na identidade do comandante
    await user.should_see(marker="identity-filter")
    user.find(marker="card-search").type("bo")
    await asyncio.sleep(0.2)
    assert fake_api.where_calls[-1] == ("bo", "id<=r")
    user.find(marker="identity-filter").click()  # desmarca: volta às sugestões normais
    user.find(marker="card-search").clear().type("bol")
    await asyncio.sleep(0.2)
    assert fake_api.where_calls[-1] == ("bo", "id<=r")
    # editar de novo: o comandante atual vem preenchido; tirar e salvar remove
    user.find(marker="edit-command-zone").click()
    await user.should_see(marker="commander-pick-chosen")
    user.find(marker="commander-pick-clear").click()
    user.find(marker="zone-save").click()
    await user.should_see("Sem comandante")
    assert lines(deck.id) == []


async def test_editing_deck_keeps_commander_and_edition(user: User, fake_api: FakeScryfall):
    from tests.sample_cards import LEGEND
    deck = run(decks.create_deck, 1, "Goblins", format="commander")
    run(decks.set_commanders, 1, deck.id, [to_card(LEGEND)])
    run(decks.add_card, 1, deck.id, to_card(BOLT), 1)
    await user.open(f"/deck/{deck.id}/edit")
    user.find(marker="edit-deck").click()
    await user.should_see(marker="commander-pick-chosen")
    user.find(marker="deck-notes").type("goblins")
    user.find(marker="deck-save").click()
    await user.should_see("Deck salvo.")
    assert lines(deck.id) == [("Krenko, Mob Boss", 1, "commander"), ("Lightning Bolt", 1, "main")]


# ---------- versões ----------
async def test_versions_in_builder(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Burn", format="modern")
    run(decks.add_card, 1, deck.id, to_card(BOLT), 4)
    await user.open(f"/deck/{deck.id}/edit")
    select = user.find(marker="version-select").elements.pop()
    assert list(select.options.values()) == ["Original (4)"]
    user.find(marker="new-version").click()
    user.find(marker="ask-text").type("Sem Bolt")
    user.find(marker="ask-ok").click()
    await user.should_see("Versão \"Sem Bolt\" criada a partir de \"Original\".")
    [line] = run(decks.list_cards, 1, deck.id)
    user.find(marker=f"line-minus-{line.id}").click()
    user.find(marker=f"line-minus-{line.id}").click()
    await user.should_see("2 cartas")
    select = user.find(marker="version-select").elements.pop()
    assert list(select.options.values()) == ["Original (4)", "Sem Bolt (2)"]
    first = next(k for k, v in select.options.items() if v.startswith("Original"))
    select.value = first
    await user.should_see("4 cartas")
    assert run(decks.get_deck, 1, deck.id).version_name == "Original"
    # a grade mostra a versão atual
    await user.open("/decks")
    await user.should_see("Modern · 4 cartas · Original (2 versões)")
    await user.open(f"/deck/{deck.id}/edit")
    user.find(marker="rename-version").click()
    user.find(marker="ask-text").clear().type("Torneio")
    user.find(marker="ask-ok").click()
    await user.should_see("Torneio (4)")
    user.find(marker="delete-version").click()
    user.find(marker="confirm-ok").click()
    await user.should_see("Versão apagada. Agora você está em \"Sem Bolt\".")
    assert [v.name for v in run(decks.list_versions, 1, deck.id)] == ["Sem Bolt"]


# ---------- estatísticas ----------
async def test_stats_tab_per_version(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Burn", format="modern")
    run(decks.add_card, 1, deck.id, to_card(BOLT), 4)
    run(decks.add_card, 1, deck.id, to_card(DELVER), 2)
    run(decks.add_card, 1, deck.id, to_card(LAND), 4)
    run(col.add_card, 1, to_card(BOLT), 4)
    await user.open(f"/deck/{deck.id}/edit")
    await user.should_not_see(marker="stat-cards")  # só calcula com a aba aberta
    user.find(marker="view-stats").click()
    await user.should_see(marker="curve-chart")

    def tile(marker: str) -> str:
        return " ".join(e.text for e in user.find(marker=marker).elements.pop().descendants() if hasattr(e, "text"))

    assert "10" in tile("stat-cards") and "40% do deck" in tile("stat-lands")
    assert "1,00" in tile("stat-average") and "6" in tile("stat-missing")
    await asyncio.sleep(0.1)
    # Bolt (1.25 x 4) + Delver (0.10 x 2) + Wastes sem preço
    assert "US$ 5,20" in tile("stat-value")
    # outra versão: estatísticas próprias
    run(decks.create_version, 1, deck.id, "Só terrenos")
    for line in run(decks.list_cards, 1, deck.id):
        if line.card_name != "Wastes":
            run(decks.remove_line, 1, deck.id, line.id)
    await user.open(f"/deck/{deck.id}/edit")
    user.find(marker="view-stats").click()
    await user.should_see(marker="stat-cards")
    assert "4" in tile("stat-cards") and "100% do deck" in tile("stat-lands")


async def test_export_dialog(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Burn", format="modern")
    run(decks.add_card, 1, deck.id, to_card(BOLT), 4)
    run(decks.add_card, 1, deck.id, to_card(LAND), 20)
    run(decks.add_card, 1, deck.id, to_card(DELVER), 2)
    await user.open(f"/deck/{deck.id}/edit")
    # lista dividida por tipo
    await user.should_see(marker="group-creature")
    await user.should_see(marker="group-instant")
    await user.should_see(marker="group-land")
    await user.should_see("Mágicas instantâneas")
    user.find(marker="export-deck").click()
    preview = user.find(marker="export-preview").elements.pop()
    assert preview.value == "2 Delver of Secrets // Insectile Aberration\n4 Lightning Bolt\n20 Wastes\n"
    user.find(marker="export-format").elements.pop().value = "arena"
    assert preview.value.startswith("Deck\n2 Delver of Secrets (ISD) 51\n4 Lightning Bolt (M10) 146\n")
    user.find(marker="export-download").click()
    user.find(marker="export-copy").click()
    await user.should_see("Copiado.")


async def test_compare_versions_dialog(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Burn", format="modern")
    run(decks.add_card, 1, deck.id, to_card(BOLT), 4)
    run(decks.add_card, 1, deck.id, to_card(DELVER), 2, section="sideboard")
    run(decks.create_version, 1, deck.id, "Nova")
    for line in run(decks.list_cards, 1, deck.id):
        if line.section == "sideboard":
            run(decks.remove_line, 1, deck.id, line.id)
        else:
            run(decks.change_quantity, 1, deck.id, line.id, -1)
    run(decks.add_card, 1, deck.id, to_card(LAND), 3)
    await user.open(f"/deck/{deck.id}/edit")
    user.find(marker="compare-versions").click()
    await user.should_see("3 carta(s) a mais e 3 a menos em \"Nova\".")
    await user.should_see(marker="compare-in")
    await user.should_see("Delver of Secrets // Insectile Aberration (sideboard)")
    await user.should_see("4 → 3")
    b = user.find(marker="compare-b").elements.pop()
    user.find(marker="compare-a").elements.pop().value = b.value
    await user.should_see("Escolha duas versões diferentes.")


async def test_stats_sources_and_probabilities(user: User, fake_api: FakeScryfall):
    deck = run(decks.create_deck, 1, "Burn", format="modern")
    run(decks.add_card, 1, deck.id, to_card(BOLT), 4)
    run(decks.add_card, 1, deck.id, to_card(GOLD_HELIX), 36)
    run(decks.add_card, 1, deck.id, to_card(LAND), 20)
    await user.open(f"/deck/{deck.id}/edit")
    user.find(marker="view-stats").click()
    await user.should_see(marker="hand-distribution")
    # 20 terrenos em 60: chance de 2 a 4 na mão de 7
    await user.should_see("Chance de abrir com 2 a 4 terrenos: 72%")
    await user.should_see(marker="draw-result")
    card = user.find(marker="draw-card").elements.pop()
    card.value = "o-bolt"
    user.find(marker="draw-turn").elements.pop().value = 1
    await user.should_see("40% de ter pelo menos uma de 4 cópias até o turno 1 (7 cartas vistas")
    user.find(marker="draw-play").elements.pop().value = False
    await user.should_see("até o turno 1 (8 cartas vistas")
    await asyncio.sleep(0.1)
    await user.should_see(marker="stats-sources")  # Wastes: incolor
    await user.should_see("Incolor")


async def test_long_notes_collapse_and_expand(user: User, fake_api: FakeScryfall):
    long_text = "Lista do torneio de sábado. " * 12
    deck = run(decks.create_deck, 1, "Burn", notes=long_text)
    short = run(decks.create_deck, 1, "Curto", notes="aggro")
    await user.open(f"/deck/{deck.id}/edit")
    text = user.find(marker="deck-notes-text").elements.pop()
    assert "line-clamp-3" in text.classes
    user.find(marker="deck-notes-toggle").click()
    assert "line-clamp-3" not in text.classes
    await user.should_see("ver menos")
    user.find(marker="deck-notes-toggle").click()
    assert "line-clamp-3" in text.classes
    await user.open(f"/deck/{short.id}/edit")
    await user.should_see("aggro")
    await user.should_not_see(marker="deck-notes-toggle")


async def test_plus_minus_updates_in_place_and_collection_loads_on_demand(user: User, fake_api: FakeScryfall,
                                                                           monkeypatch):
    from mtg_collection.ui.pages import deck_builder
    calls = []
    real = deck_builder.collection.list_entries
    monkeypatch.setattr(deck_builder.collection, "list_entries", lambda *a, **k: calls.append(1) or real(*a, **k))
    deck = run(decks.create_deck, 1, "Burn")
    bolt = run(decks.add_card, 1, deck.id, to_card(BOLT), 2)
    run(decks.add_card, 1, deck.id, to_card(LAND), 10)
    run(col.add_card, 1, to_card(BOLT), 1)
    await user.open(f"/deck/{deck.id}/edit")
    name_row = user.find(marker=f"deck-line-{bolt.id}").elements.pop()
    user.find(marker=f"line-plus-{bolt.id}").click()
    await user.should_see("13 cartas")
    assert user.find(marker=f"line-qty-{bolt.id}").elements.pop().text == "3"
    assert not name_row.is_deleted  # a linha não foi redesenhada
    assert calls == []  # a coleção não foi lida com a aba fechada
    user.find(marker="tab-collection").click()
    await user.should_see("tem 1 · 3 no deck")
    assert len(calls) == 1
    user.find(marker=f"line-minus-{bolt.id}").click()
    await user.should_see("tem 1 · 2 no deck")  # aba aberta: acompanha sem reler a coleção
    assert len(calls) == 1
    user.find(marker=f"edit-line-{bolt.id}").click()
    await user.should_see(marker="line-quantity")
    assert user.find(marker="line-quantity").elements.pop().value == 2  # o lápis abre com a quantidade atual
