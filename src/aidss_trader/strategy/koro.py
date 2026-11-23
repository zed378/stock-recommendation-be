"""Spot-applicable deterministic strategy adapted from KORO / Math Atlas (02/09 & 03/09).

Implements the long-only spot components in pure `Decimal`:
- OBV linear regression slope (`obv_reg_period`, Atlas: 48) for trend direction.
- Optional persistence gates: lag-1 return autocorrelation `rho_1 > 0` (`autocorr_window`,
  Atlas: 180, 0 = disabled) and Variance Ratio `VR(q) > 1` (`vr_horizon`, Atlas: 6, 0 = disabled).
- EMA-ATR pullback timing (`ema_period`, Atlas: 21; `atr_period`, Atlas: 14): enters long on a
  pullback bar (`close < prev_close`) that touches or sits at/below EMA while remaining within
  `max_extension_atr` ATRs (`|close - EMA| / ATR <= max_extension_atr`, Atlas: 0.5).
- Exits when OBV regression slope turns negative (in addition to the bot-side ATR stop).

Futures-only and non-deterministic Atlas mechanisms (SHORT legs, OI/Funding weights, margin MMR
halving, martingale ADD, probabilistic entry lottery) are deliberately excluded for Indodax Spot
compliance (ADR-004, ADR-009, ADR-025).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal

from aidss_trader.connector.types import Candle
from aidss_trader.strategy.base import PositionState, Signal, SignalKind, snapshot
from aidss_trader.strategy.indicators import atr, ema, lag1_autocorr, obv_slope, variance_ratio


@dataclass(frozen=True, slots=True)
class KoroObvPullbackParams:
    obv_reg_period: int
    ema_period: int
    max_extension_atr: Decimal
    autocorr_window: int
    vr_horizon: int
    atr_period: int
    atr_stop_multiple: Decimal
    cooldown_s: int

    def __post_init__(self) -> None:
        if min(self.obv_reg_period, self.ema_period, self.atr_period) < 2:
            raise ValueError("obv_reg_period, ema_period, and atr_period must be at least 2")
        if self.max_extension_atr <= 0:
            raise ValueError("max_extension_atr must be positive")
        if self.autocorr_window < 0 or (0 < self.autocorr_window < 3):
            raise ValueError("autocorr_window must be 0 (disabled) or at least 3")
        if self.vr_horizon < 0 or self.vr_horizon == 1:
            raise ValueError("vr_horizon must be 0 (disabled) or at least 2")
        if (
            self.vr_horizon >= 2
            and self.autocorr_window > 0
            and self.autocorr_window <= self.vr_horizon
        ):
            raise ValueError("autocorr_window must be greater than vr_horizon")
        if self.atr_stop_multiple <= 0 or self.cooldown_s < 0:
            raise ValueError("atr_stop_multiple must be positive and cooldown_s not negative")


class KoroObvPullback:
    """Long-only spot trend-following pullback strategy (KORO Atlas 02/09 + 03/09)."""

    name = "koro_obv_pullback"
    strategy_id = name

    def __init__(self, params: KoroObvPullbackParams) -> None:
        self.params = params

    def version_id(self) -> str:
        blob = json.dumps(asdict(self.params), sort_keys=True, default=str)
        return f"{self.name}-{hashlib.sha256(blob.encode()).hexdigest()[:12]}"

    def min_history(self) -> int:
        p = self.params
        base = max(p.obv_reg_period, p.ema_period, p.atr_period + 1) + 1
        if p.autocorr_window > 0:
            return max(base, p.autocorr_window + 1)
        return base

    def evaluate(self, candles: Sequence[Candle], position: PositionState) -> Signal:
        p = self.params
        if len(candles) < self.min_history():
            return Signal(
                SignalKind.NONE, "insufficient_history", inputs=snapshot(bars=len(candles))
            )

        closes = [c.close for c in candles]
        slopes = obv_slope(candles, p.obv_reg_period)
        emas = ema(closes, p.ema_period)
        atrs = atr(candles, p.atr_period)

        slope = slopes[-1]
        ema_now = emas[-1]
        atr_now = atrs[-1]
        if slope is None or ema_now is None or atr_now is None or atr_now <= 0:
            return Signal(SignalKind.NONE, "indicator_not_ready")

        cur = candles[-1]
        prev = candles[-2]
        extension = abs(cur.close - ema_now) / atr_now
        inputs = snapshot(
            close=cur.close,
            obv_slope=slope,
            ema=ema_now,
            atr=atr_now,
            extension_atr=extension,
        )

        if position.long:
            if slope < 0:
                return Signal(SignalKind.EXIT, "obv_slope_negative", inputs=inputs)
            return Signal(SignalKind.NONE, "hold_position", inputs=inputs)

        if position.last_exit_at is not None:
            if (cur.open_time - position.last_exit_at).total_seconds() < p.cooldown_s:
                return Signal(SignalKind.NONE, "cooldown_active", inputs=inputs)

        if slope <= 0:
            return Signal(SignalKind.NONE, "obv_not_rising", inputs=inputs)

        if p.autocorr_window > 0:
            rho1 = lag1_autocorr(closes, p.autocorr_window)
            if rho1 is None or rho1 <= 0:
                return Signal(SignalKind.NONE, "autocorr_gate_failed", inputs=inputs)
            if p.vr_horizon >= 2:
                vr = variance_ratio(closes, p.autocorr_window, p.vr_horizon)
                if vr is None or vr <= 1:
                    return Signal(SignalKind.NONE, "variance_ratio_gate_failed", inputs=inputs)

        is_pullback = cur.close < prev.close
        touches_or_below_ema = (cur.low <= ema_now <= cur.high) or (cur.close <= ema_now)
        if not (is_pullback and touches_or_below_ema):
            return Signal(SignalKind.NONE, "no_ema_pullback", inputs=inputs)

        if extension > p.max_extension_atr:
            return Signal(SignalKind.NONE, "overextended_from_ema", inputs=inputs)

        stop_price = cur.close - atr_now * p.atr_stop_multiple
        if stop_price <= 0:
            return Signal(SignalKind.NONE, "stop_non_positive", inputs=inputs)

        return Signal(
            SignalKind.ENTRY,
            "koro_obv_ema_pullback",
            stop_hint=stop_price,
            inputs=inputs,
        )
