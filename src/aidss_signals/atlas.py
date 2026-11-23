"""The spot-applicable part of the owner's KORO / Math Atlas notes (slides 02/09 and 03/09).

Pure functions of closed 4H candles; no network, no database, no order. Prices are floats here
on purpose (statistics); the database keeps decimals.

What is taken from the slides, and how:

* 02/09 **character statistics** per coin from the last N=42 4H candles (7 days) and W=180 (30
  days): relative range (ATRP), Amihud illiquidity, zero-volume rate, lag-1 autocorrelation,
  variance ratio at q=6, efficiency ratio, and the 4H and 24H z-scores.
* 02/09 **cascade across the universe**: ATRP and 24H volume at or above their 30th percentile,
  Amihud at or below its 70th, positive autocorrelation, variance ratio above 1, then |z4| and
  |z24| at or below their 98th percentile (computed after the persistence gates), keep the K
  strongest by |z4|, K = min(10, universe size).
* 03/09 **routing**: the sign of the OBV regression slope over 48 observations is the side;
  price and OBV moving the same way route to trend following (TF), opposite ways to mean
  reversion (MR). TF enters on an EMA21 pullback within 0.5 ATR14 of it; MR enters after two
  consecutive closes against the side.

What is deliberately **not** taken:

* The open-interest and funding flow gate, the previous-rank condition of the MR confirmation,
  margin, leverage and anything that needs a futures venue. Public spot data has neither.
* The slides run OBV on 5-minute bars and quote volume from the venue. Here every statistic uses
  4H candles (the cadence of our signals), and the per-bar quote volume is approximated as
  base volume times close. The numbers are therefore close to, not equal to, the slides'.

Percentile gates only mean something across many coins. With fewer than `MIN_UNIVERSE` coins the
cascade returns nothing and says why, instead of pretending that the 70th percentile of five
coins is a threshold.

None of this predicts a price. A coin that passes is one whose recent behaviour satisfies stated
conditions, nothing more.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from aidss.domain.types import Candle

N_CHAR = 42
W = 180
Q = 6
K_MAX = 10
OBV_PERIOD = 48
EMA_PERIOD = 21
MAX_EXTENSION_ATR = 0.5
ZERO_RATE_MAX = 0.10
P_ATRP_MIN, P_V24_MIN, P_AMIHUD_MAX, P_Z_MAX = 30.0, 30.0, 70.0, 98.0
#: Our own safeguard, not from the slides (see the module docstring).
MIN_UNIVERSE = 20
MIN_BARS = W + 2

TF, MR = "TF", "MR"


@dataclass(frozen=True, slots=True)
class Character:
    atrp: float
    amihud: float | None
    zero_rate: float
    rho1: float | None
    vr: float | None
    er: float | None
    z4: float
    z24: float


@dataclass(frozen=True, slots=True)
class Pick:
    """A coin that passed the cascade."""

    symbol: str
    rank: int  # 1 is the strongest |z4|
    direction: int  # +1 price rising, -1 price falling (sign of z4)
    z4: float
    rho1: float
    vr: float


@dataclass(slots=True)
class Shortlist:
    picks: dict[str, Pick]
    rejected: dict[str, str]
    k: int


# ------------------------------------------------------------------------------ statistics


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _var_sample(xs: Sequence[float]) -> float:
    m = _mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    mx, my = _mean(xs), _mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / (sx * sy)


def character(candles: Sequence[Candle]) -> Character | None:
    """The 02/09 statistics for the LAST candle, or None when there is too little history or the
    data cannot support them (a non-positive price)."""
    if len(candles) < MIN_BARS:
        return None
    c = [float(x.close) for x in candles]
    h = [float(x.high) for x in candles]
    lo = [float(x.low) for x in candles]
    v = [float(x.volume) for x in candles]
    if min(c) <= 0:
        return None
    r = [math.log(c[i] / c[i - 1]) for i in range(1, len(c))]
    tr = [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, len(c))]
    last_tr, last_c, last_r = tr[-N_CHAR:], c[-N_CHAR:], r[-N_CHAR:]
    atrp = _mean([t / p for t, p in zip(last_tr, last_c, strict=True)])
    if atrp <= 0:
        return None
    vq = [vol * px for vol, px in zip(v[-N_CHAR:], last_c, strict=True)]
    positive = [(abs(rr), q) for rr, q in zip(last_r, vq, strict=True) if q > 0]
    amihud = _mean([a / q for a, q in positive]) if positive else None
    zero_rate = sum(1 for q in vq if q == 0) / N_CHAR

    window = r[-W:]
    rho1 = _pearson(window[:-1], window[1:])
    vr = None
    if _var_sample(window) > 0:
        rq = [sum(window[i : i + Q]) for i in range(len(window) - Q + 1)]
        denom = Q * _var_sample(window)
        vr = _var_sample(rq) / denom if denom > 0 else None
    path = sum(abs(c[i] - c[i - 1]) for i in range(len(c) - N_CHAR, len(c)))
    er = abs(c[-1] - c[-1 - N_CHAR]) / path if path > 0 else None
    z4 = math.log(c[-1] / c[-2]) / atrp
    z24 = math.log(c[-1] / c[-1 - Q]) / (atrp * math.sqrt(Q))
    return Character(atrp, amihud, zero_rate, rho1, vr, er, z4, z24)


def percentile(values: Sequence[float], p: float) -> float:
    """Linear interpolation between order statistics (the usual definition)."""
    xs = sorted(values)
    if not xs:
        raise ValueError("no values")
    pos = (len(xs) - 1) * p / 100.0
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


# ------------------------------------------------------------------------------- cascade


def cascade(
    chars: Mapping[str, Character], quote_volume_24h: Mapping[str, float], universe_top_n: int
) -> Shortlist:
    """Apply the 02/09 gates across the universe. `rejected` names the first gate a coin failed."""
    k = min(K_MAX, universe_top_n)
    rejected: dict[str, str] = {}
    live: dict[str, Character] = {}
    for sym, ch in chars.items():
        vol = quote_volume_24h.get(sym, 0.0)
        if vol <= 0:
            rejected[sym] = "NO_VOLUME"
        elif ch.zero_rate > ZERO_RATE_MAX:
            rejected[sym] = "ZERO_VOLUME_BARS"
        elif ch.amihud is None:
            rejected[sym] = "NO_AMIHUD"
        else:
            live[sym] = ch
    if len(live) < MIN_UNIVERSE:
        for sym in live:
            rejected[sym] = f"UNIVERSE_TOO_SMALL:{len(live)}<{MIN_UNIVERSE}"
        return Shortlist({}, rejected, k)

    p_atrp = percentile([c.atrp for c in live.values()], P_ATRP_MIN)
    p_vol = percentile([quote_volume_24h[s] for s in live], P_V24_MIN)
    p_ami = percentile([c.amihud for c in live.values() if c.amihud is not None], P_AMIHUD_MAX)
    persistent: dict[str, Character] = {}
    for sym, ch in live.items():
        if ch.atrp < p_atrp:
            rejected[sym] = "LOW_ATRP"
        elif quote_volume_24h[sym] < p_vol:
            rejected[sym] = "LOW_V24"
        elif ch.amihud is not None and ch.amihud > p_ami:
            rejected[sym] = "ILLIQUID"
        elif ch.rho1 is None or ch.rho1 <= 0:
            rejected[sym] = "NO_AUTOCORR"
        elif ch.vr is None or ch.vr <= 1:
            rejected[sym] = "NO_VARIANCE_RATIO"
        else:
            persistent[sym] = ch
    if not persistent:
        return Shortlist({}, rejected, k)

    # The z caps are percentiles over the coins that passed the persistence gates (02/09 #06).
    cap4 = percentile([abs(c.z4) for c in persistent.values()], P_Z_MAX)
    cap24 = percentile([abs(c.z24) for c in persistent.values()], P_Z_MAX)
    survivors: list[tuple[str, Character]] = []
    for sym, ch in persistent.items():
        if abs(ch.z4) > cap4 or abs(ch.z24) > cap24:
            rejected[sym] = "EXTREME_Z"
        elif ch.z4 == 0:
            rejected[sym] = "NO_DIRECTION"
        else:
            survivors.append((sym, ch))
    survivors.sort(key=lambda t: (-abs(t[1].z4), t[0]))
    picks: dict[str, Pick] = {}
    for rank, (sym, ch) in enumerate(survivors, start=1):
        if rank > k:
            rejected[sym] = "BEYOND_TOP_K"
            continue
        assert ch.rho1 is not None and ch.vr is not None
        picks[sym] = Pick(sym, rank, 1 if ch.z4 > 0 else -1, ch.z4, ch.rho1, ch.vr)
    return Shortlist(picks, rejected, k)


# -------------------------------------------------------------------------------- routing


def obv_slope(candles: Sequence[Candle], period: int = OBV_PERIOD) -> float | None:
    """OLS slope of OBV over the last `period` observations (03/09 #01). OBV starts at 0 at the
    first candle given and adds the base volume signed by the close change."""
    if len(candles) < period + 1:
        return None
    obv, series = 0.0, [0.0]
    for prev, cur in zip(candles, candles[1:], strict=False):
        d = float(cur.close) - float(prev.close)
        obv += (1 if d > 0 else -1 if d < 0 else 0) * float(cur.volume)
        series.append(obv)
    ys = series[-period:]
    mean_y = _mean(ys)
    center = (period - 1) / 2
    den = sum((j - center) ** 2 for j in range(period))
    return sum((j - center) * (y - mean_y) for j, y in enumerate(ys)) / den


def ema_last(values: Sequence[float], period: int = EMA_PERIOD) -> float | None:
    """EMA with alpha 2/(period+1), seeded with the simple average of the first `period` values."""
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1)
    cur = _mean(values[:period])
    for x in values[period:]:
        cur = x * alpha + cur * (1 - alpha)
    return cur


@dataclass(frozen=True, slots=True)
class Route:
    kind: str  # TF | MR
    side: str  # LONG | SHORT
    extension_atr: float  # TF: distance from the EMA in ATR; MR: size of the two-bar move in ATR
    reference: float  # TF: the EMA; MR: the previous close


def route(candles: Sequence[Candle], pick: Pick, atr_now: float) -> Route | None:
    """The entry on the LAST candle for a shortlisted coin, or None (03/09 #04 to #06)."""
    if atr_now <= 0 or len(candles) < OBV_PERIOD + 2:
        return None
    slope = obv_slope(candles)
    if slope is None or slope == 0:
        return None  # OBV flat or invalid is rejected
    s = 1 if slope > 0 else -1
    side = "LONG" if s > 0 else "SHORT"
    closes = [float(x.close) for x in candles]
    cur = candles[-1]
    close, prev_close = closes[-1], closes[-2]
    if pick.direction == s:  # trend following: pullback to the EMA
        ema = ema_last(closes)
        if ema is None:
            return None
        pulled_back = s * (close - prev_close) < 0
        touches = float(cur.low) <= ema <= float(cur.high) or s * (close - ema) <= 0
        extension = abs(close - ema) / atr_now
        if pulled_back and touches and extension <= MAX_EXTENSION_ATR:
            return Route(TF, side, extension, ema)
        return None
    # mean reversion: the price moved against the OBV for two closes in a row
    h = -pick.direction  # +1 after a dump, -1 after a pump; equals the side sign
    if len(closes) >= 3 and all(h * (closes[-i] / closes[-i - 1] - 1) < 0 for i in (1, 2)):
        move = abs(close - closes[-3]) / atr_now
        return Route(MR, side, move, prev_close)
    return None


def score(r: Route, pick: Pick, k: int, aligned: bool) -> tuple[int, dict[str, float]]:
    """A transparent 0 to 100 rank (not a probability): shortlist rank 40, persistence 20, entry
    timing 20, BTC 4H trend aligned with the side 20."""
    rank_part = 40.0 * (k - pick.rank + 1) / k
    persistence = 10.0 * min(1.0, pick.rho1 / 0.3) + 10.0 * min(1.0, (pick.vr - 1.0) / 0.5)
    if r.kind == TF:
        timing = 20.0 * (1.0 - min(1.0, r.extension_atr / MAX_EXTENSION_ATR))
    else:
        timing = 20.0 * min(1.0, r.extension_atr / 2.0)
    parts = {
        "rank": round(rank_part, 2),
        "persistence": round(persistence, 2),
        "timing": round(timing, 2),
        "btc": 20.0 if aligned else 0.0,
    }
    return max(0, min(100, round(sum(parts.values())))), parts
