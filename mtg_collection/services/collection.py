"""Coleção de cada usuário e suas versões personalizadas. Sem interface.

Toda função recebe o user_id e só enxerga os dados desse usuário: tentar mexer no item de outra pessoa
dá o mesmo erro de item inexistente.
"""
import re
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.orm import Session

from mtg_collection import config
from mtg_collection.database.tables import CollectionEntryRow, CustomPrintRow, DeckCardRow
from mtg_collection.models import Card, CollectionEntry, CollectionSummary, CustomPrint, Prices
from mtg_collection.services import custom_cards, folders

MAX_QUANTITY = 9999
MAX_PRICE_CENTS = 100_000_000  # R$ 1.000.000,00


class CollectionError(Exception):
    """Erro com mensagem pronta para mostrar ao usuário."""


# ---------- conversões ----------
def to_entry(row: CollectionEntryRow) -> CollectionEntry:
    if row.custom_card is not None:  # carta personalizada: nome sempre o atual da carta
        return CollectionEntry(
            id=row.id, oracle_id=row.oracle_id, card_name=row.custom_card.name, quantity=row.quantity,
            foil=row.foil, is_proxy=row.is_proxy, price_paid_cents=row.price_paid_cents, notes=row.notes,
            custom_card_id=row.custom_card_id, set_name="Carta personalizada", rarity="special",
            type_line=row.custom_card.type_line, image_small=row.image_small, image_normal=row.image_normal,
            folder_id=row.folder_id, created_at=row.created_at, updated_at=row.updated_at)
    custom = row.custom_print
    return CollectionEntry(
        id=row.id, oracle_id=row.oracle_id, card_name=row.card_name, quantity=row.quantity, foil=row.foil,
        is_proxy=row.is_proxy, price_paid_cents=row.price_paid_cents, notes=row.notes,
        scryfall_id=row.scryfall_id, custom_print_id=row.custom_print_id,
        base_scryfall_id=custom.base_scryfall_id if custom else row.scryfall_id,
        # versão personalizada: nome e código vêm sempre da versão (se ela for renomeada, a coleção acompanha)
        set_code=custom.code if custom else row.set_code,
        set_name=custom.name if custom else row.set_name,
        collector_number="" if custom else row.collector_number,
        rarity="special" if custom else row.rarity,
        type_line=row.type_line, image_small=row.image_small, image_normal=row.image_normal,
        folder_id=row.folder_id, created_at=row.created_at, updated_at=row.updated_at,
        lang="en" if custom else row.lang,
    )


def to_custom_print(row: CustomPrintRow) -> CustomPrint:
    return CustomPrint(id=row.id, oracle_id=row.oracle_id, card_name=row.card_name, name=row.name, code=row.code,
                       artist=row.artist, notes=row.notes, image_filename=row.image_filename,
                       base_scryfall_id=row.base_scryfall_id, created_at=row.created_at)


_THOUSANDS = re.compile(r"\d{1,3}(\.\d{3})+")  # "1.500", "1.234.567": ponto como milhar, sem centavos
_NUMBER = re.compile(r"\d+(\.\d*)?|\.\d+")


def parse_price(text: str | None) -> int | None:
    """Preço digitado em reais ("12,50", "R$ 1.234,56", "1.500", "7") -> centavos. Vazio = sem preço.
    Ponto seguido de exatamente 3 dígitos é milhar (como se escreve no Brasil); "3.5" e "1.50" são centavos."""
    cleaned = re.sub(r"[R$\s]", "", text or "")
    if not cleaned:
        return None
    if "," in cleaned:  # formato brasileiro: ponto é milhar, vírgula é decimal
        integer, _, cents = cleaned.partition(",")
        if "." in integer and not _THOUSANDS.fullmatch(integer):
            raise CollectionError("Preço inválido. Use algo como 12,50.")
        cleaned = f"{integer.replace('.', '')}.{cents}"
    elif _THOUSANDS.fullmatch(cleaned):
        cleaned = cleaned.replace(".", "")
    # só dígitos e um ponto: o Decimal aceitaria também "NaN", "Infinity", "1e9" e sinal, que não são preço
    if not _NUMBER.fullmatch(cleaned):
        raise CollectionError("Preço inválido. Use algo como 12,50.")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise CollectionError("Preço inválido. Use algo como 12,50.") from None
    if not value.is_finite() or value < 0 or value.as_tuple().exponent < -2:
        raise CollectionError("Preço inválido. Use no máximo duas casas decimais.")
    cents = int(value * 100)
    if cents > MAX_PRICE_CENTS:
        raise CollectionError("Preço alto demais.")
    return cents


