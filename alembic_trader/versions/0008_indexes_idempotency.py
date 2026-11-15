"""Dashboard query indexes (P5) and durable Idempotency-Key replay table (ADR-051).

Revision ID: 0008_indexes_idempotency
Revises: 0007_backtest_runs
Create Date: 2026-11-15
"""

from __future__ import annotations

from alembic import op

from aidss_trader.db.base import Base
from aidss_trader.db.models import (
    ApprovalRow,
    AuditLog,
    Fill,
    IdempotencyRecord,
    LedgerEntry,
    OrderIntentRow,
    OrderRow,
    ReconciliationDifference,
    ReconciliationRun,
    TradingEvent,
)

revision = "0008_indexes_idempotency"
down_revision = "0007_backtest_runs"
branch_labels = None
depends_on = None

_INDEXED_MODELS = (
    AuditLog,
    OrderIntentRow,
    OrderRow,
    Fill,
    LedgerEntry,
    ReconciliationRun,
    ReconciliationDifference,
    ApprovalRow,
    TradingEvent,
)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind, tables=[IdempotencyRecord.__table__], checkfirst=True)
    for model in _INDEXED_MODELS:
        for idx in model.__table__.indexes:
            idx.create(bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        op.execute("GRANT SELECT, INSERT, DELETE ON trading.idempotency_key TO trader_rw")


def downgrade() -> None:
    bind = op.get_bind()
    IdempotencyRecord.__table__.drop(bind, checkfirst=True)
