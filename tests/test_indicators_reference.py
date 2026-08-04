"""Cross-check every indicator against the naive reference implementations.

Phase 3's stated risk is "a formula error slips through for lack of adequate
tests" (Section 15). This module is the mitigation.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from aidss.indicators import core
from aidss.indicators.engine import candles_to_frame
from tests import reference as ref

TOLERANCE = 1e-9


@pytest.fixture
def frame(candles) -> pd.DataFrame:
    return candles_to_frame(candles)


def assert_matches(actual: pd.Series, expected: list[float | None], label: str) -> None:
    """Compare element by element, treating NaN and None as the same 'no value'."""
    values = actual.tolist()
    assert len(values) == len(expected), f"{label}: length mismatch"
    for i, (got, want) in enumerate(zip(values, expected, strict=True)):
        got_missing = got is None or (isinstance(got, float) and math.isnan(got))
        if want is None:
            assert got_missing, f"{label}[{i}]: expected no value, got {got}"
            continue
        assert not got_missing, f"{label}[{i}]: expected {want}, got no value"
        assert got == pytest.approx(want, abs=TOLERANCE), f"{label}[{i}]"


@pytest.mark.parametrize("period", [5, 20, 50])
def test_sma_matches_reference(frame: pd.DataFrame, period: int) -> None:
    closes = frame["close"].tolist()
    assert_matches(core.sma(frame["close"], period), ref.naive_sma(closes, period), "sma")


@pytest.mark.parametrize("period", [5, 12, 26])
def test_ema_matches_reference(frame: pd.DataFrame, period: int) -> None:
    closes = frame["close"].tolist()
    assert_matches(core.ema(frame["close"], period), ref.naive_ema(closes, period), "ema")


@pytest.mark.parametrize("period", [7, 14, 21])
def test_rsi_matches_reference(frame: pd.DataFrame, period: int) -> None:
    closes = frame["close"].tolist()
    assert_matches(core.rsi(frame["close"], period), ref.naive_rsi(closes, period), "rsi")


def test_macd_matches_reference(frame: pd.DataFrame) -> None:
    closes = frame["close"].tolist()
    result = core.macd(frame["close"], 12, 26, 9)

    fast = ref.naive_ema(closes, 12)
    slow = ref.naive_ema(closes, 26)
    macd_line = [
        None if (f is None or s is None) else f - s for f, s in zip(fast, slow, strict=True)
    ]
    assert_matches(result["macd"], macd_line, "macd")

    # The signal line is an EMA over the MACD line's non-null tail.
    compact = [v for v in macd_line if v is not None]
    signal_compact = ref.naive_ema(compact, 9)
    first = next(i for i, v in enumerate(macd_line) if v is not None)
    signal = [None] * first + signal_compact
    assert_matches(result["signal"], signal, "macd.signal")


@pytest.mark.parametrize("period", [10, 14])
def test_atr_matches_reference(frame: pd.DataFrame, period: int) -> None:
    expected = ref.naive_atr(
        frame["high"].tolist(), frame["low"].tolist(), frame["close"].tolist(), period
    )
    actual = core.atr(frame["high"], frame["low"], frame["close"], period)
    assert_matches(actual, expected, "atr")


def test_true_range_matches_reference(frame: pd.DataFrame) -> None:
    expected = ref.naive_true_range(
        frame["high"].tolist(), frame["low"].tolist(), frame["close"].tolist()
    )
    assert_matches(core.true_range(frame["high"], frame["low"], frame["close"]), expected, "tr")


@pytest.mark.parametrize("period", [14])
def test_adx_matches_reference(frame: pd.DataFrame, period: int) -> None:
    expected = ref.naive_adx(
        frame["high"].tolist(), frame["low"].tolist(), frame["close"].tolist(), period
    )
    actual = core.adx(frame["high"], frame["low"], frame["close"], period)
    for column in ("plus_di", "minus_di", "dx", "adx"):
        assert_matches(actual[column], expected[column], f"adx.{column}")


def test_bollinger_matches_reference(frame: pd.DataFrame) -> None:
    expected = ref.naive_bollinger(frame["close"].tolist(), 20, 2.0)
    actual = core.bollinger_bands(frame["close"], 20, 2.0)
    for column in ("middle", "upper", "lower"):
        assert_matches(actual[column], expected[column], f"bollinger.{column}")


def test_obv_matches_reference(frame: pd.DataFrame) -> None:
    expected = ref.naive_obv(frame["close"].tolist(), frame["volume"].tolist())
    assert_matches(core.obv(frame["close"], frame["volume"]), expected, "obv")


def test_stochastic_k_matches_reference(frame: pd.DataFrame) -> None:
    expected = ref.naive_stochastic(
        frame["high"].tolist(), frame["low"].tolist(), frame["close"].tolist(), 14
    )
    actual = core.stochastic(frame["high"], frame["low"], frame["close"], 14, 3)
    assert_matches(actual["k"], expected, "stochastic.k")


def test_wilder_smoothing_matches_reference(frame: pd.DataFrame) -> None:
    values = frame["close"].tolist()
    assert_matches(core.wilder_smooth(frame["close"], 14), ref.naive_wilder(values, 14), "wilder")
