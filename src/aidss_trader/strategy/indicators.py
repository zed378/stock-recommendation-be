"""EMA, ATR, and ADX in `Decimal`, Wilder's smoothing where the indicator defines it.

These are the Trader's own implementation: the Trader must not import `aidss`
(ADR-001), and prices stay `Decimal` end to end (ADR-025). A value with too
little history is `None`, never zero: zero would read as a measurement.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from aidss_trader.connector.types import Candle

ZERO = Decimal(0)


def ema(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    """Seeded with the simple average of the first `period` values."""
    if period < 1:
        raise ValueError("period must be at least 1")
    out: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return out
    alpha = Decimal(2) / Decimal(period + 1)
    current = sum(values[:period], ZERO) / period
    out[period - 1] = current
    for i in range(period, len(values)):
        current = values[i] * alpha + current * (1 - alpha)
        out[i] = current
    return out


def true_ranges(candles: Sequence[Candle]) -> list[Decimal | None]:
    out: list[Decimal | None] = [None]
    for prev, cur in zip(candles, candles[1:], strict=False):
        out.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return out


def atr(candles: Sequence[Candle], period: int) -> list[Decimal | None]:
    trs = true_ranges(candles)
    out: list[Decimal | None] = [None] * len(candles)
    if len(candles) < period + 1:
        return out
    current = sum((t for t in trs[1 : period + 1] if t is not None), ZERO) / period
    out[period] = current
    for i in range(period + 1, len(candles)):
        current = (current * (period - 1) + (trs[i] or ZERO)) / period
        out[i] = current
    return out


def adx(candles: Sequence[Candle], period: int) -> list[Decimal | None]:
    """Wilder's ADX. Needs about `2 * period` candles before the first value."""
    n = len(candles)
    out: list[Decimal | None] = [None] * n
    if n < 2 * period + 1:
        return out
    plus_dm: list[Decimal] = [ZERO]
    minus_dm: list[Decimal] = [ZERO]
    for prev, cur in zip(candles, candles[1:], strict=False):
        up, down = cur.high - prev.high, prev.low - cur.low
        plus_dm.append(up if up > down and up > 0 else ZERO)
        minus_dm.append(down if down > up and down > 0 else ZERO)
    trs = [t or ZERO for t in true_ranges(candles)]

    s_tr = sum(trs[1 : period + 1], ZERO)
    s_pdm = sum(plus_dm[1 : period + 1], ZERO)
    s_mdm = sum(minus_dm[1 : period + 1], ZERO)
    dx: list[Decimal] = []

    def directional(s_tr_: Decimal, s_p: Decimal, s_m: Decimal) -> Decimal:
        if s_tr_ == 0:
            return ZERO
        di_p, di_m = Decimal(100) * s_p / s_tr_, Decimal(100) * s_m / s_tr_
        total = di_p + di_m
        return ZERO if total == 0 else Decimal(100) * abs(di_p - di_m) / total

    dx.append(directional(s_tr, s_pdm, s_mdm))
    for i in range(period + 1, n):
        s_tr = s_tr - s_tr / period + trs[i]
        s_pdm = s_pdm - s_pdm / period + plus_dm[i]
        s_mdm = s_mdm - s_mdm / period + minus_dm[i]
        dx.append(directional(s_tr, s_pdm, s_mdm))
    if len(dx) < period:
        return out
    current = sum(dx[:period], ZERO) / period
    out[2 * period - 1 + 0] = current  # first ADX sits at index 2*period - 1 + 1 - 1
    for k in range(period, len(dx)):
        current = (current * (period - 1) + dx[k]) / period
        out[period + k] = current
    return out
