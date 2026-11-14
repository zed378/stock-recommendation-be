"""Trading core: intents, orders, fills, ledger, stops, state, kill switch, reconciliation.

Additive only. The privilege shape is the design (docs/03-DATA-MODEL/07):

* append-only for the running role: order_event, fill, ledger_entry,
  risk_check_result, breaker_event, kill_switch_event, kill_switch_step,
  reconciliation_run, reconciliation_difference (the last two need UPDATE only to
  stamp a resolution, granted on those columns alone);
* `order` may be updated on its state columns ONLY, so an order's price, size, and
  identity cannot be rewritten after it was sent.
"""

from __future__ import annotations

from alembic import op

import aidss_trader.db.models  # noqa: F401
from aidss_trader.db.base import SCHEMA, Base

revision = "0003_trading_core"
down_revision = "0002_market_data"
branch_labels = None
depends_on = None

_TABLES = (
    "order_intent",
    "risk_check_result",
    "order",
    "order_event",
    "fill",
    "ledger_entry",
    "position_stop",
    "trading_state",
    "kill_switch_event",
    "kill_switch_step",
    "breaker_event",
    "reconciliation_run",
    "reconciliation_difference",
)
_APPEND_ONLY = (
    "risk_check_result",
    "order_event",
    "fill",
    "ledger_entry",
    "breaker_event",
    "kill_switch_event",
    "kill_switch_step",
    "reconciliation_run",
)
_ORDER_UPDATABLE = (
    "exchange_order_id",
    "full_order_id",
    "executed_qty",
    "state",
    "exchange_status",
    "cancel_reason",
    "reprices",
    "updated_at",
)


def _tables(names):
    return [Base.metadata.tables[f"{SCHEMA}.{t}"] for t in names]


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind, tables=_tables(_TABLES))
    if bind.dialect.name != "postgresql":
        return
    for table in _APPEND_ONLY:
        op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.{table} TO trader_rw")
    op.execute(f'GRANT SELECT, INSERT ON {SCHEMA}."order" TO trader_rw')
    cols = ", ".join(_ORDER_UPDATABLE)
    op.execute(f'GRANT UPDATE ({cols}) ON {SCHEMA}."order" TO trader_rw')
    op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.order_intent TO trader_rw")
    op.execute(f"GRANT UPDATE (state) ON {SCHEMA}.order_intent TO trader_rw")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.position_stop TO trader_rw")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.trading_state TO trader_rw")
    op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.reconciliation_difference TO trader_rw")
    op.execute(
        f"GRANT UPDATE (resolved_at, resolution_note) ON {SCHEMA}.reconciliation_difference "
        "TO trader_rw"
    )
    op.execute(
        f"GRANT UPDATE (finished_at, differences, result) "
        f"ON {SCHEMA}.reconciliation_run TO trader_rw"
    )
    op.execute(f"GRANT UPDATE (finished_at) ON {SCHEMA}.kill_switch_event TO trader_rw")


def downgrade() -> None:
    # Development databases only (docs/03-DATA-MODEL/07).
    Base.metadata.drop_all(op.get_bind(), tables=_tables(reversed(_TABLES)))
