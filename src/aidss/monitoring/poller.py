"""Ask the provider what followed assets are trading at, and evaluate the rules.

"Near real time" is the honest name for this. The free sources this platform
runs on are delayed - Yahoo's public endpoint by roughly fifteen minutes - and
polling faster does not make the data newer, it just asks the same stale number
more often. Every snapshot records whether the provider claimed to be live, so
the interface can say so rather than implying a freshness nobody has.

The unit of work is one asset for all the users following it: two people
watching BBCA should cost one provider call, not two, and the alert
deduplication is per user so they are each still told once.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.collectors.market_data import load_candles
from aidss.db.models import (
    Alert,
    AnalysisResult,
    Asset,
    QuoteSnapshot,
    Recommendation,
    Watchlist,
    WatchlistItem,
)
from aidss.domain.types import Timeframe
from aidss.indicators.engine import IndicatorEngine
from aidss.indicators.features import compute_features
from aidss.monitoring.alerts import AlertCandidate, evaluate, record
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.interfaces import MarketDataProvider

logger = logging.getLogger("aidss.monitoring")

#: How far back a stored recommendation stays relevant for alerting. Beyond
#: this, its levels describe a market that has moved on, and alerting against
#: them would be measuring today against a stale opinion.
RECOMMENDATION_MAX_AGE = timedelta(days=30)


@dataclass(slots=True)
class PollReport:
    polled: int = 0
    quoted: int = 0
    alerts_raised: int = 0
    unavailable: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    delayed_source: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "polled": self.polled,
            "quoted": self.quoted,
            "alerts_raised": self.alerts_raised,
            "unavailable": list(self.unavailable),
            "skipped": list(self.skipped),
            "delayed_source": self.delayed_source,
        }


def watched_assets(session: Session) -> dict[uuid.UUID, list[uuid.UUID]]:
    """asset id -> the users following it, across every category.

    Keyed by asset so one provider call serves everyone watching it.
    """
    rows = session.execute(
        select(WatchlistItem.asset_id, Watchlist.user_id)
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .distinct()
    ).all()

    followers: dict[uuid.UUID, list[uuid.UUID]] = {}
    for asset_id, user_id in rows:
        followers.setdefault(asset_id, []).append(user_id)
    return followers


def _latest_recommendation(session: Session, asset_id: uuid.UUID, now: datetime):
    """The most recent stored recommendation for an asset, if it is still fresh."""
    row = session.execute(
        select(Recommendation, AnalysisResult.created_at)
        .join(AnalysisResult, AnalysisResult.id == Recommendation.analysis_result_id)
        .where(AnalysisResult.asset_id == asset_id)
        .order_by(Recommendation.created_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    recommendation, created_at = row
    if created_at is not None and now - created_at > RECOMMENDATION_MAX_AGE:
        return None
    return recommendation


def _previous_stance(session: Session, asset_id: uuid.UUID) -> str | None:
    """The stance before the current one, for detecting a change.

    Two rows are read rather than one: a stance is only "changed" relative to
    something, and comparing against nothing would fire on the first analysis
    of every asset.
    """
    rows = session.execute(
        select(Recommendation.label)
        .join(AnalysisResult, AnalysisResult.id == Recommendation.analysis_result_id)
        .where(AnalysisResult.asset_id == asset_id)
        .order_by(Recommendation.created_at.desc())
        .limit(2)
    ).all()
    return rows[1][0].value if len(rows) == 2 else None


def _last_observed_price(session: Session, asset_id: uuid.UUID) -> Decimal | None:
    """The previous poll's price, so a crossing can be detected rather than a state.

    Without it, "price is above resistance" is true on every poll after the
    first and the alert becomes a running commentary.
    """
    row = session.scalar(
        select(QuoteSnapshot)
        .where(QuoteSnapshot.asset_id == asset_id)
        .order_by(QuoteSnapshot.observed_at.desc())
        .limit(1)
    )
    return row.price if row else None


def _levels_and_volatility(
    session: Session, asset_id: uuid.UUID
) -> tuple[list[Decimal], list[Decimal], Decimal | None]:
    candles = load_candles(session, asset_id, Timeframe.D1)
    if len(candles) < 30:
        return [], [], None

    snapshot = IndicatorEngine().snapshot(candles)
    levels = snapshot.get("levels") or {}
    support = [Decimal(str(v)) for v in levels.get("support", []) if v is not None]
    resistance = [Decimal(str(v)) for v in levels.get("resistance", []) if v is not None]

    features = compute_features(candles)
    annual = features.get("volatility_20b")
    # The stored figure is annualised; a daily band is what a single session's
    # move should be judged against. 252 trading days, square root of time.
    daily = (
        Decimal(str(annual)) / Decimal("15.87")
        if isinstance(annual, (int, float)) and annual
        else None
    )
    return support, resistance, daily


def poll_watched_assets(
    session: Session,
    provider: MarketDataProvider,
    *,
    asset_ids: list[uuid.UUID] | None = None,
    now: datetime | None = None,
) -> PollReport:
    """One pass over every followed asset."""
    now = now or datetime.now(UTC)
    report = PollReport(delayed_source=not provider.supports_realtime())

    followers = watched_assets(session)
    if asset_ids is not None:
        followers = {k: v for k, v in followers.items() if k in asset_ids}

    for asset_id, user_ids in followers.items():
        asset = session.get(Asset, asset_id)
        if asset is None or not asset.is_active:
            continue

        report.polled += 1
        try:
            quote = provider.get_quote(asset.ticker)
        except ProviderUnavailableError as exc:
            # One unreachable ticker must not end the pass: the others are
            # still worth observing, and a delisted symbol would otherwise
            # silently stop monitoring for everything after it.
            report.unavailable.append(f"{asset.ticker}: {exc}")
            logger.warning("quote unavailable", extra={"ticker": asset.ticker})
            continue

        previous_price = _last_observed_price(session, asset_id)

        session.add(
            QuoteSnapshot(
                asset_id=asset_id,
                price=quote.price,
                previous_close=quote.previous_close,
                quoted_at=quote.timestamp,
                source=provider.name,
                is_delayed=not provider.supports_realtime(),
            )
        )
        session.flush()
        report.quoted += 1

        support, resistance, daily_volatility = _levels_and_volatility(session, asset_id)
        recommendation = _latest_recommendation(session, asset_id, now)

        candidates: list[AlertCandidate] = evaluate(
            asset_id=asset_id,
            ticker=asset.ticker,
            price=quote.price,
            previous_close=quote.previous_close,
            support_levels=support,
            resistance_levels=resistance,
            suggested_stop=recommendation.suggested_stop if recommendation else None,
            previous_price=previous_price,
            daily_volatility=daily_volatility,
            stance=recommendation.label.value if recommendation else None,
            previous_stance=_previous_stance(session, asset_id),
            now=now,
        )
        if not candidates:
            continue

        for user_id in user_ids:
            report.alerts_raised += len(record(session, user_id, asset_id, candidates))

    session.flush()
    return report


def recent_alerts(
    session: Session,
    user_id: uuid.UUID,
    *,
    limit: int = 50,
    unacknowledged_only: bool = False,
) -> list[Alert]:
    stmt = select(Alert).where(Alert.user_id == user_id)
    if unacknowledged_only:
        stmt = stmt.where(Alert.acknowledged_at.is_(None))
    return list(
        session.scalars(stmt.order_by(Alert.triggered_at.desc()).limit(limit)).all()
    )


def latest_quotes(
    session: Session, asset_ids: list[uuid.UUID]
) -> dict[uuid.UUID, QuoteSnapshot]:
    """The most recent snapshot per asset, for the monitoring screen."""
    if not asset_ids:
        return {}
    rows = session.scalars(
        select(QuoteSnapshot)
        .where(QuoteSnapshot.asset_id.in_(asset_ids))
        .order_by(QuoteSnapshot.observed_at.desc())
    ).all()

    latest: dict[uuid.UUID, QuoteSnapshot] = {}
    for row in rows:
        latest.setdefault(row.asset_id, row)
    return latest
