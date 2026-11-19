"""One-change variants of the reference strategy, for controlled experiments (ADR-063).

Each class is `ema_adx` with exactly one addition, so a backtest difference between a variant and
the reference can be traced to that one change instead of to a different set of numbers:

* `EmaAdxRising`     entry only while ADX is rising (the trend is strengthening, not fading)
* `EmaAdxDi`         entry only while +DI exceeds -DI (the direction agrees with the EMA cross)
* `EmaAdxAtrFilter`  entry only when volatility (ATR as a share of price) is not too low
* `EmaAdxTrail`      the stop follows the price up at a multiple of ATR, and never moves down
* `EmaAdxRegime`     entry only when the market is trending by Kaufman's efficiency ratio

A variant keeps the reference's entry, exit and stop; its filter can only refuse an entry the
reference would have made. The trailing stop is the one addition that touches an exit: it travels
as a `stop_hint` on a NONE signal while a position is open, and the stop holder (backtest engine or
paper book) applies it only if it raises the stop (ADR-007: tightened, never widened).

Pure functions of closed candles, no defaults for any number (OQ-11). Paper and backtest only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, fields
from decimal import Decimal

from aidss_trader.connector.types import Candle
from aidss_trader.strategy.base import PositionState, Signal, SignalKind, snapshot
from aidss_trader.strategy.ema_adx import EmaAdxParams, EmaAdxStrategy
from aidss_trader.strategy.indicators import (
    adx,
    atr,
    directional_lines,
    efficiency_ratio,
)
from aidss_trader.strategy.library import _version


def _core_params(p: EmaAdxParams) -> EmaAdxParams:
    return EmaAdxParams(**{f.name: getattr(p, f.name) for f in fields(EmaAdxParams)})


class _Variant:
    name: str
    strategy_id: str

    def __init__(self, params: EmaAdxParams) -> None:
        self.params = params
        self._core = EmaAdxStrategy(_core_params(params))

    def version_id(self) -> str:
        return _version(self.name, self.params)

    def _extra_history(self) -> int:
        return 0

    def min_history(self) -> int:
        return max(self._core.min_history(), self._extra_history() + 1)

    def _blocked(self, candles: Sequence[Candle]) -> tuple[str, dict[str, str]] | None:
        return None

    def _manage(self, candles: Sequence[Candle], signal: Signal) -> Signal:
        return signal

    def evaluate(self, candles: Sequence[Candle], position: PositionState) -> Signal:
        if len(candles) < self.min_history():
            return Signal(
                SignalKind.NONE, "insufficient_history", inputs=snapshot(bars=len(candles))
            )
        signal = self._core.evaluate(candles, position)
        if position.long:
            return self._manage(candles, signal)
        if signal.kind is SignalKind.ENTRY:
            blocked = self._blocked(candles)
            if blocked is not None:
                reason, extra = blocked
                return Signal(SignalKind.NONE, reason, inputs={**signal.inputs, **extra})
        return signal


@dataclass(frozen=True, slots=True)
class RisingParams(EmaAdxParams):
    rise_bars: int

    def __post_init__(self) -> None:
        EmaAdxParams.__post_init__(self)
        if self.rise_bars < 1:
            raise ValueError("rise_bars must be at least 1")


class EmaAdxRising(_Variant):
    name = "ema_adx_rising"
    strategy_id = name

    def _extra_history(self) -> int:
        p = self.params
        return 2 * p.adx_period + p.rise_bars

    def _blocked(self, candles):
        p = self.params
        series = adx(candles, p.adx_period)
        now, before = series[-1], series[-1 - p.rise_bars]
        extra = snapshot(adx_now=now, adx_before=before)
        if now is None or before is None or now <= before:
            return "adx_not_rising", extra
        return None


@dataclass(frozen=True, slots=True)
class DiParams(EmaAdxParams):
    di_margin: Decimal

    def __post_init__(self) -> None:
        EmaAdxParams.__post_init__(self)
        if not 0 <= self.di_margin < 100:
            raise ValueError("di_margin must be from 0 up to 100")


class EmaAdxDi(_Variant):
    name = "ema_adx_di"
    strategy_id = name

    def _blocked(self, candles):
        p = self.params
        plus, minus = directional_lines(candles, p.adx_period)
        pdi, mdi = plus[-1], minus[-1]
        extra = snapshot(plus_di=pdi, minus_di=mdi)
        if pdi is None or mdi is None or pdi - mdi <= p.di_margin:
            return "di_not_confirming", extra
        return None


@dataclass(frozen=True, slots=True)
class AtrFilterParams(EmaAdxParams):
    min_atr_pct: Decimal

    def __post_init__(self) -> None:
        EmaAdxParams.__post_init__(self)
        if not 0 < self.min_atr_pct < 100:
            raise ValueError("min_atr_pct must be above 0 and below 100")


class EmaAdxAtrFilter(_Variant):
    name = "ema_adx_atr_filter"
    strategy_id = name

    def _blocked(self, candles):
        p = self.params
        vol, close = atr(candles, p.atr_period)[-1], candles[-1].close
        share = None if vol is None or close <= 0 else vol / close * 100
        if share is None or share < p.min_atr_pct:
            return "volatility_too_low", snapshot(atr_pct=share, min_atr_pct=p.min_atr_pct)
        return None


@dataclass(frozen=True, slots=True)
class TrailParams(EmaAdxParams):
    trail_atr_multiple: Decimal

    def __post_init__(self) -> None:
        EmaAdxParams.__post_init__(self)
        if self.trail_atr_multiple <= 0:
            raise ValueError("trail_atr_multiple must be positive")


class EmaAdxTrail(_Variant):
    name = "ema_adx_trail"
    strategy_id = name

    def _manage(self, candles, signal):
        if signal.kind is not SignalKind.NONE:
            return signal  # the reference's own exit still applies
        p = self.params
        vol = atr(candles, p.atr_period)[-1]
        if vol is None:
            return signal
        trail = candles[-1].close - p.trail_atr_multiple * vol
        return Signal(
            SignalKind.NONE,
            "trail",
            stop_hint=trail,
            inputs={**signal.inputs, **snapshot(trail_stop=trail)},
        )


@dataclass(frozen=True, slots=True)
class RegimeParams(EmaAdxParams):
    er_period: int
    er_min: Decimal

    def __post_init__(self) -> None:
        EmaAdxParams.__post_init__(self)
        if self.er_period < 2:
            raise ValueError("er_period must be at least 2")
        if not 0 < self.er_min <= 1:
            raise ValueError("er_min must be above 0 and at most 1")


class EmaAdxRegime(_Variant):
    name = "ema_adx_regime"
    strategy_id = name

    def _extra_history(self) -> int:
        return self.params.er_period

    def _blocked(self, candles):
        p = self.params
        ratio = efficiency_ratio([c.close for c in candles], p.er_period)[-1]
        if ratio is None or ratio < p.er_min:
            return "ranging_market", snapshot(efficiency_ratio=ratio, er_min=p.er_min)
        return None


# --------------------------------------------------------------- combined (ADR-063)
#
# The reference with the DI confirmation (D2) as the parent, plus one more filter each. The DI check
# runs first, so a blocked entry reports the first filter that refused it. Because every filter only
# removes entries, a combined variant enters exactly where both single-filter variants enter.


@dataclass(frozen=True, slots=True)
class DiRisingParams(DiParams):
    rise_bars: int

    def __post_init__(self) -> None:
        DiParams.__post_init__(self)
        if self.rise_bars < 1:
            raise ValueError("rise_bars must be at least 1")


class EmaAdxDiRising(EmaAdxDi):
    """D6: +DI above -DI, and ADX rising."""

    name = "ema_adx_di_rising"
    strategy_id = name

    def _extra_history(self) -> int:
        p = self.params
        return 2 * p.adx_period + p.rise_bars

    def _blocked(self, candles):
        blocked = super()._blocked(candles)
        if blocked is not None:
            return blocked
        p = self.params
        series = adx(candles, p.adx_period)
        now, before = series[-1], series[-1 - p.rise_bars]
        if now is None or before is None or now <= before:
            return "adx_not_rising", snapshot(adx_now=now, adx_before=before)
        return None


@dataclass(frozen=True, slots=True)
class DiAtrParams(DiParams):
    min_atr_pct: Decimal

    def __post_init__(self) -> None:
        DiParams.__post_init__(self)
        if not 0 < self.min_atr_pct < 100:
            raise ValueError("min_atr_pct must be above 0 and below 100")


class EmaAdxDiAtrFilter(EmaAdxDi):
    """D7: +DI above -DI, and enough volatility."""

    name = "ema_adx_di_atr_filter"
    strategy_id = name

    def _blocked(self, candles):
        blocked = super()._blocked(candles)
        if blocked is not None:
            return blocked
        p = self.params
        vol, close = atr(candles, p.atr_period)[-1], candles[-1].close
        share = None if vol is None or close <= 0 else vol / close * 100
        if share is None or share < p.min_atr_pct:
            return "volatility_too_low", snapshot(atr_pct=share, min_atr_pct=p.min_atr_pct)
        return None
