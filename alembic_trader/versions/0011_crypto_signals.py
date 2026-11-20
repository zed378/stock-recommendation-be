"""Crypto signal worker: its settings, scans, scored coins and receiver acknowledgements (ADR-066).

Revision ID: 0011_crypto_signals
Revises: 0010_backtest_extra_metrics
Create Date: 2026-11-20

Additive. The Trader's API role edits the settings and reads the history. The worker runs as its own
role, `signals_rw`, created by a superuser (this migration cannot create roles), and gets only the
four tables below; its grants are applied here when the role exists and again by
`deploy/trader/grant_signals_role.sql` when it is created later.
"""

from __future__ import annotations

from alembic import op

import aidss_trader.db.models  # noqa: F401
from aidss_trader.db.base import SCHEMA, Base

revision = "0011_crypto_signals"
down_revision = "0010_backtest_extra_metrics"
branch_labels = None
depends_on = None

_TABLES = ("signal_config", "signal_scan", "signal_candidate", "signal_ack")


def _tables(names):
    return [Base.metadata.tables[f"{SCHEMA}.{t}"] for t in names]


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind, tables=_tables(_TABLES))
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.signal_config TO trader_rw")
    for table in ("signal_scan", "signal_candidate", "signal_ack"):
        op.execute(f"GRANT SELECT ON {SCHEMA}.{table} TO trader_rw")
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'signals_rw') THEN
            GRANT USAGE ON SCHEMA {SCHEMA} TO signals_rw;
            GRANT SELECT ON {SCHEMA}.signal_config TO signals_rw;
            GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.signal_scan TO signals_rw;
            GRANT SELECT, INSERT ON {SCHEMA}.signal_candidate TO signals_rw;
            GRANT SELECT, INSERT ON {SCHEMA}.signal_ack TO signals_rw;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Development databases only (docs/03-DATA-MODEL/07); production never drops a table.
    Base.metadata.drop_all(op.get_bind(), tables=_tables(reversed(_TABLES)))
