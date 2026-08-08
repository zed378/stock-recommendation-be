"""Deterministic confidence calibration and price levels (Section 14.4).

Two things a language model must not be trusted with here, and both are
handled in this module instead.

**The confidence score.** Section 14.4 requires "a consistently calibrated
score, not an arbitrary number from the LLM". A self-reported confidence
measures how fluent an answer felt, which is close to uncorrelated with how
much evidence stood behind it - a model with one indicator and no fundamentals
will happily report 85. So the score is computed from observable properties of
the evidence, by the function below, and the model's own number is kept only
for comparison.

**The prices.** Support, resistance, target, and the suggested stop are all
derived from the Indicator Engine's deterministic output, with the method
recorded alongside. A price invented by a model is a number nobody measured,
and it would appear in the interface next to numbers that were.

The weights below are a judgement, not a discovery. They are stated here so
they can be argued with and re-tuned, which is the point of writing them down
rather than leaving them implicit in a prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from aidss.domain.types import RecommendationLabel
from aidss.prompts.schemas import Bias, DataSufficiency

#: How much each evidence source contributes to coverage. Technical analysis
#: carries the most because it is the only source computed from complete,
#: verified data; news carries the least because sentiment is the softest
#: signal of the three.
SOURCE_WEIGHTS: dict[str, float] = {
    "technical_analyzer": 0.45,
    "fundamental_analyzer": 0.35,
    "news_analyzer": 0.20,
}

#: What a stated data_sufficiency is worth when computing coverage.
SUFFICIENCY_CREDIT: dict[DataSufficiency, float] = {
    DataSufficiency.SUFFICIENT: 1.0,
    DataSufficiency.PARTIAL: 0.5,
    DataSufficiency.INSUFFICIENT: 0.0,
}

#: Component weights for the final score.
COVERAGE_WEIGHT = 0.40
AGREEMENT_WEIGHT = 0.40
BALANCE_WEIGHT = 0.20

#: No recommendation is ever certain. A ceiling below 100 is a standing
#: reminder that this is analysis, not knowledge.
MAX_CONFIDENCE = 95.0

#: Minimum calibrated confidence a "strong" label must clear (Section 14.4).
STRONG_LABEL_MIN_CONFIDENCE = 70.0

_PRICE_QUANT = Decimal("0.01")

#: Multiple of ATR used for the suggested stop distance. Two ATR is the common
#: convention: wide enough that ordinary daily noise does not reach it.
STOP_ATR_MULTIPLE = Decimal("2")


@dataclass(frozen=True, slots=True)
class EvidenceSignal:
    """One analyzer's contribution, reduced to what calibration needs."""

    agent: str
    direction: int  # +1 bullish, 0 neutral, -1 bearish
    sufficiency: DataSufficiency


@dataclass(slots=True)
class CalibrationResult:
    confidence: float
    coverage: float
    agreement: float
    balance: float
    #: Human-readable account of how the number was reached. Stored with the
    #: recommendation so a score can be explained rather than merely displayed.
    explanation: str
    signals: list[EvidenceSignal] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "confidence": self.confidence,
            "components": {
                "coverage": round(self.coverage, 4),
                "agreement": round(self.agreement, 4),
                "balance": round(self.balance, 4),
            },
            "explanation": self.explanation,
            "signals": [
                {"agent": s.agent, "direction": s.direction, "sufficiency": s.sufficiency.value}
                for s in self.signals
            ],
        }


def _bias_direction(value: Any) -> int:
    if isinstance(value, Bias):
        return {Bias.BULLISH: 1, Bias.NEUTRAL: 0, Bias.BEARISH: -1}[value]
    return 0


def signals_from_agent_outputs(outputs: dict[str, Any]) -> list[EvidenceSignal]:
    """Reduce each analyzer's output to a direction and a data-sufficiency.

    ``outputs`` maps agent name to that agent's validated output model.
    """
    signals: list[EvidenceSignal] = []

    for agent, output in outputs.items():
        if agent not in SOURCE_WEIGHTS:
            continue

        if hasattr(output, "bias"):
            direction = _bias_direction(output.bias)
        elif hasattr(output, "sentiment_score"):
            # Sentiment is continuous; anything inside +/-0.2 is noise rather
            # than a directional claim.
            score = float(output.sentiment_score)
            direction = 1 if score > 0.2 else (-1 if score < -0.2 else 0)
        else:
            direction = 0

        signals.append(
            EvidenceSignal(
                agent=agent,
                direction=direction,
                sufficiency=getattr(output, "data_sufficiency", DataSufficiency.PARTIAL),
            )
        )
    return signals


def compute_coverage(signals: list[EvidenceSignal]) -> float:
    """How much of the possible evidence was actually available and usable.

    An analysis resting on price data alone scores far lower than one with
    fundamentals and news behind it, however confident its narrative sounds.
    """
    total_weight = sum(SOURCE_WEIGHTS.values())
    earned = sum(
        SOURCE_WEIGHTS[s.agent] * SUFFICIENCY_CREDIT[s.sufficiency]
        for s in signals
        if s.agent in SOURCE_WEIGHTS
    )
    return earned / total_weight if total_weight else 0.0


def compute_agreement(signals: list[EvidenceSignal]) -> float:
    """Whether the usable sources point the same way.

    Only sources with some data are counted: an analyzer that reported
    insufficient data has no opinion, and treating its silence as neutrality
    would dilute a genuine consensus into apparent disagreement.

    With one usable source there is nothing to agree with. That returns 0.5 -
    neither corroborated nor contradicted - rather than 1.0, because a lone
    voice agreeing with itself is not evidence of anything.
    """
    usable = [s for s in signals if s.sufficiency is not DataSufficiency.INSUFFICIENT]
    if not usable:
        return 0.0
    if len(usable) == 1:
        return 0.5

    directions = [s.direction for s in usable]
    dominant = max(set(directions), key=directions.count)
    return directions.count(dominant) / len(directions)


