"""4-hour breakout signals and their simulated lifecycle (ADR-067). Additive.

Revision ID: 0012_signal_trade
Revises: 0011_crypto_signals
Create Date: 2026-11-20
"""

from __future__ import annotations

from alembic import op

import aidss_trader.db.models  # noqa: F401
from aidss_trader.db.base import SCHEMA, Base

revision = "0012_signal_trade"
down_revision = "0011_crypto_signals"
branch_labels = None
depends_on = None

_TABLES = ("signal_trade",)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind, tables=[Base.metadata.tables[f"{SCHEMA}.{t}"] for t in _TABLES])
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"GRANT SELECT ON {SCHEMA}.signal_trade TO trader_rw")
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'signals_rw') THEN
            GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.signal_trade TO signals_rw;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Development databases only (docs/03-DATA-MODEL/07); production never drops a table.
    Base.metadata.drop_all(
        op.get_bind(), tables=[Base.metadata.tables[f"{SCHEMA}.{t}"] for t in _TABLES]
    )
