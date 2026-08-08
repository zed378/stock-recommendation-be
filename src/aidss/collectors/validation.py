"""Cleaning & Validation - the first stage of the data pipeline (Section 10).

Provider data is not always clean: bars arrive with negative volume, a high
below the close, a zero price during a halt, or an absurd jump caused by a
decimal-place error. All of it is rejected here so the Indicator Engine never
computes on top of garbage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from aidss.domain.types import Candle

#: How far price may move between consecutive bars before the bar is treated as
#: an outlier. This is detection, not correction: suspicious data is rejected
#: rather than quietly "fixed", because a silent fix hides a broken feed.
DEFAULT_MAX_JUMP_RATIO = Decimal("0.5")


@dataclass(frozen=True, slots=True)
class Rejection:
    candle: Candle
    reason: str


@dataclass(slots=True)
class ValidationResult:
    accepted: list[Candle] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


def _structural_problem(candle: Candle) -> str | None:
    prices = (candle.open, candle.high, candle.low, candle.close)
    if any(p <= 0 for p in prices):
        return "non-positive price"
    if candle.volume < 0:
        return "negative volume"
    if candle.high < max(candle.open, candle.close):
        return "high below open/close"
    if candle.low > min(candle.open, candle.close):
        return "low above open/close"
    if candle.high < candle.low:
        return "high below low"
    return None


def validate_candles(
    candles: list[Candle], *, max_jump_ratio: Decimal = DEFAULT_MAX_JUMP_RATIO
) -> ValidationResult:
    """Per-bar structural checks plus a cross-bar outlier check.

    Outliers are measured against the last *valid* close rather than the
    immediately preceding bar, so one corrupt bar does not drag the bars after
    it into rejection too.
    """
    result = ValidationResult()
    last_valid_close: Decimal | None = None

    for candle in candles:
        problem = _structural_problem(candle)
        if problem is not None:
            result.rejected.append(Rejection(candle, problem))
            continue

        if last_valid_close is not None and last_valid_close > 0:
            jump = abs(candle.close - last_valid_close) / last_valid_close
            if jump > max_jump_ratio:
                result.rejected.append(
                    Rejection(candle, f"price jump of {jump:.2%} exceeds the plausible threshold")
                )
                continue

        result.accepted.append(candle)
        last_valid_close = candle.close

    return result
