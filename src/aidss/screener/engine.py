"""Run the criteria over stored assets and rank what comes back.

The output is a *screen*: a list of assets meeting stated conditions, each
carrying the conditions it met. It is deliberately not called a prediction, a
forecast, or a signal anywhere in this file, because it is none of those and
the naming is the only thing standing between a screen and being read as one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.collectors.market_data import load_candles
from aidss.db.models import Asset
from aidss.domain.types import Timeframe
from aidss.indicators.engine import IndicatorEngine
from aidss.indicators.features import compute_features
from aidss.market.idx_rules import auto_reject_band
from aidss.screener.criteria import (
    CRITERIA_BY_HORIZON,
    HORIZON_BARS,
    Horizon,
    Reading,
    max_score,
)

#: Fewer bars than this and the longer criteria are reading noise. An asset is
#: reported as insufficient rather than scored on what little exists - a screen
#: that silently ranks a two-week-old listing against a five-year one is
#: comparing two different measurements.
MIN_BARS = 60

#: How much of the session's upward auto-rejection band must be consumed before
#: the asset is flagged. 0.6 is a judgement, not a threshold anyone published,
#: and it is configurable for that reason.
DEFAULT_LIMIT_PROXIMITY = Decimal("0.6")


@dataclass(frozen=True, slots=True)
class MetCriterion:
    key: str
    describes: str
    weight: float

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "describes": self.describes, "weight": self.weight}


@dataclass(frozen=True, slots=True)
class LimitProximity:
    """How much of the session's upward band the price has consumed."""

    consumed: float
    ceiling: Decimal
    limit_percent: float
    reference_price: Decimal

    def as_dict(self) -> dict[str, Any]:
        return {
            "consumed": round(self.consumed, 4),
            "ceiling": str(self.ceiling),
            "limit_percent": self.limit_percent,
            "reference_price": str(self.reference_price),
        }


@dataclass(frozen=True, slots=True)
class ScreenedAsset:
    ticker: str
    asset_id: uuid.UUID
    exchange: str
    name: str | None
    sector: str | None
    close: Decimal | None
    as_of: datetime | None
    score: float
    #: What a perfect match would score, so the number is readable.
    out_of: float
    met: list[MetCriterion]
    #: Criteria that did not fire. Shown because "why is this one *not* here"
    #: is asked as often as "why is it".
    unmet: list[str]
    limit_proximity: LimitProximity | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "asset_id": str(self.asset_id),
            "exchange": self.exchange,
            "name": self.name,
            "sector": self.sector,
            "close": str(self.close) if self.close is not None else None,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "score": round(self.score, 3),
            "out_of": round(self.out_of, 3),
            "met": [m.as_dict() for m in self.met],
            "unmet": list(self.unmet),
            "limit_proximity": (
                self.limit_proximity.as_dict() if self.limit_proximity else None
            ),
        }


@dataclass(slots=True)
class ScreenResult:
    horizon: Horizon
    generated_at: datetime
    #: How many assets were considered, so an empty result is distinguishable
    #: from an empty universe.
    considered: int
    #: Assets skipped for want of history, named rather than silently dropped.
    insufficient_history: list[str] = field(default_factory=list)
    picks: list[ScreenedAsset] = field(default_factory=list)
    caveat: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon.value,
            "generated_at": self.generated_at.isoformat(),
            "considered": self.considered,
            "insufficient_history": list(self.insufficient_history),
            "picks": [p.as_dict() for p in self.picks],
            "caveat": self.caveat,
        }


SCREEN_CAVEAT = (
    "This is a screen, not a forecast. Each entry lists the stated conditions "
    "that are currently true of it; none of them predicts a price, and the "
    "score is a count of conditions met, not a probability of rising. The "
    "horizon names the window each condition is conventionally read over, not "
    "how long anything will take to happen. Informational only, not investment "
    "advice - this platform places no orders."
)


def _reading(candles: list, engine: IndicatorEngine) -> Reading | None:
    snapshot = engine.snapshot(candles)
    if not snapshot.get("indicators"):
        return None
    return Reading(
        close=float(candles[-1].close) if candles else None,
        indicators=snapshot.get("indicators") or {},
        features=compute_features(candles),
        levels=snapshot.get("levels") or {},
        breakout=snapshot.get("breakout") or {},
        structure=snapshot.get("structure"),
    )


