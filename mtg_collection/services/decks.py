"""Decks de cada usuário: criar, editar, apagar, mover entre pastas, capa e cores. Sem interface.

Como na coleção, toda função recebe o user_id e só mexe nos decks desse usuário.
"""
from dataclasses import dataclass

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.orm import Session, selectinload

from mtg_collection import config
from mtg_collection.database.tables import (
    CollectionEntryRow,
    CustomCardRow,
    CustomPrintRow,
    DeckCardRow,
    DeckRow,
    DeckVersionRow,
    UserRow,
)
from mtg_collection.models import Card, Deck, DeckCard, DeckVersion
from mtg_collection.services import collection, custom_cards, folders

VISIBILITIES = ("private", "friends")
SECTIONS = ("commander", "companion", "main", "sideboard", "maybe")  # também a ordem de exibição
DECK_SECTIONS = ("main", "commander")  # o que conta como "cartas do deck" (o resto fica fora)
COLOR_ORDER = "WUBRG"
MAX_QUANTITY = 999
FIRST_VERSION = "Original"


class DeckError(Exception):
    """Erro com mensagem pronta para mostrar ao usuário."""


# ---------- conversões ----------
def deck_colors(cards: list[DeckCardRow]) -> tuple[str, ...]:
    """Identidade de cor do deck, na ordem WUBRG: a do comandante, se houver; senão a soma das cartas.
    Deck com cartas mas sem nenhuma cor é incolor ("C"); deck vazio não tem cor."""
    commanders = [card for card in cards if card.section == "commander"]
    present = {letter for card in commanders or cards for letter in card.color_identity}
    colors = tuple(c for c in COLOR_ORDER if c in present)
    return colors or (("C",) if cards else ())


def to_deck(row: DeckRow) -> Deck:
    return Deck(
        id=row.id, user_id=row.user_id, name=row.name, format=row.format, notes=row.notes,
        visibility=row.visibility, folder_id=row.folder_id, colors=deck_colors(row.cards),
        card_count=sum(c.quantity for c in row.cards if c.section in DECK_SECTIONS),
        cover_filename=row.cover_filename, version_id=row.current_version_id,
        version_name=next((v.name for v in row.versions if v.id == row.current_version_id), ""),
        version_count=len(row.versions),
        cover_art_url=row.cover_art_url, cover_card_name=row.cover_card_name,
        created_at=row.created_at, updated_at=row.updated_at,
    )


def to_deck_card(row: DeckCardRow) -> DeckCard:
    fields = dict(
        id=row.id, deck_id=row.deck_id, oracle_id=row.oracle_id, card_name=row.card_name, quantity=row.quantity,
        section=row.section, scryfall_id=row.scryfall_id, custom_print_id=row.custom_print_id,
        custom_card_id=row.custom_card_id, foil=row.foil, is_proxy=row.is_proxy,
        price_paid_cents=row.price_paid_cents, notes=row.notes, set_code=row.set_code, set_name=row.set_name,
        collector_number=row.collector_number, rarity=row.rarity, color_identity=row.color_identity,
        type_line=row.type_line, mana_cost=row.mana_cost, image_small=row.image_small,
        image_normal=row.image_normal, image_art_crop=row.image_art_crop, lang=row.lang)
    if row.custom_card is not None:  # nome e dados sempre os atuais da carta personalizada
        fields.update(card_name=row.custom_card.name, set_code="", set_name="Carta personalizada",
                      collector_number="", rarity="special", type_line=row.custom_card.type_line,
                      mana_cost=row.custom_card.mana_cost)
    elif row.custom_print is not None:
        fields.update(set_code=row.custom_print.code, set_name=row.custom_print.name, collector_number="",
                      rarity="special")
    return DeckCard(**fields)


# ---------- decks ----------
def create_deck(s: Session, user_id: int, name: str, format: str = "", notes: str = "",
                folder_id: int | None = None, visibility: str = "private") -> Deck:
    """Cria o deck já com a primeira versão ("Original") como atual.

    Dois flush: o id da versão só existe depois de gravada, e o deck precisa dele em current_version_id."""
    folders.check_folder(s, user_id, folders.DECKS, folder_id)
    row = DeckRow(user_id=user_id, folder_id=folder_id, cover_card_name="", **_fields(name, format, notes,
                                                                                         visibility))
    s.add(row)
    row.versions.append(DeckVersionRow(name=FIRST_VERSION))
    s.flush()
    row.current_version_id = row.versions[0].id
    s.flush()
    return to_deck(row)


