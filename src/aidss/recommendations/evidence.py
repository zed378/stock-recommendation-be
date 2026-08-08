"""The bars a recommendation rests on, marked up so a chart can show them.

Explainability has been text-only: a stance, a paragraph, and a list of
supporting and contradicting indicators. That is checkable in principle and
hard in practice - "price is above its 50-bar average" asks the reader to hold
two numbers in their head and trust that the platform compared them correctly.

Drawn instead, the same claim is one glance. So this returns the price series
together with every level the recommendation named and every point where a
supporting condition can be located in time, in one payload, so the chart and
the prose cannot disagree about what was said.

**The marks are levels and observations, never projections.** No trend line
extends past the last bar, and a target price is drawn as a horizontal level
with its stated method attached, not as a path the price is expected to take. A
line sloping into empty space to the right of the last bar is a forecast
regardless of what the legend calls it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.collectors.market_data import load_candles
from aidss.db.models import AnalysisResult, Asset, Recommendation
from aidss.domain.types import Timeframe


@dataclass(frozen=True, slots=True)
class MarkedLevel:
    """A horizontal price line the recommendation named."""

    key: str
    price: Decimal
    #: Why this number exists. A level with no stated basis is treated by the
    #: reader as more certain than it is, which Section 23 makes a rule for the PDF
    #: export and which applies at least as strongly to a chart.
    basis: str

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "price": str(self.price), "basis": self.basis}


@dataclass(slots=True)
class ChartEvidence:
    ticker: str
    timeframe: str
    generated_at: datetime | None
    bars: list[dict[str, Any]] = field(default_factory=list)
    levels: list[MarkedLevel] = field(default_factory=list)
    #: Conditions the analysis cited, each with the bar it is anchored to where
    #: one can be identified. Conditions with no locatable bar are still
    #: listed - dropping them would make the chart look like the whole of the
    #: evidence when it is a subset.
    marks: list[dict[str, Any]] = field(default_factory=list)
    caveat: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "timeframe": self.timeframe,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "bars": self.bars,
            "levels": [level.as_dict() for level in self.levels],
            "marks": list(self.marks),
            "caveat": self.caveat,
        }


EVIDENCE_CAVEAT = (
    "Every line here is a level computed from past prices or a condition "
    "observed in them. Nothing on this chart is projected forward: a target is "
    "drawn as a level with its stated basis, not as a path, and no line extends "
    "beyond the last completed bar."
)

_LEVEL_BASIS = {
    "support_level": "nearest confirmed swing low below the close",
    "resistance_level": "nearest confirmed swing high above the close",
    "target_price": "from the recommendation, with the method it stated",
    "suggested_stop": "suggested, not instructed - see the analysis",
}


def _bars(session: Session, asset: Asset, timeframe: Timeframe, limit: int) -> list[dict]:
    candles = load_candles(session, asset.id, timeframe, limit=limit)
    return [
        {
            "t": candle.timestamp.isoformat(),
            "o": str(candle.open),
            "h": str(candle.high),
            "l": str(candle.low),
            "c": str(candle.close),
            "v": str(candle.volume),
        }
        for candle in candles
    ]


def for_recommendation(
    session: Session,
    ticker: str,
    *,
    timeframe: Timeframe = Timeframe.D1,
    bars: int = 180,
) -> ChartEvidence | None:
    """Assemble the chart payload for an issuer's latest stored recommendation.

    Returns None when there is no stored recommendation. A chart with no marks
    on it would render as an ordinary price chart while sitting under a heading
    that promises an explanation, which is worse than an empty state saying an
    analysis has not been run.
    """
    asset = session.scalar(select(Asset).where(Asset.ticker == ticker.upper()))
    if asset is None:
        return None

    row = session.execute(
        select(Recommendation, AnalysisResult)
        .join(AnalysisResult, AnalysisResult.id == Recommendation.analysis_result_id)
        .where(AnalysisResult.asset_id == asset.id)
        .order_by(Recommendation.created_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    recommendation, result = row

    evidence = ChartEvidence(
        ticker=asset.ticker,
        timeframe=timeframe.value,
        generated_at=result.generated_at,
        bars=_bars(session, asset, timeframe, bars),
        caveat=EVIDENCE_CAVEAT,
    )

    for key, basis in _LEVEL_BASIS.items():
        price = getattr(recommendation, key, None)
        if price is not None:
            evidence.levels.append(MarkedLevel(key=key, price=price, basis=basis))

    # The factors as the analysis wrote them. Rendered beside the chart rather
    # than as floating labels: they are sentences, and a sentence pinned to a
    # candle implies the condition happened on that one bar, which is true of
    # a crossing and false of "the trend has strength".
    for factor in recommendation.supporting_factors or []:
        evidence.marks.append({"text": str(factor), "side": "supporting"})
    for factor in recommendation.conflicting_factors or []:
        # Included, and that is the point. A chart that draws only what agrees
        # with the stance is an argument, not an explanation - the same reason
        # Section 14.4 makes contradicting indicators a required field.
        evidence.marks.append({"text": str(factor), "side": "conflicting"})

    return evidence


def owner_of(session: Session, result_id: uuid.UUID) -> uuid.UUID | None:
    """Which account requested an analysis, if any did."""
    from aidss.db.models import AIConversation

    result = session.get(AnalysisResult, result_id)
    if result is None or result.conversation_id is None:
        return None
    conversation = session.get(AIConversation, result.conversation_id)
    return conversation.user_id if conversation else None
