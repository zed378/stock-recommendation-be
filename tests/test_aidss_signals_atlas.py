"""The spot part of the owner's Math Atlas notes (slides 02/09 and 03/09): statistics checked
against an independent numpy implementation, the cascade gate by gate, and the OBV routing."""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import numpy as np
import pytest

from aidss.domain.types import Candle
from aidss_signals import atlas
from aidss_signals import h4 as h4mod

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def make(closes, highs=None, lows=None, vols=None) -> list[Candle]:
    out = []
    for i, c in enumerate(closes):
        hi = highs[i] if highs else c * 1.004
        lo = lows[i] if lows else c * 0.996
        v = vols[i] if vols else 100.0
        out.append(
            Candle(
                T0 + timedelta(hours=4 * i), D(str(c)), D(str(hi)), D(str(lo)), D(str(c)), D(str(v))
            )
        )
    return out


def ar_closes(n=300, phi=0.4, sigma=0.01, seed=1, start=100.0) -> list[float]:
    rng = random.Random(seed)
    r, price, out = 0.0, start, []
    for _ in range(n):
        r = phi * r + rng.gauss(0, sigma)
        price *= math.exp(r)
        out.append(price)
    return out


# --------------------------------------------------------------------------- statistics


def test_percentile_interpolates_linearly() -> None:
    assert atlas.percentile([1, 2, 3, 4], 0) == 1
    assert atlas.percentile([1, 2, 3, 4], 100) == 4
    assert atlas.percentile([1, 2, 3, 4], 50) == pytest.approx(2.5)
    assert atlas.percentile([4, 1, 3, 2], 30) == pytest.approx(np.percentile([1, 2, 3, 4], 30))
    assert atlas.percentile([7.0], 98) == 7.0
    with pytest.raises(ValueError):
        atlas.percentile([], 50)


def test_character_matches_an_independent_numpy_calculation() -> None:
    closes = ar_closes()
    candles = make(closes)
    ch = atlas.character(candles)
    assert ch is not None
    c = np.array(closes)
    h = np.array([float(x.high) for x in candles])
    lo = np.array([float(x.low) for x in candles])
    r = np.diff(np.log(c))
    tr = np.maximum.reduce([h[1:] - lo[1:], abs(h[1:] - c[:-1]), abs(lo[1:] - c[:-1])])
    atrp = np.mean(tr[-42:] / c[1:][-42:])
    assert ch.atrp == pytest.approx(atrp)
    w = r[-180:]
    assert ch.rho1 == pytest.approx(np.corrcoef(w[:-1], w[1:])[0, 1])
    rq = np.array([w[i : i + 6].sum() for i in range(len(w) - 5)])
    assert ch.vr == pytest.approx(rq.var(ddof=1) / (6 * w.var(ddof=1)))
    path = np.abs(np.diff(c[-43:])).sum()
    assert ch.er == pytest.approx(abs(c[-1] - c[-43]) / path)
    assert ch.z4 == pytest.approx(math.log(c[-1] / c[-2]) / atrp)
    assert ch.z24 == pytest.approx(math.log(c[-1] / c[-7]) / (atrp * math.sqrt(6)))
    vq = np.array([100.0]) * c[-42:]
    assert ch.amihud == pytest.approx(np.mean(np.abs(r[-42:]) / vq))
    assert ch.zero_rate == 0.0


def test_persistent_returns_have_positive_autocorrelation_and_a_variance_ratio_above_one() -> None:
    trending = atlas.character(make(ar_closes(phi=0.6, seed=3)))
    reverting = atlas.character(make(ar_closes(phi=-0.6, seed=3)))
    assert trending.rho1 > 0 and trending.vr > 1
    assert reverting.rho1 < 0 and reverting.vr < 1


def test_zero_volume_bars_are_counted_and_left_out_of_amihud() -> None:
    vols = [100.0] * 300
    for i in range(-42, 0, 6):
        vols[i] = 0.0
    ch = atlas.character(make(ar_closes(), vols=vols))
    assert ch.zero_rate == pytest.approx(7 / 42)
    assert ch.amihud is not None and ch.amihud > 0


def test_too_little_history_or_a_bad_price_gives_none() -> None:
    assert atlas.character(make(ar_closes(n=atlas.MIN_BARS - 1))) is None
    assert atlas.character(make(ar_closes(n=atlas.MIN_BARS))) is not None
    bad = ar_closes()
    bad[100] = 0.0
    assert atlas.character(make(bad, highs=[1.0] * 300, lows=[0.0] * 300)) is None
    flat = atlas.character(make([5.0] * 300))  # no movement: undefined statistics stay None
    assert flat is not None and flat.rho1 is None and flat.vr is None and flat.z4 == 0


