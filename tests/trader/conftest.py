"""Hermetic fixtures for the Trader.

SQLite has no schemas, so the `trading` schema is translated away. That is fine
for logic; anything that depends on roles or column privileges needs PostgreSQL
and is marked `postgres`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import aidss_trader.db.models  # noqa: F401
from aidss_trader.db.base import Base


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    ).execution_options(schema_translate_map={"trading": None})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as s:
        yield s
    engine.dispose()


@pytest.fixture
def fernet() -> Fernet:
    # Generated inside the test: no key from any other source appears in the repository.
    return Fernet(Fernet.generate_key())


@pytest.fixture
def key_file(tmp_path: Path) -> Path:
    path = tmp_path / "master.key"
    path.write_bytes(Fernet.generate_key())
    return path
