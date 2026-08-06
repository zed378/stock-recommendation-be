"""Technical conditions the alert rules are evaluated against.

Separated from the rules for the same reason the rules are separated from the
database: this turns bars into numbers, `alerts.evaluate` turns numbers into
candidates, and neither needs the other to be tested.

Everything here is computed from stored daily bars. **That is a real ceiling,
and it is worth naming rather than working around.** Two of the conditions
people usually ask for cannot be built on daily OHLCV at all:

  * **Big-order / lot-size flow.** Whether a day's volume came from one
    institutional block or ten thousand retail lots is a property of the trade
    tape. A daily bar has one volume number and no way back to its parts.
  * **Unusual market activity by transaction frequency.** "Frequency rose
    sharply within minutes" needs per-minute trade counts. The free sources
    this platform runs on publish neither, and the delayed quote is one price
    every fifteen minutes.

Inventing a proxy for either - treating a volume spike as a "big order", or a
price jump as "unusual frequency" - would produce an alert that names something
it did not observe. `VOLUME_SPIKE` says what was actually seen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from aidss.domain.types import Candle
from aidss.indicators import core
from aidss.indicators.engine import candles_to_frame

#: A day's volume at or above this multiple of its own 20-day average is a
#: spike. Two is what people mean by "unusually busy"; lower catches ordinary
#: variation and teaches readers to ignore the alert.
VOLUME_SPIKE_RATIO = Decimal("2.0")

#: Above this much of a move, a volume spike is no longer early. The point of
#: the pairing is a day that is busy *before* the price has run, so the reader
#: is looking at something they could still think about rather than at a move
#: that already happened.
QUIET_MOVE_LIMIT = Decimal("0.05")

#: Standard RSI bands. Not tuned, deliberately: these are the numbers every
#: chart in the market draws its lines at, and an alert firing at 32 because
#: someone preferred it would not mean what its name says.
RSI_OVERSOLD = Decimal("30")
RSI_OVERBOUGHT = Decimal("70")

#: Stochastic bands, likewise conventional.
STOCH_OVERSOLD = Decimal("20")
STOCH_OVERBOUGHT = Decimal("80")

#: A gap smaller than this is a tick, not a gap.
GAP_THRESHOLD = Decimal("0.02")

#: How long a breakout has to hold. Fail inside this many sessions and the
#: break is reported as false rather than as a breakout that quietly reversed.
FALSE_BREAKOUT_SESSIONS = 3

#: Bars examined when looking for divergence. Long enough to contain two swing
#: lows, short enough that the older one still describes this move.
DIVERGENCE_LOOKBACK = 30

#: Sessions in a trading year. Used for the 52-week window, which is what
#: everyone means by "the year's high" even though a year has more days.
YEAR_SESSIONS = 250

#: How close to the yearly extreme counts as "at" it. The same relative band as
#: the level rules, for the same reason: a Rp 100 stock and a Rp 10,000 one are
#: judged the same way.
EXTREME_BAND = Decimal("0.02")

#: Bollinger bandwidth at or below this percentile of its own recent history is
#: a squeeze. A percentile rather than an absolute width, because "narrow" only
#: means anything relative to how wide this issuer's bands usually are.
SQUEEZE_PERCENTILE = Decimal("0.10")

#: Sessions of bandwidth history the percentile is measured against.
SQUEEZE_LOOKBACK = 120

#: A session whose high-low range exceeds this multiple of the average true
#: range has expanded. Two is far enough outside ordinary variation to be worth
#: an interruption.
RANGE_EXPANSION_RATIO = Decimal("2.0")

#: The reward-to-risk ratio worth reporting: at least twice as far to the
#: nearest resistance as to the nearest support.
MIN_REWARD_TO_RISK = Decimal("2.0")

#: Net foreign flow at or beyond this multiple of its own recent average
#: absolute flow is a spike. Measured against the issuer's own history because
#: a hundred billion rupiah is a quiet day in BBCA and an impossible one in a
#: small cap.
FOREIGN_FLOW_RATIO = Decimal("2.5")

#: Sessions of foreign flow the baseline is taken over.
FOREIGN_FLOW_LOOKBACK = 20

#: The fast and slow averages whose crossing is called golden or death. Ten and
#: fifty because that is the pair the request named; the engine's own snapshot
#: carries 20/50/200, so these are computed here rather than read from it.
FAST_MA = 10
SLOW_MA = 50


def _dec(value: object) -> Decimal | None:
    """Decimal, or nothing. Pandas hands back NaN for "not enough bars yet"."""
    if value is None:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return Decimal(str(number))


@dataclass(frozen=True, slots=True)
class TechnicalSignals:
    """What the latest bar looks like, and what the one before it looked like.

    Both, because a crossing is a statement about two points in time. A single
    snapshot can say "the fast average is above the slow one", which is true on
    the day of the cross and every day after it - and an alert that fires every
    day after a cross is an alert people switch off.
    """

    as_of: date | None = None

    fast_ma: Decimal | None = None
    slow_ma: Decimal | None = None
    previous_fast_ma: Decimal | None = None
    previous_slow_ma: Decimal | None = None

    rsi: Decimal | None = None
    previous_rsi: Decimal | None = None

    macd: Decimal | None = None
    macd_signal: Decimal | None = None
    previous_macd: Decimal | None = None
    previous_macd_signal: Decimal | None = None

    stochastic_k: Decimal | None = None
    previous_stochastic_k: Decimal | None = None

    volume: Decimal | None = None
    volume_ratio: Decimal | None = None

    #: Today's open against yesterday's close, when today's bar exists.
    session_open: Decimal | None = None
    previous_close: Decimal | None = None

    #: A resistance level broken within the last few sessions that price has
    #: since fallen back below.
    failed_breakout_level: Decimal | None = None

    #: Price made a lower low while RSI made a higher one.
    bullish_divergence: bool = False

    #: The highest and lowest close of the last trading year.
    year_high: Decimal | None = None
    year_low: Decimal | None = None

    #: Bollinger bandwidth now, and where that sits in its own recent history.
    #: The percentile is what makes "narrow" mean anything: bands that are
    #: always tight on a quiet issuer are not a squeeze.
    bandwidth: Decimal | None = None
    bandwidth_percentile: Decimal | None = None

    #: This session's high-low range against the average true range.
    range_ratio: Decimal | None = None


def compute_signals(candles: list[Candle]) -> TechnicalSignals:
    """Reduce stored bars to the conditions the alert rules ask about.

    Returns an empty bundle rather than raising when there is too little
    history. A newly listed issuer having no 50-day average is an ordinary
    state, and every rule below already treats a missing value as "cannot say".
    """
    if len(candles) < 2:
        return TechnicalSignals()

    frame = candles_to_frame(candles)
    close = frame["close"]
    volume = frame["volume"]

    fast = core.sma(close, FAST_MA) if len(close) >= FAST_MA else pd.Series(dtype=float)
    slow = core.sma(close, SLOW_MA) if len(close) >= SLOW_MA else pd.Series(dtype=float)
    rsi = core.rsi(close) if len(close) >= 15 else pd.Series(dtype=float)
    # Both return a DataFrame of named columns rather than a tuple, so the
    # columns are pulled out by name - unpacking a DataFrame yields its column
    # *names*, which fails later and confusingly.
    empty = pd.Series(dtype=float)
    macd_frame = core.macd(close) if len(close) >= 35 else None
    macd_line = macd_frame["macd"] if macd_frame is not None else empty
    signal_line = macd_frame["signal"] if macd_frame is not None else empty

    stoch_frame = (
        core.stochastic(frame["high"], frame["low"], close) if len(close) >= 15 else None
    )
    stoch_k = stoch_frame["k"] if stoch_frame is not None else empty
    ratio = core.volume_ratio(volume) if len(volume) >= 21 else pd.Series(dtype=float)

    def at(series: pd.Series, back: int = 0) -> Decimal | None:
        return _dec(series.iloc[-1 - back]) if len(series) > back else None

    bandwidth_now, bandwidth_rank = _bandwidth(frame, close)

    latest = candles[-1]
    previous = candles[-2]

    return TechnicalSignals(
        as_of=latest.timestamp.date(),
        fast_ma=at(fast),
        slow_ma=at(slow),
        previous_fast_ma=at(fast, 1),
        previous_slow_ma=at(slow, 1),
        rsi=at(rsi),
        previous_rsi=at(rsi, 1),
        macd=at(macd_line),
        macd_signal=at(signal_line),
        previous_macd=at(macd_line, 1),
        previous_macd_signal=at(signal_line, 1),
        stochastic_k=at(stoch_k),
        previous_stochastic_k=at(stoch_k, 1),
        volume=latest.volume,
        volume_ratio=at(ratio),
        session_open=latest.open,
        previous_close=previous.close,
        failed_breakout_level=_failed_breakout(candles),
        bullish_divergence=_has_bullish_divergence(close, rsi),
        year_high=_dec(close.iloc[-YEAR_SESSIONS:].max()) if len(close) >= 60 else None,
        year_low=_dec(close.iloc[-YEAR_SESSIONS:].min()) if len(close) >= 60 else None,
        bandwidth=bandwidth_now,
        bandwidth_percentile=bandwidth_rank,
        range_ratio=_range_ratio(frame),
    )


def _failed_breakout(candles: list[Candle]) -> Decimal | None:
    """A level broken upward in the last few sessions that price fell back under.

    The level is the highest close of the window *before* the break, which is
    what the break was a break of. Judged on closes rather than intraday highs:
    a wick through a level and a session that closed above it are different
    events, and only the second is what anybody means by a breakout.
    """
    if len(candles) < FALSE_BREAKOUT_SESSIONS + 21:
        return None

    recent = candles[-FALSE_BREAKOUT_SESSIONS:]
    baseline = candles[-(FALSE_BREAKOUT_SESSIONS + 20) : -FALSE_BREAKOUT_SESSIONS]
    level = max(candle.close for candle in baseline)

    broke = any(candle.close > level for candle in recent)
    back_below = candles[-1].close < level
    return level if broke and back_below else None


def _has_bullish_divergence(close: pd.Series, rsi: pd.Series) -> bool:
    """Price at a lower low while RSI is at a higher one.

    Compares the two halves of the window rather than hunting for swing pivots.
    Pivot detection needs bars on both sides to confirm a turn, so the most
    recent one is always provisional - and a divergence alert about a low that
    has not finished forming is an alert about nothing yet.
    """
    if len(close) < DIVERGENCE_LOOKBACK or len(rsi) < DIVERGENCE_LOOKBACK:
        return False

    window_close = close.iloc[-DIVERGENCE_LOOKBACK:]
    window_rsi = rsi.iloc[-DIVERGENCE_LOOKBACK:]
    half = DIVERGENCE_LOOKBACK // 2

    earlier_low = window_close.iloc[:half].min()
    later_low = window_close.iloc[half:].min()
    earlier_rsi = window_rsi.iloc[:half].min()
    later_rsi = window_rsi.iloc[half:].min()

    if any(value != value for value in (earlier_low, later_low, earlier_rsi, later_rsi)):
        return False
    return bool(later_low < earlier_low and later_rsi > earlier_rsi)


def _bandwidth(frame: pd.DataFrame, close: pd.Series) -> tuple[Decimal | None, Decimal | None]:
    """Bollinger bandwidth, and where it sits in its own recent history.

    The percentile is the part that matters. An absolute width cannot say
    anything: bands two percent wide are a squeeze on a volatile miner and
    ordinary on a utility, so "narrow" is only meaningful against how wide this
    issuer's bands usually are.
    """
    if len(close) < 25:
        return None, None
    bands = core.bollinger_bands(close)
    series = bands["bandwidth"].dropna()
    if series.empty:
        return None, None

    window = series.iloc[-SQUEEZE_LOOKBACK:]
    current = float(series.iloc[-1])
    # Share of the window at or below today. Zero means today is the narrowest
    # the bands have been in the whole window.
    rank = float((window <= current).mean()) if len(window) > 1 else None
    return _dec(current), _dec(rank)


def _range_ratio(frame: pd.DataFrame) -> Decimal | None:
    """This session's high-low range against the average true range.

    Measured against ATR rather than against the average high-low range,
    because ATR already accounts for gaps - and a session that opened away from
    yesterday's close and then traded quietly has a small range but was not a
    quiet session.
    """
    if len(frame) < 20:
        return None
    average = core.atr(frame["high"], frame["low"], frame["close"])
    if average.empty:
        return None
    latest_atr = float(average.iloc[-1])
    if latest_atr != latest_atr or latest_atr <= 0:
        return None
    today = float(frame["high"].iloc[-1] - frame["low"].iloc[-1])
    return _dec(today / latest_atr)


def reward_to_risk(
    price: Decimal, support_levels: list[Decimal] | None, resistance_levels: list[Decimal] | None
) -> tuple[Decimal, Decimal, Decimal] | None:
    """How far to the nearest resistance against how far to the nearest support.

    Returns `(ratio, support, resistance)` or nothing when either side is
    missing. Both sides are required rather than assumed: a ratio computed
    against an imagined support is a number with no measurement behind it, and
    it is exactly the sort of figure a reader would treat as though there were.
    """
    below = [level for level in (support_levels or []) if 0 < level < price]
    above = [level for level in (resistance_levels or []) if level > price]
    if not below or not above:
        return None

    support = max(below)
    resistance = min(above)
    risk = price - support
    if risk <= 0:
        return None
    return (resistance - price) / risk, support, resistance


def foreign_flow_ratio(history: list[Decimal]) -> tuple[Decimal, Decimal] | None:
    """The latest net foreign flow against the typical size of recent ones.

    `history` is newest first. The baseline is the mean *absolute* flow of the
    preceding sessions, not the mean signed flow: a name that alternates large
    buying and large selling has a signed average near zero, and dividing by
    that would make every ordinary session look like a spike.

    Returns `(ratio, latest)` where the ratio is signed - so the caller can
    tell accumulation from distribution without recomputing anything.
    """
    if len(history) < 6:
        return None

    latest, *earlier = history[:FOREIGN_FLOW_LOOKBACK]
    baseline = sum(abs(value) for value in earlier) / len(earlier)
    if baseline <= 0:
        return None
    return latest / baseline, latest
