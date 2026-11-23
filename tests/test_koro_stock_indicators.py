"""Unit tests for equity-applicable KORO Atlas indicators in src/aidss/indicators."""

from __future__ import annotations

import pandas as pd

from aidss.indicators import core
from aidss.indicators.engine import IndicatorSpec, compute


def _sample_frame(n: int = 80) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")
    closes = [1000.0 + float(i * i) * 0.25 for i in range(1, n + 1)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 15.0 for c in closes],
            "low": [c - 15.0 for c in closes],
            "close": closes,
            "volume": [100_000.0] * n,
        },
        index=idx,
    )


def test_stock_obv_regression_slope_and_persistence_indicators() -> None:
    frame = _sample_frame(80)
    slope = compute(frame, IndicatorSpec("obv_slope", {"period": 48}))["value"]
    assert slope.iloc[:47].isna().all()
    assert slope.iloc[-1] > 0

    rho1 = compute(frame, IndicatorSpec("lag1_autocorr", {"window": 60}))["value"]
    assert rho1.iloc[-1] > 0

    vr = compute(frame, IndicatorSpec("variance_ratio", {"window": 60, "horizon": 6}))["value"]
    assert vr.iloc[-1] > 1


def test_stock_ema_atr_pullback_flags_touch_within_half_atr() -> None:
    frame = _sample_frame(60)
    ema21 = core.ema(frame["close"], 21).iloc[-1]
    # Append a pullback day that touches EMA21 within 0.5 ATR.
    next_day = frame.index[-1] + pd.Timedelta(days=1)
    frame.loc[next_day] = {
        "open": frame["close"].iloc[-1],
        "high": frame["close"].iloc[-1],
        "low": ema21 - 2.0,
        "close": ema21 + 2.0,
        "volume": 90_000.0,
    }
    res = compute(
        frame,
        IndicatorSpec(
            "ema_atr_pullback", {"ema_period": 21, "atr_period": 14, "max_extension_atr": 0.5}
        ),
    )
    assert res["extension_atr"].iloc[-1] <= 0.5
    assert res["pullback_eligible"].iloc[-1] == 1.0
