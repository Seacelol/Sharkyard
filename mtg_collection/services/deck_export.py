"""Exporta uma versão do deck nos formatos mais usados. Puro: só monta o texto do arquivo.

- texto: "4 Lightning Bolt", com cabeçalhos de seção (lê em quase todo site e app)
- arena: MTG Arena, com edição e número; sem "talvez", que o Arena não tem
- moxfield: formato do Arena mais *F* para foil e a seção "talvez" (Moxfield e Archidekt importam)
- mtgo: .txt do Magic Online: principal, linha em branco e sideboard (comandante e companheiro vão no sideboard)
- cockatrice: .cod (XML) com as zonas main e side
- csv: planilha com quantidade, nome, edição, número, foil, proxy, seção, preço pago e observações
"""
import csv
import io
from dataclasses import dataclass
from xml.sax.saxutils import escape, quoteattr

from mtg_collection.models import DeckCard
from mtg_collection.services.deck_stats import TYPE_GROUPS, type_group

_GROUP_ORDER = [key for key, _, _ in TYPE_GROUPS] + ["other"]
_HEADERS = {"commander": "Commander", "companion": "Companion", "main": "Deck", "sideboard": "Sideboard",
            "maybe": "Maybeboard"}


@dataclass(frozen=True, slots=True)
class ExportFormat:
    """Formato de exportação oferecido na tela: `key` é o identificador, o resto aparece para o usuário e no
    arquivo baixado."""
    key: str
    label: str
    extension: str
    media_type: str
    description: str


FORMATS = {f.key: f for f in (
    ExportFormat("texto", "Texto simples", "txt", "text/plain",
                 "Uma carta por linha (\"4 Lightning Bolt\"), com as seções. Aceito pela maioria dos sites."),
    ExportFormat("arena", "MTG Arena", "txt", "text/plain",
                 "Com edição e número. Copie e use \"Importar\" no Arena. Sem a seção talvez."),
    ExportFormat("moxfield", "Moxfield / Archidekt", "txt", "text/plain",
                 "Formato do Arena com *F* nas cartas foil e a seção talvez."),
    ExportFormat("mtgo", "Magic Online (.txt)", "txt", "text/plain",
                 "Principal, linha em branco e sideboard. Comandante e companheiro vão no sideboard."),
    ExportFormat("cockatrice", "Cockatrice (.cod)", "cod", "application/xml",
                 "Arquivo de deck do Cockatrice. Comandante e companheiro vão no sideboard."),
    ExportFormat("csv", "Planilha (.csv)", "csv", "text/csv",
                 "Tudo de cada carta: edição, foil, proxy, seção, preço pago e observações."),
)}


def export(fmt: str, deck_name: str, lines: list[DeckCard]) -> str:
    builders = {"texto": _text, "arena": _arena, "moxfield": _moxfield, "mtgo": _mtgo, "cockatrice": _cockatrice,
                "csv": _csv}
    return builders[fmt](deck_name, _sorted(lines))


def filename(deck_name: str, version_name: str, fmt: str) -> str:
    base = f"{deck_name} - {version_name}" if version_name else deck_name
    safe = "".join(c if c.isalnum() or c in " -_()" else "_" for c in base).strip() or "deck"
    return f"{safe}.{FORMATS[fmt].extension}"


def _sorted(lines: list[DeckCard]) -> list[DeckCard]:
    return sorted(lines, key=lambda line: (_GROUP_ORDER.index(type_group(line.type_line)), line.card_name.lower()))


def short_name(line: DeckCard) -> str:
    """Nome que Arena e MTGO esperam: carta de duas faces, aventura e afins só pelo nome da frente; carta
    dividida (Fire // Ice, Rooms) com as duas metades."""
    if " // " not in line.card_name:
        return line.card_name
    halves = line.type_line.split(" // ")
    split = not any("Land" in half for half in halves) and (
        all("—" not in half for half in halves) or all("Room" in half for half in halves))
    return line.card_name if split else line.card_name.split(" // ")[0]


