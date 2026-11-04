from mtg_collection.models import Card, DeckCard
from mtg_collection.services import companion
from mtg_collection.services.deck_validation import validate


def line(name, cost, type_line, qty=1, section="main"):
    return DeckCard(id=0, deck_id=1, oracle_id=f"o-{name}", card_name=name, quantity=qty, section=section,
                    mana_cost=cost, type_line=type_line)


MOUNTAIN = line("Mountain", "", "Basic Land — Mountain", 20)
BOLT = line("Lightning Bolt", "{R}", "Instant", 4)
GOBLIN = line("Goblin Guide", "{R}", "Creature — Goblin Scout", 4)
GOYF = line("Tarmogoyf", "{1}{G}", "Creature — Lhurgoyf", 4)
TITAN = line("Inferno Titan", "{4}{R}{R}", "Creature — Giant", 1)
HELIX = line("Lightning Helix", "{R}{W}", "Instant", 4)
CAT = line("Leonin", "{W}", "Creature — Cat Soldier", 4)
WRATH = line("Wrath", "{2}{W}{W}", "Sorcery", 2)
RING = line("Sol Ring", "{1}", "Artifact", 1)


def run(name, deck, cards=None, minimum=60):
    return companion.check(name, deck, cards or {}, minimum)


def test_each_companion():
    assert run("Gyruda, Doom of Depths", [MOUNTAIN, GOYF, TITAN]) is None
    assert run("Gyruda, Doom of Depths", [BOLT, GOYF]) == \
        "Condição de Gyruda não cumprida (cada carta com valor de mana par): Lightning Bolt (1)."
    assert run("Jegantha, the Wellspring", [BOLT, HELIX, GOYF]) is None
    assert "Inferno Titan, Wrath" in run("Jegantha, the Wellspring", [TITAN, WRATH, BOLT])
    assert run("Kaheera, the Orphanguard", [CAT, BOLT, MOUNTAIN]) is None
    assert "Goblin Guide" in run("Kaheera, the Orphanguard", [CAT, GOBLIN])
    assert run("Keruga, the Macrosage", [TITAN, WRATH, MOUNTAIN]) is None
    assert "Lightning Bolt (1)" in run("Keruga, the Macrosage", [TITAN, BOLT])
    assert run("Lurrus of the Dream-Den", [GOBLIN, GOYF, MOUNTAIN, WRATH]) is None  # feitiço não é permanente
    assert "Inferno Titan (6)" in run("Lurrus of the Dream-Den", [GOYF, TITAN])
    assert run("Lutri, the Spellchaser", [line("A", "{R}", "Instant"), MOUNTAIN]) is None
    assert "Lightning Bolt (4)" in run("Lutri, the Spellchaser", [BOLT])
    assert run("Obosh, the Preypiercer", [BOLT, GOBLIN, MOUNTAIN]) is None
    assert "Tarmogoyf (2)" in run("Obosh, the Preypiercer", [BOLT, GOYF])
    assert run("Umori, the Collector", [GOBLIN, GOYF, MOUNTAIN]) is None
    assert "não têm um tipo em comum" in run("Umori, the Collector", [GOBLIN, BOLT])
    assert run("Yorion, Sky Nomad", [line("Island", "", "Basic Land — Island", 80)]) is None
    assert "pelo menos 80" in run("Yorion, Sky Nomad", [MOUNTAIN, BOLT])
    assert run("Not a companion", [BOLT]) is None


def test_zirda_uses_card_text():
    pick = Card(id="x", oracle_id="o-Pick", name="Pick", set_code="", set_name="", collector_number="",
                rarity="", type_line="Artifact — Equipment", mana_cost="{1}", oracle_text="Equip {2}: ...")
    statue = Card(id="y", oracle_id="o-Statue", name="Statue", set_code="", set_name="", collector_number="",
                  rarity="", type_line="Artifact", mana_cost="{1}", oracle_text="Flash (You may cast it: ok.)")
    deck = [line("Pick", "{1}", "Artifact — Equipment"), line("Statue", "{1}", "Artifact"), MOUNTAIN, BOLT]
    result = run("Zirda, the Dawnwaker", deck, {"o-Pick": pick, "o-Statue": statue})
    assert result == "Condição de Zirda não cumprida (cada permanente com uma habilidade ativada): Statue."


def test_validation_uses_condition_and_gladiator_rules():
    lurrus = line("Lurrus of the Dream-Den", "{1}{W/B}{W/B}", "Legendary Creature — Cat Nightmare", 1, "companion")
    warnings = validate("modern", [MOUNTAIN, TITAN, line("Plains", "", "Basic Land — Plains", 39), lurrus], {})
    assert warnings == ["Condição de Lurrus of the Dream-Den não cumprida (cada permanente com valor de mana 2 ou "
                        "menos): Inferno Titan (6)."]
    big = [line("Forest", "", "Basic Land — Forest", 105)]
    assert validate("gladiator", big, {}) == []  # no mínimo 100, não exatamente
    assert validate("gladiator", [*big, lurrus], {}) == ["Este formato não permite companheiro."]
