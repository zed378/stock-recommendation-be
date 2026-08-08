"""Run the criteria over stored assets and rank what comes back.

The output is a *screen*: a list of assets meeting stated conditions, each
carrying the conditions it met. It is deliberately not called a prediction, a
forecast, or a signal anywhere in this file, because it is none of those and
the naming is the only thing standing between a screen and being read as one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
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
    #: Null for issuers the platform has no `Asset` row for, which is most of
    #: the exchange. The screen covers every issuer with session records;
    #: only a handful have been registered for analysis.
    asset_id: uuid.UUID | None
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
    #: Criteria whose inputs did not exist, kept apart from the ones that were
    #: checked and found false. Reported so a low score reads as "met three of
    #: the four things measurable here" rather than as a verdict.
    unevaluable: list[str] = field(default_factory=list)
    limit_proximity: LimitProximity | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "asset_id": str(self.asset_id) if self.asset_id else None,
            "exchange": self.exchange,
            "name": self.name,
            "sector": self.sector,
            "close": str(self.close) if self.close is not None else None,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "score": round(self.score, 3),
            "out_of": round(self.out_of, 3),
            "met": [m.as_dict() for m in self.met],
            "unmet": list(self.unmet),
            "unevaluable": list(self.unevaluable),
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


class _WatchedReading(Reading):
    """A `Reading` that remembers when a lookup found nothing.

    Needed to tell "this condition was checked and is false" apart from "this
    condition could not be checked". Both make `test` return False, and
    conflating them produces a specific, quiet lie: the exchange table holds
    about sixty sessions per issuer, so `sma(period=200)` is null for every one
    of them, and the 30-day horizon then reports a top score of 2.0 out of a
    ceiling of 3.9. A reader sees a mediocre stock. What actually happened is
    that an issuer met every condition anybody could evaluate, and 1.9 of the
    advertised ceiling was never reachable.

    Only value lookups are watched. A missing support level means no level is
    nearby, which is a finding about the chart rather than a gap in the data.
    """

    __slots__ = ("missed",)

    def __init__(self, reading: Reading) -> None:
        super().__init__(
            close=reading.close,
            indicators=reading.indicators,
            features=reading.features,
            levels=reading.levels,
            breakout=reading.breakout,
            structure=reading.structure,
        )
        self.missed = False

    def indicator(self, key: str, field: str = "value") -> float | None:
        found = super().indicator(key, field)
        if found is None:
            self.missed = True
        return found

    def feature(self, key: str) -> float | None:
        found = super().feature(key)
        if found is None:
            self.missed = True
        return found


def horizon_scores(candles: list) -> dict[str, dict[str, list[str]]]:
    """Which criteria fire for each horizon, evaluated once over shared bars.

    Called by the market scan rather than by the endpoint. The indicator
    snapshot is the expensive part - about 44 ms - and the four horizons read
    the same one, so evaluating all of them together costs barely more than
    evaluating one. Doing it per request instead meant the picks screen could
    only afford the dozen assets with imported price history, which is how a
    whole-exchange screener ended up ranking a watchlist.

    Three outcomes per criterion, not two: met, checked-and-false, and could
    not be checked. The third is what short history produces, and folding it
    into the second is how a screen reports a ceiling it cannot reach.
    """
    plain = _reading(candles, IndicatorEngine())
    if plain is None:
        return {}
    reading = _WatchedReading(plain)

    out: dict[str, dict[str, list[str]]] = {}
    for horizon, criteria in CRITERIA_BY_HORIZON.items():
        met: list[str] = []
        unevaluable: list[str] = []
        for criterion in criteria:
            reading.missed = False
            try:
                fired = bool(criterion.test(reading))
            except (TypeError, ValueError):
                # Raising here would lose the whole issuer because one
                # indicator was short.
                fired = False
                reading.missed = True
            if fired:
                met.append(criterion.key)
            elif reading.missed:
                unevaluable.append(criterion.key)
        out[horizon.value] = {"met": met, "unevaluable": unevaluable}
    return out


def limit_proximity(candles: list) -> dict[str, Any] | None:
    """The auto-rejection band reading, as JSON for storage."""
    found = _limit_proximity(candles)
    return found.as_dict() if found else None


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


def screen_stored(
    session: Session,
    horizon: Horizon,
    *,
    limit: int = 20,
    tickers: list[str] | None = None,
    min_score: float = 0.0,
    near_limit_only: bool = False,
    limit_proximity_threshold: Decimal = DEFAULT_LIMIT_PROXIMITY,
    on_date: date | None = None,
    now: datetime | None = None,
) -> ScreenResult:
    """Rank the whole exchange from the stored scan.

    The universe is every issuer the exchange published a session record for
    with enough history - about eight hundred - not the dozen with imported
    price bars. That is the difference between a screener and a watchlist
    viewer: a list that can only show what somebody already follows cannot
    surface anything they have not thought of, which is the one thing a
    screener is for.

    `tickers` narrows to a watchlist. It is a filter over the same pass, not a
    different query, so a criterion means the same thing on both settings.
    """
    from aidss.db.models import Issuer, MarketScanResult
    from aidss.monitoring.scan import latest_scan_date

    now = now or datetime.now(UTC)
    criteria = CRITERIA_BY_HORIZON[horizon]
    by_key = {criterion.key: criterion for criterion in criteria}

    on_date = on_date or latest_scan_date(session)
    if on_date is None:
        # No scan has run. Reported as an empty universe rather than an empty
        # result: "nothing meets your conditions" and "nothing has been looked
        # at yet" are different answers and only one of them is about the market.
        return ScreenResult(
            horizon=horizon, generated_at=now, considered=0, caveat=SCREEN_CAVEAT
        )

    stmt = select(MarketScanResult).where(MarketScanResult.session_date == on_date)
    if tickers is not None:
        # An explicit empty list means "I follow nothing", which is a real
        # answer and not the same as "no filter".
        stmt = stmt.where(MarketScanResult.ticker.in_([t.upper() for t in tickers] or [""]))
    rows = list(session.scalars(stmt).all())

    # One query for the names rather than one per row. At eight hundred issuers
    # the per-row version is the whole cost of the endpoint.
    directory = {
        issuer.ticker: issuer
        for issuer in session.scalars(
            select(Issuer).where(Issuer.ticker.in_([row.ticker for row in rows] or [""]))
        ).all()
    }
    registered = {
        asset.ticker: asset
        for asset in session.scalars(
            select(Asset).where(Asset.ticker.in_([row.ticker for row in rows] or [""]))
        ).all()
    }

    result = ScreenResult(
        horizon=horizon, generated_at=now, considered=len(rows), caveat=SCREEN_CAVEAT
    )

    for row in rows:
        stored = (row.horizon_scores or {}).get(horizon.value)
        if isinstance(stored, list):
            stored = {"met": stored, "unevaluable": []}
        if not isinstance(stored, dict):
            # Scanned before the horizons were stored, or the indicators were
            # too short to evaluate. Named rather than silently dropped.
            result.insufficient_history.append(row.ticker)
            continue

        met_keys = stored.get("met", [])
        blind = set(stored.get("unevaluable", []))
        met = [by_key[key] for key in met_keys if key in by_key]
        score = sum(criterion.weight for criterion in met)
        if score < min_score:
            continue

        # The ceiling excludes what could not be checked. Two hundred bars of
        # history do not exist for most of this exchange, so reporting the full
        # ceiling would mark an issuer that met everything measurable as having
        # met half of it.
        reachable = sum(c.weight for c in criteria if c.key not in blind)

        proximity = _stored_proximity(row.limit_proximity)
        if near_limit_only and (
            proximity is None or Decimal(str(proximity.consumed)) < limit_proximity_threshold
        ):
            continue

        issuer = directory.get(row.ticker)
        asset = registered.get(row.ticker)
        result.picks.append(
            ScreenedAsset(
                ticker=row.ticker,
                # Null for the ~800 issuers nobody registered. The alternative
                # was inventing an id, which reads as "this is analysable" on a
                # screen where most entries are not yet.
                asset_id=asset.id if asset else None,
                exchange=asset.exchange if asset else "IDX",
                name=(asset.name if asset else None) or (issuer.name if issuer else None),
                sector=(asset.sector if asset else None) or (issuer.sector if issuer else None),
                close=row.close,
                as_of=row.scanned_at,
                score=score,
                out_of=reachable,
                met=[
                    MetCriterion(
                        key=criterion.key,
                        describes=criterion.describes,
                        weight=criterion.weight,
                    )
                    for criterion in met
                ],
                unmet=[
                    c.key
                    for c in criteria
                    if c.key not in set(met_keys) and c.key not in blind
                ],
                unevaluable=sorted(blind),
                limit_proximity=proximity,
            )
        )

    result.picks.sort(key=lambda p: (-p.score, p.ticker))
    result.picks = result.picks[:limit]
    return result


def _stored_proximity(payload: dict[str, Any] | None) -> LimitProximity | None:
    if not payload:
        return None
    try:
        return LimitProximity(
            consumed=float(payload["consumed"]),
            ceiling=Decimal(str(payload["ceiling"])),
            limit_percent=float(payload["limit_percent"]),
            reference_price=Decimal(str(payload["reference_price"])),
        )
    except (KeyError, TypeError, ValueError):
        # Written by an older scan in a shape this no longer understands.
        # Dropping the band is better than dropping the pick.
        return None


def bars_for(horizon: Horizon) -> int:
    """Trading bars the horizon's window covers, for display."""
    return HORIZON_BARS[horizon]
