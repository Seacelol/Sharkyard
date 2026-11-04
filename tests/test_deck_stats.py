from mtg_collection.models import DeckCard
from mtg_collection.services.deck_stats import compute, mana_value, pips


def line(name, cost, type_line, quantity=1, section="main", **extra):
    return DeckCard(id=0, deck_id=1, oracle_id=f"o-{name}", card_name=name, quantity=quantity, section=section,
                    mana_cost=cost, type_line=type_line, **extra)


def test_mana_value():
    assert mana_value("{2}{W}{W}") == 4
    assert mana_value("{X}{R}") == 1
    assert mana_value("{2/W}{W/U}{G/P}") == 4
    assert mana_value("") == 0
    assert mana_value("{1}{R} // {2}{U}", "Instant // Instant") == 5  # carta dividida soma
    assert mana_value("{3}{G} // {1}{G}", "Creature — Giant // Sorcery — Adventure") == 4


def test_pips():
    assert pips("{2}{W}{W}{W/U}{G/P}") == {"W": 3, "U": 1, "G": 1}


def test_compute():
    lines = [
        line("Bolt", "{R}", "Instant", 4, rarity="common", price_paid_cents=150),
        line("Goblin", "{1}{R}", "Creature — Goblin", 3, rarity="common", is_proxy=True),
        line("Titan", "{6}{R}{R}", "Artifact Creature — Golem", 1, rarity="mythic"),
        line("Krenko", "{2}{R}{R}", "Legendary Creature — Goblin", 1, "commander", rarity="rare"),
        line("Mountain", "", "Basic Land — Mountain", 10, rarity="common"),
        line("Pathway", "{G}", "Instant // Land", 1, rarity="rare", custom_print_id=3),  # mágica pela frente
        line("Side", "{U}", "Instant", 2, "sideboard"),
        line("Talvez", "{U}", "Instant", 9, "maybe"),
        line("Lutri", "{3}{U/R}{U/R}", "Legendary Creature — Otter", 1, "companion"),
    ]
    stats = compute(lines)
    assert (stats.cards, stats.lands, stats.spells) == (20, 10, 10)
    # (4x1 + 3x2 + 8 + 4 + 1) / 10
    assert stats.average_mana_value == 2.3
    assert stats.curve == {0: 0, 1: 5, 2: 3, 3: 0, 4: 1, 5: 0, 6: 0, 7: 1}
    assert stats.creature_curve == {0: 0, 1: 0, 2: 3, 3: 0, 4: 1, 5: 0, 6: 0, 7: 1}
    assert stats.types == [("Criaturas", 5), ("Mágicas instantâneas", 5), ("Artefatos", 1), ("Terrenos", 10)]
    assert stats.pips == {"R": 4 + 3 + 2 + 2, "G": 1}
    assert stats.rarities == [("Comum", 17), ("Rara", 2), ("Mítica", 1)]
    assert (stats.proxies, stats.custom, stats.paid_cents, stats.priced_cards) == (3, 1, 600, 4)


def test_empty():
    stats = compute([])
    assert stats.cards == 0 and stats.average_mana_value == 0 and stats.types == []


def test_group_by_type():
    from mtg_collection.services.deck_stats import group_by_type, type_group
    assert type_group("Artifact Creature — Golem") == "creature"
    assert type_group("Land Creature — Forest Dryad") == "creature"
    assert type_group("Artifact Land") == "land"
    assert type_group("Enchantment Creature — God") == "creature"
    assert type_group("Legendary Enchantment Artifact") == "artifact"
    assert type_group("Instant // Land") == "instant"
    assert type_group("Legendary Planeswalker — Jace") == "planeswalker"
    assert type_group("Kindred Instant — Elf") == "instant"
    assert type_group("Conspiracy") == "other"
    lines = [line("Bolt", "{R}", "Instant"), line("Mountain", "", "Basic Land — Mountain"),
             line("Golem", "{3}", "Artifact Creature — Golem"), line("Ponder", "{U}", "Sorcery")]
    assert [(k, t, [x.card_name for x in g]) for k, t, g in group_by_type(lines)] == [
        ("creature", "Criaturas", ["Golem"]), ("instant", "Mágicas instantâneas", ["Bolt"]),
        ("sorcery", "Feitiços", ["Ponder"]), ("land", "Terrenos", ["Mountain"])]


def test_land_colors():
    from mtg_collection.services.deck_stats import land_colors
    assert land_colors("Basic Land — Forest", "") == {"G"}
    assert land_colors("Land", "{T}: Add {C}.\n{T}, Pay 1 life: Add {R} or {G}.") == {"C", "R", "G"}
    assert land_colors("Land", "{T}: Add one mana of any color.") == set("WUBRG")
    assert land_colors("Land — Mountain Forest", "({T}: Add {R} or {G}.)") == {"R", "G"}
    fetch = "{T}, Pay 1 life, Sacrifice: Search your library for a Plains or Island card, put it onto the battlefield."
    assert land_colors("Land", fetch) == {"W", "U"}
    wilds = "{T}, Sacrifice: Search your library for a basic land card, put it onto the battlefield tapped."
    assert land_colors("Land", wilds, {"R", "G"}) == {"R", "G"}
    assert land_colors("Basic Land", "") == set() and land_colors("Basic Land — Wastes", "") == {"C"}


def test_land_sources():
    from mtg_collection.services.deck_stats import land_sources
    lines = [DeckCard(id=1, deck_id=1, oracle_id="f", card_name="Forest", quantity=8, type_line="Basic Land — Forest"),
             DeckCard(id=2, deck_id=1, oracle_id="m", card_name="Mountain", quantity=7,
                      type_line="Basic Land — Mountain"),
             DeckCard(id=3, deck_id=1, oracle_id="w", card_name="Wilds", quantity=2, type_line="Land"),
             DeckCard(id=4, deck_id=1, oracle_id="b", card_name="Bolt", quantity=4, type_line="Instant")]
    texts = {3: "Search your library for a basic land card."}
    assert land_sources(lines, texts) == {"R": 9, "G": 10}


def test_probabilities():
    from mtg_collection.services.deck_stats import at_least_one, cards_seen, exactly, opening_lands
    assert round(at_least_one(60, 4, 7), 4) == 0.3995  # 4 cópias em 60, mão de 7: ~40%
    assert at_least_one(60, 0, 7) == 0 and at_least_one(10, 10, 1) == 1
    assert cards_seen(1, True) == 7 and cards_seen(1, False) == 8 and cards_seen(3, True) == 9
    assert round(exactly(60, 24, 7, 3), 4) == 0.3087
    deck = [DeckCard(id=1, deck_id=1, oracle_id="m", card_name="Mountain", quantity=24, type_line="Basic Land"),
            DeckCard(id=2, deck_id=1, oracle_id="b", card_name="Bolt", quantity=36, type_line="Instant"),
            DeckCard(id=3, deck_id=1, oracle_id="k", card_name="Krenko", quantity=1, type_line="Creature",
                     section="commander")]
    dist = opening_lands(deck)
    assert round(sum(dist.values()), 6) == 1 and round(dist[3], 4) == 0.3087