def _section(lines: list[DeckCard], section: str) -> list[DeckCard]:
    return [line for line in lines if line.section == section]


def _printing(line: DeckCard) -> str:
    """" (M10) 146" para edição oficial. Versão e carta personalizadas vão só com o nome."""
    if line.custom_print_id or line.custom_card_id or not line.set_code:
        return ""
    return f" ({line.set_code.upper()})" + (f" {line.collector_number}" if line.collector_number else "")


def _blocks(lines: list[DeckCard], sections: tuple[str, ...], fmt_line, main_header: bool) -> str:
    blocks = []
    for section in sections:
        chosen = _section(lines, section)
        if not chosen:
            continue
        header = [] if section == "main" and not main_header else [_HEADERS[section]]
        blocks.append("\n".join(header + [fmt_line(line) for line in chosen]))
    return "\n\n".join(blocks) + "\n"


def _text(_name: str, lines: list[DeckCard]) -> str:
    return _blocks(lines, ("commander", "companion", "main", "sideboard", "maybe"),
                   lambda line: f"{line.quantity} {line.card_name}", main_header=False)


def _arena(_name: str, lines: list[DeckCard]) -> str:
    return _blocks(lines, ("commander", "companion", "main", "sideboard"),
                   lambda line: f"{line.quantity} {short_name(line)}{_printing(line)}", main_header=True)


def _moxfield(_name: str, lines: list[DeckCard]) -> str:
    return _blocks(lines, ("commander", "companion", "main", "sideboard", "maybe"),
                   lambda line: f"{line.quantity} {line.card_name}{_printing(line)}" + (" *F*" if line.foil else ""),
                   main_header=True)


def _mtgo(_name: str, lines: list[DeckCard]) -> str:
    def name(line: DeckCard) -> str:
        return short_name(line).replace(" // ", "/")  # o MTGO escreve carta dividida como "Fire/Ice"

    main = [f"{line.quantity} {name(line)}" for line in _section(lines, "main")]
    side = [f"{line.quantity} {name(line)}" for section in ("commander", "companion", "sideboard")
            for line in _section(lines, section)]
    return "\n".join(main) + ("\n\n" + "\n".join(side) if side else "") + "\n"


def _cockatrice(name: str, lines: list[DeckCard]) -> str:
    def zone(zone_name: str, chosen: list[DeckCard]) -> list[str]:
        if not chosen:
            return []
        cards = [f"        <card number=\"{line.quantity}\" name={quoteattr(line.card_name)}/>" for line in chosen]
        return [f"    <zone name=\"{zone_name}\">", *cards, "    </zone>"]

    side = [line for section in ("commander", "companion", "sideboard") for line in _section(lines, section)]
    return "\n".join([
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
        "<cockatrice_deck version=\"1\">",
        f"    <deckname>{escape(name)}</deckname>",
        "    <comments></comments>",
        *zone("main", _section(lines, "main")),
        *zone("side", side),
        "</cockatrice_deck>",
    ]) + "\n"


def _cell(value) -> str:
    """Texto que começa com = + - @ vira fórmula no Excel: um apóstrofo na frente deixa como texto."""
    text = str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _csv(_name: str, lines: list[DeckCard]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["Count", "Name", "Edition", "Collector Number", "Foil", "Proxy", "Section", "Price Paid (BRL)",
                     "Notes"])
    for section in ("commander", "companion", "main", "sideboard", "maybe"):
        for line in _section(lines, section):
            price = f"{line.price_paid_cents / 100:.2f}" if line.price_paid_cents is not None else ""
            row = [line.quantity, line.card_name, "" if line.custom_card_id else line.set_code.upper(),
                   line.collector_number, "foil" if line.foil else "", "yes" if line.is_proxy else "",
                   _HEADERS[section], price, line.notes]
            writer.writerow([_cell(value) for value in row])
    return out.getvalue()
