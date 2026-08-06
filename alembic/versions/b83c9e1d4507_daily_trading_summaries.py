"""the exchange's own session record, including foreign participation

Revision ID: b83c9e1d4507
Revises: a4e18d6c37f2
Create Date: 2026-08-06 16:05:41.772913
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b83c9e1d4507'
down_revision: str | None = 'a4e18d6c37f2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Separate from `historical_prices`, which holds OHLCV normalised across
    # several providers. This is IDX's end-of-session record and carries what
    # no price feed does - foreign buy and sell value, and the transaction
    # count - which is the only reason it exists.
    op.create_table(
        "daily_trading_summaries",
        sa.Column("id", sa.Uuid(), nullable=False),
        # Keyed by ticker rather than by asset: the exchange publishes all 963
        # issuers whether or not this platform tracks them, and making the row
        # wait for an `Asset` would start the history exactly when somebody
        # adds the ticker - which is when it is least useful.
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("close", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("previous_close", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("volume", sa.Numeric(precision=28, scale=2), nullable=True),
        sa.Column("value", sa.Numeric(precision=28, scale=2), nullable=True),
        # A daily count, not the per-minute frequency an unusual-activity
        # screen would want. The exchange does not publish that for free.
        sa.Column("frequency", sa.Integer(), nullable=True),
        # Stored as the two sides rather than their difference: a small net on
        # huge two-way flow and a small net on almost no flow are different
        # sessions, and the difference alone cannot tell them apart.
        sa.Column("foreign_buy", sa.Numeric(precision=28, scale=2), nullable=True),
        sa.Column("foreign_sell", sa.Numeric(precision=28, scale=2), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # Idempotent per session, because the exchange revises the same day's
        # figures after the close.
        sa.UniqueConstraint("ticker", "session_date", name="uq_trading_summary_session"),
    )
    op.create_index(
        op.f("ix_daily_trading_summaries_ticker"), "daily_trading_summaries", ["ticker"]
    )
    op.create_index(
        op.f("ix_daily_trading_summaries_session_date"),
        "daily_trading_summaries",
        ["session_date"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_daily_trading_summaries_session_date"), table_name="daily_trading_summaries"
    )
    op.drop_index(
        op.f("ix_daily_trading_summaries_ticker"), table_name="daily_trading_summaries"
    )
    op.drop_table("daily_trading_summaries")
