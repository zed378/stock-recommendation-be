"""Technical indicator maths - purely deterministic (Section 5.3).

There is no LLM in this module, and there must never be one. Every number is
computed here so the AI layer only ever *interprets* settled values rather than
deriving them, which is the main defence against hallucinated figures
(Section 2.7).

Conventions held consistently throughout:

* EMA is seeded with the SMA of the first period, the usual TA-library
  convention, so the first ``period - 1`` values are NaN rather than forced.
* The Wilder family (RSI, ATR, ADX) uses Wilder smoothing (alpha = 1/period),
  not an ordinary EMA (alpha = 2/(period+1)). Mixing the two is a classic
  source of values that look nearly right and are not.
* A value with insufficient history is NaN, never 0 - zero is a measurement,
  absence is not.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------


def sma(series: pd.Series, period: int) -> pd.Series:
    _check_period(period)
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """EMA seeded with SMA(period) at index ``period - 1``."""
    _check_period(period)
    values = series.astype(float)
    if len(values) < period:
        return pd.Series(np.nan, index=series.index, dtype=float)

    seeded = values.copy()
    seeded.iloc[: period - 1] = np.nan
    seeded.iloc[period - 1] = values.iloc[:period].mean()
    return seeded.ewm(alpha=2.0 / (period + 1), adjust=False, ignore_na=False).mean()


def wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """Wilder smoothing: seed with the first period's mean, then alpha = 1/period."""
    _check_period(period)
    values = series.astype(float)
    valid = values.dropna()
    if len(valid) < period:
        return pd.Series(np.nan, index=series.index, dtype=float)

    seeded = pd.Series(np.nan, index=values.index, dtype=float)
    seed_position = values.index.get_loc(valid.index[period - 1])
    seeded.iloc[seed_position] = valid.iloc[:period].mean()
    seeded.iloc[seed_position + 1 :] = values.iloc[seed_position + 1 :].to_numpy()
    return seeded.ewm(alpha=1.0 / period, adjust=False, ignore_na=False).mean()


