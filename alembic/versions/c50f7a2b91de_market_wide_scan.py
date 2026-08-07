"""OHLC on the session record, and one whole-market scan feeding alerts and picks

Revision ID: c50f7a2b91de
Revises: b83c9e1d4507
Create Date: 2026-08-06 17:31:08.442915
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'c50f7a2b91de'
down_revision: str | None = 'b83c9e1d4507'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VARIANT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    # The session record already carried close and volume. With open, high and
    # low it is a full bar - which means one request per session yields OHLCV
    # for all 963 issuers, against 963 per-ticker backfills for the same thing.
    # That is what makes a whole-market scan affordable at all.
    #
    # `open_price` is stored as reported and distrusted downstream: several
    # hundred issuers publish it as zero on an ordinary session even when they
    # traded.
    op.add_column(
        "daily_trading_summaries",
        sa.Column("open_price", sa.Numeric(precision=24, scale=8), nullable=True),
    )
    op.add_column(
        "daily_trading_summaries",
        sa.Column("high", sa.Numeric(precision=24, scale=8), nullable=True),
    )
    op.add_column(
        "daily_trading_summaries",
        sa.Column("low", sa.Numeric(precision=24, scale=8), nullable=True),
    )

    # One analysis pass over the whole exchange, read by both the alerts and
    # the screener. Previously each answered its own question its own way, so a
    # criterion could mean one thing on the monitoring screen and something
    # subtly different on the picks screen.
    op.create_table(
        "market_scan_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("close", sa.Numeric(precision=24, scale=8), nullable=True),
        # `AlertKind` values: the same vocabulary the alerts use, because they
        # are the same conditions. A screener with its own private rule list is
        # how the two drift apart.
        sa.Column("matched", JSON_VARIANT, nullable=False),
        # A tally of conditions met, not a probability of anything - named as a
        # count for that reason.
        sa.Column("matched_count", sa.Integer(), nullable=False),
        sa.Column("signals", JSON_VARIANT, nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", "session_date", name="uq_market_scan_session"),
    )
    op.create_index(op.f("ix_market_scan_results_ticker"), "market_scan_results", ["ticker"])
    op.create_index(
        op.f("ix_market_scan_results_session_date"), "market_scan_results", ["session_date"]
    )
    op.create_index(
        op.f("ix_market_scan_results_matched_count"), "market_scan_results", ["matched_count"]
    )
    # The screener's query: this session, best matches first.
    op.create_index(
        "ix_market_scan_session_count", "market_scan_results", ["session_date", "matched_count"]
    )


def downgrade() -> None:
    op.drop_index("ix_market_scan_session_count", table_name="market_scan_results")
    op.drop_index(op.f("ix_market_scan_results_matched_count"), table_name="market_scan_results")
    op.drop_index(op.f("ix_market_scan_results_session_date"), table_name="market_scan_results")
    op.drop_index(op.f("ix_market_scan_results_ticker"), table_name="market_scan_results")
    op.drop_table("market_scan_results")
    for column in ("low", "high", "open_price"):
        op.drop_column("daily_trading_summaries", column)