def compute_balance(supporting: int, conflicting: int) -> float:
    """How lopsided the stated evidence is.

    A recommendation listing eight supporting factors and no conflicting one
    has not weighed anything, so it scores 0 here rather than full marks. The
    curve is deliberately gentle: some genuine imbalance is normal, and only
    total one-sidedness is treated as a failure to look.
    """
    total = supporting + conflicting
    if total == 0:
        return 0.0
    if conflicting == 0:
        return 0.0
    ratio = min(supporting, conflicting) / max(supporting, conflicting)
    # A 1:2 split is healthy scepticism, not a problem; scale so it scores well.
    return min(1.0, 0.5 + ratio / 2)


def calibrate(
    agent_outputs: dict[str, Any],
    *,
    supporting_count: int,
    conflicting_count: int,
) -> CalibrationResult:
    """Compute the confidence that will actually be stored."""
    signals = signals_from_agent_outputs(agent_outputs)

    coverage = compute_coverage(signals)
    agreement = compute_agreement(signals)
    balance = compute_balance(supporting_count, conflicting_count)

    raw = COVERAGE_WEIGHT * coverage + AGREEMENT_WEIGHT * agreement + BALANCE_WEIGHT * balance
    confidence = round(min(raw * 100.0, MAX_CONFIDENCE), 1)

    usable = [s for s in signals if s.sufficiency is not DataSufficiency.INSUFFICIENT]
    explanation = (
        f"Calibrated from {len(usable)} usable evidence source(s) of "
        f"{len(SOURCE_WEIGHTS)} possible: coverage {coverage:.0%}, "
        f"directional agreement {agreement:.0%}, evidence balance {balance:.0%}. "
        f"Capped at {MAX_CONFIDENCE:.0f} because no analysis is certain."
    )

    return CalibrationResult(
        confidence=confidence,
        coverage=coverage,
        agreement=agreement,
        balance=balance,
        explanation=explanation,
        signals=signals,
    )


def evidence_direction(signals: list[EvidenceSignal]) -> int | None:
    """The direction the usable evidence points, or None when it is split.

    Used to catch a label that contradicts its own evidence. Returns None
    unless the usable sources are unanimous, so the check only fires on a
    clear contradiction rather than second-guessing every judgement call.
    """
    usable = [s for s in signals if s.sufficiency is not DataSufficiency.INSUFFICIENT]
    if not usable:
        return None
    directions = {s.direction for s in usable}
    return directions.pop() if len(directions) == 1 else None


# ---------------------------------------------------------------------------
# Price levels - measured, never generated
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DerivedLevels:
    """Prices attached to a recommendation, each with its method recorded."""

    support: Decimal | None = None
    resistance: Decimal | None = None
    target_price: Decimal | None = None
    target_price_method: str | None = None
    suggested_stop: Decimal | None = None
    suggested_stop_method: str | None = None


def _quantize(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(_PRICE_QUANT, rounding=ROUND_HALF_UP)


def derive_levels(snapshot: dict[str, Any], label: RecommendationLabel) -> DerivedLevels:
    """Build the price fields of Section 14.4 from computed indicators.

    Every value returned traces back to a swing level or an ATR reading that
    the Indicator Engine measured. When the basis is missing the field stays
    ``None``: Section 14.4 asks for a target price "if a basis for calculating
    one exists", and inventing one when it does not would be the opposite of
    what that qualification is for.
    """
    levels = DerivedLevels()
    if not snapshot:
        return levels

    last_close = snapshot.get("last_close")
    price_levels = snapshot.get("levels") or {}
    supports = [float(v) for v in price_levels.get("support", [])]
    resistances = [float(v) for v in price_levels.get("resistance", [])]

    # `support_resistance` returns supports descending and resistances
    # ascending, so the first of each is the nearest to price.
    if supports:
        levels.support = _quantize(supports[0])
    if resistances:
        levels.resistance = _quantize(resistances[0])

    if last_close is None:
        return levels

    direction = label.direction
    atr = _extract_atr(snapshot)

    if direction > 0 and resistances:
        levels.target_price = _quantize(resistances[0])
        levels.target_price_method = "nearest confirmed swing resistance above the last close"
    elif direction < 0 and supports:
        levels.target_price = _quantize(supports[0])
        levels.target_price_method = "nearest confirmed swing support below the last close"

    if atr is not None and atr > 0 and direction != 0:
        distance = _quantize(Decimal(str(atr)) * STOP_ATR_MULTIPLE)
        close = Decimal(str(last_close))
        # For a constructive stance the stop sits below price, and vice versa.
        stop = close - distance if direction > 0 else close + distance
        if stop > 0:
            levels.suggested_stop = _quantize(stop)
            levels.suggested_stop_method = (
                f"{STOP_ATR_MULTIPLE} x ATR(14) = {distance} "
                f"{'below' if direction > 0 else 'above'} the last close - a suggestion "
                "for the reader to weigh, not an order"
            )

    return levels


def _extract_atr(snapshot: dict[str, Any]) -> float | None:
    indicators = snapshot.get("indicators") or {}
    for key, payload in indicators.items():
        if key.startswith("atr(") and isinstance(payload, dict):
            value = payload.get("value")
            if value is not None:
                return float(value)
    return None