# ----------------------------------------------------------------------------- cascade


def ch(atrp=0.02, amihud=1e-9, zero=0.0, rho=0.2, vr=1.2, z4=1.0, z24=1.0) -> atlas.Character:
    return atlas.Character(atrp, amihud, zero, rho, vr, 0.3, z4, z24)


def universe(n=30):
    """n coins that pass every gate, with distinct |z4| so the ranking is unambiguous."""
    chars = {f"C{i:02d}": ch(atrp=0.02 + i * 1e-4, z4=0.5 + i * 0.01, z24=0.4) for i in range(n)}
    vol = {s: 1e7 + i * 1e5 for i, s in enumerate(chars)}
    return chars, vol


def test_a_universe_smaller_than_the_minimum_returns_nothing_and_says_why() -> None:
    chars, vol = universe(atlas.MIN_UNIVERSE - 1)
    out = atlas.cascade(chars, vol, 10)
    assert out.picks == {} and all(
        v.startswith("UNIVERSE_TOO_SMALL") for v in out.rejected.values()
    )


def test_each_gate_rejects_for_its_own_reason() -> None:
    chars, vol = universe(30)
    chars["LOWATR"] = ch(atrp=0.001)
    chars["ILLIQ"] = ch(atrp=0.03, amihud=1.0)
    chars["NOAC"] = ch(atrp=0.03, rho=-0.1)
    chars["NOVR"] = ch(atrp=0.03, vr=0.9)
    chars["ZEROBARS"] = ch(atrp=0.03, zero=0.2)
    chars["NOVOL"] = ch(atrp=0.03)
    chars["NOAMI"] = atlas.Character(0.03, None, 0.0, 0.2, 1.2, 0.3, 1.0, 1.0)
    chars["HUGEZ"] = ch(atrp=0.03, z4=50.0)
    for s in ("LOWATR", "ILLIQ", "NOAC", "NOVR", "ZEROBARS", "NOAMI", "HUGEZ"):
        vol[s] = 2e7
    vol["NOVOL"] = 0.0
    out = atlas.cascade(chars, vol, 10)
    assert out.rejected["LOWATR"] == "LOW_ATRP" and out.rejected["ILLIQ"] == "ILLIQUID"
    assert out.rejected["NOAC"] == "NO_AUTOCORR" and out.rejected["NOVR"] == "NO_VARIANCE_RATIO"
    assert out.rejected["ZEROBARS"] == "ZERO_VOLUME_BARS" and out.rejected["NOVOL"] == "NO_VOLUME"
    assert out.rejected["NOAMI"] == "NO_AMIHUD" and out.rejected["HUGEZ"] == "EXTREME_Z"
    assert "HUGEZ" not in out.picks


def test_the_shortlist_keeps_the_k_strongest_with_the_price_direction() -> None:
    chars, vol = universe(30)
    chars["C05"] = ch(atrp=0.03, z4=-1.5, z24=-0.4)  # strongest move, falling
    chars["C06"] = ch(atrp=0.03, z4=1.4, z24=0.4)
    chars["OUT"] = ch(atrp=0.03, z4=9.0)  # beyond the 98th percentile: dropped, not ranked
    vol["OUT"] = 2e7
    vol["C05"] = vol["C06"] = 2e7
    out = atlas.cascade(chars, vol, 10)
    assert out.rejected["OUT"] == "EXTREME_Z"
    assert len(out.picks) == 10 and out.k == 10
    assert out.picks["C05"].rank == 1 and out.picks["C05"].direction == -1
    assert out.picks["C06"].rank == 2 and out.picks["C06"].direction == 1
    assert sorted(p.rank for p in out.picks.values()) == list(range(1, 11))
    assert any(v == "BEYOND_TOP_K" for v in out.rejected.values())
    assert atlas.cascade(chars, vol, 4).k == 4 and len(atlas.cascade(chars, vol, 4).picks) == 4


# ------------------------------------------------------------------------------ routing


def test_obv_slope_follows_volume_on_rising_and_falling_closes() -> None:
    up = make([100 + i for i in range(80)])
    down = make([200 - i for i in range(80)])
    assert atlas.obv_slope(up) > 0 and atlas.obv_slope(down) < 0
    assert atlas.obv_slope(make([100.0] * 80)) == 0
    assert atlas.obv_slope(up[:30]) is None


