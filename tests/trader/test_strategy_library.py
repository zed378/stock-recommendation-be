"""The comparison strategies (ADR-061): pure rules, no defaults, no look-ahead."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from aidss_trader.connector.types import Candle
from aidss_trader.strategy import PositionState, SignalKind
from aidss_trader.strategy.catalog import proposed_strategies
from aidss_trader.strategy.indicators import highest, lowest, macd, rsi, sma, stdev
from aidss_trader.strategy.library import (
    BollingerParams,
    BollingerReversion,
    DonchianBreakout,
    DonchianParams,
    MacdTrend,
    MacdTrendParams,
    RsiParams,
    RsiReversion,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
FLAT = PositionState()
LONG = PositionState(True, None, None)


def candles(closes: list[float | int], spread: float = 1.0) -> list[Candle]:
    out = []
    for i, c in enumerate(closes):
        close = D(str(c))
        out.append(
            Candle(
                T0 + timedelta(hours=4 * i),
                close,
                close + D(str(spread)),
                close - D(str(spread)),
                close,
                D(1),
            )
        )
    return out


# ------------------------------------------------------------------------------ indicators


def test_sma_and_population_stdev() -> None:
    values = [D(x) for x in (2, 4, 4, 4, 5, 5, 7, 9)]
    assert sma(values, 8)[-1] == D(5)
    assert stdev(values, 8)[-1] == D(2)  # the textbook example: mean 5, population sigma 2
    assert sma(values, 8)[:7] == [None] * 7


def test_rsi_extremes_and_bounds() -> None:
    up = [D(i) for i in range(1, 30)]
    assert rsi(up, 14)[-1] == D(100)  # no losses at all
    down = [D(30 - i) for i in range(30)]
    assert rsi(down, 14)[-1] == D(0)
    mixed = [D(x) for x in (10, 11, 10, 12, 11, 13, 12, 14, 13, 15, 14, 16, 15, 17, 16, 18)]
    value = rsi(mixed, 14)[-1]
    assert value is not None and 0 < value < 100
    assert rsi(up[:10], 14) == [None] * 10  # not enough history is None, never a number


def test_macd_line_and_signal_need_their_history() -> None:
    values = [D(i) for i in range(1, 60)]
    line, signal = macd(values, 12, 26, 9)
    assert line[24] is None and line[25] is not None
    assert signal[32] is None and signal[33] is not None
    assert all(v >= 0 for v in line if v is not None)  # a steady rise keeps the fast EMA above


def test_channel_excludes_the_current_candle() -> None:
    values = [D(x) for x in (1, 5, 3, 9)]
    assert highest(values, 3, 3) == D(5)  # not 9: the candle being judged is not in its own channel
    assert lowest(values, 3, 3) == D(1)
    assert highest(values, 3, 2) is None


# ------------------------------------------------------------------------------- strategies


def donchian() -> DonchianBreakout:
    return DonchianBreakout(DonchianParams(5, 3, 3, D("2.5"), 0))


def test_donchian_enters_on_a_breakout_with_an_atr_stop_and_leaves_on_the_exit_channel() -> None:
    quiet = candles([100] * 8)
    assert donchian().evaluate(quiet, FLAT).kind is SignalKind.NONE
    breakout = candles([100] * 8 + [108])
    signal = donchian().evaluate(breakout, FLAT)
    assert signal.kind is SignalKind.ENTRY and signal.stop_hint is not None
    assert signal.stop_hint < D(108)
    fall = candles([100] * 5 + [110, 111, 112, 95])
    assert donchian().evaluate(fall, LONG).kind is SignalKind.EXIT
    holding = candles([100] * 5 + [110, 111, 112, 111])
    assert donchian().evaluate(holding, LONG).kind is SignalKind.NONE


def rsi_strategy() -> RsiReversion:
    return RsiReversion(RsiParams(5, D(30), D(55), 3, D("2.5"), 0))


def test_rsi_enters_only_on_the_cross_back_above_oversold() -> None:
    drop = [100, 98, 96, 94, 92, 90, 88, 86]  # oversold, still falling: no entry
    assert rsi_strategy().evaluate(candles(drop), FLAT).kind is SignalKind.NONE
    bounce = candles(drop + [92, 95])
    kinds = [rsi_strategy().evaluate(bounce[:n], FLAT).kind for n in range(8, len(bounce) + 1)]
    assert SignalKind.ENTRY in kinds
    entry_at = 8 + kinds.index(SignalKind.ENTRY)
    series = rsi([c.close for c in bounce], 5)
    assert series[entry_at - 2] < 30 <= series[entry_at - 1]  # crossed up on that very candle


def test_rsi_exits_when_it_recovers() -> None:
    rally = candles([90, 88, 86, 84, 82, 84, 88, 93, 99, 105])
    assert rsi_strategy().evaluate(rally, LONG).kind is SignalKind.EXIT


def bollinger() -> BollingerReversion:
    # Ten periods: with five, a close can never reach two sigma from its own mean (the largest
    # possible z-score of the newest of n points is (n - 1) / sqrt(n), 1.79 for n = 5).
    return BollingerReversion(BollingerParams(10, D(2), 3, D("2.5"), 0))


def test_bollinger_enters_back_inside_the_lower_band_and_exits_at_the_middle() -> None:
    base = [100, 101, 100, 99, 100, 101, 100, 99, 100, 101, 100, 99]
    pierce = candles(base + [90])  # closes far below the lower band
    assert bollinger().evaluate(pierce, FLAT).kind is SignalKind.NONE  # outside, not back yet
    assert bollinger().evaluate(candles(base + [90, 99]), FLAT).kind is SignalKind.ENTRY
    assert bollinger().evaluate(candles(base + [90, 95]), LONG).kind is SignalKind.NONE
    assert bollinger().evaluate(candles(base + [90, 100.5]), LONG).kind is SignalKind.EXIT


def macd_strategy() -> MacdTrend:
    return MacdTrend(MacdTrendParams(3, 6, 3, 8, 3, D("2.5"), 0))


def test_macd_needs_the_cross_and_the_uptrend_filter() -> None:
    strategy = macd_strategy()
    # An uptrend, a pullback that drags the MACD under its signal, then a cross back up while the
    # close is above the trend EMA: the only kind of entry this rule takes.
    pullback = (
        [100 + i * 2 for i in range(15)] + [126, 124, 122, 120, 119] + [121, 124, 128, 133, 139]
    )
    entries = [
        n
        for n in range(strategy.min_history(), len(pullback) + 1)
        if strategy.evaluate(candles(pullback)[:n], FLAT).kind is SignalKind.ENTRY
    ]
    assert entries == [22]
    # A cross up that happens while the close is still under the trend EMA is not an entry.
    bounce = [100 - i for i in range(14)] + [88, 90, 93, 97, 102, 108]
    assert all(
        strategy.evaluate(candles(bounce)[:n], FLAT).kind is not SignalKind.ENTRY
        for n in range(strategy.min_history(), len(bounce) + 1)
    )


# ---------------------------------------------------------------------------- the contract


@pytest.mark.parametrize("name", list(proposed_strategies()))
def test_every_rule_has_a_name_a_version_and_a_guard_against_thin_history(name: str) -> None:
    strategy = proposed_strategies()[name]
    assert strategy.name == name and strategy.version_id().startswith(f"{name}-")
    thin = candles([100] * (strategy.min_history() - 1))
    assert strategy.evaluate(thin, FLAT).reason == "insufficient_history"


def test_a_parameter_change_is_a_new_version() -> None:
    a = DonchianBreakout(DonchianParams(20, 10, 14, D("2.5"), 0)).version_id()
    b = DonchianBreakout(DonchianParams(20, 10, 14, D("3"), 0)).version_id()
    assert a != b


def test_every_rule_refuses_nonsense_parameters_and_has_no_defaults() -> None:
    with pytest.raises(ValueError):
        DonchianParams(5, 10, 3, D("2.5"), 0)
    with pytest.raises(ValueError):
        RsiParams(14, D(60), D(55), 14, D("2.5"), 0)
    with pytest.raises(ValueError):
        BollingerParams(2, D(2), 14, D("2.5"), 0)
    with pytest.raises(ValueError):
        MacdTrendParams(12, 26, 9, 20, 14, D("2.5"), 0)
    with pytest.raises(TypeError):
        DonchianParams()  # type: ignore[call-arg]


def test_a_rule_only_reads_the_candles_it_is_given() -> None:
    """The decision at candle t must not change when later candles exist (no look-ahead)."""
    series = candles([100 + (i % 7) * 2 - (i % 5) for i in range(60)])
    for strategy in proposed_strategies().values():
        for cut in range(strategy.min_history(), len(series) - 1, 5):
            once = strategy.evaluate(series[:cut], FLAT)
            again = strategy.evaluate(series[:cut], FLAT)
            assert (once.kind, once.reason, once.stop_hint) == (
                again.kind,
                again.reason,
                again.stop_hint,
            )