def update_deck(s: Session, user_id: int, deck_id: int, *, name: str, format: str = "", notes: str = "",
                folder_id: int | None = None, visibility: str = "private") -> Deck:
    """Troca os dados gerais do deck (não mexe nas cartas nem nas versões)."""
    row = _deck_row(s, user_id, deck_id)
    folders.check_folder(s, user_id, folders.DECKS, folder_id)
    for key, value in _fields(name, format, notes, visibility).items():
        setattr(row, key, value)
    row.folder_id = folder_id
    s.flush()
    return to_deck(row)


def get_deck(s: Session, user_id: int, deck_id: int) -> Deck:
    return to_deck(_deck_row(s, user_id, deck_id))


def list_decks(s: Session, user_id: int) -> list[Deck]:
    """Decks do usuário, do mais recente para o mais antigo (atualização)."""
    query = select(DeckRow).where(DeckRow.user_id == user_id) \
        .options(selectinload(DeckRow.cards), selectinload(DeckRow.versions)) \
        .order_by(DeckRow.updated_at.desc(), DeckRow.id.desc())
    return [to_deck(r) for r in s.scalars(query)]


def count_decks(s: Session, user_id: int) -> int:
    return s.scalar(select(func.count()).select_from(DeckRow).where(DeckRow.user_id == user_id))


def delete_decks(s: Session, user_id: int, deck_ids: list[int]) -> list[str]:
    """Apaga vários decks de uma vez (todos ou nenhum), com as cartas personalizadas que só existiam neles.
    Devolve as imagens (capas e dessas cartas) que podem ter ficado sem uso."""
    rows = _deck_rows(s, user_id, deck_ids)
    ids = [r.id for r in rows]
    files = [r.cover_filename for r in rows if r.cover_filename]
    files += s.scalars(select(CustomCardRow.image_filename).where(
        CustomCardRow.deck_id.in_(ids), CustomCardRow.image_filename.is_not(None))).all()
    # um DELETE para todos: versões, cartas, vitórias e cartas só do deck saem pelas chaves estrangeiras
    s.execute(delete(DeckRow).where(DeckRow.id.in_(ids)))
    s.expire_all()
    return files


def move_decks(s: Session, user_id: int, deck_ids: list[int], folder_id: int | None) -> int:
    """Move os decks para a pasta (None = sem pasta), todos ou nenhum. Devolve quantos foram movidos."""
    folders.check_folder(s, user_id, folders.DECKS, folder_id)
    rows = _deck_rows(s, user_id, deck_ids)
    s.execute(update(DeckRow).where(DeckRow.id.in_([r.id for r in rows])).values(folder_id=folder_id))
    s.expire_all()
    return len(rows)


# ---------- versões ----------
def list_versions(s: Session, user_id: int, deck_id: int) -> list[DeckVersion]:
    row = _deck_row(s, user_id, deck_id)
    counts = dict(s.execute(
        select(DeckCardRow.version_id, func.sum(DeckCardRow.quantity))
        .where(DeckCardRow.deck_id == row.id, DeckCardRow.section.in_(DECK_SECTIONS))
        .group_by(DeckCardRow.version_id)).all())
    return [DeckVersion(id=v.id, deck_id=row.id, name=v.name, card_count=counts.get(v.id, 0),
                        created_at=v.created_at) for v in row.versions]


def create_version(s: Session, user_id: int, deck_id: int, name: str) -> Deck:
    """Nova versão com cópia das cartas da versão atual, e já passa a ser a atual."""
    row = _deck_row(s, user_id, deck_id)
    version = DeckVersionRow(name=_version_name(row, name))
    row.versions.append(version)
    s.flush()
    copies = [{**{c.key: getattr(line, c.key) for c in DeckCardRow.__table__.columns
                  if c.key not in ("id", "version_id", "created_at")}, "version_id": version.id}
              for line in row.cards]
    if copies:
        s.execute(insert(DeckCardRow), copies)  # uma gravação para todas as linhas copiadas
    return select_version(s, user_id, deck_id, version.id)


