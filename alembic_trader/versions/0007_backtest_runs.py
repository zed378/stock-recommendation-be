"""Backtest runs: persisted reproducible backtest evidence for promotion gates. Additive only."""

from __future__ import annotations

from alembic import op

import aidss_trader.db.models  # noqa: F401
from aidss_trader.db.base import SCHEMA, Base

revision = "0007_backtest_runs"
down_revision = "0006_paper_lifecycle"
branch_labels = None
depends_on = None

_TABLES = ("backtest_run",)


def _tables(names):
    return [Base.metadata.tables[f"{SCHEMA}.{t}"] for t in names]


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind, tables=_tables(_TABLES))
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.backtest_run TO trader_rw")


def downgrade() -> None:
    # Development databases only (docs/03-DATA-MODEL/07).
    Base.metadata.drop_all(op.get_bind(), tables=_tables(reversed(_TABLES)))
