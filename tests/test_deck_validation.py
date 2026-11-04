from mtg_collection.models import DeckCard
from mtg_collection.services import deck_validation
from mtg_collection.services.deck_validation import validate
from mtg_collection.services.scryfall import to_card
from tests.conftest import FakeScryfall
from tests.sample_cards import BOLT, DELVER, GOLD, LAND, LEGEND, RATS

CARDS = {c.oracle_id: c for c in map(to_card, (BOLT, DELVER, GOLD, LAND, LEGEND, RATS))}


def line(card, quantity=1, section="main", **extra):
    c = CARDS[card] if isinstance(card, str) else card
    return DeckCard(id=0, deck_id=1, oracle_id=c.oracle_id, card_name=c.name, quantity=quantity, section=section,
                    color_identity="".join(c.color_identity), type_line=c.type_line, rarity=c.rarity, **extra)


def filler(n, section="main"):
    """n terrenos básicos: completam o tamanho sem gerar aviso."""
    return [line("o-wastes", n, section)] if n else []


def test_no_format_or_casual_is_never_checked():
    assert validate("", [line("o-bolt", 9)], CARDS) == []
    assert validate("casual", [line("o-bolt", 9)], CARDS) == []


def test_constructed_valid_and_size():
    assert validate("modern", [line("o-bolt", 4), *filler(56)], CARDS) == []
    assert validate("modern", [line("o-bolt", 4), *filler(50)], CARDS) == [
        "O deck tem 54 cartas; o formato pede no mínimo 60."]


def test_copies_basic_lands_and_any_number():
    warnings = validate("modern", [line("o-bolt", 5), line("o-rats", 20), *filler(40)], CARDS)
    assert warnings == ["Lightning Bolt: 5 cópias; o máximo é 4 cópias."]


def test_copies_count_main_and_sideboard_together():
    warnings = validate("modern", [line("o-bolt", 3), line("o-bolt", 2, "sideboard"), *filler(57)], CARDS)
    assert warnings == ["Lightning Bolt: 5 cópias; o máximo é 4 cópias."]


def test_sideboard_limit_and_maybe_ignored():
    deck = [*filler(60), line("o-delver", 4, "sideboard"), *filler(12, "sideboard"), line("o-bolt", 30, "maybe")]
    assert validate("modern", deck, CARDS) == ["O sideboard tem 16 cartas; o máximo é 15."]


def test_legality_banned_not_legal_restricted():
    assert validate("standard", [line("o-bolt"), *filler(59)], CARDS) == [
        "Lightning Bolt não é legal neste formato."]
    assert validate("vintage", [line("o-bolt", 2), *filler(58)], CARDS) == [
        "Lightning Bolt: 2 cópias; o máximo é 1 cópia."]
    assert validate("vintage", [line("o-bolt", 1), *filler(59)], CARDS) == []


def test_unknown_card_data_only_skips_legality():
    assert validate("standard", [line("o-bolt", 5), *filler(55)], {}) == [
        "Lightning Bolt: 5 cópias; o máximo é 4 cópias."]


def test_commander_valid():
    deck = [line("o-krenko", section="commander"), line("o-bolt"), *filler(98)]
    assert validate("commander", deck, CARDS) == []


def test_commander_problems():
    deck = [line("o-bolt", section="commander"), line("o-bolt", 2), line("o-delver"), line("o-gold"),
            line("o-rats", 30), *filler(60), line("o-delver", 1, "sideboard")]
    assert validate("commander", deck, CARDS) == [
        "O deck tem 95 cartas; o formato pede exatamente 100.",
        "Este formato não usa sideboard; as cartas do sideboard ficam de fora.",
        "Lightning Bolt não pode ser comandante neste formato.",
        "Fora da identidade de cor do comandante: Delver of Secrets // Insectile Aberration, Lightning Helix, "
        "Relentless Rats.",
        "Lightning Bolt: 3 cópias; o máximo é 1 cópia.",
    ]


def test_commander_missing():
    assert validate("commander", [line("o-bolt"), *filler(99)], CARDS) == [
        "Falta o comandante: escolha no topo da página do deck."]


def test_custom_cards_always_warn():
    from mtg_collection.models import Card
    custom = Card(id="customcard-1", oracle_id="customcard-1", name="Meu Dragão", set_code="", set_name="",
                  collector_number="", rarity="special", type_line="Legendary Creature", mana_cost="",
                  oracle_text="")
    deck = [line(custom, section="commander", custom_card_id=1), *filler(99)]
    assert validate("commander", deck, CARDS) == [
        "Cartas personalizadas não valem em formatos oficiais: Meu Dragão."]


async def test_check_fetches_by_oracle_id(monkeypatch):
    fake = FakeScryfall()
    monkeypatch.setattr(deck_validation.scryfall.client, "find_cards", fake.find_cards)
    deck = [line("o-bolt"), line("o-bolt", 1, "maybe"), *filler(59)]
    assert await deck_validation.check("standard", deck) == ["Lightning Bolt não é legal neste formato."]
    assert fake.find_calls == [[{"oracle_id": "o-bolt"}, {"oracle_id": "o-wastes"}]]
    assert await deck_validation.check("casual", deck) == [] and len(fake.find_calls) == 1
    fake.find_error = True
    warnings = await deck_validation.check("standard", deck)
    assert warnings == ["Não deu para consultar a legalidade das cartas no Scryfall agora; o resto foi conferido."]