def select_version(s: Session, user_id: int, deck_id: int, version_id: int) -> Deck:
    """Torna a versão a atual: a que a grade mostra e a que a montagem edita."""
    row = _deck_row(s, user_id, deck_id)
    if not any(v.id == version_id for v in row.versions):
        raise DeckError("Versão não encontrada.")
    row.current_version_id = version_id
    s.flush()
    s.expire(row, ["cards"])  # a lista de cartas passa a ser a da outra versão
    return to_deck(row)


def rename_version(s: Session, user_id: int, deck_id: int, version_id: int, name: str) -> None:
    """Renomeia a versão; o nome não pode repetir o de outra versão do mesmo deck (sem diferenciar maiúsculas)."""
    row = _deck_row(s, user_id, deck_id)
    version = _version_row(row, version_id)
    version.name = _version_name(row, name, ignore=version)
    s.flush()


def delete_version(s: Session, user_id: int, deck_id: int, version_id: int) -> Deck:
    """Apaga a versão e as cartas dela. A última versão não pode ser apagada."""
    row = _deck_row(s, user_id, deck_id)
    version = _version_row(row, version_id)
    if len(row.versions) == 1:
        raise DeckError("O deck precisa ter pelo menos uma versão.")
    remaining = [v for v in row.versions if v.id != version_id]
    if row.current_version_id == version_id:
        row.current_version_id = remaining[-1].id
    s.execute(delete(DeckCardRow).where(DeckCardRow.version_id == version_id))
    row.versions.remove(version)
    s.flush()
    s.expire(row, ["cards"])
    return to_deck(row)


def _version_row(row: DeckRow, version_id: int) -> DeckVersionRow:
    version = next((v for v in row.versions if v.id == version_id), None)
    if version is None:
        raise DeckError("Versão não encontrada.")
    return version


def _version_name(row: DeckRow, name: str, ignore: DeckVersionRow | None = None) -> str:
    name = " ".join(name.split())[:config.VERSION_NAME_MAX]
    if not name:
        raise DeckError("Dê um nome para a versão.")
    if any(v.name.lower() == name.lower() for v in row.versions if v is not ignore):
        raise DeckError(f"Já existe uma versão chamada \"{name}\".")
    return name


# ---------- capa ----------
def set_cover_card(s: Session, user_id: int, deck_id: int, deck_card_id: int) -> tuple[Deck, str | None]:
    """Usa a arte de uma carta do deck como capa. Devolve (deck, imagem enviada que deixou de ser usada)."""
    row = _deck_row(s, user_id, deck_id)
    card = next((c for c in row.cards if c.id == deck_card_id), None)
    if card is None:
        raise DeckError("Essa carta não está neste deck.")
    old_file = row.cover_filename
    row.cover_filename = None
    row.cover_art_url = card.image_art_crop or card.image_normal
    row.cover_card_name = card.card_name
    s.flush()
    return to_deck(row), old_file


def set_cover_image(s: Session, user_id: int, deck_id: int, filename: str) -> tuple[Deck, str | None]:
    """Usa uma imagem enviada como capa (tem prioridade sobre a arte de carta). Devolve (deck, imagem enviada
    anterior), para quem chama apagar o arquivo se ninguém mais usar."""
    row = _deck_row(s, user_id, deck_id)
    old_file = row.cover_filename
    row.cover_filename = filename
    s.flush()
    return to_deck(row), old_file


def clear_cover(s: Session, user_id: int, deck_id: int) -> tuple[Deck, str | None]:
    """Tira a capa (enviada e de carta). Devolve (deck, imagem enviada que deixou de ser usada)."""
    row = _deck_row(s, user_id, deck_id)
    old_file = row.cover_filename
    row.cover_filename, row.cover_art_url, row.cover_card_name = None, None, ""
    s.flush()
    return to_deck(row), old_file


def cover_image_in_use(s: Session, filename: str) -> bool:
    return s.scalar(select(DeckRow.id).where(DeckRow.cover_filename == filename)) is not None


