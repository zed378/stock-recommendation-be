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


def _load(name: str = "0001_foundation.py"):
    spec = importlib.util.spec_from_file_location(name, ROOT / "alembic_trader" / "versions" / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrades_create_exactly_the_declared_tables() -> None:
    first, second, third, fourth, fifth, sixth, seventh = (
        _load("0001_foundation.py"),
        _load("0002_market_data.py"),
        _load("0003_trading_core.py"),
        _load("0004_operator_surface.py"),
        _load("0005_runtime.py"),
        _load("0006_paper_lifecycle.py"),
        _load("0007_backtest_runs.py"),
    )
    assert second.down_revision == first.revision and third.down_revision == second.revision
    assert fourth.down_revision == third.revision and fifth.down_revision == fourth.revision
    assert sixth.down_revision == fifth.revision
    assert seventh.down_revision == sixth.revision
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool).execution_options(
        schema_translate_map={"trading": None}
    )
    with engine.connect() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            first.upgrade()
            second.upgrade()
            third.upgrade()
            fourth.upgrade()
            fifth.upgrade()
            sixth.upgrade()
            seventh.upgrade()
        built = set(inspect(conn).get_table_names())
        declared = {t.name for t in Base.metadata.tables.values()}
        assert (
            built
            == declared
            == set(first._FOUNDATION_TABLES)
            | set(second._TABLES)
            | set(third._TABLES)
            | set(fourth._TABLES)
            | set(fifth._TABLES)
            | set(sixth._TABLES)
            | set(seventh._TABLES)
        )
        columns = {c["name"] for c in inspect(conn).get_columns("audit_log")}
        assert {"seq", "prev_hash", "hash", "before", "after"} <= columns
