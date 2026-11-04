from mtg_collection.services.search_query import Comparison, SearchFilters, build_query


def q(**kwargs) -> str:
    return build_query(SearchFilters(**kwargs))


def test_empty():
    assert q() == ""


def test_name_words_and_special_chars():
    assert q(name="lightning bolt") == "lightning bolt"
    assert q(name='Jace, the "Mind" Sculptor') == "Jace, the Mind Sculptor"
    assert q(name="t:dragon") == '"t:dragon"'  # não vira filtro sem querer


def test_oracle_text_phrase():
    assert q(oracle_text="draw  a card") == 'o:"draw a card"'
    assert q(oracle_text="flying") == "o:flying"


def test_types_include_exclude_and_quotes():
    assert q(types=[("Legendary", True), ("Dragon", True)]) == "t:Legendary t:Dragon"
    assert q(types=[("Creature", True), ("Human", False)]) == "t:Creature -t:Human"
    assert q(types=[("Time Lord", True)]) == 't:"Time Lord"'
    assert q(types=[("  ", True)]) == ""


def test_colors_modes_and_order():
    assert q(colors={"r", "w"}) == "c>=wr"
    assert q(colors={"u", "b"}, color_mode="=") == "c=ub"
    assert q(colors={"g"}, color_mode="<=") == "c<=g"
    assert q(colors={"c"}) == "c=c"
    assert q(colors={"c", "r"}) == "c>=r"  # incolor + cor: cor prevalece


def test_identity():
    assert q(identity={"w", "u"}) == "id<=wu"
    assert q(identity={"c"}) == "id=c"


def test_mana_cost_and_comparisons():
    assert q(mana_cost="{2}{R} {R}") == "m:{2}{R}{R}"
    assert q(mana_value=Comparison("<=", "3")) == "mv<=3"
    assert q(power=Comparison(">=", " 4 "), toughness=Comparison("=", "*")) == "pow>=4 tou=*"
    assert q(loyalty=Comparison("bogus", "3")) == "loy=3"
    assert q(mana_value=Comparison("<=", "")) == ""


def test_legality():
    assert q(format="modern") == "f:modern"
    assert q(format="vintage", legality="restricted") == "restricted:vintage"
    assert q(format="legacy", legality="banned") == "banned:legacy"
    assert q(legality="banned") == ""


def test_sets_and_rarities_use_or():
    assert q(sets=["M10"]) == "s:m10"
    assert q(sets=["m10", "2xm"]) == "(s:m10 OR s:2xm)"
    assert q(rarities=["rare", "mythic"]) == "(r:rare OR r:mythic)"


def test_artist_flavor_price_language():
    assert q(artist="Christopher Moeller") == 'a:"Christopher Moeller"'
    assert q(flavor_text="mishra") == "ft:mishra"
    assert q(price=Comparison("<", "5")) == "usd<5"
    assert q(price_currency="eur", price=Comparison(">=", "10.5")) == "eur>=10.5"
    assert q(price_currency="brl", price=Comparison("<", "5")) == ""
    assert q(language="pt") == "lang:pt"


def test_display_options():
    assert q(order="usd", direction="desc", all_prints=True) == "order:usd direction:desc unique:prints"
    assert q(direction="sideways") == ""


def test_full_combination_order():
    query = q(name="dragon", types=[("creature", True)], colors={"r"}, mana_value=Comparison("<=", "4"),
              format="commander", rarities=["mythic"], order="released")
    assert query == "dragon t:creature c>=r mv<=4 f:commander r:mythic order:released"
