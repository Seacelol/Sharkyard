"""Pastas para organizar a coleção e os decks. Sem interface.

Cada usuário tem suas pastas, separadas por tipo (coleção ou decks). Apagar uma pasta não apaga o conteúdo:
os itens voltam para "sem pasta" (o banco faz isso com ON DELETE SET NULL).
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mtg_collection import config
from mtg_collection.database.tables import CollectionEntryRow, DeckRow, FolderRow
from mtg_collection.models import Folder

COLLECTION = "collection"
DECKS = "decks"
_CONTENT = {COLLECTION: CollectionEntryRow, DECKS: DeckRow}


class FolderError(Exception):
    """Erro com mensagem pronta para mostrar ao usuário."""


def list_folders(s: Session, user_id: int, kind: str) -> list[Folder]:
    """Pastas em ordem alfabética, com quantos itens (lotes da coleção ou decks) cada uma tem."""
    content = _CONTENT[kind]
    counts = dict(s.execute(
        select(content.folder_id, func.count()).where(content.user_id == user_id, content.folder_id.is_not(None))
        .group_by(content.folder_id)).all())
    rows = s.scalars(select(FolderRow).where(FolderRow.user_id == user_id, FolderRow.kind == kind)
                     .order_by(func.lower(FolderRow.name)))
    return [Folder(id=r.id, kind=r.kind, name=r.name, item_count=counts.get(r.id, 0)) for r in rows]


def create_folder(s: Session, user_id: int, kind: str, name: str) -> Folder:
    """Cria uma pasta de coleção ou de decks (`kind`); o nome não repete dentro do mesmo tipo."""
    name = _valid_name(s, user_id, kind, name)
    row = FolderRow(user_id=user_id, kind=kind, name=name)
    s.add(row)
    s.flush()
    return Folder(id=row.id, kind=kind, name=name)


def rename_folder(s: Session, user_id: int, folder_id: int, name: str) -> Folder:
    row = _row(s, user_id, folder_id)
    row.name = _valid_name(s, user_id, row.kind, name, ignore_id=row.id)
    return Folder(id=row.id, kind=row.kind, name=row.name)


def delete_folder(s: Session, user_id: int, folder_id: int) -> None:
    s.delete(_row(s, user_id, folder_id))


def check_folder(s: Session, user_id: int, kind: str, folder_id: int | None) -> None:
    """Confere que a pasta (se houver) é do usuário e do tipo certo, antes de colocar algo nela."""
    if folder_id is not None and _row(s, user_id, folder_id).kind != kind:
        raise FolderError("Pasta não encontrada.")


def _valid_name(s: Session, user_id: int, kind: str, name: str, ignore_id: int | None = None) -> str:
    name = " ".join(name.split())[:config.FOLDER_NAME_MAX]
    if not name:
        raise FolderError("Dê um nome para a pasta.")
    query = select(FolderRow.id).where(FolderRow.user_id == user_id, FolderRow.kind == kind,
                                       func.lower(FolderRow.name) == name.lower())
    if ignore_id is not None:
        query = query.where(FolderRow.id != ignore_id)
    if s.scalar(query):
        raise FolderError("Já existe uma pasta com esse nome.")
    return name


def _row(s: Session, user_id: int, folder_id: int) -> FolderRow:
    row = s.get(FolderRow, folder_id)
    if row is None or row.user_id != user_id:
        raise FolderError("Pasta não encontrada.")
    return row
