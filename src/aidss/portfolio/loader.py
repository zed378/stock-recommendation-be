"""Loads a stored portfolio into the deterministic metric types.

Kept separate from the metrics so those stay pure functions over plain data -
testable without a database, and reusable by the simulation endpoint which
works on hypothetical positions that were never stored.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.collectors.market_data import load_candles
from aidss.db.models import Asset, HistoricalPrice, Portfolio, PortfolioHolding
from aidss.domain.types import Candle, Timeframe
from aidss.portfolio.metrics import Position

#: Bars loaded per holding for correlation and portfolio risk. A year of daily
#: data comfortably clears the VaR observation floor.
RISK_LOOKBACK_BARS = 400


def load_positions(session: Session, portfolio: Portfolio) -> list[Position]:
    rows = session.execute(
        select(PortfolioHolding, Asset)
        .join(Asset, Asset.id == PortfolioHolding.asset_id)
        .where(PortfolioHolding.portfolio_id == portfolio.id)
        .order_by(Asset.ticker)
    ).all()

    positions: list[Position] = []
    for holding, asset in rows:
        positions.append(
            Position(
                ticker=asset.ticker,
                sector=asset.sector,
                quantity=holding.quantity,
                average_price=holding.average_price,
                last_price=_latest_close(session, asset.id),
            )
        )
    return positions


def _latest_close(session: Session, asset_id: uuid.UUID):
    """Most recent stored close, or None when the asset has never been ingested.

    None rather than a guess: the metrics fall back to cost basis and report
    how many positions that applied to, which is visible in a way a silent
    substitution would not be.
    """
    return session.scalar(
        select(HistoricalPrice.close)
        .where(
            HistoricalPrice.asset_id == asset_id,
            HistoricalPrice.timeframe == Timeframe.D1.value,
        )
        .order_by(HistoricalPrice.timestamp.desc())
        .limit(1)
    )


def load_price_series(
    session: Session, positions: list[Position], *, lookback: int = RISK_LOOKBACK_BARS
) -> dict[str, list[Candle]]:
    """Daily candles per holding, for correlation and portfolio-level risk."""
    series: dict[str, list[Candle]] = {}
    for position in positions:
        asset = session.scalar(select(Asset).where(Asset.ticker == position.ticker))
        if asset is None:
            continue
        candles = load_candles(session, asset.id, Timeframe.D1, limit=lookback)
        if candles:
            series[position.ticker] = candles
    return series


def default_portfolio(session: Session, user_id: uuid.UUID) -> Portfolio | None:
    return session.scalar(
        select(Portfolio).where(Portfolio.user_id == user_id, Portfolio.name == "Default")
    )


def stale_cutoff(days: int = 7) -> datetime:
    """Prices older than this are worth flagging in the narrative."""
    return datetime.now(UTC) - timedelta(days=days)
