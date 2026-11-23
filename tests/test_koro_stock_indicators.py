"""Unit tests for equity-applicable KORO Atlas indicators in src/aidss/indicators."""

from __future__ import annotations

import pandas as pd
import pytest

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


def _noisy_frame(n: int = 120, seed: int = 5) -> pd.DataFrame:
    import numpy as np

    rng = np.random.default_rng(seed)
    closes = 1000 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes * (1 + rng.uniform(0.001, 0.01, n)),
            "low": closes * (1 - rng.uniform(0.001, 0.01, n)),
            "close": closes,
            "volume": rng.uniform(50_000, 150_000, n),
        },
        index=idx,
    )


def test_stock_character_statistics_match_a_direct_calculation() -> None:
    import numpy as np

    f = _noisy_frame()
    c, h, lo, v = (f[k].to_numpy() for k in ("close", "high", "low", "volume"))
    n = 42
    tr = np.maximum.reduce([h[1:] - lo[1:], abs(h[1:] - c[:-1]), abs(lo[1:] - c[:-1])])
    expected_atrp = float(np.mean(tr[-n:] / c[1:][-n:]))
    atrp = compute(f, IndicatorSpec("atrp", {"period": n}))["value"]
    assert atrp.iloc[: n - 1].isna().all() and atrp.iloc[-1] == pytest.approx(expected_atrp)

    r = np.diff(np.log(c))
    ami = compute(f, IndicatorSpec("amihud", {"period": n}))["value"]
    assert ami.iloc[-1] == pytest.approx(float(np.mean(np.abs(r[-n:]) / (c[1:] * v[1:])[-n:])))

    er = compute(f, IndicatorSpec("efficiency_ratio", {"period": n}))["value"]
    assert er.iloc[-1] == pytest.approx(abs(c[-1] - c[-1 - n]) / np.abs(np.diff(c[-n - 1 :])).sum())

    z1 = compute(f, IndicatorSpec("return_zscore", {"horizon": 1, "atrp_period": n}))["value"]
    assert z1.iloc[-1] == pytest.approx(float(np.log(c[-1] / c[-2])) / expected_atrp)
    z5 = compute(f, IndicatorSpec("return_zscore", {"horizon": 5, "atrp_period": n}))["value"]
    assert z5.iloc[-1] == pytest.approx(float(np.log(c[-1] / c[-6])) / (expected_atrp * 5**0.5))


def test_zero_volume_bars_are_counted_and_do_not_enter_amihud() -> None:
    f = _noisy_frame()
    f.iloc[-10:-5, f.columns.get_loc("volume")] = 0.0
    rate = compute(f, IndicatorSpec("zero_volume_rate", {"period": 42}))["value"]
    assert rate.iloc[-1] == pytest.approx(5 / 42)
    ami = compute(f, IndicatorSpec("amihud", {"period": 42}))["value"]
    assert ami.iloc[-1] > 0 and not pd.isna(ami.iloc[-1])


def test_character_statistics_reject_bad_arguments_and_short_history() -> None:
    f = _noisy_frame(30)
    assert compute(f, IndicatorSpec("atrp", {"period": 42}))["value"].isna().all()
    with pytest.raises(ValueError):
        core.return_zscore(f["high"], f["low"], f["close"], horizon=0)
    with pytest.raises(ValueError):
        core.atrp(f["high"], f["low"], f["close"], period=0)