# ---------------------------------------------------------------------------
# Momentum
# ---------------------------------------------------------------------------


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI. A strictly rising series gives 100, a falling one gives 0."""
    _check_period(period)
    delta = close.astype(float).diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = wilder_smooth(gain.iloc[1:], period).reindex(close.index)
    avg_loss = wilder_smooth(loss.iloc[1:], period).reindex(close.index)

    result = pd.Series(np.nan, index=close.index, dtype=float)
    both_known = avg_gain.notna() & avg_loss.notna()
    # avg_loss == 0 makes RS infinite, so RSI is 100 when there were gains and
    # 50 when the series was flat (no gains and no losses leaves RSI undefined).
    no_loss = both_known & (avg_loss == 0)
    normal = both_known & (avg_loss != 0)

    rs = avg_gain[normal] / avg_loss[normal]
    result[normal] = 100.0 - (100.0 / (1.0 + rs))
    result[no_loss] = np.where(avg_gain[no_loss] > 0, 100.0, 50.0)
    return result


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    if fast >= slow:
        raise ValueError("the fast period must be smaller than the slow period")
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = _ema_on_sparse(macd_line, signal)
    return pd.DataFrame(
        {
            "macd": macd_line,
            "signal": signal_line,
            "histogram": macd_line - signal_line,
        }
    )


def stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14, d_period: int = 3
) -> pd.DataFrame:
    _check_period(k_period)
    _check_period(d_period)
    lowest = low.rolling(k_period, min_periods=k_period).min()
    highest = high.rolling(k_period, min_periods=k_period).max()
    span = highest - lowest
    # A zero range (perfectly flat price) maps to a neutral 50 rather than a
    # division by zero.
    percent_k = np.where(span == 0, 50.0, (close - lowest) / span.replace(0, np.nan) * 100.0)
    k_series = pd.Series(percent_k, index=close.index).where(span.notna())
    return pd.DataFrame(
        {"k": k_series, "d": k_series.rolling(d_period, min_periods=d_period).mean()}
    )


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------


def bollinger_bands(
    close: pd.Series, period: int = 20, num_std: float = 2.0
) -> pd.DataFrame:
    _check_period(period)
    middle = sma(close, period)
    # ddof=0 (population) is the Bollinger convention, and differs from pandas'
    # default of ddof=1 - using the default would widen every band slightly.
    std = close.rolling(period, min_periods=period).std(ddof=0)
    upper = middle + num_std * std
    lower = middle - num_std * std
    return pd.DataFrame(
        {
            "middle": middle,
            "upper": upper,
            "lower": lower,
            "bandwidth": (upper - lower) / middle.replace(0, np.nan),
        }
    )


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    if len(high) == 0:
        return pd.Series(dtype=float, index=high.index)
    prev_close = close.shift(1)
    ranges = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    )
    tr = ranges.max(axis=1)
    # The first bar has no previous close, so TR reduces to high - low.
    tr.iloc[0] = high.iloc[0] - low.iloc[0]
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    return wilder_smooth(true_range(high, low, close), period)


def rolling_volatility(
    close: pd.Series, period: int = 20, annualize: int | None = 252
) -> pd.Series:
    """Realised volatility from log returns."""
    _check_period(period)
    log_returns = np.log(close.astype(float) / close.astype(float).shift(1))
    vol = log_returns.rolling(period, min_periods=period).std(ddof=1)
    if annualize:
        vol = vol * np.sqrt(annualize)
    return vol


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------


def adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.DataFrame:
    """Wilder's ADX and directional indicators.

    Directional movement counts only when one direction *exceeds* the other; an
    inside bar therefore contributes zero DM in both directions.
    """
    _check_period(period)
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index
    )
    plus_dm.iloc[0] = np.nan
    minus_dm.iloc[0] = np.nan

    tr = true_range(high, low, close)
    atr_series = wilder_smooth(tr.iloc[1:], period).reindex(high.index)
    smooth_plus = wilder_smooth(plus_dm.iloc[1:], period).reindex(high.index)
    smooth_minus = wilder_smooth(minus_dm.iloc[1:], period).reindex(high.index)

    safe_atr = atr_series.replace(0, np.nan)
    plus_di = 100.0 * smooth_plus / safe_atr
    minus_di = 100.0 * smooth_minus / safe_atr

    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx_series = wilder_smooth(dx.dropna(), period).reindex(high.index)

    return pd.DataFrame(
        {"adx": adx_series, "plus_di": plus_di, "minus_di": minus_di, "dx": dx}
    )


def ichimoku(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    conversion: int = 9,
    base: int = 26,
    span_b: int = 52,
) -> pd.DataFrame:
    def midpoint(period: int) -> pd.Series:
        return (
            high.rolling(period, min_periods=period).max()
            + low.rolling(period, min_periods=period).min()
        ) / 2.0

    tenkan = midpoint(conversion)
    kijun = midpoint(base)
    return pd.DataFrame(
        {
            "tenkan_sen": tenkan,
            "kijun_sen": kijun,
            # Both spans are displaced `base` bars forward - that displacement
            # is what puts the cloud ahead of price.
            "senkou_span_a": ((tenkan + kijun) / 2.0).shift(base),
            "senkou_span_b": midpoint(span_b).shift(base),
            # Chikou is displaced backwards, so the newest bars are necessarily
            # empty.
            "chikou_span": close.shift(-base),
        }
    )


# ---------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume. The first bar is the zero reference point."""
    direction = np.sign(close.diff().fillna(0.0))
    return (direction * volume.astype(float)).cumsum()


def volume_ratio(volume: pd.Series, period: int = 20) -> pd.Series:
    """Volume relative to its own average - the basis for spotting volume spikes."""
    average = sma(volume.astype(float), period)
    return volume.astype(float) / average.replace(0, np.nan)


# ---------------------------------------------------------------------------
# Market structure
# ---------------------------------------------------------------------------