def can_view_cover(s: Session, viewer_id: int, filename: str) -> bool:
    """Dono sempre vê; amigos veem a capa de decks marcados como visíveis para eles (de conta ativa)."""
    row = s.execute(select(DeckRow.user_id, DeckRow.visibility, UserRow.is_disabled)
                    .join(UserRow, UserRow.id == DeckRow.user_id).where(DeckRow.cover_filename == filename)).first()
    return row is not None and (row.user_id == viewer_id or (row.visibility == "friends" and not row.is_disabled))


# ---------- decks dos amigos (só leitura) ----------
@dataclass(frozen=True, slots=True)
class SharedDeck:
    deck: Deck
    owner_name: str
    owner_avatar: str | None = None


def list_shared_decks(s: Session, viewer_id: int) -> list[SharedDeck]:
    """Decks de outros usuários marcados como visíveis para os amigos, mais recentes primeiro."""
    query = select(DeckRow, UserRow.display_name, UserRow.avatar_filename) \
        .join(UserRow, UserRow.id == DeckRow.user_id) \
        .where(DeckRow.user_id != viewer_id, DeckRow.visibility == "friends", UserRow.is_disabled.is_(False)) \
        .options(selectinload(DeckRow.cards), selectinload(DeckRow.versions)) \
        .order_by(DeckRow.updated_at.desc(), DeckRow.id.desc())
    return [SharedDeck(to_deck(row), name, avatar) for row, name, avatar in s.execute(query)]


def get_shared_deck(s: Session, viewer_id: int, deck_id: int) -> SharedDeck:
    """Deck de outro usuário, se ele deixou visível. Deck privado ou de conta desativada responde como
    inexistente (a conta desativada some para os amigos, mas os dados continuam lá)."""
    row = s.get(DeckRow, deck_id)
    owner = s.get(UserRow, row.user_id) if row is not None else None
    if row is None or row.user_id == viewer_id or row.visibility != "friends" or owner.is_disabled:
        raise DeckError("Deck não encontrado.")
    return SharedDeck(to_deck(row), owner.display_name, owner.avatar_filename)


def shared_versions(s: Session, viewer_id: int, deck_id: int) -> list[DeckVersion]:
    deck = get_shared_deck(s, viewer_id, deck_id).deck
    return list_versions(s, deck.user_id, deck_id)


def shared_cards(s: Session, viewer_id: int, deck_id: int, version_id: int | None = None) -> list[DeckCard]:
    """Cartas de uma versão (a atual do dono, se não disser qual). Ver outra versão não muda a do dono."""
    deck = get_shared_deck(s, viewer_id, deck_id).deck
    return list_cards(s, deck.user_id, deck_id, version_id)


def can_view_card_image(s: Session, viewer_id: int, image_url: str) -> bool:
    """Imagem de carta/versão personalizada que aparece num deck visível para o amigo.

    Parte do arquivo (nome no fim do endereço) para a versão ou carta dona dele e daí para as linhas de deck pelo
    id, tudo com índice. Comparar o endereço com as cópias guardadas nas linhas percorria a tabela inteira a cada
    imagem pedida."""
    filename = image_url.rsplit("/", 1)[-1]
    prints = select(CustomPrintRow.id).where(CustomPrintRow.image_filename == filename)
    cards = select(CustomCardRow.id).where(CustomCardRow.image_filename == filename)
    visible = select(DeckCardRow.id).join(DeckRow, DeckRow.id == DeckCardRow.deck_id) \
        .join(UserRow, UserRow.id == DeckRow.user_id) \
        .where(DeckRow.visibility == "friends", DeckRow.user_id != viewer_id, UserRow.is_disabled.is_(False))
    return any(s.scalar(visible.where(condition).limit(1)) is not None
               for condition in (DeckCardRow.custom_print_id.in_(prints), DeckCardRow.custom_card_id.in_(cards)))


