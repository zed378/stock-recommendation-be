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
    first, second, third, fourth, fifth, sixth, seventh, eighth, ninth = (
        _load("0001_foundation.py"),
        _load("0002_market_data.py"),
        _load("0003_trading_core.py"),
        _load("0004_operator_surface.py"),
        _load("0005_runtime.py"),
        _load("0006_paper_lifecycle.py"),
        _load("0007_backtest_runs.py"),
        _load("0008_indexes_idempotency.py"),
        _load("0009_intent_strategy_id.py"),
    )
    assert second.down_revision == first.revision and third.down_revision == second.revision
    assert fourth.down_revision == third.revision and fifth.down_revision == fourth.revision
    assert sixth.down_revision == fifth.revision
    assert seventh.down_revision == sixth.revision
    assert eighth.down_revision == seventh.revision
    assert ninth.down_revision == eighth.revision
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
            eighth.upgrade()
            ninth.upgrade()
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
            | {"idempotency_key"}
        )
        columns = {c["name"] for c in inspect(conn).get_columns("audit_log")}
        assert {"seq", "prev_hash", "hash", "before", "after"} <= columns


def test_0010_adds_the_extra_metrics_column_and_keeps_old_rows() -> None:
    import sqlalchemy as sa

    tenth = _load("0010_backtest_extra_metrics.py")
    assert tenth.down_revision == "0009_intent_strategy_id"
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE backtest_run (id INTEGER PRIMARY KEY, pair TEXT)"))
        conn.execute(sa.text("INSERT INTO backtest_run (pair) VALUES ('BTCIDR')"))
        with Operations.context(MigrationContext.configure(conn)):
            tenth.upgrade()
            tenth.upgrade()
        assert "extra_metrics" in {c["name"] for c in inspect(conn).get_columns("backtest_run")}
        assert conn.execute(sa.text("SELECT extra_metrics FROM backtest_run")).scalar() is None


def test_0009_adds_the_intent_column_to_a_table_that_lacks_it_and_keeps_old_rows() -> None:
    import sqlalchemy as sa

    ninth = _load("0009_intent_strategy_id.py")
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE order_intent (id INTEGER PRIMARY KEY, identity TEXT)"))
        conn.execute(sa.text("INSERT INTO order_intent (identity) VALUES ('v1|BTCIDR|t|BUY')"))
        with Operations.context(MigrationContext.configure(conn)):
            ninth.upgrade()
            ninth.upgrade()  # running it twice is harmless
        cols = {c["name"] for c in inspect(conn).get_columns("order_intent")}
        assert "strategy_id" in cols
        assert conn.execute(sa.text("SELECT strategy_id FROM order_intent")).scalar() is None
        assert "ix_order_intent_strategy_id" in {
            i["name"] for i in inspect(conn).get_indexes("order_intent")
        }
