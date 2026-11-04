from mtg_collection.models import DeckCard
from mtg_collection.services.deck_export import FORMATS, export, filename, short_name
from mtg_collection.services.decklist import parse_decklist


def line(name, qty, type_line="Instant", section="main", set_code="M10", number="146", **extra):
    return DeckCard(id=0, deck_id=1, oracle_id=f"o-{name}", card_name=name, quantity=qty, section=section,
                    type_line=type_line, set_code=set_code, collector_number=number, **extra)


DECK = [
    line("Mountain", 20, "Basic Land — Mountain", set_code="M10", number="242"),
    line("Lightning Bolt", 4, foil=True, price_paid_cents=150, notes="da loja, ótima"),
    line("Krenko, Mob Boss", 1, "Legendary Creature — Goblin", "commander", "M13", "139"),
    line("Delver of Secrets // Insectile Aberration", 2, "Creature — Human Wizard // Creature — Human Insect",
         set_code="ISD", number="51"),
    line("Fire // Ice", 1, "Instant // Instant", "sideboard", "MH2", "290"),
    line("Alter Bolt", 1, custom_print_id=3, set_code="ALT", number=""),
    line("Meu Dragão", 1, "Creature — Dragon", custom_card_id=5, set_code="", number=""),
    line("Talvez", 1, section="maybe"),
]


def test_short_names():
    assert short_name(DECK[3]) == "Delver of Secrets"
    assert short_name(DECK[4]) == "Fire // Ice"
    assert short_name(line("Bonecrusher Giant // Stomp", 1, "Creature — Giant // Instant — Adventure")) == \
        "Bonecrusher Giant"
    assert short_name(line("Valakut Awakening // Valakut Stoneforge", 1, "Instant // Land")) == "Valakut Awakening"


def test_text_grouped_by_type_and_readable_back():
    text = export("texto", "Burn", DECK)
    assert text == ("Commander\n1 Krenko, Mob Boss\n\n"
                    "2 Delver of Secrets // Insectile Aberration\n1 Meu Dragão\n1 Alter Bolt\n4 Lightning Bolt\n"
                    "20 Mountain\n\nSideboard\n1 Fire // Ice\n\nMaybeboard\n1 Talvez\n")
    lines, errors = parse_decklist(text)
    assert errors == [] and sum(x.quantity for x in lines) == 31


def test_arena_and_moxfield():
    arena = export("arena", "Burn", DECK)
    assert arena.startswith("Commander\n1 Krenko, Mob Boss (M13) 139\n\nDeck\n2 Delver of Secrets (ISD) 51\n")
    assert "1 Alter Bolt\n" in arena and "4 Lightning Bolt (M10) 146\n" in arena  # personalizada sem edição
    assert "Maybeboard" not in arena and "Sideboard\n1 Fire // Ice (MH2) 290\n" in arena
    mox = export("moxfield", "Burn", DECK)
    assert "4 Lightning Bolt (M10) 146 *F*\n" in mox and "Maybeboard\n1 Talvez (M10) 146\n" in mox
    parsed, errors = parse_decklist(mox)
    assert errors == [] and any(x.foil and x.set_code == "m10" for x in parsed)


def test_mtgo_and_cockatrice():
    mtgo = export("mtgo", "Burn", DECK)
    assert mtgo.endswith("20 Mountain\n\n1 Krenko, Mob Boss\n1 Fire/Ice\n")
    assert "Commander" not in mtgo and "Talvez" not in mtgo
    cod = export("cockatrice", "Burn & <Co>", DECK)
    assert "<deckname>Burn &amp; &lt;Co&gt;</deckname>" in cod
    assert '<card number="4" name="Lightning Bolt"/>' in cod
    assert cod.index('<zone name="side">') < cod.index('name="Krenko, Mob Boss"')


def test_csv():
    rows = export("csv", "Burn", DECK).splitlines()
    assert rows[0] == "Count,Name,Edition,Collector Number,Foil,Proxy,Section,Price Paid (BRL),Notes"
    assert '4,Lightning Bolt,M10,146,foil,,Deck,1.50,"da loja, ótima"' in rows
    assert "1,Meu Dragão,,,,,Deck,," in rows


def test_filename():
    assert filename("Burn/RDW", "Original", "cockatrice") == "Burn_RDW - Original.cod"
    assert set(FORMATS) == {"texto", "arena", "moxfield", "mtgo", "cockatrice", "csv"}


def test_csv_blocks_spreadsheet_formulas():
    rows = export("csv", "x", [line("=HYPERLINK(\"http://x\")", 1, notes="+1 contra aggro")]).splitlines()
    assert rows[1].startswith("1,\"'=HYPERLINK(\"\"http://x\"\")\"") and rows[1].endswith(",'+1 contra aggro")