# ---------- cartas do deck ----------
def add_card(s: Session, user_id: int, deck_id: int, card: Card, quantity: int = 1, section: str = "main", *,
             foil: bool = False, is_proxy: bool = False) -> DeckCard:
    """Adiciona ao deck. Soma numa linha igual (mesma impressão, seção e foil/proxy, sem preço e observação)."""
    row = _deck_row(s, user_id, deck_id)
    _check_line(section, quantity)
    if not card.oracle_id:
        raise DeckError("Esta carta não pode ser adicionada.")
    _check_printing(s, user_id, deck_id, card)
    existing = next((c for c in row.cards if c.section == section and c.foil == foil and c.is_proxy == is_proxy
                     and c.price_paid_cents is None and not c.notes and _same_printing(c, card)), None)
    if existing:
        # no máximo só soma o que cabe; se não cabe nenhuma, avisa em vez de fingir que adicionou
        if existing.quantity >= MAX_QUANTITY:
            raise DeckError(f"Essa carta já tem o máximo de {MAX_QUANTITY} cópias nesta seção.")
        existing.quantity = min(existing.quantity + quantity, MAX_QUANTITY)
        s.flush()
        return to_deck_card(existing)
    line = DeckCardRow(quantity=quantity, section=section, foil=foil, is_proxy=is_proxy, notes="",
                       **_printing_fields(card))
    row.cards.append(line)
    s.flush()
    return to_deck_card(line)


def set_commanders(s: Session, user_id: int, deck_id: int, cards: list[Card]) -> None:
    """Define os comandantes (até 2, com parceiro). Quem já era comandante continua com a mesma linha."""
    if len(cards) > 2:
        raise DeckError("No máximo 2 comandantes (com parceiro).")
    _set_zone(s, user_id, deck_id, "commander", cards, from_section="main")


def set_companion(s: Session, user_id: int, deck_id: int, card: Card | None) -> None:
    _set_zone(s, user_id, deck_id, "companion", [card] if card else [], from_section="sideboard")


def _set_zone(s: Session, user_id: int, deck_id: int, section: str, cards: list[Card], from_section: str) -> None:
    """Troca as cartas da zona de comando. Carta que já estava no deck (em `from_section`) é levada para a zona,
    para não ficar repetida."""
    row = _deck_row(s, user_id, deck_id)
    if len({c.oracle_id for c in cards}) != len(cards):
        raise DeckError("Escolha cartas diferentes.")
    wanted = {c.oracle_id: c for c in cards}
    for line in [c for c in row.cards if c.section == section]:
        if line.oracle_id in wanted:
            wanted.pop(line.oracle_id)
        else:
            row.cards.remove(line)
            s.delete(line)
    for oracle_id, card in wanted.items():
        _check_printing(s, user_id, deck_id, card)
        existing = next((c for c in row.cards if c.section == from_section and c.oracle_id == oracle_id), None)
        if existing and existing.quantity == 1:
            existing.section = section
            continue
        if existing:
            existing.quantity -= 1
        row.cards.append(DeckCardRow(quantity=1, section=section, foil=False, is_proxy=False, notes="",
                                     **_printing_fields(card)))
    s.flush()


def update_line(s: Session, user_id: int, deck_id: int, line_id: int, *, quantity: int, section: str,
                foil: bool = False, is_proxy: bool = False, price_paid_cents: int | None = None, notes: str = "",
                printing: Card | None = None) -> DeckCard:
    """Edita uma linha. `printing` troca a edição (precisa ser da mesma carta)."""
    line = _line_row(s, user_id, deck_id, line_id)
    _check_line(section, quantity)
    if price_paid_cents is not None and price_paid_cents < 0:
        raise DeckError("Preço inválido.")
    if printing is not None:
        if printing.oracle_id != line.oracle_id:
            raise DeckError("A edição escolhida é de outra carta.")
        _check_printing(s, user_id, deck_id, printing)
        for key, value in _printing_fields(printing).items():
            setattr(line, key, value)
    line.quantity, line.section, line.foil, line.is_proxy = quantity, section, foil, is_proxy
    line.price_paid_cents, line.notes = price_paid_cents, notes.strip()
    s.flush()
    return to_deck_card(line)


def change_quantity(s: Session, user_id: int, deck_id: int, line_id: int, delta: int) -> DeckCard | None:
    """Soma ou subtrai cópias. Chegando a zero, a linha sai do deck (devolve None)."""
    line = _line_row(s, user_id, deck_id, line_id)
    new_quantity = line.quantity + delta
    if new_quantity <= 0:
        s.delete(line)
        s.flush()
        return None
    line.quantity = min(new_quantity, MAX_QUANTITY)
    s.flush()
    return to_deck_card(line)


def remove_line(s: Session, user_id: int, deck_id: int, line_id: int) -> None:
    s.delete(_line_row(s, user_id, deck_id, line_id))
    s.flush()


