"""ORM foundation: declarative Base, portable column types, session factory.

Production runs on PostgreSQL (Section 14); tests run on in-memory SQLite. The
types below are what let one set of model definitions serve both.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, TypeDecorator, create_engine, types
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from aidss.config import Settings, get_settings

#: JSON that becomes JSONB on PostgreSQL, which is what Section 8.2 specifies.
JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class GUID(TypeDecorator):
    """Native UUID on PostgreSQL, a 36-character string elsewhere."""

    impl = types.CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGUUID(as_uuid=True))
        return dialect.type_descriptor(types.CHAR(36))

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return value if dialect.name == "postgresql" else str(value)

    def process_result_value(self, value: Any, dialect: Any) -> uuid.UUID | None:
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class UTCDateTime(TypeDecorator):
    """A DateTime that is always timezone-aware UTC in both directions.

    Without this, SQLite hands back naive datetimes and time comparisons in
    the collector stop matching PostgreSQL's behaviour.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"Expected datetime, got {type(value).__name__}")
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are rejected; pass timezone-aware UTC")
        return value.astimezone(UTC)

    def process_result_value(self, value: Any, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Embedding(TypeDecorator):
    """A pgvector column on PostgreSQL, a JSON array elsewhere.

    Used by ``knowledge_chunks`` and ``news_embeddings`` (Phase 7).

    The width comes from settings rather than a literal, because it is a
    property of the embedding model in use - 1536 for text-embedding-3-small,
    3072 for -3-large, 768 for nomic-embed-text. Hard-coding one of them would
    mean a schema change to switch models, which contradicts the
    provider-agnostic principle the rest of the platform is built on (FR-07).

    Note the asymmetry this papers over: PostgreSQL enforces the width, SQLite
    does not. A test suite running on SQLite will therefore accept vectors that
    production rejects, which is precisely the bug this docstring exists to
    stop the next person from re-introducing.
    """

    impl = JSON
    cache_ok = True

    def __init__(self, dimensions: int | None = None) -> None:
        super().__init__()
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        # Resolved lazily: the column is defined at import time, before
        # settings are necessarily loaded.
        return self._dimensions or get_settings().embedding_dimensions

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dimensions))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        vector = list(value)
        # Checked on every dialect, so a SQLite test fails for the same reason
        # production would rather than silently passing.
        if len(vector) != self.dimensions:
            raise ValueError(
                f"embedding has {len(vector)} dimensions but the column expects "
                f"{self.dimensions}. The embedding model and "
                "AIDSS_EMBEDDING_DIMENSIONS must agree; vectors of different "
                "widths cannot be compared."
            )
        return vector


def enum_column(enum_cls: type[Any], *, length: int = 20) -> Enum:
    """A string enum column that stores the enum's *value*, not its name.

    SQLAlchemy defaults to persisting `RecommendationLabel.WATCHLIST` as
    ``"WATCHLIST"``, while the API, the JSON snapshots, and every StrEnum
    comparison in the code use ``"watchlist"``. That leaves the same fact
    written two ways inside one database - and a dashboard filtering
    ``WHERE label = 'buy'`` silently returns nothing.

    ``values_callable`` makes the stored form the canonical one.
    """
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda e: [member.value for member in e],
    )


class Base(DeclarativeBase):
    type_annotation_map = {
        dict[str, Any]: JSONVariant,
        list[Any]: JSONVariant,
        datetime: UTCDateTime,
        uuid.UUID: GUID,
    }


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


def create_db_engine(settings: Settings | None = None, **kwargs: Any) -> Engine:
    settings = settings or get_settings()
    connect_args: dict[str, Any] = {}
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        echo=settings.debug,
        connect_args=connect_args,
        **kwargs,
    )


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_db_engine()
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _SessionLocal


def configure_engine(engine: Engine) -> None:
    """Replace the global engine - used by tests and CLI scripts."""
    global _engine, _SessionLocal
    _engine = engine
    _SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
