"""Operator surface: strategy modes, mode changes, approvals, events, step-up grants.

Additive only. Append-only for the running role except the columns that must change:
approval decision, event acknowledgement and delivery, grant use, strategy mode.
"""

from __future__ import annotations

from alembic import op

import aidss_trader.db.models  # noqa: F401
from aidss_trader.db.base import SCHEMA, Base

revision = "0004_operator_surface"
down_revision = "0003_trading_core"
branch_labels = None
depends_on = None

_TABLES = ("strategy", "mode_change", "approval", "trading_event", "step_up_grant")


def _tables(names):
    return [Base.metadata.tables[f"{SCHEMA}.{t}"] for t in names]


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind, tables=_tables(_TABLES))
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.mode_change TO trader_rw")
    op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.strategy TO trader_rw")
    op.execute(f"GRANT UPDATE (version, mode, since) ON {SCHEMA}.strategy TO trader_rw")
    op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.approval TO trader_rw")
    op.execute(
        f"GRANT UPDATE (state, decided_at, decided_by, reason) ON {SCHEMA}.approval TO trader_rw"
    )
    op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.trading_event TO trader_rw")
    op.execute(
        f"GRANT UPDATE (acked_at, acked_by, mobile, attempts, last_attempt_at) "
        f"ON {SCHEMA}.trading_event TO trader_rw"
    )
    op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.step_up_grant TO trader_rw")
    op.execute(f"GRANT UPDATE (used_at) ON {SCHEMA}.step_up_grant TO trader_rw")


def downgrade() -> None:
    # Development databases only (docs/03-DATA-MODEL/07).
    Base.metadata.drop_all(op.get_bind(), tables=_tables(reversed(_TABLES)))