def _limit_proximity(candles: list) -> LimitProximity | None:
    """How much of today's upward band the latest bar has used.

    Needs two bars: the band is defined against the *previous* close, so a
    single bar has nothing to measure against.
    """
    if len(candles) < 2:
        return None
    previous_close = Decimal(str(candles[-2].close))
    band = auto_reject_band(previous_close)
    if band is None:
        return None

    consumed = band.proximity(Decimal(str(candles[-1].close)))
    if consumed is None:
        return None
    return LimitProximity(
        consumed=float(consumed),
        ceiling=band.ceiling.quantize(Decimal("0.01")),
        limit_percent=float(band.limit_fraction * 100),
        reference_price=previous_close,
    )


def screen(
    session: Session,
    horizon: Horizon,
    *,
    timeframe: Timeframe = Timeframe.D1,
    limit: int = 20,
    asset_ids: list[uuid.UUID] | None = None,
    min_score: float = 0.0,
    near_limit_only: bool = False,
    limit_proximity_threshold: Decimal = DEFAULT_LIMIT_PROXIMITY,
    now: datetime | None = None,
) -> ScreenResult:
    """Rank stored assets by how many of the horizon's conditions they meet.

    Runs over whatever price history is already stored. It fetches nothing:
    a screen that collected data would take minutes and would spend provider
    quota on assets nobody asked about.
    """
    now = now or datetime.now(UTC)
    criteria = CRITERIA_BY_HORIZON[horizon]
    ceiling = max_score(horizon)
    engine = IndicatorEngine()

    stmt = select(Asset).where(Asset.is_active.is_(True))
    if asset_ids is not None:
        if not asset_ids:
            return ScreenResult(
                horizon=horizon, generated_at=now, considered=0, caveat=SCREEN_CAVEAT
            )
        stmt = stmt.where(Asset.id.in_(asset_ids))

    assets = list(session.scalars(stmt.order_by(Asset.ticker)).all())
    result = ScreenResult(
        horizon=horizon, generated_at=now, considered=len(assets), caveat=SCREEN_CAVEAT
    )

    for asset in assets:
        candles = load_candles(session, asset.id, timeframe)
        if len(candles) < MIN_BARS:
            result.insufficient_history.append(asset.ticker)
            continue

        reading = _reading(candles, engine)
        if reading is None:
            result.insufficient_history.append(asset.ticker)
            continue

        met: list[MetCriterion] = []
        unmet: list[str] = []
        for criterion in criteria:
            try:
                fired = bool(criterion.test(reading))
            except (TypeError, ValueError):
                # A criterion that cannot be evaluated is not met. Letting it
                # raise would drop the whole screen because one asset lacked
                # one indicator.
                fired = False
            if fired:
                met.append(
                    MetCriterion(
                        key=criterion.key,
                        describes=criterion.describes,
                        weight=criterion.weight,
                    )
                )
            else:
                unmet.append(criterion.key)

        proximity = _limit_proximity(candles)
        if near_limit_only and (
            proximity is None or Decimal(str(proximity.consumed)) < limit_proximity_threshold
        ):
            continue

        score = sum(m.weight for m in met)
        if score < min_score:
            continue

        result.picks.append(
            ScreenedAsset(
                ticker=asset.ticker,
                asset_id=asset.id,
                exchange=asset.exchange,
                name=asset.name,
                sector=asset.sector,
                close=candles[-1].close,
                as_of=candles[-1].timestamp,
                score=score,
                out_of=ceiling,
                met=met,
                unmet=unmet,
                limit_proximity=proximity,
            )
        )

    # Ticker breaks ties, so the same data always produces the same order. A
    # ranking that reshuffles between identical runs cannot be reasoned about.
    result.picks.sort(key=lambda p: (-p.score, p.ticker))
    result.picks = result.picks[:limit]
    return result


def bars_for(horizon: Horizon) -> int:
    """Trading bars the horizon's window covers, for display."""
    return HORIZON_BARS[horizon]
