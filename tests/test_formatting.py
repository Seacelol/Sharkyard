from datetime import date
from decimal import Decimal

from mtg_collection.ui.formatting import (
    date_br,
    highlight,
    price,
    rules_text_html,
    sorted_legalities,
    stats,
    symbol_file,
    symbols_html,
)


def test_price():
    assert price(Decimal("1.5"), "USD") == "USD 1.50"
    assert price(None, "EUR") == "EUR -"


def test_highlight_middle_case_insensitive():
    assert highlight("Nalathni Dragon", "LATH") == 'Na<span class="text-orange-600">lath</span>ni Dragon'


def test_highlight_no_match_or_empty():
    assert highlight("Lightning Bolt", "xyz") == "Lightning Bolt"
    assert highlight("Lightning Bolt", "  ") == "Lightning Bolt"


def test_highlight_escapes_html():
    assert highlight("<b>Bolt</b>", "bolt") == '&lt;b&gt;<span class="text-orange-600">Bolt</span>&lt;/b&gt;'


def test_symbol_file():
    assert symbol_file("W") == "W"
    assert symbol_file("W/U") == "WU"
    assert symbol_file("2/W") == "2W"
    assert symbol_file("g/p") == "GP"
    assert symbol_file("½") == "HALF"


def test_symbols_html():
    out = symbols_html("{2}{R} <x>")
    assert out.count('class="mana-symbol"') == 2
    assert 'src="https://svgs.scryfall.io/card-symbols/2.svg"' in out
    assert "&lt;x&gt;" in out


def test_rules_text_reminder_in_italic():
    out = rules_text_html("Flying (This creature can't be blocked {T}.)")
    assert out.startswith('Flying <span class="reminder">(')
    assert 'card-symbols/T.svg' in out


def test_stats():
    assert stats("2", "3", None, None) == "2/3"
    assert stats("*", "*", None, None) == "*/*"
    assert stats(None, None, "4", None) == "Lealdade 4"
    assert stats(None, None, None, "5") == "Defesa 5"
    assert stats(None, None, None, None) is None


def test_sorted_legalities_order_and_unknown_at_end():
    result = sorted_legalities({"vintage": "restricted", "zeta": "legal", "standard": "banned"})
    assert result == [
        ("Standard", "banned", "Banida"), ("Vintage", "restricted", "Restrita"), ("Zeta", "legal", "Legal")]


def test_date_br():
    assert date_br(date(2009, 7, 17)) == "17/07/2009"
    assert date_br(None) == "-"


def test_brl():
    from mtg_collection.ui.formatting import brl, brl_input
    assert brl(None) == "-" and brl(0) == "R$ 0,00" and brl(5) == "R$ 0,05"
    assert brl(123456) == "R$ 1.234,56" and brl(100000000) == "R$ 1.000.000,00"
    assert brl_input(None) == "" and brl_input(1250) == "12,50" and brl_input(7) == "0,07"
