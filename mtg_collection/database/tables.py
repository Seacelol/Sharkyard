"""Tabelas do banco (ORM). Só a camada de serviços usa estas classes; a interface recebe os modelos de domínio."""
from datetime import UTC, date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    """Conta de usuário. Entra por convite (ver services.accounts); o primeiro a se cadastrar vira admin."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # sempre minúsculo
    display_name: Mapped[str] = mapped_column(String(60))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Trocado a cada troca de senha: invalida a sessão em outros navegadores
    session_token: Mapped[str] = mapped_column(String(64))
    # o admin pode tirar a pessoa do ranking sem apagar as vitórias
    hidden_from_ranking: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    avatar_filename: Mapped[str | None] = mapped_column(String(80), nullable=True)  # ícone já recortado
    bio: Mapped[str] = mapped_column(String(20), default="", server_default="")
    # senha temporária gerada pelo admin: a pessoa precisa criar uma nova antes de usar o app
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    is_disabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")  # não consegue entrar
    theme: Mapped[str] = mapped_column(String(20), default="tubarao", server_default="tubarao")  # ui/theme.py
    theme_mode: Mapped[str] = mapped_column(String(10), default="auto", server_default="auto")  # claro/escuro
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SettingRow(Base):
    """Configurações gerais em chave/valor (ex: código de convite)."""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))


class FolderRow(Base):
    """Pasta do usuário, para a coleção (kind="collection") ou para os decks (kind="decks")."""
    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CustomPrintRow(Base):
    """Versão personalizada de uma carta, criada por um usuário."""
    __tablename__ = "custom_prints"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    oracle_id: Mapped[str] = mapped_column(String(36), index=True)
    card_name: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(80))
    code: Mapped[str] = mapped_column(String(8), default="")
    artist: Mapped[str] = mapped_column(String(80), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    image_filename: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    base_scryfall_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CustomCardRow(Base):
    """Carta criada pelo usuário. deck_id preenchido = existe só naquele deck; vazio = está na coleção."""
    __tablename__ = "custom_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    deck_id: Mapped[int | None] = mapped_column(
        ForeignKey("decks.id", ondelete="CASCADE", name="fk_custom_cards_deck_id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    mana_cost: Mapped[str] = mapped_column(String(80), default="")
    type_line: Mapped[str] = mapped_column(String(200), default="")
    oracle_text: Mapped[str] = mapped_column(Text, default="")
    power: Mapped[str] = mapped_column(String(8), default="")
    toughness: Mapped[str] = mapped_column(String(8), default="")
    loyalty: Mapped[str] = mapped_column(String(8), default="")
    colors: Mapped[str] = mapped_column(String(5), default="")
    image_filename: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CollectionEntryRow(Base):
    """Lote de cartas na coleção. Guarda uma cópia dos dados de exibição para a lista abrir sem consultar a API."""
    __tablename__ = "collection_entries"
    __table_args__ = (
        CheckConstraint("quantity >= 1", name="quantity_positive"),
        CheckConstraint("price_paid_cents IS NULL OR price_paid_cents >= 0", name="price_not_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    oracle_id: Mapped[str] = mapped_column(String(36), index=True)
    card_name: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    foil: Mapped[bool] = mapped_column(Boolean, default=False)
    is_proxy: Mapped[bool] = mapped_column(Boolean, default=False)
    price_paid_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lang: Mapped[str] = mapped_column(String(8), default="en", server_default="en")  # idioma da impressão
    notes: Mapped[str] = mapped_column(Text, default="")
    # impressão: do Scryfall (scryfall_id) ou versão personalizada (custom_print_id)
    scryfall_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    custom_print_id: Mapped[int | None] = mapped_column(
        ForeignKey("custom_prints.id", ondelete="CASCADE"), nullable=True, index=True)
    custom_card_id: Mapped[int | None] = mapped_column(
        ForeignKey("custom_cards.id", ondelete="CASCADE", name="fk_collection_entries_custom_card_id"),
        nullable=True, index=True)
    set_code: Mapped[str] = mapped_column(String(12), default="")
    set_name: Mapped[str] = mapped_column(String(120), default="")
    collector_number: Mapped[str] = mapped_column(String(16), default="")
    rarity: Mapped[str] = mapped_column(String(16), default="")
    type_line: Mapped[str] = mapped_column(String(200), default="")
    image_small: Mapped[str | None] = mapped_column(String(300), nullable=True)
    image_normal: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # apagar a pasta não apaga os itens: eles voltam para "sem pasta"
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL", name="fk_collection_entries_folder_id"), nullable=True,
        index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    custom_print: Mapped[CustomPrintRow | None] = relationship(lazy="joined")
    custom_card: Mapped[CustomCardRow | None] = relationship(lazy="joined")


class DeckRow(Base):
    """Deck do usuário. As cartas ficam nas versões; `cards` aponta só para as da versão atual."""
    __tablename__ = "decks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    format: Mapped[str] = mapped_column(String(30), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    visibility: Mapped[str] = mapped_column(String(16), default="private")
    # capa: imagem enviada (cover_filename) ou arte de uma carta do deck (cópia da URL, sem chave estrangeira:
    # se a carta sair do deck, a capa continua até o usuário trocar)
    cover_filename: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cover_art_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cover_card_name: Mapped[str] = mapped_column(String(200), default="")
    # versão aberta por último: é a que a grade mostra e a que a montagem edita. Sem chave estrangeira para não
    # criar um ciclo decks <-> deck_versions (a versão já aponta para o deck)
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hidden_from_ranking: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    versions: Mapped[list["DeckVersionRow"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="DeckVersionRow.id")
    # só as cartas da versão atual; adicionar aqui já grava deck_id e version_id
    cards: Mapped[list["DeckCardRow"]] = relationship(
        primaryjoin="and_(DeckRow.id == foreign(DeckCardRow.deck_id), "
                    "DeckRow.current_version_id == foreign(DeckCardRow.version_id))",
        cascade="all, delete-orphan", passive_deletes=True)


class DeckVersionRow(Base):
    """Versão de um deck: cada uma tem a própria lista de cartas."""
    __tablename__ = "deck_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeckCardRow(Base):
    """Carta dentro de um deck, com cópia dos dados de exibição (como na coleção)."""
    __tablename__ = "deck_cards"
    __table_args__ = (CheckConstraint("quantity >= 1", name="deck_quantity_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("deck_versions.id", ondelete="CASCADE", name="fk_deck_cards_version_id"), index=True)
    oracle_id: Mapped[str] = mapped_column(String(36), index=True)
    card_name: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    section: Mapped[str] = mapped_column(String(16), default="main")
    scryfall_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    custom_print_id: Mapped[int | None] = mapped_column(
        ForeignKey("custom_prints.id", ondelete="CASCADE"), nullable=True, index=True)
    custom_card_id: Mapped[int | None] = mapped_column(
        ForeignKey("custom_cards.id", ondelete="CASCADE", name="fk_deck_cards_custom_card_id"), nullable=True,
        index=True)
    foil: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    is_proxy: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    price_paid_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lang: Mapped[str] = mapped_column(String(8), default="en", server_default="en")  # idioma da impressão
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    set_code: Mapped[str] = mapped_column(String(12), default="", server_default="")
    set_name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    collector_number: Mapped[str] = mapped_column(String(16), default="", server_default="")
    rarity: Mapped[str] = mapped_column(String(16), default="", server_default="")
    color_identity: Mapped[str] = mapped_column(String(5), default="")
    type_line: Mapped[str] = mapped_column(String(200), default="")
    mana_cost: Mapped[str] = mapped_column(String(80), default="")
    image_small: Mapped[str | None] = mapped_column(String(300), nullable=True)
    image_normal: Mapped[str | None] = mapped_column(String(300), nullable=True)
    image_art_crop: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    custom_print: Mapped[CustomPrintRow | None] = relationship(lazy="joined")
    custom_card: Mapped[CustomCardRow | None] = relationship(lazy="joined")


class SeasonRow(Base):
    """Temporada do ranking. A que tem ended_at vazio é a atual (no máximo uma)."""
    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    started_at: Mapped[date] = mapped_column(Date)
    ended_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WinRow(Base):
    """Uma vitória (partida ganha) de um deck. Apagar o deck apaga as vitórias dele."""
    __tablename__ = "wins"

    id: Mapped[int] = mapped_column(primary_key=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[int | None] = mapped_column(
        ForeignKey("deck_versions.id", ondelete="SET NULL"), nullable=True)
    season_id: Mapped[int | None] = mapped_column(
        ForeignKey("seasons.id", ondelete="SET NULL"), nullable=True, index=True)
    played_on: Mapped[date] = mapped_column(Date, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
