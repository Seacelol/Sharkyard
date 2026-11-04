from mtg_collection.models import Card, CardFace, DeckCard
from mtg_collection.services import commander as cmd
from mtg_collection.services.deck_validation import validate


def card(name, type_line="Legendary Creature — Human", text="", identity="R", oracle_id=None):
    return Card(id=name, oracle_id=oracle_id or f"o-{name}", name=name, set_code="tst", set_name="Teste",
                collector_number="1", rarity="rare", type_line=type_line, mana_cost="", oracle_text=text,
                color_identity=tuple(identity), legalities={})


PARTNER_A = card("Tymna", text="Lifelink\nPartner (You can have two commanders if both have partner.)", identity="WB")
PARTNER_B = card("Thrasios", text="Partner (You can have two commanders if both have partner.)", identity="GU")
PAIR_X = card("Pir", text="Partner with Toothy, Imaginary Friend (When this creature enters, target player may put "
                          "Toothy into their hand from their library, then shuffle.)", identity="U")
PAIR_Y = card("Toothy, Imaginary Friend", text="Partner with Pir, Imaginative Rascal\nWhen Toothy dies, draw.")
PAIR_X_REAL = card("Pir, Imaginative Rascal", text="Partner with Toothy, Imaginary Friend (When this...)")
FRIENDS_A = card("Will", text="Friends forever (You can have two commanders if both have friends forever.)")
FRIENDS_B = card("Lucas", text="Friends forever")
SURVIVOR_A = card("Tyvar", text="Partner—Survivors (You can have two commanders if both have this ability.)")
SURVIVOR_B = card("Zimone", text="Flying\nPartner—Survivors")
CHOOSER = card("Wilson", text="Choose a Background (You can have a Background as a second commander.)")
BACKGROUND = card("Raised by Giants", type_line="Legendary Enchantment — Background", identity="G")
COMPANION_D = card("Amy Pond", text="Doctor's companion (You can have two commanders if the other is the Doctor.)")
DOCTOR = card("The Tenth Doctor", type_line="Legendary Creature — Time Lord Doctor")
NOT_DOCTOR = card("Rose", type_line="Legendary Creature — Human Time Lord Doctor")
SOLO = card("Krenko", text="{T}: Create goblins.")
LUTRI = card("Lutri, the Spellchaser", type_line="Legendary Creature — Elemental Otter", identity="UR",
             text="Companion — Each nonland card in your starting deck has a different name.\nFlash")


def test_partner_variants():
    assert cmd.can_pair(PARTNER_A, PARTNER_B)
    assert cmd.can_pair(PAIR_X_REAL, PAIR_Y) and cmd.can_pair(PAIR_Y, PAIR_X_REAL)
    assert not cmd.can_pair(PAIR_X, PAIR_Y)  # nome não bate
    assert not cmd.can_pair(PAIR_X_REAL, PARTNER_A)  # partner with só com a carta citada
    assert cmd.can_pair(FRIENDS_A, FRIENDS_B) and not cmd.can_pair(FRIENDS_A, PARTNER_A)
    assert cmd.can_pair(SURVIVOR_A, SURVIVOR_B) and not cmd.can_pair(SURVIVOR_A, FRIENDS_A)
    assert cmd.can_pair(CHOOSER, BACKGROUND) and cmd.can_pair(BACKGROUND, CHOOSER)
    assert not cmd.can_pair(BACKGROUND, PARTNER_A)
    assert cmd.can_pair(COMPANION_D, DOCTOR) and not cmd.can_pair(COMPANION_D, NOT_DOCTOR)
    assert not cmd.can_pair(SOLO, PARTNER_A) and not cmd.can_pair(PARTNER_A, PARTNER_A)


def test_can_have_partner_and_companion():
    assert all(cmd.can_have_partner(c) for c in (PARTNER_A, PAIR_Y, FRIENDS_A, SURVIVOR_B, CHOOSER, BACKGROUND,
                                                 COMPANION_D, DOCTOR))
    assert not cmd.can_have_partner(SOLO)
    assert cmd.is_companion(LUTRI) and not cmd.is_companion(SOLO)


