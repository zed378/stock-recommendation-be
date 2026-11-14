"""Market data: pair_rule and candle. Additive only.

`candle` is append-only for the running role (INSERT, SELECT): a stored candle is
never rewritten, and a re-fetch that disagrees is recorded as a conflict rather
than overwriting history. `pair_rule` is refreshed, so it may be updated.
"""

from __future__ import annotations

from alembic import op

import aidss_trader.db.models  # noqa: F401
from aidss_trader.db.base import SCHEMA, Base

revision = "0002_market_data"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None

_TABLES = ("pair_rule", "candle")


def _tables(names):
    return [Base.metadata.tables[f"{SCHEMA}.{t}"] for t in names]


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind, tables=_tables(_TABLES))
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.candle TO trader_rw")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.pair_rule TO trader_rw")


def downgrade() -> None:
    # Development databases only (docs/03-DATA-MODEL/07).
    bind = op.get_bind()
    Base.metadata.drop_all(bind, tables=_tables(reversed(_TABLES)))
