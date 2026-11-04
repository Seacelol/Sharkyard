from mtg_collection.services.decklist import DecklistLine, parse_decklist


def parse(text):
    return parse_decklist(text)


def simple(text):
    lines, errors = parse(text)
    assert errors == []
    return [(line.quantity, line.name, line.section) for line in lines]


def test_quantity_formats():
    assert simple("3 Lightning Bolt\n3x Counterspell\n2X Brainstorm\n4 x Ponder\nForest") == [
        (3, "Lightning Bolt", "main"), (3, "Counterspell", "main"), (2, "Brainstorm", "main"),
        (4, "Ponder", "main"), (1, "Forest", "main")]


def test_names_starting_with_x_and_numbers():
    assert simple("3 Xenagos, the Reveler\n1 Xantid Swarm\nx") == [
        (3, "Xenagos, the Reveler", "main"), (1, "Xantid Swarm", "main"), (1, "x", "main")]
    assert simple("1 Borrowing 100,000 Arrows") == [(1, "Borrowing 100,000 Arrows", "main")]


def test_ignores_blank_and_comments_and_extra_spaces():
    assert simple("\n  // meu deck\n# comentário\n  2   Lightning    Bolt  \n\n") == [(2, "Lightning Bolt", "main")]


def test_section_headers():
    text = ("Commander\n1 Atraxa, Praetors' Voice\nDeck\n4 Swords to Plowshares\nSideboard:\n2 Pyroblast\n"
            "Maybeboard\n1 Mox")
    assert simple(text) == [(1, "Atraxa, Praetors' Voice", "commander"), (4, "Swords to Plowshares", "main"),
                            (2, "Pyroblast", "sideboard"), (1, "Mox", "maybe")]


def test_sb_prefix_only_for_that_line():
    assert simple("4 Bolt\nSB: 2 Pyroblast\n1 Ponder") == [(4, "Bolt", "main"), (2, "Pyroblast", "sideboard"),
                                                             (1, "Ponder", "main")]


def test_arena_and_moxfield_suffixes():
    lines, errors = parse("4 Lightning Bolt (M10) 146\n2 Counterspell (MH2)\n1 Ponder (2XM) 61 *F*\n1 Opt (XLN) 65p")
    assert errors == []
    assert lines[0] == DecklistLine(1, 4, "Lightning Bolt", "main", "m10", "146", False)
    assert (lines[1].set_code, lines[1].collector_number) == ("mh2", None)
    assert (lines[2].set_code, lines[2].collector_number, lines[2].foil) == ("2xm", "61", True)
    assert lines[3].collector_number == "65p"


def test_parentheses_in_name_are_not_a_set():
    # "(a)" não parece código de edição (precisa de 2 a 6 letras/números), então fica no nome
    assert simple("1 Who // What // When // Where // Why") == [(1, "Who // What // When // Where // Why", "main")]


def test_errors_keep_line_number_and_text():
    lines, errors = parse("4 Bolt\n0 Ponder\n1000 Island\n  \n5x")
    assert [(e.line_no, e.text) for e in errors] == [(2, "0 Ponder"), (3, "1000 Island")]
    assert "1 a 999" in errors[0].reason
    # "5x" sozinho vira uma carta chamada "5x" (o Scryfall vai dizer que não existe)
    assert [(line.quantity, line.name) for line in lines] == [(4, "Bolt"), (1, "5x")]


def test_default_section_until_a_header():
    lines, _ = parse_decklist("2 Pyroblast\nDeck\n4 Bolt", default_section="sideboard")
    assert [(line.name, line.section) for line in lines] == [("Pyroblast", "sideboard"), ("Bolt", "main")]
