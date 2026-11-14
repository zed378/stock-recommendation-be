"""The foundation migration builds exactly the tables the models declare (drift check, SQLite path).

The grants are PostgreSQL-only and are exercised by test_privileges_postgres.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

from aidss_trader.db.base import Base

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "alembic_trader" / "versions" / "0001_foundation.py"


def _load():
    spec = importlib.util.spec_from_file_location("m0001", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_creates_exactly_the_foundation_tables() -> None:
    module = _load()
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool).execution_options(
        schema_translate_map={"trading": None}
    )
    with engine.connect() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        built = set(inspect(conn).get_table_names())
        declared = {t.name for t in Base.metadata.tables.values()}
        assert built == declared == set(module._FOUNDATION_TABLES)
        columns = {c["name"] for c in inspect(conn).get_columns("audit_log")}
        assert {"seq", "prev_hash", "hash", "before", "after"} <= columns


def test_every_declared_table_is_covered_by_the_migration() -> None:
    """A table added to the models without a migration would otherwise ship only in tests."""
    module = _load()
    assert {t.name for t in Base.metadata.tables.values()} == set(module._FOUNDATION_TABLES)
