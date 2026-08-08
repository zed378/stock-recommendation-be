"""The conditions each horizon looks for, written as data.

Every criterion is a named, inspectable rule over the indicator snapshot the
engine already computed. Two consequences follow from that, and both are the
point:

  * A screen result can say **exactly why** an asset appeared, in the reader's
    own vocabulary - "RSI recovering from oversold", not "score 0.72".
  * A criterion can be tested on its own. A scoring function that is one opaque
    expression can only be tested through its output, which means a wrong
    weight and a wrong formula look identical from the outside.

**What these are not.** No criterion predicts a price and no combination of
them produces a probability. Each says a condition observed in past bars is
currently true. Conditions associated with rises are not causes of rises, and
this module is careful never to imply otherwise: the horizons below describe
*the window each condition is usually read over*, not how long anything will
take to happen.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Horizon(StrEnum):
    """The window a condition is conventionally read over."""

    D1 = "1d"
    D7 = "7d"
    D14 = "14d"
    D30 = "30d"


HORIZON_BARS: dict[Horizon, int] = {
    Horizon.D1: 1,
    Horizon.D7: 5,
    Horizon.D14: 10,
    Horizon.D30: 21,
}


@dataclass(frozen=True, slots=True)
class Criterion:
    """One named condition over an indicator snapshot.

    ``weight`` orders results; it is not a probability and does not sum to one.
    Two assets differing by 0.3 differ in how many stated conditions they meet,
    nothing more.
    """

    key: str
    weight: float
    #: Shown to the reader when the condition is met. Present tense, factual.
    describes: str
    test: Callable[[Reading], bool]


@dataclass(slots=True)
class Reading:
    """A flattened view of one asset's snapshot, with absence made explicit.

    Every accessor returns None rather than a default when the value is
    missing. A screen that treated an absent RSI as 50 would rank an asset with
    no history alongside one that was measured and found neutral.
    """

    close: float | None
    indicators: dict[str, dict[str, Any]]
    features: dict[str, Any]
    levels: dict[str, list[float]]
    breakout: dict[str, Any]
    structure: str | None

    def indicator(self, key: str, field: str = "value") -> float | None:
        node = self.indicators.get(key)
        if not isinstance(node, dict):
            return None
        value = node.get(field)
        return float(value) if isinstance(value, (int, float)) else None

    def feature(self, key: str) -> float | None:
        value = self.features.get(key)
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def nearest_resistance(self) -> float | None:
        levels = [float(x) for x in self.levels.get("resistance", []) if x is not None]
        above = [x for x in levels if self.close is not None and x > self.close]
        return min(above) if above else None

    @property
    def nearest_support(self) -> float | None:
        levels = [float(x) for x in self.levels.get("support", []) if x is not None]
        below = [x for x in levels if self.close is not None and x < self.close]
        return max(below) if below else None


# --- shared predicates -----------------------------------------------------


def _above(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and a > b


def _between(value: float | None, low: float, high: float) -> bool:
    return value is not None and low <= value <= high


def _positive(value: float | None) -> bool:
    """Present *and* above zero.

    `(value or 0) > 0` reads the same and is not: it is False for a missing
    value, which is right here but wrong the moment the comparison points the
    other way. `(value or 0) < 0.10` was True for every asset with no data at
    all, so a screen ranked assets it had never measured. Requiring presence
    explicitly is what stops that reappearing the next time a criterion is
    added.
    """
    return value is not None and value > 0


def _below(value: float | None, ceiling: float) -> bool:
    return value is not None and value < ceiling


def _at_least(value: float | None, floor: float) -> bool:
    return value is not None and value >= floor


def _rising_volume(reading: Reading, threshold: float = 1.2) -> bool:
    ratio = reading.indicator("volume_ratio(period=20)")
    return ratio is not None and ratio >= threshold


def _near_resistance(reading: Reading, within: float = 0.03) -> bool:
    """Close enough to a level that clearing it is the next thing that happens.

    Distance is relative, so a Rp 100 stock and a Rp 10,000 one are judged the
    same way rather than the cheaper one always looking closer.
    """
    resistance = reading.nearest_resistance
    if resistance is None or reading.close is None or resistance <= 0:
        return False
    return (resistance - reading.close) / resistance <= within


def _recovering(reading: Reading) -> bool:
    """Off the worst of the drawdown, with both readings actually present."""
    current = reading.feature("drawdown_current")
    worst = reading.feature("drawdown_max")
    if current is None or worst is None or worst >= 0:
        return False
    return current > worst / 2


def _volatility_contained(reading: Reading) -> bool:
    short = reading.feature("volatility_20b")
    longer = reading.feature("volatility_60b")
    if short is None or longer is None or longer <= 0:
        return False
    return short <= longer * 1.25


# --- criteria --------------------------------------------------------------
#
# Grouped by the window each condition is normally read over. A one-day screen
# reads today's tape; a one-month screen reads trend structure. Mixing them
# would produce a single ranking that answers neither question.

_D1 = (
    Criterion(
        key="up_on_above_average_volume",
        weight=1.0,
        describes="today's bar is up on above-average volume",
        test=lambda r: _positive(r.feature("return_1b")) and _rising_volume(r, 1.5),
    ),
    Criterion(
        key="pressing_resistance",
        weight=0.9,
        describes="price is pressing against the nearest resistance",
        test=lambda r: _near_resistance(r, 0.02),
    ),
    Criterion(
        key="stochastic_turning_up",
        weight=0.7,
        describes="stochastic %K has crossed above %D from a low reading",
        test=lambda r: (
            _above(r.indicator("stochastic(d_period=3,k_period=14)", "k"),
                   r.indicator("stochastic(d_period=3,k_period=14)", "d"))
            and _between(r.indicator("stochastic(d_period=3,k_period=14)", "k"), 0, 60)
        ),
    ),
    Criterion(
        key="above_short_average",
        weight=0.5,
        describes="price is above its 20-bar average",
        test=lambda r: _above(r.close, r.indicator("sma(period=20)")),
    ),
    Criterion(
        key="breakout_up_confirmed",
        weight=1.0,
        describes="a breakout above the recent range is in progress",
        # `detect_breakout` says "bullish", never "up". Tested against "up",
        # this was dead - the heaviest criterion in the 1d horizon, worth 1.0 of
        # its 4.1, silently unreachable. It survived because the screen only
        # ever ranked the dozen assets with imported price bars, where a
        # criterion firing zero times is indistinguishable from a quiet market.
        # Over 799 issuers it stood out: the same scan reported ninety names at
        # 52-week highs, and not one of them breaking a 20-bar range.
        test=lambda r: r.breakout.get("direction") == "bullish",
    ),
)

_D7 = (
    Criterion(
        key="macd_histogram_positive",
        weight=1.0,
        describes="MACD histogram is positive - momentum is building rather than fading",
        test=lambda r: _positive(r.indicator("macd(fast=12,signal=9,slow=26)", "histogram")),
    ),
    Criterion(
        key="rsi_recovering",
        weight=0.9,
        describes="RSI is recovering through the 40-60 band rather than overbought",
        test=lambda r: _between(r.indicator("rsi(period=14)"), 40, 65),
    ),
    Criterion(
        key="short_above_medium_average",
        weight=0.8,
        describes="the 20-bar average is above the 50-bar average",
        test=lambda r: _above(r.indicator("sma(period=20)"), r.indicator("sma(period=50)")),
    ),
    Criterion(
        key="volume_supporting",
        weight=0.6,
        describes="volume is running above its own 20-bar average",
        test=lambda r: _rising_volume(r, 1.2),
    ),
    Criterion(
        key="near_breakout_level",
        weight=0.7,
        describes="price is within reach of the level that would confirm a breakout",
        test=lambda r: _near_resistance(r, 0.05),
    ),
)

_D14 = (
    Criterion(
        key="trend_has_strength",
        weight=1.0,
        describes="ADX shows a trend with actual strength behind it, not drift",
        test=lambda r: _at_least(r.indicator("adx(period=14)", "adx"), 20),
    ),
    Criterion(
        key="directional_bias_up",
        weight=1.0,
        describes="positive directional movement exceeds negative",
        test=lambda r: _above(
            r.indicator("adx(period=14)", "plus_di"), r.indicator("adx(period=14)", "minus_di")
        ),
    ),
    Criterion(
        key="above_medium_average",
        weight=0.8,
        describes="price is above its 50-bar average",
        test=lambda r: _above(r.close, r.indicator("sma(period=50)")),
    ),
    Criterion(
        key="not_stretched",
        weight=0.6,
        describes="price is not stretched far above its 20-bar average",
        test=lambda r: _below(r.feature("gap_from_sma20"), 0.10),
    ),
    Criterion(
        key="room_in_the_range",
        weight=0.5,
        describes="price sits below the top of its 52-bar range, leaving room",
        test=lambda r: _between(r.feature("range_position_52b"), 0.35, 0.90),
    ),
)

_D30 = (
    Criterion(
        key="above_long_average",
        weight=1.0,
        describes="price is above its 200-bar average - the longer trend is up",
        test=lambda r: _above(r.close, r.indicator("sma(period=200)")),
    ),
    Criterion(
        key="medium_above_long_average",
        weight=0.9,
        describes="the 50-bar average is above the 200-bar average",
        test=lambda r: _above(r.indicator("sma(period=50)"), r.indicator("sma(period=200)")),
    ),
    Criterion(
        key="recovering_from_drawdown",
        weight=0.7,
        describes="the current drawdown is well off its worst",
        test=_recovering,
    ),
    Criterion(
        key="positive_over_the_quarter",
        weight=0.8,
        describes="the 60-bar return is positive",
        test=lambda r: _positive(r.feature("return_60b")),
    ),
    Criterion(
        key="volatility_not_elevated",
        weight=0.5,
        describes="volatility is not elevated relative to its longer reading",
        test=_volatility_contained,
    ),
)


CRITERIA_BY_HORIZON: dict[Horizon, tuple[Criterion, ...]] = {
    Horizon.D1: _D1,
    Horizon.D7: _D7,
    Horizon.D14: _D14,
    Horizon.D30: _D30,
}


def max_score(horizon: Horizon) -> float:
    """The score an asset meeting every criterion would reach.

    Reported alongside the score so "3.1" is readable as "3.1 out of 4.1"
    rather than as a number on an unstated scale.
    """
    return sum(c.weight for c in CRITERIA_BY_HORIZON[horizon])