# ---------- coleção ----------
def add_card(s: Session, user_id: int, card: Card, quantity: int = 1, folder_id: int | None = None, *,
             foil: bool = False, is_proxy: bool = False, price_paid_cents: int | None = None, notes: str = ""
             ) -> CollectionEntry:
    """Adiciona à coleção. Se já existir um lote igual na mesma pasta (mesma impressão, mesmo foil/proxy, sem
    preço e sem observação), soma a quantidade nele em vez de criar uma linha repetida. Lotes com preço ou
    observação ficam sempre separados."""
    _check_quantity(quantity)
    folders.check_folder(s, user_id, folders.COLLECTION, folder_id)
    if not card.oracle_id:
        raise CollectionError("Esta carta não pode ser adicionada (sem identificador).")
    notes = notes.strip()
    query = select(CollectionEntryRow).where(
        CollectionEntryRow.user_id == user_id, CollectionEntryRow.foil.is_(foil),
        CollectionEntryRow.is_proxy.is_(is_proxy), CollectionEntryRow.price_paid_cents.is_(None),
        CollectionEntryRow.notes == "",
        CollectionEntryRow.folder_id.is_(None) if folder_id is None else CollectionEntryRow.folder_id == folder_id)
    if card.is_custom_card:
        custom_cards.move_to_collection(s, user_id, card.custom_card_id)  # carta só do deck passa a ser sua
        query = query.where(CollectionEntryRow.custom_card_id == card.custom_card_id)
    elif card.is_custom:
        _custom_row(s, user_id, card.custom_print_id)
        query = query.where(CollectionEntryRow.custom_print_id == card.custom_print_id)
    else:
        query = query.where(CollectionEntryRow.scryfall_id == card.id)
    row = s.scalar(query) if price_paid_cents is None and not notes else None
    if row:
        row.quantity = min(row.quantity + quantity, MAX_QUANTITY)
    else:
        row = CollectionEntryRow(user_id=user_id, quantity=quantity, folder_id=folder_id, foil=foil,
                                 is_proxy=is_proxy, price_paid_cents=price_paid_cents, notes=notes,
                                 **_print_fields(card))
        s.add(row)
    s.flush()
    return to_entry(row)


@dataclass(frozen=True, slots=True)
class NewItem:
    """Uma carta a adicionar com add_cards (as mesmas opções de add_card)."""
    card: Card
    quantity: int = 1
    foil: bool = False
    is_proxy: bool = False
    price_paid_cents: int | None = None
    notes: str = ""


