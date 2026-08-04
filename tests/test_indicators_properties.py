"""Analytic properties that must hold regardless of implementation.

Agreement with a reference implementation proves the two agree; these cases
prove they agree on the *right* answer, using inputs whose result is known
from the definition alone.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from aidss.indicators import core


def series(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


# --- Moving averages -------------------------------------------------------


def test_sma_of_constant_series_is_that_constant() -> None:
    result = core.sma(series([7.0] * 30), 10)
    assert result.iloc[9:].eq(7.0).all()
    assert result.iloc[:9].isna().all()


def test_sma_warmup_length_equals_period_minus_one() -> None:
    result = core.sma(series(list(range(50))), 14)
    assert result.isna().sum() == 13


def test_ema_of_constant_series_is_that_constant() -> None:
    result = core.ema(series([3.5] * 40), 12)
    assert result.iloc[11:].round(12).eq(3.5).all()


def test_ema_reacts_faster_than_sma_to_a_step_change() -> None:
    values = [100.0] * 30 + [200.0] * 5
    ema_last = core.ema(series(values), 10).iloc[-1]
    sma_last = core.sma(series(values), 10).iloc[-1]
    assert ema_last > sma_last


def test_shorter_period_ema_is_closer_to_the_latest_price() -> None:
    values = [100.0] * 30 + [150.0] * 3
    fast = core.ema(series(values), 5).iloc[-1]
    slow = core.ema(series(values), 20).iloc[-1]
    assert abs(fast - 150.0) < abs(slow - 150.0)


def test_series_shorter_than_period_yields_all_nan() -> None:
    assert core.ema(series([1.0, 2.0, 3.0]), 10).isna().all()
    assert core.sma(series([1.0, 2.0, 3.0]), 10).isna().all()


# --- RSI -------------------------------------------------------------------


def test_rsi_of_a_strictly_rising_series_is_100() -> None:
    result = core.rsi(series([float(i) for i in range(1, 40)]), 14)
    assert result.dropna().eq(100.0).all()


def test_rsi_of_a_strictly_falling_series_is_0() -> None:
    result = core.rsi(series([float(i) for i in range(40, 1, -1)]), 14)
    assert result.dropna().eq(0.0).all()


def test_rsi_stays_within_bounds(candles) -> None:
    closes = pd.Series([float(c.close) for c in candles])
    values = core.rsi(closes, 14).dropna()
    assert not values.empty
    assert values.between(0.0, 100.0).all()


def test_rsi_of_a_flat_series_is_neutral() -> None:
    # No gains and no losses: the ratio is undefined, so 50 is reported rather
    # than an arbitrary extreme.
    result = core.rsi(series([50.0] * 30), 14)
    assert result.dropna().eq(50.0).all()


# --- MACD ------------------------------------------------------------------


def test_macd_line_equals_fast_ema_minus_slow_ema(candles) -> None:
    closes = pd.Series([float(c.close) for c in candles])
    result = core.macd(closes, 12, 26, 9)
    expected = core.ema(closes, 12) - core.ema(closes, 26)
    pd.testing.assert_series_equal(
        result["macd"], expected, check_names=False, rtol=0, atol=1e-12
    )


def test_macd_histogram_equals_line_minus_signal(candles) -> None:
    closes = pd.Series([float(c.close) for c in candles])
    result = core.macd(closes)
    computed = (result["macd"] - result["signal"]).dropna()
    pd.testing.assert_series_equal(
        result["histogram"].dropna(), computed, check_names=False, rtol=0, atol=1e-12
    )


def test_macd_rejects_fast_period_not_smaller_than_slow() -> None:
    with pytest.raises(ValueError, match="fast"):
        core.macd(series([1.0] * 50), fast=26, slow=12)


# --- Bollinger -------------------------------------------------------------


def test_bollinger_middle_band_is_the_sma(candles) -> None:
    closes = pd.Series([float(c.close) for c in candles])
    bands = core.bollinger_bands(closes, 20, 2.0)
    pd.testing.assert_series_equal(
        bands["middle"], core.sma(closes, 20), check_names=False, rtol=0, atol=1e-12
    )


def test_bollinger_bands_collapse_onto_the_mean_when_price_is_flat() -> None:
    bands = core.bollinger_bands(series([10.0] * 30), 20, 2.0)
    last = bands.iloc[-1]
    assert last["upper"] == pytest.approx(10.0)
    assert last["lower"] == pytest.approx(10.0)


def test_bollinger_bands_are_symmetric_about_the_middle(candles) -> None:
    closes = pd.Series([float(c.close) for c in candles])
    bands = core.bollinger_bands(closes, 20, 2.0).dropna()
    upper_gap = bands["upper"] - bands["middle"]
    lower_gap = bands["middle"] - bands["lower"]
    assert np.allclose(upper_gap.to_numpy(), lower_gap.to_numpy(), atol=1e-12)


# --- ATR / ADX -------------------------------------------------------------


def test_true_range_is_never_negative(candles) -> None:
    high = pd.Series([float(c.high) for c in candles])
    low = pd.Series([float(c.low) for c in candles])
    close = pd.Series([float(c.close) for c in candles])
    assert (core.true_range(high, low, close) >= 0).all()


def test_atr_of_constant_bars_equals_the_bar_range() -> None:
    high = series([110.0] * 30)
    low = series([100.0] * 30)
    close = series([105.0] * 30)
    assert core.atr(high, low, close, 14).dropna().round(9).eq(10.0).all()


def test_adx_and_di_stay_within_bounds(candles) -> None:
    high = pd.Series([float(c.high) for c in candles])
    low = pd.Series([float(c.low) for c in candles])
    close = pd.Series([float(c.close) for c in candles])
    result = core.adx(high, low, close, 14)
    for column in ("adx", "plus_di", "minus_di", "dx"):
        values = result[column].dropna()
        assert not values.empty, f"{column} produced no values"
        assert values.between(0.0, 100.0).all(), f"{column} out of range"


def test_plus_di_dominates_in_a_clean_uptrend() -> None:
    high = series([100.0 + i for i in range(60)])
    low = series([98.0 + i for i in range(60)])
    close = series([99.0 + i for i in range(60)])
    result = core.adx(high, low, close, 14).dropna()
    assert (result["plus_di"] > result["minus_di"]).all()


# --- Structure -------------------------------------------------------------


def test_pivot_detection_finds_the_obvious_peak_and_trough() -> None:
    high = series([1, 2, 3, 10, 3, 2, 1, 2, 3, 4])
    low = series([1, 2, 3, 4, 3, 2, 0.5, 2, 3, 4])
    pivots = core.pivot_points(high, low, left=3, right=3)
    assert bool(pivots["swing_high"].iloc[3])
    assert bool(pivots["swing_low"].iloc[6])
    assert pivots["swing_high"].sum() == 1


def test_breakout_window_excludes_the_current_bar() -> None:
    # Close pushes above every one of the prior 20 highs.
    high = series([100.0] * 20 + [120.0])
    low = series([90.0] * 21)
    close = series([95.0] * 20 + [119.0])
    result = core.detect_breakout(high, low, close, lookback=20)
    assert result["direction"] == "bullish"
    assert result["level"] == pytest.approx(100.0)


def test_no_breakout_reported_inside_the_prior_range() -> None:
    high = series([100.0] * 21)
    low = series([90.0] * 21)
    close = series([95.0] * 21)
    assert core.detect_breakout(high, low, close, 20)["direction"] == "none"


def test_market_structure_reads_an_uptrend() -> None:
    high = series([10, 12, 11, 9, 14, 13, 12, 11, 18, 15, 14, 13])
    low = series([8, 9, 8, 5, 11, 10, 9, 8, 15, 12, 11, 10])
    assert core.market_structure(high, low, left=2, right=2) == "uptrend"


def test_support_levels_sit_below_price_and_resistance_above(candles) -> None:
    high = pd.Series([float(c.high) for c in candles])
    low = pd.Series([float(c.low) for c in candles])
    close = pd.Series([float(c.close) for c in candles])
    levels = core.support_resistance(high, low, close)
    last = float(close.iloc[-1])
    assert all(level < last for level in levels["support"])
    assert all(level > last for level in levels["resistance"])


# --- Volatility & volume ---------------------------------------------------


def test_volatility_of_a_flat_series_is_zero() -> None:
    assert core.rolling_volatility(series([100.0] * 40), 20).dropna().round(12).eq(0.0).all()


def test_obv_rises_when_price_rises() -> None:
    close = series([1.0, 2.0, 3.0, 4.0])
    volume = series([10.0, 10.0, 10.0, 10.0])
    assert core.obv(close, volume).tolist() == [0.0, 10.0, 20.0, 30.0]


def test_volume_ratio_is_one_when_volume_matches_its_average() -> None:
    assert core.volume_ratio(series([500.0] * 30), 20).dropna().round(12).eq(1.0).all()


# --- Guard rails -----------------------------------------------------------


@pytest.mark.parametrize("bad_period", [0, -1, 2.5])
def test_invalid_periods_are_rejected(bad_period) -> None:
    with pytest.raises(ValueError):
        core.sma(series([1.0, 2.0, 3.0]), bad_period)


def test_empty_input_does_not_raise() -> None:
    empty = pd.Series(dtype=float)
    assert core.true_range(empty, empty, empty).empty
    assert core.sma(empty, 5).empty


def test_ichimoku_leading_spans_are_shifted_forward() -> None:
    high = series([float(100 + i) for i in range(120)])
    low = series([float(90 + i) for i in range(120)])
    close = series([float(95 + i) for i in range(120)])
    result = core.ichimoku(high, low, close, 9, 26, 52)
    # Both leading spans are displaced 26 bars ahead, so the first 26+ entries
    # cannot have a value.
    assert result["senkou_span_a"].iloc[:26].isna().all()
    assert not math.isnan(result["senkou_span_a"].iloc[-1])
    # The lagging span is pushed back, so the last 26 entries are empty.
    assert result["chikou_span"].iloc[-26:].isna().all()
