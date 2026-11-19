"""More rule shapes, for comparison in a backtest (ADR-061). Long-only spot, closed candles.

Four textbook rules next to the reference `ema_adx`: a trend breakout, two mean reversions, and a
momentum cross with a trend filter. Like the reference they are pure functions of the closed
candles and the position state, with no network, database or clock, and a signal carries no size
and no authority: the Intent Builder and the Risk Engine still decide what becomes an order.

**Nothing here runs live.** The runtime loads only `ema_adx` and these classes are not wired into
it. They exist so the same backtest engine, costs, sizing and limits can be run over the same
candles for every rule. The parameters are in `catalog.py` and are the owner's to adopt or change
(OQ-11); like `ema_adx` no parameter has a default.

Every entry carries the same stop shape as the reference (close minus a multiple of ATR), so the
position size, which the risk rule derives from the stop distance, does not differ between rules
for a reason that has nothing to do with the rule.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal

from aidss_trader.connector.types import Candle
from aidss_trader.strategy.base import PositionState, Signal, SignalKind, snapshot
from aidss_trader.strategy.indicators import atr, ema, highest, lowest, macd, rsi, sma, stdev


def _version(name: str, params: object) -> str:
    """A parameter change is a new version, and a new version starts in PAPER (ADR-003)."""
    blob = json.dumps(asdict(params), sort_keys=True, default=str)  # type: ignore[call-overload]
    return f"{name}-{hashlib.sha256(blob.encode()).hexdigest()[:12]}"


def _cooling_down(candles: Sequence[Candle], position: PositionState, cooldown_s: int) -> bool:
    if position.last_exit_at is None:
        return False
    return (candles[-1].open_time - position.last_exit_at).total_seconds() < cooldown_s


def _need(candles: Sequence[Candle], minimum: int) -> Signal | None:
    if len(candles) < minimum:
        return Signal(SignalKind.NONE, "insufficient_history", inputs=snapshot(bars=len(candles)))
    return None


# ---------------------------------------------------------------------------------- Donchian


@dataclass(frozen=True, slots=True)
class DonchianParams:
    entry_period: int
    exit_period: int
    atr_period: int
    atr_stop_multiple: Decimal
    cooldown_s: int

    def __post_init__(self) -> None:
        if min(self.entry_period, self.exit_period, self.atr_period) < 2:
            raise ValueError("periods must be at least 2")
        if self.exit_period > self.entry_period:
            raise ValueError("the exit channel must not be longer than the entry channel")
        if self.atr_stop_multiple <= 0 or self.cooldown_s < 0:
            raise ValueError("the ATR multiple must be positive and the cooldown not negative")


class DonchianBreakout:
    """Trend: enter when the close breaks above the highest high of the previous `entry_period`
    candles; leave when it breaks below the lowest low of the previous `exit_period`."""

    name = "donchian_breakout"
    strategy_id = name

    def __init__(self, params: DonchianParams) -> None:
        self.params = params

    def version_id(self) -> str:
        return _version(self.name, self.params)

    def min_history(self) -> int:
        p = self.params
        return max(p.entry_period + 1, p.atr_period + 1)

    def evaluate(self, candles: Sequence[Candle], position: PositionState) -> Signal:
        p = self.params
        if (short := _need(candles, self.min_history())) is not None:
            return short
        highs, lows = [c.high for c in candles], [c.low for c in candles]
        closes = [c.close for c in candles]
        end = len(candles) - 1
        upper = highest(highs, p.entry_period, end)
        lower = lowest(lows, p.exit_period, end)
        vol = atr(candles, p.atr_period)[-1]
        inputs = snapshot(close=closes[-1], upper=upper, lower=lower, atr=vol)
        if upper is None or lower is None or vol is None:
            return Signal(SignalKind.NONE, "insufficient_history", inputs=inputs)
        if position.long:
            if closes[-1] < lower:
                return Signal(SignalKind.EXIT, "broke_exit_channel", inputs=inputs)
            return Signal(SignalKind.NONE, "hold", inputs=inputs)
        if _cooling_down(candles, position, p.cooldown_s):
            return Signal(SignalKind.NONE, "cooldown", inputs=inputs)
        if closes[-1] > upper:
            stop = closes[-1] - p.atr_stop_multiple * vol
            return Signal(SignalKind.ENTRY, "broke_entry_channel", stop_hint=stop, inputs=inputs)
        return Signal(SignalKind.NONE, "no_signal", inputs=inputs)


# ------------------------------------------------------------------------------------- RSI


@dataclass(frozen=True, slots=True)
class RsiParams:
    rsi_period: int
    oversold: Decimal
    exit_level: Decimal
    atr_period: int
    atr_stop_multiple: Decimal
    cooldown_s: int

    def __post_init__(self) -> None:
        if min(self.rsi_period, self.atr_period) < 2:
            raise ValueError("periods must be at least 2")
        if not 0 < self.oversold < self.exit_level < 100:
            raise ValueError("need 0 < oversold < exit_level < 100")
        if self.atr_stop_multiple <= 0 or self.cooldown_s < 0:
            raise ValueError("the ATR multiple must be positive and the cooldown not negative")


class RsiReversion:
    """Mean reversion: enter when the RSI climbs back above `oversold` after being below it;
    leave when it reaches `exit_level`."""

    name = "rsi_reversion"
    strategy_id = name

    def __init__(self, params: RsiParams) -> None:
        self.params = params

    def version_id(self) -> str:
        return _version(self.name, self.params)

    def min_history(self) -> int:
        p = self.params
        return max(p.rsi_period + 2, p.atr_period + 1)

    def evaluate(self, candles: Sequence[Candle], position: PositionState) -> Signal:
        p = self.params
        if (short := _need(candles, self.min_history())) is not None:
            return short
        closes = [c.close for c in candles]
        series = rsi(closes, p.rsi_period)
        now, before = series[-1], series[-2]
        vol = atr(candles, p.atr_period)[-1]
        inputs = snapshot(close=closes[-1], rsi=now, rsi_prev=before, atr=vol)
        if now is None or before is None or vol is None:
            return Signal(SignalKind.NONE, "insufficient_history", inputs=inputs)
        if position.long:
            if now >= p.exit_level:
                return Signal(SignalKind.EXIT, "rsi_recovered", inputs=inputs)
            return Signal(SignalKind.NONE, "hold", inputs=inputs)
        if _cooling_down(candles, position, p.cooldown_s):
            return Signal(SignalKind.NONE, "cooldown", inputs=inputs)
        if before < p.oversold <= now:
            stop = closes[-1] - p.atr_stop_multiple * vol
            return Signal(
                SignalKind.ENTRY, "rsi_back_above_oversold", stop_hint=stop, inputs=inputs
            )
        return Signal(SignalKind.NONE, "no_signal", inputs=inputs)


# ------------------------------------------------------------------------------- Bollinger


@dataclass(frozen=True, slots=True)
class BollingerParams:
    period: int
    width: Decimal
    atr_period: int
    atr_stop_multiple: Decimal
    cooldown_s: int

    def __post_init__(self) -> None:
        if self.period < 3 or self.atr_period < 2:
            raise ValueError("periods are too short")
        if self.width <= 0 or self.atr_stop_multiple <= 0 or self.cooldown_s < 0:
            raise ValueError("width and ATR multiple must be positive, the cooldown not negative")


class BollingerReversion:
    """Mean reversion: enter when the close comes back inside the lower band after closing
    below it; leave when it reaches the middle band."""

    name = "bollinger_reversion"
    strategy_id = name

    def __init__(self, params: BollingerParams) -> None:
        self.params = params

    def version_id(self) -> str:
        return _version(self.name, self.params)

    def min_history(self) -> int:
        p = self.params
        return max(p.period + 1, p.atr_period + 1)

    def evaluate(self, candles: Sequence[Candle], position: PositionState) -> Signal:
        p = self.params
        if (short := _need(candles, self.min_history())) is not None:
            return short
        closes = [c.close for c in candles]
        mid, dev = sma(closes, p.period), stdev(closes, p.period)
        vol = atr(candles, p.atr_period)[-1]
        if mid[-1] is None or mid[-2] is None or dev[-1] is None or dev[-2] is None or vol is None:
            return Signal(
                SignalKind.NONE, "insufficient_history", inputs=snapshot(bars=len(closes))
            )
        lower_now = mid[-1] - p.width * dev[-1]
        lower_prev = mid[-2] - p.width * dev[-2]
        inputs = snapshot(close=closes[-1], middle=mid[-1], lower=lower_now, atr=vol)
        if position.long:
            if closes[-1] >= mid[-1]:
                return Signal(SignalKind.EXIT, "reached_middle_band", inputs=inputs)
            return Signal(SignalKind.NONE, "hold", inputs=inputs)
        if _cooling_down(candles, position, p.cooldown_s):
            return Signal(SignalKind.NONE, "cooldown", inputs=inputs)
        if closes[-2] < lower_prev and closes[-1] >= lower_now:
            stop = closes[-1] - p.atr_stop_multiple * vol
            return Signal(
                SignalKind.ENTRY, "back_inside_lower_band", stop_hint=stop, inputs=inputs
            )
        return Signal(SignalKind.NONE, "no_signal", inputs=inputs)


# ---------------------------------------------------------------------------------- MACD


@dataclass(frozen=True, slots=True)
class MacdTrendParams:
    fast: int
    slow: int
    signal: int
    trend_period: int
    atr_period: int
    atr_stop_multiple: Decimal
    cooldown_s: int

    def __post_init__(self) -> None:
        if not 0 < self.fast < self.slow or self.signal < 1:
            raise ValueError("need 0 < fast < slow and signal >= 1")
        if self.trend_period < self.slow or self.atr_period < 2:
            raise ValueError("the trend EMA must be at least as long as the slow EMA")
        if self.atr_stop_multiple <= 0 or self.cooldown_s < 0:
            raise ValueError("the ATR multiple must be positive and the cooldown not negative")


class MacdTrend:
    """Momentum: enter on a MACD cross above its signal line while the close is above the trend
    EMA; leave on the cross back below."""

    name = "macd_trend"
    strategy_id = name

    def __init__(self, params: MacdTrendParams) -> None:
        self.params = params

    def version_id(self) -> str:
        return _version(self.name, self.params)

    def min_history(self) -> int:
        p = self.params
        return max(p.trend_period + 1, p.slow + p.signal + 1, p.atr_period + 1)

    def evaluate(self, candles: Sequence[Candle], position: PositionState) -> Signal:
        p = self.params
        if (short := _need(candles, self.min_history())) is not None:
            return short
        closes = [c.close for c in candles]
        line, sig = macd(closes, p.fast, p.slow, p.signal)
        trend = ema(closes, p.trend_period)[-1]
        vol = atr(candles, p.atr_period)[-1]
        inputs = snapshot(close=closes[-1], macd=line[-1], signal=sig[-1], trend=trend, atr=vol)
        if (
            line[-1] is None
            or line[-2] is None
            or sig[-1] is None
            or sig[-2] is None
            or trend is None
            or vol is None
        ):
            return Signal(SignalKind.NONE, "insufficient_history", inputs=inputs)
        crossed_up = line[-2] <= sig[-2] and line[-1] > sig[-1]
        crossed_down = line[-2] >= sig[-2] and line[-1] < sig[-1]
        if position.long:
            if crossed_down:
                return Signal(SignalKind.EXIT, "macd_crossed_down", inputs=inputs)
            return Signal(SignalKind.NONE, "hold", inputs=inputs)
        if _cooling_down(candles, position, p.cooldown_s):
            return Signal(SignalKind.NONE, "cooldown", inputs=inputs)
        if crossed_up and closes[-1] > trend:
            stop = closes[-1] - p.atr_stop_multiple * vol
            return Signal(
                SignalKind.ENTRY, "macd_cross_up_in_uptrend", stop_hint=stop, inputs=inputs
            )
        return Signal(SignalKind.NONE, "no_signal", inputs=inputs)