def test_ema_is_seeded_with_the_simple_average() -> None:
    assert atlas.ema_last([1.0] * 5) is None
    flat = [10.0] * 21
    assert atlas.ema_last(flat) == 10.0
    assert atlas.ema_last(flat + [32.0]) == pytest.approx(10 + (32 - 10) * 2 / 22)


def rising(n=120):
    return [100.0 * 1.003**i for i in range(n)]


def with_last(closes, last_close, high, low):
    cs = make(closes)
    cs[-1] = Candle(
        cs[-1].timestamp,
        D(str(closes[-2])),
        D(str(high)),
        D(str(low)),
        D(str(last_close)),
        D("100"),
    )
    return cs


def test_trend_following_enters_on_a_pullback_to_the_ema() -> None:
    closes = rising()
    x = closes[-1]
    for _ in range(8):  # the last close that sits on the EMA it helps to define
        x = atlas.ema_last(closes[:-1] + [x])
    cs = with_last(closes[:-1] + [x], x, closes[-2] * 1.001, x * 0.995)
    atr = 1.0
    pick = atlas.Pick("X", 1, 1, 1.0, 0.3, 1.3)
    r = atlas.route(cs, pick, atr)
    assert r is not None and (r.kind, r.side) == (atlas.TF, "LONG")
    assert r.extension_atr <= atlas.MAX_EXTENSION_ATR
    # an up close is not a pullback; far from the EMA is overextended; a falling-price pick with
    # a rising OBV is mean reversion instead and needs two down closes
    up_close = with_last(closes, closes[-1] * 1.01, closes[-1] * 1.02, closes[-1])
    assert atlas.route(up_close, pick, atr) is None
    far = with_last(
        closes[:-1] + [closes[-2] * 0.99], closes[-2] * 0.99, closes[-2], closes[-2] * 0.985
    )
    assert atlas.route(far, pick, 0.2) is None
    assert atlas.route(cs, pick, 0.0) is None


def test_mean_reversion_needs_two_closes_against_the_side() -> None:
    closes = rising()
    closes[-2] = closes[-3] * 0.998
    closes[-1] = closes[-2] * 0.998
    cs = make(closes)
    pick = atlas.Pick("X", 1, -1, -1.0, 0.3, 1.3)  # price falling while OBV is rising
    r = atlas.route(cs, pick, 1.0)
    assert r is not None and (r.kind, r.side) == (atlas.MR, "LONG")
    closes[-2] = closes[-3] * 1.002  # only the last close is down: no confirmation
    assert atlas.route(make(closes), pick, 1.0) is None


def test_a_flat_obv_is_rejected() -> None:
    flat = make([100.0] * 120)
    assert atlas.route(flat, atlas.Pick("X", 1, 1, 1.0, 0.3, 1.3), 1.0) is None


def test_the_score_is_a_bounded_rank_with_named_parts() -> None:
    pick = atlas.Pick("X", 1, 1, 1.0, 0.3, 1.5)
    best, parts = atlas.score(atlas.Route(atlas.TF, "LONG", 0.0, 100.0), pick, 10, True)
    assert best == 100 and parts == {"rank": 40.0, "persistence": 20.0, "timing": 20.0, "btc": 20.0}
    worst, _ = atlas.score(
        atlas.Route(atlas.TF, "LONG", 0.5, 100.0), atlas.Pick("Y", 10, 1, 1.0, 0.0, 1.0), 10, False
    )
    assert 0 <= worst <= 10


def test_detect_uses_the_atlas_route_only_when_the_strategy_is_chosen_and_a_pick_exists() -> None:
    closes = rising(260)
    x = closes[-1]
    for _ in range(8):
        x = atlas.ema_last(closes[:-1] + [x])
    cs = with_last(closes[:-1] + [x], x, closes[-2] * 1.001, x * 0.995)
    p = h4mod.H4Params(20, 20, 2.0, 1.5)
    pick = atlas.Pick("X", 1, 1, 1.0, 0.3, 1.3)
    on = h4mod.detect(cs, p, ("ATLAS",), "bullish", False, (pick, 10))
    assert on is not None and on.strategy == "ATLAS" and on.side == "LONG"
    assert on.components["btc"] == 20.0 and on.components["route_mr"] == 0.0
    assert h4mod.detect(cs, p, ("ATLAS",), "bullish", False, None) is None
    assert h4mod.detect(cs, p, ("DONCHIAN",), "bullish", False, (pick, 10)) is None
    assert h4mod.signal_id("ATLAS", "XUSDT", "LONG", on.candle_open).startswith("aidss4h-atlas-")
