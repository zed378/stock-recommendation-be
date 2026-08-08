"""Store the horizon screen alongside the criteria match.

The horizon screener ranked whatever had imported price history - twelve names
against the exchange's nine hundred - because it read `historical_prices` and
those exist only for assets somebody registered. The whole-exchange bars have
been in `daily_trading_summaries` since the market scan landed; the screener
simply was not reading them.

It cannot read them on demand: an indicator snapshot is about 44 ms and the
exchange has ~800 issuers with enough history, so a live whole-market screen is
half a minute per request and it would run again on every horizon toggle. The
scan already visits every issuer and already computes the snapshot the criteria
need, so the four horizons are evaluated there and stored. Reading the picks
becomes a query.

Revision ID: a1c8e4f70d23
Revises: c50f7a2b91de
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "a1c8e4f70d23"
down_revision: str | None = "c50f7a2b91de"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Only the *met* criterion keys per horizon, not the rendered result. The
    # weight and the description belong to the criterion definition, and a copy
    # frozen into every row would go stale the moment a description is reworded
    # - leaving old rows explaining themselves in language the code no longer
    # uses.
    op.add_column(
        "market_scan_results",
        sa.Column(
            "horizon_scores",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default="{}",
        ),
    )
    # Distance into the session's upward auto-rejection band. Computed from the
    # last two bars, which the scan has and a reader of the stored row does not.
    op.add_column(
        "market_scan_results",
        sa.Column(
            "limit_proximity",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("market_scan_results", "limit_proximity")
    op.drop_column("market_scan_results", "horizon_scores")
