"""Cartas de exemplo no formato real da API do Scryfall."""
BOLT = {
    "id": "1", "oracle_id": "o-bolt", "name": "Lightning Bolt", "lang": "en", "released_at": "2009-07-17",
    "set": "m10", "set_name": "Magic 2010", "collector_number": "146", "rarity": "common",
    "type_line": "Instant", "mana_cost": "{R}", "oracle_text": "Lightning Bolt deals 3 damage to any target.",
    "flavor_text": "The sparkmage shrieked.", "artist": "Christopher Moeller", "finishes": ["nonfoil", "foil"],
    "color_identity": ["R"],
    "image_uris": {"small": "https://img/bolt-s.jpg", "normal": "https://img/bolt-n.jpg",
                   "large": "https://img/bolt-l.jpg", "art_crop": "https://img/bolt-art.jpg"},
    "prices": {"usd": "1.25", "usd_foil": "4.00", "eur": None, "eur_foil": None, "tix": "0.03"},
    "legalities": {"standard": "not_legal", "modern": "legal", "vintage": "restricted", "commander": "legal",
                   "oathbreaker": "banned", "newformat": "legal"},
    "scryfall_uri": "https://scryfall.com/card/m10/146",
}
BOLT_REPRINT = {**BOLT, "id": "1b", "set": "2xm", "set_name": "Double Masters", "collector_number": "129",
                "rarity": "uncommon", "released_at": "2020-08-07", "prices": {"usd": "2.10", "eur": "1.80"}}
DELVER = {
    "id": "2", "oracle_id": "o-delver", "name": "Delver of Secrets // Insectile Aberration", "lang": "en",
    "set": "isd", "set_name": "Innistrad", "collector_number": "51", "rarity": "common",
    "type_line": "Creature — Human Wizard // Creature — Human Insect", "released_at": "2011-09-30",
    "color_identity": ["U"],
    "card_faces": [
        {"name": "Delver of Secrets", "mana_cost": "{U}", "type_line": "Creature — Human Wizard",
         "oracle_text": "At the beginning of your upkeep, look at the top card of your library. (Reminder.)",
         "power": "1", "toughness": "1", "artist": "Nils Hamm",
         "image_uris": {"small": "https://img/d-s.jpg", "normal": "https://img/d-n.jpg", "large": "https://img/d-l.jpg",
                        "art_crop": "https://img/d-art.jpg"}},
        {"name": "Insectile Aberration", "mana_cost": "", "type_line": "Creature — Human Insect",
         "oracle_text": "Flying", "power": "3", "toughness": "2", "artist": "Nils Hamm",
         "image_uris": {"small": "https://img/d2-s.jpg", "normal": "https://img/d2-n.jpg",
                        "large": "https://img/d2-l.jpg"}},
    ],
    "legalities": {"modern": "legal", "pauper": "legal"},
    "prices": {"usd": "0.10", "eur": "0.05"},
}
RULINGS = {"object": "list", "data": [
    {"source": "wotc", "published_at": "2020-08-07", "comment": "This can target a planeswalker. {T} does nothing."},
]}

GOLD = {
    "id": "3", "oracle_id": "o-gold", "name": "Lightning Helix", "lang": "en", "set": "rav", "set_name": "Ravnica",
    "collector_number": "213", "rarity": "uncommon", "type_line": "Instant", "mana_cost": "{R}{W}",
    "oracle_text": "Lightning Helix deals 3 damage to any target and you gain 3 life.", "color_identity": ["R", "W"],
    "image_uris": {"small": "https://img/h-s.jpg", "normal": "https://img/h-n.jpg", "large": "https://img/h-l.jpg",
                   "art_crop": "https://img/h-art.jpg"},
}
LAND = {
    "id": "4", "oracle_id": "o-wastes", "name": "Wastes", "lang": "en", "set": "ogw",
    "set_name": "Oath of the Gatewatch",
    "collector_number": "183", "rarity": "common", "type_line": "Basic Land", "mana_cost": "", "color_identity": [],
    "image_uris": {"small": "https://img/w-s.jpg", "normal": "https://img/w-n.jpg", "large": "https://img/w-l.jpg"},
}
LEGEND = {
    "id": "5", "oracle_id": "o-krenko", "name": "Krenko, Mob Boss", "lang": "en", "set": "m13",
    "set_name": "Magic 2013", "collector_number": "139", "rarity": "rare",
    "type_line": "Legendary Creature — Goblin Warrior",
    "mana_cost": "{2}{R}{R}", "oracle_text": "{T}: Create X 1/1 red Goblin creature tokens.", "color_identity": ["R"],
    "legalities": {"commander": "legal", "modern": "legal"},
    "image_uris": {"small": "https://img/k-s.jpg", "normal": "https://img/k-n.jpg", "large": "https://img/k-l.jpg",
                   "art_crop": "https://img/k-art.jpg"},
}
RATS = {
    "id": "6", "oracle_id": "o-rats", "name": "Relentless Rats", "lang": "en", "set": "m11", "set_name": "Magic 2011",
    "collector_number": "111", "rarity": "uncommon", "type_line": "Creature — Rat", "mana_cost": "{1}{B}{B}",
    "oracle_text": "A deck can have any number of cards named Relentless Rats.", "color_identity": ["B"],
    "legalities": {"commander": "legal", "modern": "legal"},
}


def _legend(card_id, name, type_line, text, identity):
    return {"id": card_id, "oracle_id": f"o-{card_id}", "name": name, "lang": "en", "set": "c16",
            "set_name": "Commander 2016",
            "collector_number": card_id, "rarity": "mythic", "type_line": type_line, "mana_cost": "",
            "oracle_text": text, "color_identity": identity, "legalities": {"commander": "legal"},
            "image_uris": {"small": f"https://img/{card_id}-s.jpg", "normal": f"https://img/{card_id}-n.jpg",
                           "large": f"https://img/{card_id}-l.jpg"}}


TYMNA = _legend("7", "Tymna the Weaver", "Legendary Creature — Human Cleric",
                "Lifelink\nPartner (You can have two commanders if both have partner.)", ["W", "B"])
THRASIOS = _legend("8", "Thrasios, Triton Hero", "Legendary Creature — Merfolk Wizard",
                   "{4}: Scry 1.\nPartner (You can have two commanders if both have partner.)", ["G", "U"])
LUTRI = _legend("9", "Lutri, the Spellchaser", "Legendary Creature — Elemental Otter",
                "Companion — Each nonland card in your starting deck has a different name.\nFlash", ["U", "R"])
