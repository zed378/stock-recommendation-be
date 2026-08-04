"""Independent, deliberately naive implementations of every indicator.

The production code in ``aidss.indicators.core`` is vectorised on top of
pandas; these are plain Python loops written straight from the textbook
definitions. Checking one against the other is the point: two implementations
that share no machinery are unlikely to be wrong in the same way, whereas a
test that reimplements the production approach would mostly assert that the
code equals itself.
"""

from __future__ import annotations

import math


def naive_sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(values)):
        if i < period - 1:
            out.append(None)
        else:
            out.append(sum(values[i - period + 1 : i + 1]) / period)
    return out


def naive_ema(values: list[float], period: int) -> list[float | None]:
    """EMA seeded with the SMA of the first `period` values."""
    if len(values) < period:
        return [None] * len(values)

    alpha = 2.0 / (period + 1)
    out: list[float | None] = [None] * (period - 1)
    current = sum(values[:period]) / period
    out.append(current)
    for value in values[period:]:
        current = current + alpha * (value - current)
        out.append(current)
    return out


def naive_wilder(values: list[float], period: int) -> list[float | None]:
    """Wilder smoothing: seed with a plain mean, then alpha = 1 / period."""
    if len(values) < period:
        return [None] * len(values)

    out: list[float | None] = [None] * (period - 1)
    current = sum(values[:period]) / period
    out.append(current)
    for value in values[period:]:
        current = current + (value - current) / period
        out.append(current)
    return out


def naive_rsi(closes: list[float], period: int = 14) -> list[float | None]:
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = naive_wilder(gains, period)
    avg_loss = naive_wilder(losses, period)

    out: list[float | None] = [None]  # index 0 has no preceding bar
    for g, loss in zip(avg_gain, avg_loss, strict=True):
        if g is None or loss is None:
            out.append(None)
        elif loss == 0:
            out.append(100.0 if g > 0 else 50.0)
        else:
            out.append(100.0 - 100.0 / (1.0 + g / loss))
    return out


def naive_true_range(
    highs: list[float], lows: list[float], closes: list[float]
) -> list[float]:
    out = [highs[0] - lows[0]]
    for i in range(1, len(highs)):
        prev_close = closes[i - 1]
        out.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - prev_close),
                abs(lows[i] - prev_close),
            )
        )
    return out


def naive_atr(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> list[float | None]:
    return naive_wilder(naive_true_range(highs, lows, closes), period)


def naive_adx(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> dict[str, list[float | None]]:
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    for i in range(1, len(highs)):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)

    tr = naive_true_range(highs, lows, closes)[1:]

    smooth_tr = naive_wilder(tr, period)
    smooth_plus = naive_wilder(plus_dm, period)
    smooth_minus = naive_wilder(minus_dm, period)

    plus_di: list[float | None] = [None]
    minus_di: list[float | None] = [None]
    dx: list[float | None] = [None]
    dx_compact: list[float] = []

    for atr_value, p, m in zip(smooth_tr, smooth_plus, smooth_minus, strict=True):
        if atr_value is None or atr_value == 0:
            plus_di.append(None)
            minus_di.append(None)
            dx.append(None)
            continue
        pdi = 100.0 * p / atr_value  # type: ignore[operator]
        mdi = 100.0 * m / atr_value  # type: ignore[operator]
        plus_di.append(pdi)
        minus_di.append(mdi)
        total = pdi + mdi
        value = None if total == 0 else 100.0 * abs(pdi - mdi) / total
        dx.append(value)
        if value is not None:
            dx_compact.append(value)

    smoothed_dx = naive_wilder(dx_compact, period)
    adx: list[float | None] = [None] * len(highs)
    first_dx_index = next((i for i, v in enumerate(dx) if v is not None), None)
    if first_dx_index is not None:
        for offset, value in enumerate(smoothed_dx):
            adx[first_dx_index + offset] = value

    return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di, "dx": dx}


def naive_bollinger(
    closes: list[float], period: int = 20, num_std: float = 2.0
) -> dict[str, list[float | None]]:
    middle: list[float | None] = []
    upper: list[float | None] = []
    lower: list[float | None] = []
    for i in range(len(closes)):
        if i < period - 1:
            middle.append(None)
            upper.append(None)
            lower.append(None)
            continue
        window = closes[i - period + 1 : i + 1]
        mean = sum(window) / period
        # Population standard deviation (ddof=0) - the Bollinger convention.
        variance = sum((x - mean) ** 2 for x in window) / period
        std = math.sqrt(variance)
        middle.append(mean)
        upper.append(mean + num_std * std)
        lower.append(mean - num_std * std)
    return {"middle": middle, "upper": upper, "lower": lower}


def naive_obv(closes: list[float], volumes: list[float]) -> list[float]:
    out = [0.0]
    total = 0.0
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            total += volumes[i]
        elif closes[i] < closes[i - 1]:
            total -= volumes[i]
        out.append(total)
    return out


def naive_stochastic(
    highs: list[float], lows: list[float], closes: list[float], k_period: int = 14
) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(closes)):
        if i < k_period - 1:
            out.append(None)
            continue
        window_high = max(highs[i - k_period + 1 : i + 1])
        window_low = min(lows[i - k_period + 1 : i + 1])
        span = window_high - window_low
        out.append(50.0 if span == 0 else (closes[i] - window_low) / span * 100.0)
    return out
