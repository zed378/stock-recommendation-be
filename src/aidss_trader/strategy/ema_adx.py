"""Reference strategy: EMA trend filter with ADX strength and an ATR stop (ADR-019).

Rule shapes only. **No parameter has a default**: they are the owner's numbers
(OQ-11) and an unset one means the strategy cannot be constructed, so it can
never run on a value somebody guessed.

Entry: flat, fast EMA above slow EMA, ADX above `adx_threshold`, and not within
`cooldown_s` of the last exit. Stop: close minus `atr_stop_multiple` x ATR.
Exit: the trend filter fails at a candle close.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal

from aidss_trader.connector.types import Candle
from aidss_trader.strategy.base import PositionState, Signal, SignalKind, snapshot
from aidss_trader.strategy.indicators import adx, atr, ema


@dataclass(frozen=True, slots=True)
class EmaAdxParams:
    ema_fast: int
    ema_slow: int
    adx_period: int
    adx_threshold: Decimal
    atr_period: int
    atr_stop_multiple: Decimal
    cooldown_s: int

    def __post_init__(self) -> None:
        if not 0 < self.ema_fast < self.ema_slow:
            raise ValueError("ema_fast must be positive and shorter than ema_slow")
        if min(self.adx_period, self.atr_period) < 1 or self.atr_stop_multiple <= 0:
            raise ValueError("periods and the ATR multiple must be positive")
        if not 0 < self.adx_threshold <= 100:
            raise ValueError("adx_threshold must be above 0 and at most 100")
        if self.cooldown_s < 0:
            raise ValueError("cooldown_s cannot be negative")


class EmaAdxStrategy:
    name = "ema_adx"

    def __init__(self, params: EmaAdxParams) -> None:
        self.params = params

    def version_id(self) -> str:
        """A parameter change is a new version, and a new version starts in PAPER (ADR-003)."""
        blob = json.dumps(asdict(self.params), sort_keys=True, default=str)
        return f"{self.name}-{hashlib.sha256(blob.encode()).hexdigest()[:12]}"

    def min_history(self) -> int:
        p = self.params
        return max(p.ema_slow, 2 * p.adx_period + 1, p.atr_period + 1)

    def evaluate(self, candles: Sequence[Candle], position: PositionState) -> Signal:
        p = self.params
        if len(candles) < self.min_history():
            return Signal(
                SignalKind.NONE, "insufficient_history", inputs=snapshot(bars=len(candles))
            )
        closes = [c.close for c in candles]
        fast, slow = ema(closes, p.ema_fast)[-1], ema(closes, p.ema_slow)[-1]
        strength, vol = adx(candles, p.adx_period)[-1], atr(candles, p.atr_period)[-1]
        inputs = snapshot(
            close=closes[-1],
            ema_fast=fast,
            ema_slow=slow,
            adx=strength,
            atr=vol,
            adx_threshold=p.adx_threshold,
        )
        if fast is None or slow is None or strength is None or vol is None:
            return Signal(SignalKind.NONE, "insufficient_history", inputs=inputs)
        trend_up = fast > slow

        if position.long:
            if not trend_up:
                return Signal(SignalKind.EXIT, "trend_filter_failed", inputs=inputs)
            return Signal(SignalKind.NONE, "hold", inputs=inputs)

        if position.last_exit_at is not None:
            waited = (candles[-1].open_time - position.last_exit_at).total_seconds()
            if waited < p.cooldown_s:
                return Signal(SignalKind.NONE, "cooldown", inputs=inputs)
        if trend_up and strength > p.adx_threshold:
            stop = closes[-1] - p.atr_stop_multiple * vol
            return Signal(SignalKind.ENTRY, "trend_up_and_strong", stop_hint=stop, inputs=inputs)
        return Signal(SignalKind.NONE, "no_signal", inputs=inputs)