def add_cards(s: Session, user_id: int, items: list[NewItem], folder_id: int | None = None) -> int:
    """Várias cartas de uma vez, com a mesma regra de add_card (soma no lote igual sem preço nem observação).
    Lê os lotes da pasta numa consulta e grava as linhas novas numa só, em vez de 2 a 3 consultas por carta.
    Devolve quantas cópias entraram de fato (lote que bate no máximo de cópias só soma o que coube)."""
    folders.check_folder(s, user_id, folders.COLLECTION, folder_id)
    for item in items:
        _check_quantity(item.quantity)
        if not item.card.oracle_id:
            raise CollectionError("Esta carta não pode ser adicionada (sem identificador).")
    custom_prints = {i.card.custom_print_id for i in items if i.card.is_custom}
    if custom_prints:  # versões personalizadas: todas do usuário? (uma consulta)
        mine = set(s.scalars(select(CustomPrintRow.id).where(CustomPrintRow.id.in_(custom_prints),
                                                             CustomPrintRow.user_id == user_id)))
        if mine != custom_prints:
            raise CollectionError("Versão personalizada não encontrada.")
    for custom_id in {i.card.custom_card_id for i in items if i.card.is_custom_card}:
        custom_cards.move_to_collection(s, user_id, custom_id)  # só cartas personalizadas (poucas)

    def key(card: Card, foil: bool, is_proxy: bool) -> tuple:
        target = ("card", card.custom_card_id) if card.is_custom_card else \
            ("print", card.custom_print_id) if card.is_custom else ("scryfall", card.id)
        return (*target, foil, is_proxy)

    lots = {}  # lotes onde dá para somar: sem preço, sem observação, nesta pasta
    for row in s.scalars(select(CollectionEntryRow).where(
            CollectionEntryRow.user_id == user_id, CollectionEntryRow.price_paid_cents.is_(None),
            CollectionEntryRow.notes == "",
            CollectionEntryRow.folder_id.is_(None) if folder_id is None
            else CollectionEntryRow.folder_id == folder_id)):
        kind_id = ("card", row.custom_card_id) if row.custom_card_id else \
            ("print", row.custom_print_id) if row.custom_print_id else ("scryfall", row.scryfall_id)
        lots.setdefault((*kind_id, row.foil, row.is_proxy), row)
    new_rows: dict = {}  # lote novo criado neste lote de cartas (cartas repetidas somam nele)
    plain: list[dict] = []  # com preço ou observação: sempre linha própria
    added = 0
    for item in items:
        notes = item.notes.strip()
        fields = dict(user_id=user_id, quantity=item.quantity, folder_id=folder_id, foil=item.foil,
                      is_proxy=item.is_proxy, price_paid_cents=item.price_paid_cents, notes=notes,
                      **_print_fields(item.card))
        if item.price_paid_cents is not None or notes:
            plain.append(fields)
            added += item.quantity
            continue
        k = key(item.card, item.foil, item.is_proxy)
        if k in lots:
            before = lots[k].quantity
            lots[k].quantity = min(before + item.quantity, MAX_QUANTITY)
            added += lots[k].quantity - before
        elif k in new_rows:
            before = new_rows[k]["quantity"]
            new_rows[k]["quantity"] = min(before + item.quantity, MAX_QUANTITY)
            added += new_rows[k]["quantity"] - before
        else:
            new_rows[k] = fields
            added += item.quantity
    rows = [*new_rows.values(), *plain]
    if rows:
        s.execute(insert(CollectionEntryRow), rows)  # uma gravação para todas as linhas novas
    s.flush()
    return added


_KEEP = object()  # marcador: "não mexer na pasta"


def update_entry(s: Session, user_id: int, entry_id: int, *, quantity: int, foil: bool, is_proxy: bool,
                 price_paid_cents: int | None, notes: str, printing: Card | None = None,
                 folder_id: int | None | object = _KEEP) -> CollectionEntry:
    """Edita um lote. `printing` troca a edição (Scryfall ou versão personalizada da mesma carta);
    `folder_id` move para uma pasta (None = sem pasta; omitido = continua onde está)."""
    row = _entry_row(s, user_id, entry_id)
    if folder_id is not _KEEP:
        folders.check_folder(s, user_id, folders.COLLECTION, folder_id)
        row.folder_id = folder_id
    _check_quantity(quantity)
    if price_paid_cents is not None and not 0 <= price_paid_cents <= MAX_PRICE_CENTS:
        raise CollectionError("Preço inválido.")
    if printing is not None:
        if printing.oracle_id != row.oracle_id:
            raise CollectionError("A edição escolhida é de outra carta.")
        if printing.is_custom:
            _custom_row(s, user_id, printing.custom_print_id)
        for key, value in _print_fields(printing).items():
            setattr(row, key, value)
    row.quantity, row.foil, row.is_proxy = quantity, foil, is_proxy
    row.price_paid_cents, row.notes = price_paid_cents, notes.strip()
    s.flush()
    return to_entry(row)