def list_cards(s: Session, user_id: int, deck_id: int, version_id: int | None = None) -> list[DeckCard]:
    """Cartas da versão atual (ou de outra versão do mesmo deck, só para ler)."""
    row = _deck_row(s, user_id, deck_id)
    if version_id is None or version_id == row.current_version_id:
        cards = row.cards
    else:
        _version_row(row, version_id)
        cards = s.scalars(select(DeckCardRow).where(DeckCardRow.version_id == version_id)).all()
    return [to_deck_card(c) for c in sorted(cards, key=lambda c: (SECTIONS.index(c.section), c.card_name, c.id))]


@dataclass(frozen=True, slots=True)
class Change:
    """Diferença de uma carta, numa seção, entre duas versões do deck."""
    card_name: str
    section: str
    before: int  # cópias na versão A
    after: int  # cópias na versão B
    type_line: str = ""

    @property
    def delta(self) -> int:
        return self.after - self.before


def compare_versions(s: Session, user_id: int, deck_id: int, version_a: int, version_b: int) -> list[Change]:
    """O que muda de A para B, por carta (qualquer edição) e seção. Só as cartas com quantidade diferente."""
    def totals(version_id: int) -> dict[tuple[str, str], tuple[int, DeckCard]]:
        result: dict[tuple[str, str], tuple[int, DeckCard]] = {}
        for line in list_cards(s, user_id, deck_id, version_id):
            key = (line.oracle_id, line.section)
            result[key] = (result.get(key, (0, line))[0] + line.quantity, line)
        return result

    a, b = totals(version_a), totals(version_b)
    changes = []
    for key in a.keys() | b.keys():
        before, after = a.get(key, (0, None))[0], b.get(key, (0, None))[0]
        if before != after:
            line = (b.get(key) or a.get(key))[1]
            changes.append(Change(line.card_name, line.section, before, after, line.type_line))
    return sorted(changes, key=lambda c: (SECTIONS.index(c.section), c.card_name))


# ---------- deck x coleção ----------
@dataclass(frozen=True, slots=True)
class Missing:
    line: DeckCard
    quantity: int  # cópias desta linha que não estão na coleção


def missing_in_collection(s: Session, user_id: int, deck_id: int) -> list[Missing]:
    """Cartas do deck que faltam na coleção, por carta (qualquer edição) e quantidade.
    A seção "talvez" não conta. Se o deck pede 4 e a coleção tem 2, faltam 2 (das primeiras linhas)."""
    return missing_against(s, user_id, list_cards(s, user_id, deck_id))


def missing_against(s: Session, collector_id: int, lines: list[DeckCard]) -> list[Missing]:
    """O que falta na coleção de `collector_id` para montar estas linhas (serve para deck de amigo também)."""
    lines = [c for c in lines if c.section != "maybe"]
    if not lines:
        return []
    # só a soma por carta (qualquer edição), e só das cartas do deck: nada de carregar a coleção inteira
    owned: dict[str, int] = dict(s.execute(
        select(CollectionEntryRow.oracle_id, func.sum(CollectionEntryRow.quantity))
        .where(CollectionEntryRow.user_id == collector_id,
               CollectionEntryRow.oracle_id.in_({line.oracle_id for line in lines}))
        .group_by(CollectionEntryRow.oracle_id)).all())
    missing = []
    for line in lines:
        have = owned.get(line.oracle_id, 0)
        used = min(have, line.quantity)
        owned[line.oracle_id] = have - used
        if line.quantity > used:
            missing.append(Missing(line, line.quantity - used))
    return missing


def add_missing_to_collection(s: Session, user_id: int, deck_id: int, folder_id: int | None = None) -> int:
    """Põe na coleção as cópias que faltam, com edição, foil, proxy, preço e observações de cada linha.
    Cartas personalizadas que só existiam no deck passam a ser da coleção. Devolve quantas cópias entraram."""
    items = [collection.NewItem(line_as_card(m.line), m.quantity, foil=m.line.foil, is_proxy=m.line.is_proxy,
                                price_paid_cents=m.line.price_paid_cents, notes=m.line.notes)
             for m in missing_in_collection(s, user_id, deck_id)]
    return collection.add_cards(s, user_id, items, folder_id) if items else 0