def test_dfc_partner_text_in_faces():
    dfc = Card(id="d", oracle_id="o-d", name="Front // Back", set_code="", set_name="", collector_number="",
               rarity="rare", type_line="Legendary Creature", mana_cost="", oracle_text="",
               faces=(CardFace(name="Front", oracle_text="Partner"), CardFace(name="Back")))
    assert cmd.can_pair(dfc, PARTNER_A)


def test_queries_by_format():
    assert cmd.commander_query("commander") == "is:commander"
    assert cmd.commander_query("brawl") == "is:brawler"
    assert "r:uncommon" in cmd.commander_query("paupercommander")
    assert cmd.commander_query("modern") == "" and cmd.commander_kind("modern") == ""


# ---------- validação ----------
def line(c: Card, quantity=1, section="main"):
    return DeckCard(id=0, deck_id=1, oracle_id=c.oracle_id, card_name=c.name, quantity=quantity, section=section,
                    color_identity="".join(c.color_identity), type_line=c.type_line, rarity=c.rarity)


BASICS = card("Wastes", type_line="Basic Land", identity="", oracle_id="o-wastes")


def deck_with(*commanders, filler=98, extra=()):
    lines = [line(c, section="commander") for c in commanders]
    lines += [line(BASICS, filler), *extra]
    known = {c.oracle_id: c for c in [*commanders, BASICS, *[e for e in extra if isinstance(e, Card)]]}
    return lines, known


def test_valid_partners_and_identity_union():
    lines, known = deck_with(PARTNER_A, PARTNER_B)
    assert validate("commander", lines, known) == []
    green = card("Elf", type_line="Creature — Elf", identity="G")
    lines, known = deck_with(PARTNER_A, PARTNER_B, filler=97, extra=[line(green)])
    known[green.oracle_id] = green
    assert validate("commander", lines, known) == []  # G está na identidade somada (WBGU)


def test_invalid_pair_and_background():
    lines, known = deck_with(SOLO, PARTNER_A)
    assert validate("commander", lines, known) == [
        "Krenko e Tymna não podem ser comandantes juntos: os dois precisam ser parceiros um do outro."]
    lines, known = deck_with(CHOOSER, BACKGROUND)
    assert validate("commander", lines, known) == []
    lines, known = deck_with(BACKGROUND, filler=99)
    assert validate("commander", lines, known) == ["Raised by Giants não pode ser comandante neste formato."]


def test_companion_outside_the_100_in_commander():
    lines, known = deck_with(SOLO, filler=99, extra=[line(LUTRI, section="companion")])
    known[LUTRI.oracle_id] = LUTRI
    assert validate("commander", lines, known) == ["Fora da identidade de cor do comandante: Lutri, the Spellchaser."]


def test_companion_uses_sideboard_slot_in_constructed():
    side = [line(BASICS, 15, "sideboard"), line(LUTRI, section="companion"), line(SOLO, section="companion")]
    known = {c.oracle_id: c for c in (BASICS, LUTRI, SOLO)}
    assert validate("modern", [line(BASICS, 60), *side], known) == [
        "O sideboard tem 17 cartas; o máximo é 15.",
        "Só pode haver um companheiro.",
        "Krenko não tem a habilidade Companheiro (Companion)."]


def test_commander_in_format_without_commander():
    assert validate("modern", [line(SOLO, section="commander"), line(BASICS, 60)], {}) == [
        "Este formato não tem comandante: Krenko fica de fora."]


def test_brawl_accepts_legendary_vehicle_and_planeswalker():
    assert cmd.can_lead("brawl", "Legendary Artifact — Vehicle", "")
    assert cmd.can_lead("brawl", "Legendary Planeswalker — Jace", "")
    assert cmd.can_lead("brawl", "Legendary Artifact — Spacecraft", "", has_pt=True)
    assert not cmd.can_lead("brawl", "Legendary Artifact — Spacecraft", "")
    assert not cmd.can_lead("commander", "Legendary Artifact — Vehicle", "")