def delete_entry(s: Session, user_id: int, entry_id: int) -> None:
    s.delete(_entry_row(s, user_id, entry_id))


def delete_entries(s: Session, user_id: int, entry_ids: list[int]) -> int:
    """Remove vários itens de uma vez (todos ou nenhum, se algum não for do usuário). Duas consultas, não uma
    por item: confere todos juntos e apaga todos juntos."""
    ids = _owned_entry_ids(s, user_id, entry_ids)
    s.execute(delete(CollectionEntryRow).where(CollectionEntryRow.id.in_(ids)))
    s.expire_all()  # objetos já carregados nesta sessão não podem continuar valendo
    return len(ids)


def move_entries(s: Session, user_id: int, entry_ids: list[int], folder_id: int | None) -> int:
    """Move vários itens para uma pasta (None = sem pasta), numa gravação só."""
    folders.check_folder(s, user_id, folders.COLLECTION, folder_id)
    ids = _owned_entry_ids(s, user_id, entry_ids)
    s.execute(update(CollectionEntryRow).where(CollectionEntryRow.id.in_(ids)).values(folder_id=folder_id))
    s.expire_all()
    return len(ids)


def get_entry(s: Session, user_id: int, entry_id: int) -> CollectionEntry:
    return to_entry(_entry_row(s, user_id, entry_id))


def list_entries(s: Session, user_id: int, oracle_id: str | None = None) -> list[CollectionEntry]:
    """Lotes da coleção em ordem de nome e edição; com `oracle_id`, só os daquela carta (todas as impressões)."""
    query = select(CollectionEntryRow).where(CollectionEntryRow.user_id == user_id)
    if oracle_id:
        query = query.where(CollectionEntryRow.oracle_id == oracle_id)
    query = query.order_by(CollectionEntryRow.card_name, CollectionEntryRow.set_name, CollectionEntryRow.id)
    return [to_entry(r) for r in s.scalars(query).unique()]


def count_cards(s: Session, user_id: int) -> int:
    """Total de cartas (somando as quantidades) da coleção."""
    return s.scalar(select(func.coalesce(func.sum(CollectionEntryRow.quantity), 0))
                    .where(CollectionEntryRow.user_id == user_id))


def summarize(entries: list[CollectionEntry]) -> CollectionSummary:
    return CollectionSummary(
        entries=len(entries),
        cards=sum(e.quantity for e in entries),
        real_cards=sum(e.quantity for e in entries if not e.is_proxy),
        proxies=sum(e.quantity for e in entries if e.is_proxy),
        unique_cards=len({e.oracle_id for e in entries}),
        total_paid_cents=sum(e.total_paid_cents for e in entries),
    )


# ---------- versões personalizadas ----------
def create_custom_print(s: Session, user_id: int, base: Card, name: str, code: str = "", artist: str = "",
                        notes: str = "", image_filename: str | None = None) -> CustomPrint:
    """Cria uma versão personalizada a partir de uma impressão oficial, que serve de base para o texto e para a
    imagem enquanto o usuário não enviar a dele."""
    if not base.oracle_id or base.is_custom:
        raise CollectionError("Crie a versão a partir de uma impressão oficial da carta.")
    row = CustomPrintRow(user_id=user_id, oracle_id=base.oracle_id, card_name=base.name, base_scryfall_id=base.id,
                         image_filename=image_filename, **_custom_fields(name, code, artist, notes))
    s.add(row)
    s.flush()
    return to_custom_print(row)