def pivot_points(
    high: pd.Series, low: pd.Series, left: int = 3, right: int = 3
) -> pd.DataFrame:
    """Fractal swing high/low detection.

    A bar is a swing high when its high exceeds the ``left`` bars before it and
    the ``right`` bars after it. A pivot can therefore only be confirmed once
    ``right`` further bars exist - deliberately so, because confirming earlier
    would be lookahead bias.
    """
    if left < 1 or right < 1:
        raise ValueError("left and right must both be >= 1")

    n = len(high)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    highs = high.to_numpy(dtype=float)
    lows = low.to_numpy(dtype=float)

    for i in range(left, n - right):
        window_high = highs[i - left : i + right + 1]
        window_low = lows[i - left : i + right + 1]
        if highs[i] == window_high.max() and (window_high == highs[i]).sum() == 1:
            is_high[i] = True
        if lows[i] == window_low.min() and (window_low == lows[i]).sum() == 1:
            is_low[i] = True

    return pd.DataFrame({"swing_high": is_high, "swing_low": is_low}, index=high.index)


def support_resistance(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    left: int = 3,
    right: int = 3,
    max_levels: int = 3,
    cluster_tolerance: float = 0.005,
) -> dict[str, list[float]]:
    """Support/resistance levels from confirmed swings, clustered.

    Levels within ``cluster_tolerance`` of each other are treated as one zone
    and averaged, so the output is not five levels that are practically the
    same price.
    """
    pivots = pivot_points(high, low, left, right)
    last_price = float(close.iloc[-1])

    resistances = sorted(float(v) for v in high[pivots["swing_high"]] if float(v) > last_price)
    supports = sorted(
        (float(v) for v in low[pivots["swing_low"]] if float(v) < last_price), reverse=True
    )

    return {
        "support": _cluster(supports, cluster_tolerance)[:max_levels],
        "resistance": _cluster(resistances, cluster_tolerance)[:max_levels],
    }


def detect_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series, lookback: int = 20
) -> dict[str, object]:
    """A breakout is a close beyond the extreme of the **preceding** bars.

    The window deliberately excludes the current bar. Including it would mean
    the close always sits inside its own range, and no breakout would ever be
    detected.
    """
    _check_period(lookback)
    if len(close) < lookback + 1:
        return {"direction": "none", "level": None, "lookback": lookback}

    prior_high = float(high.iloc[-(lookback + 1) : -1].max())
    prior_low = float(low.iloc[-(lookback + 1) : -1].min())
    last = float(close.iloc[-1])

    if last > prior_high:
        return {"direction": "bullish", "level": prior_high, "lookback": lookback}
    if last < prior_low:
        return {"direction": "bearish", "level": prior_low, "lookback": lookback}
    return {"direction": "none", "level": None, "lookback": lookback}


def market_structure(high: pd.Series, low: pd.Series, left: int = 3, right: int = 3) -> str:
    """Classify structure from the last two swings on each side."""
    pivots = pivot_points(high, low, left, right)
    swing_highs = high[pivots["swing_high"]].tolist()
    swing_lows = low[pivots["swing_low"]].tolist()
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "undetermined"

    higher_high = swing_highs[-1] > swing_highs[-2]
    higher_low = swing_lows[-1] > swing_lows[-2]
    if higher_high and higher_low:
        return "uptrend"
    if not higher_high and not higher_low:
        return "downtrend"
    return "ranging"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _check_period(period: int) -> None:
    if not isinstance(period, int) or period < 1:
        raise ValueError(f"period must be an integer >= 1, got {period!r}")


def _ema_on_sparse(series: pd.Series, period: int) -> pd.Series:
    """EMA over a series with leading NaNs, such as the MACD line."""
    _check_period(period)
    valid = series.dropna()
    if len(valid) < period:
        return pd.Series(np.nan, index=series.index, dtype=float)
    return ema(valid, period).reindex(series.index)


def _cluster(levels: list[float], tolerance: float) -> list[float]:
    if not levels:
        return []
    clustered: list[float] = []
    bucket: list[float] = [levels[0]]
    for level in levels[1:]:
        reference = bucket[0]
        if reference != 0 and abs(level - reference) / abs(reference) <= tolerance:
            bucket.append(level)
        else:
            clustered.append(sum(bucket) / len(bucket))
            bucket = [level]
    clustered.append(sum(bucket) / len(bucket))
    return clustered
