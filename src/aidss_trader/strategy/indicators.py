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


def sma(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    """Simple moving average; `None` until `period` values exist."""
    if period < 1:
        raise ValueError("period must be at least 1")
    out: list[Decimal | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = sum(values[i - period + 1 : i + 1], ZERO) / period
    return out


def stdev(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    """Population standard deviation over the last `period` values (Bollinger's convention)."""
    if period < 2:
        raise ValueError("period must be at least 2")
    out: list[Decimal | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        mean = sum(window, ZERO) / period
        variance = sum(((v - mean) ** 2 for v in window), ZERO) / period
        out[i] = variance.sqrt()
    return out


def rsi(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    """Wilder's RSI: 100 when there were no losses in the window, 0 when no gains."""
    if period < 1:
        raise ValueError("period must be at least 1")
    n = len(values)
    out: list[Decimal | None] = [None] * n
    if n < period + 1:
        return out
    gains = [max(values[i] - values[i - 1], ZERO) for i in range(1, n)]
    losses = [max(values[i - 1] - values[i], ZERO) for i in range(1, n)]
    avg_gain = sum(gains[:period], ZERO) / period
    avg_loss = sum(losses[:period], ZERO) / period

    def value(g: Decimal, l_: Decimal) -> Decimal:
        if l_ == 0:
            return Decimal(100) if g > 0 else Decimal(50)
        return Decimal(100) - Decimal(100) / (1 + g / l_)

    out[period] = value(avg_gain, avg_loss)
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        out[i] = value(avg_gain, avg_loss)
    return out


def macd(
    values: Sequence[Decimal], fast: int, slow: int, signal: int
) -> tuple[list[Decimal | None], list[Decimal | None]]:
    """The MACD line (fast EMA minus slow EMA) and its signal line (an EMA of the MACD line)."""
    if not 0 < fast < slow or signal < 1:
        raise ValueError("need 0 < fast < slow and signal >= 1")
    fast_e, slow_e = ema(values, fast), ema(values, slow)
    line: list[Decimal | None] = [
        None if a is None or b is None else a - b for a, b in zip(fast_e, slow_e, strict=True)
    ]
    first = next((i for i, v in enumerate(line) if v is not None), None)
    sig: list[Decimal | None] = [None] * len(values)
    if first is not None:
        seeded = ema([v for v in line[first:] if v is not None], signal)
        for k, v in enumerate(seeded):
            sig[first + k] = v
    return line, sig


def highest(values: Sequence[Decimal], period: int, end: int) -> Decimal | None:
    """The highest of the `period` values that end just BEFORE index `end` (the current one is
    excluded, so a breakout is measured against what came before it)."""
    if end < period:
        return None
    return max(values[end - period : end])


def lowest(values: Sequence[Decimal], period: int, end: int) -> Decimal | None:
    if end < period:
        return None
    return min(values[end - period : end])