def update_custom_print(s: Session, user_id: int, custom_id: int, name: str, code: str = "", artist: str = "",
                        notes: str = "", image_filename: str | None = None, remove_image: bool = False, *,
                        image_url: str | None = None, base: Card | None = None) -> CustomPrint:
    """Atualiza os dados. `image_filename` troca a imagem (`image_url` é o endereço dela, que a interface monta);
    `remove_image` volta para a imagem da carta base (`base`, a impressão oficial da versão).

    A coleção e os decks guardam uma cópia do nome e da imagem. Sem atualizar essas cópias, elas continuariam
    apontando para o arquivo antigo, que é apagado logo depois por não constar mais em custom_prints."""
    row = _custom_row(s, user_id, custom_id)
    for key, value in _custom_fields(name, code, artist, notes).items():
        setattr(row, key, value)
    snapshot = dict(set_code=row.code, set_name=row.name)
    if image_filename:
        row.image_filename = image_filename
        snapshot.update(image_small=image_url, image_normal=image_url)
    elif remove_image:
        row.image_filename = None
        official = _base_of(row, base)  # sem a base, melhor sem imagem do que apontando para arquivo apagado
        snapshot.update(image_small=official.image_small if official else None,
                        image_normal=official.image_normal if official else None)
    s.flush()
    _sync_custom_print_snapshots(s, custom_id, snapshot)
    return to_custom_print(row)


def _sync_custom_print_snapshots(s: Session, custom_id: int, values: dict) -> None:
    """Um UPDATE por tabela, por mais cópias da versão que existam (como custom_cards.sync_snapshots)."""
    s.execute(update(CollectionEntryRow).where(CollectionEntryRow.custom_print_id == custom_id).values(**values))
    s.execute(update(DeckCardRow).where(DeckCardRow.custom_print_id == custom_id).values(**values))
    s.expire_all()


@dataclass(frozen=True, slots=True)
class CustomPrintUsage:
    """Onde a versão aparece: cópias na coleção (apagadas junto) e linhas de deck (voltam para a oficial)."""
    copies: int = 0
    deck_lines: int = 0


def custom_print_usage(s: Session, user_id: int, custom_id: int) -> CustomPrintUsage:
    """Para avisar antes de apagar a versão (contando todas as versões de todos os decks)."""
    _custom_row(s, user_id, custom_id)
    copies = s.scalar(select(func.coalesce(func.sum(CollectionEntryRow.quantity), 0))
                      .where(CollectionEntryRow.custom_print_id == custom_id))
    lines = s.scalar(select(func.count()).select_from(DeckCardRow).where(DeckCardRow.custom_print_id == custom_id))
    return CustomPrintUsage(copies, lines)


def delete_custom_print(s: Session, user_id: int, custom_id: int, base: Card | None = None) -> CustomPrintUsage:
    """Apaga a versão e os itens da coleção que usam ela. As linhas de deck (de todas as versões do deck) não
    somem: voltam para a impressão oficial em que a versão foi baseada (`base`, se a interface tiver ela, dá
    edição e imagem certas). Sem isso, o ON DELETE CASCADE tirava a carta dos decks sem aviso."""
    row = _custom_row(s, user_id, custom_id)
    usage = custom_print_usage(s, user_id, custom_id)
    official = _base_of(row, base)
    values = dict(scryfall_id=row.base_scryfall_id, custom_print_id=None)
    if official:
        values.update(set_code=official.set_code, set_name=official.set_name,
                      collector_number=official.collector_number, rarity=official.rarity,
                      image_small=official.image_small, image_normal=official.image_normal,
                      image_art_crop=official.image_art_crop, lang=official.lang or "en")
    else:  # sem os dados da base: edição em branco e, se a imagem era a enviada, sem imagem
        values.update(set_code="", set_name="", collector_number="", rarity="")
        if row.image_filename:
            values.update(image_small=None, image_normal=None)
    s.execute(update(DeckCardRow).where(DeckCardRow.custom_print_id == custom_id).values(**values))
    s.execute(delete(CollectionEntryRow).where(CollectionEntryRow.custom_print_id == custom_id))
    s.execute(delete(CustomPrintRow).where(CustomPrintRow.id == custom_id))
    s.expire_all()
    return usage


def get_custom_print(s: Session, user_id: int, custom_id: int) -> CustomPrint:
    return to_custom_print(_custom_row(s, user_id, custom_id))


def list_custom_prints(s: Session, user_id: int, oracle_id: str) -> list[CustomPrint]:
    query = select(CustomPrintRow).where(CustomPrintRow.user_id == user_id, CustomPrintRow.oracle_id == oracle_id)
    return [to_custom_print(r) for r in s.scalars(query.order_by(CustomPrintRow.created_at, CustomPrintRow.id))]


