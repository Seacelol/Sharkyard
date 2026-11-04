"""Cópia local das cartas do Scryfall (arquivo "All Cards" do bulk data). Sem interface.

O Scryfall publica todo dia um arquivo com todas as impressões em todos os idiomas. Ficam só as em inglês e em
português (KEEP_LANGS), mais as que só existem em outro idioma (promoções japonesas, por exemplo), como no arquivo
"Default Cards". O servidor confere de tempos em tempos se saiu um
novo (pela data em /bulk-data) e, se saiu, baixa, monta um banco SQLite novo ao lado e troca pelo antigo de uma vez.
Enquanto não existe cópia local (ou se faltar alguma carta, como as de uma coleção que saiu hoje), o cliente do
Scryfall continua perguntando à API.

Fica em cache/catalogo.db: não precisa de backup, dá para apagar e baixar de novo.
"""
import asyncio
import gzip
import io
import json
import logging
import os
import random
import re
import sqlite3
import time
import unicodedata
from collections.abc import Iterable, Iterator
from contextlib import closing
from pathlib import Path, PurePath
from urllib.parse import quote

import httpx
import ijson

from mtg_collection.models import Card
from mtg_collection.services.scryfall import _printed_name, to_card

log = logging.getLogger(__name__)

BULK_TYPE = "all_cards"
KEEP_LANGS = ("en", "pt")
SCHEMA_VERSION = "3"  # muda quando o banco ganha colunas: uma cópia de versão antiga é montada de novo
CHECK_HOURS = 6  # o arquivo sai uma vez por dia; conferir a cada 6 h pega o novo sem depender do horário
RETRY_MINUTES = 20  # depois de uma falha (sem internet, por exemplo) não espera 6 h para tentar de novo
BATCH = 2000
# Sem resposta por 2 minutos (conexão caiu sem fechar, por exemplo): desiste e tenta de novo na próxima volta.
# Sem isso o download esperaria para sempre e o catálogo nunca mais atualizaria até reiniciar o app.
DOWNLOAD_TIMEOUT = httpx.Timeout(30.0, read=120.0)
SCHEMA = """
CREATE TABLE cards (
    id TEXT PRIMARY KEY, oracle_id TEXT, name TEXT, name_fold TEXT, front_fold TEXT,
    set_code TEXT, collector_number TEXT, released_at TEXT, is_default INTEGER DEFAULT 0, lang TEXT,
    printed_fold TEXT, data TEXT
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""
INDEXES = """
CREATE INDEX ix_oracle ON cards(oracle_id);
CREATE INDEX ix_name ON cards(name_fold);
CREATE INDEX ix_front ON cards(front_fold);
CREATE INDEX ix_set_number ON cards(set_code, collector_number);
CREATE INDEX ix_default ON cards(is_default, name_fold);
CREATE INDEX ix_printed ON cards(printed_fold);
"""


def fold(text: str) -> str:
    """Nome para comparar: minúsculo, sem acento ("Lim-Dûl" -> "lim-dul", "Æther" -> "aether")."""
    text = text.lower().replace("æ", "ae").replace("œ", "oe")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _oracle_id(data: dict) -> str | None:
    return data.get("oracle_id") or ((data.get("card_faces") or [{}])[0].get("oracle_id"))


# edições que não representam bem a carta: lembranças, de brincadeira, tokens, só do Arena e afins
ODD_SET_TYPES = frozenset({"memorabilia", "funny", "token", "minigame", "alchemy", "treasure_chest"})


def _default_rank(data: dict) -> tuple:
    """Qual impressão representa a carta (a que aparece nas sugestões): em inglês, de papel, não promo, com a arte
    e a moldura normais (sem borda especial, arte estendida, versão alternativa), a mais recente. O número de
    colecionador desempata para o resultado não depender da ordem do arquivo."""
    paper = "paper" in (data.get("games") or [])
    basic = (data.get("type_line") or "").startswith("Basic")  # terreno básico de arte inteira é comum, vale igual
    effects = set(data.get("frame_effects") or ()) - {"legendary"}  # a coroa de lendária não é versão alternativa
    number = data.get("collector_number") or ""
    digits = re.match(r"\d+", number)
    return (data.get("lang", "en") == "en", paper, not data.get("digital", False), not data.get("promo", False),
            not data.get("variation", False), data.get("border_color", "black") == "black", not effects,
            basic or not data.get("full_art", False), not data.get("oversized", False),
            data.get("set_type") not in ODD_SET_TYPES, data.get("released_at") or "",
            -int(digits.group()) if digits else -10**9, number)


def build(json_path: Path, db_path: Path, updated_at: str) -> int:
    """Lê o arquivo do Scryfall aos poucos (sem carregar tudo na memória) e monta o banco. Devolve quantas cartas.

    Duas passadas: a 1ª anota quais (edição, número) existem em inglês ou português; a 2ª guarda esses dois idiomas
    e, dos outros, só a primeira impressão de um (edição, número) que não existe em nenhum dos dois. Nas linhas
    descartadas o JSON nem é lido por inteiro."""
    db_path.unlink(missing_ok=True)
    kept = {key for raw, data in _entries(json_path) if (peek := _peek(raw, data))[0] in KEEP_LANGS
            for key in [peek[1]]}
    best: dict[str, tuple[tuple, str]] = {}
    only_other: set[tuple[str, str]] = set()
    count = 0
    with closing(sqlite3.connect(db_path)) as db:
        db.executescript(SCHEMA)
        rows = []
        for raw, data in _entries(json_path):
            lang, key = _peek(raw, data)
            if lang not in KEEP_LANGS:
                if key in kept or key in only_other:
                    continue
                only_other.add(key)
            data = data if data is not None else json.loads(raw)
            oracle_id = _oracle_id(data)
            if not oracle_id or data.get("layout") in ("art_series", "token", "double_faced_token", "emblem"):
                continue
            name = data.get("name", "")
            # nome em português: também se busca por ele. Só PT, senão uma promo japonesa viraria resultado em PT
            printed = _printed_name(data) if lang == "pt" else ""
            rows.append((data["id"], oracle_id, name, fold(name), fold(name.split(" // ")[0]),
                         data.get("set", "").lower(), data.get("collector_number", ""), data.get("released_at", ""),
                         lang, fold(printed) if printed else None, json.dumps(data, separators=(",", ":"))))
            rank = _default_rank(data)
            if oracle_id not in best or rank > best[oracle_id][0]:
                best[oracle_id] = (rank, data["id"])
            if len(rows) >= BATCH:
                count += _insert(db, rows)
        count += _insert(db, rows)
        db.executemany("UPDATE cards SET is_default = 1 WHERE id = ?", [(card_id,) for _, card_id in best.values()])
        db.executescript(INDEXES)
        db.executemany("INSERT INTO meta VALUES (?, ?)", [("updated_at", updated_at), ("bulk_type", BULK_TYPE),
                                                          ("schema", SCHEMA_VERSION)])
        db.commit()
    return count


# idioma, edição e número direto do texto da linha, sem ler o JSON inteiro (chaves de nível de cima: as faces e
# as partes relacionadas não têm esses campos, e aspas dentro de textos vêm escapadas)
_LANG = re.compile(rb'"lang":\s*"([^"]*)"')
_SET = re.compile(rb'"set":\s*"([^"]*)"')
_NUMBER = re.compile(rb'"collector_number":\s*"([^"]*)"')


def _peek(raw: bytes | None, data: dict | None) -> tuple[str, tuple[str, str]]:
    if data is not None:
        return data.get("lang", "en"), (data.get("set", "").lower(), data.get("collector_number", ""))
    lang, set_code, number = (m.group(1).decode() if (m := pattern.search(raw)) else ""
                              for pattern in (_LANG, _SET, _NUMBER))
    return lang or "en", (set_code.lower(), number)


def _entries(path: Path) -> Iterator[tuple[bytes | None, dict | None]]:
    """(linha, None) quando o arquivo tem uma carta por linha (JSONL); (None, carta) quando é uma lista JSON."""
    with _open(path) as source:
        first = b""
        while not first.strip():
            first = source.read(1)
            if not first:
                return
        rest = io.BufferedReader(_Prefixed(first, source), buffer_size=1 << 20)
        if first == b"[":
            for data in ijson.items(rest, "item", use_float=True):
                yield None, data
        else:
            for line in rest:
                if line.strip():
                    yield line, None


def _open(path: Path):
    """Abre o arquivo baixado, descompactando se vier em .gz (o Scryfall publica .jsonl.gz)."""
    with open(path, "rb") as probe:
        gzipped = probe.read(2) == b"\x1f\x8b"
    return gzip.open(path, "rb") if gzipped else open(path, "rb")


class _Prefixed(io.RawIOBase):
    """Devolve os bytes já lidos na sondagem e depois continua lendo do arquivo."""

    def __init__(self, prefix: bytes, source):
        self._prefix, self._source = prefix, source

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        """Contrato do RawIOBase: preenche `buffer` e devolve quantos bytes entraram (0 = fim do arquivo)."""
        data = self._prefix or self._source.read(len(buffer))
        self._prefix = b""
        buffer[:len(data)] = data
        return len(data)


def _insert(db: sqlite3.Connection, rows: list) -> int:
    db.executemany("INSERT OR REPLACE INTO cards (id, oracle_id, name, name_fold, front_fold, set_code, "
                   "collector_number, released_at, lang, printed_fold, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   rows)
    n = len(rows)
    rows.clear()
    return n


class Catalog:
    """Consultas na cópia local. Abre uma conexão por consulta (rápido no SQLite) para a troca do arquivo
    por um novo nunca esbarrar numa conexão aberta."""

    def __init__(self, path: Path):
        self.path = path
        self._checked: tuple[tuple[int, int], bool] | None = None  # (arquivo, pronto?) da última conferência
        self._defaults: tuple[tuple[int, int], int] | None = None  # (arquivo, quantas cartas) para o sorteio

    def _signature(self) -> tuple[int, int] | None:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return None
        return stat.st_mtime_ns, stat.st_size

    @property
    def ready(self) -> bool:
        """Existe e foi montado do arquivo atual (BULK_TYPE). Uma cópia antiga, do "Default Cards", fica de fora
        até a nova ficar pronta: o cliente usa a API nesse meio-tempo. Só confere de novo se o arquivo mudar.
        Arquivo estragado (vazio, cortado, não é SQLite) também conta como não pronto: o update monta de novo."""
        signature = self._signature()
        if signature is None:
            return False
        if self._checked is None or self._checked[0] != signature:
            try:
                meta = dict(self._query("SELECT key, value FROM meta"))
            except sqlite3.DatabaseError:
                meta = {}
            self._checked = (signature, meta.get("bulk_type") == BULK_TYPE and meta.get("schema") == SCHEMA_VERSION)
        return self._checked[1]

    def _query(self, sql: str, params: Iterable = ()) -> list[tuple]:
        with closing(sqlite3.connect(_readonly_uri(self.path.absolute()), uri=True)) as db:
            return db.execute(sql, tuple(params)).fetchall()

    @staticmethod
    def _cards(rows: list[tuple]) -> list[Card]:
        return [to_card(json.loads(row[0])) for row in rows]

    def updated_at(self) -> str | None:
        if not self.ready:
            return None
        rows = self._query("SELECT value FROM meta WHERE key = 'updated_at'")
        return rows[0][0] if rows else None

    def count(self) -> int:
        return self._query("SELECT count(*) FROM cards")[0][0] if self.ready else 0

    def get(self, card_id: str) -> Card | None:
        found = self._cards(self._query("SELECT data FROM cards WHERE id = ?", [card_id]))
        return found[0] if found else None

    def random(self) -> Card | None:
        """Uma carta qualquer, na impressão que representa ela, todas com a mesma chance. Sorteia a posição entre
        as cartas (a contagem fica guardada até o arquivo mudar) e pula até ela só no índice, sem ler a tabela."""
        signature = self._signature()
        if self._defaults is None or self._defaults[0] != signature:
            self._defaults = (signature, self._query("SELECT count(*) FROM cards WHERE is_default = 1")[0][0])
        if not self._defaults[1]:
            return None
        found = self._cards(self._query(
            "SELECT data FROM cards WHERE rowid IN (SELECT rowid FROM cards INDEXED BY ix_default "
            "WHERE is_default = 1 LIMIT 1 OFFSET ?)", [random.randrange(self._defaults[1])]))
        return found[0] if found else None

    def prints(self, oracle_id: str) -> list[Card]:
        """Todas as impressões, da mais recente para a mais antiga (como a página da carta mostra)."""
        return self._cards(self._query(
            "SELECT data FROM cards WHERE oracle_id = ? "
            "ORDER BY released_at DESC, set_code, collector_number, lang = 'en' DESC",
            [oracle_id]))

    def find(self, identifier: dict) -> Card | None:
        """Mesmos identificadores do /cards/collection: id, oracle_id, set+número ou nome (com edição opcional)."""
        if "id" in identifier:
            return self.get(identifier["id"])
        if "oracle_id" in identifier:
            rows = self._query("SELECT data FROM cards WHERE oracle_id = ? "
                               "ORDER BY is_default DESC, lang = 'en' DESC, released_at DESC LIMIT 1",
                               [identifier["oracle_id"]])
        elif "collector_number" in identifier:  # a mesma edição e número em português: fica a em inglês
            rows = self._query("SELECT data FROM cards WHERE set_code = ? AND collector_number = ? "
                               "ORDER BY lang = 'en' DESC LIMIT 1",
                               [identifier.get("set", "").lower(), identifier["collector_number"]])
        elif "name" in identifier:
            name = fold(identifier["name"].strip())
            sql = "SELECT data FROM cards WHERE (name_fold = ? OR front_fold = ?)"
            params = [name, name]
            if identifier.get("set"):
                sql += " AND set_code = ?"
                params.append(identifier["set"].lower())
            rows = self._query(sql + " ORDER BY is_default DESC, lang = 'en' DESC, released_at DESC LIMIT 1", params)
        else:
            return None
        found = self._cards(rows)
        return found[0] if found else None

    def suggest(self, text: str, limit: int = 8) -> list[Card]:
        """O nome exato primeiro (ou o da frente: "Fire" acha "Fire // Ice" antes de "Fireball"); depois os que
        começam com o texto; por fim os que têm o texto em qualquer parte. Vale o nome em inglês e o impresso em
        português (aí a sugestão é a impressão em português mais recente da carta)."""
        needle = fold(text.strip())
        if len(needle) < 2:
            return []
        contains = f"%{_escape_like(needle)}%"
        front = needle + " // "
        found: dict[str, tuple] = {}  # oracle_id -> (prioridade, tamanho do nome, nome, data)
        printed = "SELECT data, oracle_id, printed_fold, max(released_at) FROM cards WHERE "
        queries = [
            # o "+" impede o SQLite de escolher o índice de is_default (percorreria todas): usa ix_name e ix_front
            (0, "SELECT data, oracle_id, name_fold FROM cards WHERE +is_default = 1 AND (name_fold = ? OR "
                "front_fold = ?) LIMIT ?", [needle, needle, limit]),
            (0, printed + "(printed_fold = ? OR (printed_fold >= ? AND printed_fold < ?)) GROUP BY oracle_id LIMIT ?",
             [needle, front, front + "\uffff", limit]),
            # os que começam com o texto: faixa no índice, rápido mesmo com dezenas de milhares de cartas
            (1, "SELECT data, oracle_id, name_fold FROM cards WHERE is_default = 1 AND name_fold >= ? "
                "AND name_fold < ? ORDER BY length(name) LIMIT ?", [needle, needle + "\uffff", limit]),
            (1, printed + "printed_fold >= ? AND printed_fold < ? GROUP BY oracle_id ORDER BY length(printed_fold) "
                "LIMIT ?", [needle, needle + "\uffff", limit]),
            # os que têm o texto no meio: o LIKE percorre só o índice (pequeno) e depois busca as linhas achadas,
            # em vez de ler a tabela inteira com o JSON das cartas
            (2, "SELECT data, oracle_id, name_fold FROM cards WHERE rowid IN (SELECT rowid FROM cards INDEXED BY "
                "ix_default WHERE is_default = 1 AND name_fold LIKE ? ESCAPE '\\') ORDER BY length(name) LIMIT ?",
             [contains, limit]),
            (2, printed + f"rowid IN ({_PRINTED_LIKE}) GROUP BY oracle_id ORDER BY length(printed_fold) LIMIT ?",
             [contains, limit]),
        ]
        for priority, sql, params in queries:
            if sum(key[0] < priority for key in found.values()) >= limit:
                break  # as de prioridade maior já enchem a lista
            for row in self._query(sql, params):
                key = (priority, len(row[2]), row[2], row[0])
                if row[1] not in found or key < found[row[1]]:
                    found[row[1]] = key
        best = sorted(found.values())[:limit]
        return [to_card(json.loads(item[3])) for item in best]

    def search_printed(self, text: str, limit: int = 175) -> list[Card]:
        """Cartas cujo nome em português tem todas as palavras do texto (uma impressão por carta, a mais recente)."""
        words = fold(text).split()
        if not words or len(" ".join(words)) < 2:
            return []
        clauses = "".join(" AND printed_fold LIKE ? ESCAPE '\\'" for _ in words[1:])
        params = [f"%{_escape_like(w)}%" for w in words]
        rows = self._query(f"SELECT data, max(released_at) FROM cards WHERE rowid IN ({_PRINTED_LIKE}{clauses}) "
                           "GROUP BY oracle_id ORDER BY length(printed_fold), printed_fold LIMIT ?", [*params, limit])
        return self._cards(rows)


# Busca "contém" nos nomes em português só pelo índice ix_printed: as linhas sem nome PT (NULL) ficam de fora pela
# faixa e o LIKE não lê o JSON das cartas. Medido: ~2 ms contra ~200 ms lendo a tabela.
_PRINTED_LIKE = ("SELECT rowid FROM cards INDEXED BY ix_printed WHERE printed_fold > '' "
                 "AND printed_fold LIKE ? ESCAPE '\\'")


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _readonly_uri(path: PurePath) -> str:
    """URI só leitura do SQLite. O caminho vai codificado: "#", "?" e "%" num nome de pasta quebrariam a URI.
    No Windows fica file:///C:/..., que o SQLite entende como o caminho com a letra do disco."""
    posix = path.as_posix()
    return "file://" + quote(posix if posix.startswith("/") else "/" + posix, safe="/:") + "?mode=ro"


