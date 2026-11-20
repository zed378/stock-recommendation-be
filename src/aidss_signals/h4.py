"""4-hour breakout signals: a Donchian breakout and a volume spike, scored and priced (ADR-067).

A prototype of the kind of rule-based signal a paid service pushes to followers, built from public
ideas with our own code and parameters. It claims nothing about profit: every signal it makes is
tracked to a simulated outcome (`lifecycle.py`) so the score can be tested against results instead
of believed.

Pure functions of closed 4H candles. Prices are floats here on purpose (indicator maths); the
database keeps them as decimals. Nothing in this module touches a network or a database.

The score is a transparent additive heuristic from 0 to 100, **a ranking and not a probability**:

    breakout distance in ATR   0 to 30    how far the close cleared the level it broke
    volume against its average 0 to 25    1x average scores 0, 3x or more scores the maximum
    candle range against ATR   0 to 15    1x ATR scores 0, 2.5x or more scores the maximum
    close near the extreme     0 to 10    close in the outer tenth of the candle scores the maximum
    BTC 4H trend aligned       0 or 20    with the side (bullish for LONG, bearish for SHORT); an
                                          unknown or opposed trend scores 0
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from aidss.domain.types import Candle

DONCHIAN = "DONCHIAN"
SPIKE = "SPIKE"
STRATEGIES = (DONCHIAN, SPIKE)
ATR_PERIOD = 14  # a fixed convention, not a tuned number
EXTREME_SHARE = 0.30  # the spike candle must close in the outer 30% of its range
H4 = timedelta(hours=4)


@dataclass(frozen=True, slots=True)
class H4Params:
    donchian_n: int
    vol_period: int
    vol_mult: float
    range_mult: float


@dataclass(frozen=True, slots=True)
class Setup:
    strategy: str
    side: str  # LONG | SHORT
    candle_open: datetime
    entry: float  # the signal candle's close
    atr: float
    score: int
    components: dict[str, float] = field(default_factory=dict)
    reference: float = 0.0  # the level broken (Donchian) or the candle's far edge (spike)


def min_history(p: H4Params) -> int:
    return max(p.donchian_n, p.vol_period, ATR_PERIOD) + 2


def _f(c: Candle) -> tuple[float, float, float, float, float]:
    return float(c.open), float(c.high), float(c.low), float(c.close), float(c.volume)


def atr_series(candles: Sequence[Candle], period: int = ATR_PERIOD) -> list[float | None]:
    """Wilder's ATR. None until `period` true ranges exist."""
    out: list[float | None] = [None] * len(candles)
    if len(candles) < period + 1:
        return out
    trs = []
    for prev, cur in zip(candles, candles[1:], strict=False):
        _, h, low, _, _ = _f(cur)
        pc = float(prev.close)
        trs.append(max(h - low, abs(h - pc), abs(low - pc)))
    current = sum(trs[:period]) / period
    out[period] = current
    for i in range(period, len(trs)):
        current = (current * (period - 1) + trs[i]) / period
        out[i + 1] = current
    return out


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _score(
    breakout_atr: float, vol_ratio: float, range_ratio: float, extreme: float, aligned: bool
) -> tuple[int, dict[str, float]]:
    parts = {
        "breakout": 30.0 * _clip(breakout_atr / 1.0, 0.0, 1.0),
        "volume": 25.0 * _clip((vol_ratio - 1.0) / 2.0, 0.0, 1.0),
        "range": 15.0 * _clip((range_ratio - 1.0) / 1.5, 0.0, 1.0),
        "extreme": 10.0 * _clip((1.0 - extreme) / 0.9, 0.0, 1.0),
        "btc": 20.0 if aligned else 0.0,
    }
    return int(round(_clip(sum(parts.values()), 0.0, 100.0))), {
        k: round(v, 2) for k, v in parts.items()
    }


def _aligned(side: str, btc_bias: str) -> bool:
    return (side == "LONG" and btc_bias == "bullish") or (side == "SHORT" and btc_bias == "bearish")


def detect(
    candles: Sequence[Candle],
    p: H4Params,
    strategies: Sequence[str],
    btc_bias: str,
    allow_short: bool,
) -> Setup | None:
    """The best setup on the LAST candle, or None.

    At most one per coin and candle, so a follower never gets two signals for the same entry
    (Donchian and spike on the same bar: the higher score wins)."""
    if len(candles) < min_history(p):
        return None
    atrs = atr_series(candles)
    atr_now, atr_before = atrs[-1], atrs[-2]
    if atr_now is None or atr_before is None or atr_now <= 0 or atr_before <= 0:
        return None
    o, h, low, c, v = _f(candles[-1])
    span = h - low
    if span <= 0:
        return None
    prior = candles[:-1]
    found: list[Setup] = []

    def setup(strategy: str, side: str, reference: float, breakout: float) -> None:
        vols = [float(x.volume) for x in prior[-p.vol_period :]]
        avg = sum(vols) / len(vols)
        vol_ratio = v / avg if avg > 0 else 0.0
        far = (h - c) / span if side == "LONG" else (c - low) / span
        score, parts = _score(
            breakout / atr_before, vol_ratio, span / atr_before, far, _aligned(side, btc_bias)
        )
        found.append(
            Setup(strategy, side, candles[-1].timestamp, c, atr_now, score, parts, reference)
        )

    if DONCHIAN in strategies:
        window = prior[-p.donchian_n :]
        top = max(float(x.high) for x in window)
        bottom = min(float(x.low) for x in window)
        if c > top:
            setup(DONCHIAN, "LONG", top, c - top)
        elif allow_short and c < bottom:
            setup(DONCHIAN, "SHORT", bottom, bottom - c)

    if SPIKE in strategies:
        vols = [float(x.volume) for x in prior[-p.vol_period :]]
        avg = sum(vols) / len(vols)
        if avg > 0 and v >= p.vol_mult * avg and span >= p.range_mult * atr_before:
            if c > o and (h - c) / span <= EXTREME_SHARE:
                setup(SPIKE, "LONG", low, c - o)
            elif allow_short and c < o and (c - low) / span <= EXTREME_SHARE:
                setup(SPIKE, "SHORT", h, o - c)

    if not found:
        return None
    return max(found, key=lambda s: (s.score, s.strategy == DONCHIAN))


def levels(
    side: str, entry: float, atr: float, stop_multiple: float, tp_r: Sequence[float]
) -> dict[str, float] | None:
    """Stop at a multiple of ATR against the trade, three targets at multiples of that distance."""
    if atr <= 0 or entry <= 0 or stop_multiple <= 0:
        return None
    risk = stop_multiple * atr
    sign = 1.0 if side == "LONG" else -1.0
    stop = entry - sign * risk
    if stop <= 0:
        return None
    px = lambda x: float(f"{x:.10g}")  # noqa: E731
    return {
        "entry": px(entry),
        "stop": px(stop),
        "tp1": px(entry + sign * tp_r[0] * risk),
        "tp2": px(entry + sign * tp_r[1] * risk),
        "tp3": px(entry + sign * tp_r[2] * risk),
        "risk": px(risk),
    }


def signal_id(strategy: str, symbol: str, side: str, candle_open: datetime) -> str:
    """Deterministic: the same candle, coin, side and strategy always give the same id, so a
    restart, a rescan or a replay can never publish or store a second copy (ADR-067)."""
    return f"aidss4h-{strategy.lower()}-{symbol}-{side.lower()}-{int(candle_open.timestamp())}"