def as_card(custom: CustomPrint, base: Card, image_url: str | None = None) -> Card:
    """Versão personalizada como Card, com o texto da carta base. `image_url` é a imagem enviada (se houver)."""
    faces = base.faces
    if image_url and faces:  # a imagem enviada substitui a frente; o verso (dupla face) continua o original
        faces = (replace(faces[0], image_normal=image_url, image_large=image_url, artist=custom.artist or
                         faces[0].artist), *faces[1:])
    return replace(
        base, id=f"custom-{custom.id}", custom_print_id=custom.id, set_code=custom.code, set_name=custom.name,
        collector_number="", rarity="special", released_at=None, finishes=(), prices=Prices(),
        artist=custom.artist or base.artist, faces=faces,
        image_small=image_url or base.image_small, image_normal=image_url or base.image_normal,
        image_large=image_url or base.image_large,
    )


def custom_print_owner(s: Session, image_filename: str) -> int | None:
    """Dono da imagem (para servir o arquivo só para quem criou)."""
    return s.scalar(select(CustomPrintRow.user_id).where(CustomPrintRow.image_filename == image_filename))


def custom_print_image_in_use(s: Session, image_filename: str) -> bool:
    return custom_print_owner(s, image_filename) is not None


# ---------- internos ----------
def _base_of(row: CustomPrintRow, base: Card | None) -> Card | None:
    """A impressão oficial da versão, se a recebida for mesmo ela (outra edição daria dados errados)."""
    if base is None or base.is_custom or base.is_custom_card or base.id != row.base_scryfall_id:
        return None
    return base


def _print_fields(card: Card) -> dict:
    return dict(oracle_id=card.oracle_id, card_name=card.name,
                scryfall_id=None if card.is_custom or card.is_custom_card else card.id,
                custom_print_id=card.custom_print_id, custom_card_id=card.custom_card_id,
                set_code=card.set_code, set_name=card.set_name, collector_number=card.collector_number,
                rarity=card.rarity, type_line=card.type_line, image_small=card.image_small,
                image_normal=card.image_normal, lang=card.lang or "en")


def _custom_fields(name: str, code: str, artist: str, notes: str) -> dict:
    name = name.strip()
    if not name:
        raise CollectionError("Dê um nome para a versão.")
    code = re.sub(r"[^A-Za-z0-9]", "", code).upper()
    return dict(name=name[:config.CUSTOM_PRINT_NAME_MAX], code=code[:8], artist=artist.strip()[:80],
                notes=notes.strip())


def _check_quantity(quantity: int) -> None:
    if not isinstance(quantity, int) or not 1 <= quantity <= MAX_QUANTITY:
        raise CollectionError(f"A quantidade deve ser de 1 a {MAX_QUANTITY}.")


def _owned_entry_ids(s: Session, user_id: int, entry_ids: list[int]) -> list[int]:
    """Os ids, sem repetição, se todos forem do usuário (uma consulta para todos); senão, erro e nada muda."""
    ids = list(dict.fromkeys(entry_ids))
    owned = set(s.scalars(select(CollectionEntryRow.id).where(
        CollectionEntryRow.id.in_(ids), CollectionEntryRow.user_id == user_id)))
    if len(owned) != len(ids):
        raise CollectionError("Item não encontrado na sua coleção.")
    return ids


def _entry_row(s: Session, user_id: int, entry_id: int) -> CollectionEntryRow:
    row = s.get(CollectionEntryRow, entry_id)
    if row is None or row.user_id != user_id:
        raise CollectionError("Item não encontrado na sua coleção.")
    return row


def _custom_row(s: Session, user_id: int, custom_id: int | None) -> CustomPrintRow:
    row = s.get(CustomPrintRow, custom_id) if custom_id else None
    if row is None or row.user_id != user_id:
        raise CollectionError("Versão personalizada não encontrada.")
    return row