async def update(client, catalog: Catalog) -> bool:
    """Baixa e monta o catálogo se o Scryfall tiver um arquivo mais novo. Devolve True se atualizou."""
    info = client._json(await client._get(f"/bulk-data/{BULK_TYPE}"))
    remote = info["updated_at"]
    if catalog.updated_at() == remote:
        return False
    url = _download_url(info)
    if not url:  # a resposta direta veio sem o link: procura na lista de todos os arquivos
        listing = client._json(await client._get("/bulk-data")).get("data") or []
        url = next((_download_url(item) for item in listing if item.get("type") == BULK_TYPE), None)
    if not url:
        raise RuntimeError(f"O Scryfall não informou o link do arquivo. Campos recebidos: {sorted(info)}")
    catalog.path.parent.mkdir(parents=True, exist_ok=True)
    download = catalog.path.with_suffix(".download.json")
    building = catalog.path.with_suffix(".building.db")
    log.info("Catálogo do Scryfall: baixando o arquivo de %s", remote)
    try:
        async with client.http.stream("GET", url, timeout=DOWNLOAD_TIMEOUT) as response:
            response.raise_for_status()
            with open(download, "wb") as out:
                async for chunk in response.aiter_bytes(1 << 20):
                    out.write(chunk)
        # montar e trocar fora do loop da interface: a troca pode esperar alguém terminar de ler no Windows
        count = await asyncio.to_thread(_build_and_replace, download, building, catalog.path, remote)
    finally:  # deu certo ou não, nada temporário fica para trás; se a troca falhou, o catálogo atual segue intacto
        download.unlink(missing_ok=True)
        building.unlink(missing_ok=True)
    log.info("Catálogo do Scryfall atualizado: %s cartas", count)
    return True


def _download_url(info: dict) -> str | None:
    """Link do arquivo: "download_uri" pela documentação; aceita outro campo com "download" no nome se mudar."""
    for key in ("download_uri", *sorted(k for k in info if "download" in k)):
        value = info.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    return None


def _build_and_replace(download: Path, building: Path, target: Path, updated_at: str) -> int:
    count = build(download, building, updated_at)
    _replace(building, target)
    return count


def _replace(source: Path, target: Path, attempts: int = 25) -> None:
    """Troca o arquivo de uma vez. No Windows a troca falha se alguém estiver lendo naquele instante: tenta de novo."""
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.2)


async def keep_updated(client, catalog: Catalog) -> None:
    """Roda para sempre em segundo plano: confere agora e depois a cada CHECK_HOURS horas. Se falhar, tenta de novo
    em RETRY_MINUTES minutos."""
    while True:
        try:
            await update(client, catalog)
            delay = CHECK_HOURS * 3600
        except Exception:  # sem internet, Scryfall fora do ar: tenta de novo daqui a pouco
            log.exception("Não deu para atualizar o catálogo do Scryfall agora")
            delay = RETRY_MINUTES * 60
        await asyncio.sleep(delay)