def line_as_card(line: DeckCard) -> Card:
    """A linha do deck como Card (com os dados guardados nela), para levar à coleção."""
    card_id = line.scryfall_id or (f"custom-{line.custom_print_id}" if line.custom_print_id else line.oracle_id)
    return Card(id=card_id, name=line.card_name, set_code=line.set_code, set_name=line.set_name,
                collector_number=line.collector_number, rarity=line.rarity, type_line=line.type_line,
                mana_cost=line.mana_cost, oracle_text="", oracle_id=line.oracle_id,
                custom_print_id=line.custom_print_id, custom_card_id=line.custom_card_id,
                color_identity=tuple(line.color_identity), image_small=line.image_small,
                image_normal=line.image_normal, image_art_crop=line.image_art_crop, lang=line.lang)


# ---------- internos ----------
def _fields(name: str, format: str, notes: str, visibility: str) -> dict:
    name = " ".join(name.split())
    if not name:
        raise DeckError("Dê um nome para o deck.")
    if visibility not in VISIBILITIES:
        raise DeckError("Visibilidade inválida.")
    return dict(name=name[:config.DECK_NAME_MAX], format=format.strip()[:30], notes=notes.strip(),
                visibility=visibility)


def _check_line(section: str, quantity: int) -> None:
    if section not in SECTIONS:
        raise DeckError("Seção inválida.")
    if not isinstance(quantity, int) or not 1 <= quantity <= MAX_QUANTITY:
        raise DeckError(f"A quantidade deve ser de 1 a {MAX_QUANTITY}.")


def _check_printing(s: Session, user_id: int, deck_id: int, card: Card) -> None:
    """Versões e cartas personalizadas precisam ser do usuário (e a carta, da coleção ou deste deck)."""
    if card.is_custom_card:
        try:
            custom = custom_cards.get(s, user_id, card.custom_card_id)
        except custom_cards.CustomCardError as e:
            raise DeckError(str(e)) from None
        if custom.deck_id not in (None, deck_id):
            raise DeckError("Essa carta personalizada é de outro deck.")
    elif card.is_custom:
        try:
            collection.get_custom_print(s, user_id, card.custom_print_id)
        except collection.CollectionError as e:
            raise DeckError(str(e)) from None


def _same_printing(line: DeckCardRow, card: Card) -> bool:
    if card.is_custom_card:
        return line.custom_card_id == card.custom_card_id
    if card.is_custom:
        return line.custom_print_id == card.custom_print_id
    return line.scryfall_id == card.id and line.custom_print_id is None and line.custom_card_id is None


def _printing_fields(card: Card) -> dict:
    official = not (card.is_custom or card.is_custom_card)
    return dict(
        oracle_id=card.oracle_id, card_name=card.name, scryfall_id=card.id if official else None,
        custom_print_id=card.custom_print_id, custom_card_id=card.custom_card_id,
        set_code=card.set_code, set_name=card.set_name, collector_number=card.collector_number, rarity=card.rarity,
        color_identity="".join(c for c in COLOR_ORDER if c in card.color_identity), type_line=card.type_line,
        mana_cost=card.mana_cost, image_small=card.image_small, image_normal=card.image_normal,
        image_art_crop=card.image_art_crop, lang=card.lang or "en")


def _line_row(s: Session, user_id: int, deck_id: int, line_id: int) -> DeckCardRow:
    deck = _deck_row(s, user_id, deck_id)
    line = next((c for c in deck.cards if c.id == line_id), None)
    if line is None:
        raise DeckError("Essa carta não está neste deck.")
    return line


def _deck_rows(s: Session, user_id: int, deck_ids: list[int]) -> list[DeckRow]:
    """Vários decks do usuário numa consulta; se algum não for dele, erro e nada muda."""
    ids = list(dict.fromkeys(deck_ids))
    rows = s.scalars(select(DeckRow).where(DeckRow.id.in_(ids), DeckRow.user_id == user_id)).all()
    if len(rows) != len(ids):
        raise DeckError("Deck não encontrado.")
    return list(rows)


def _deck_row(s: Session, user_id: int, deck_id: int) -> DeckRow:
    row = s.get(DeckRow, deck_id)
    if row is None or row.user_id != user_id:
        raise DeckError("Deck não encontrado.")
    return row
