"""4-hour Donchian and volume-spike signals, their score, levels and ids, and the simulated
lifecycle that decides what a follower would have got (ADR-067). Pure functions, no network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from aidss.domain.types import Candle
from aidss_signals import h4
from aidss_signals.lifecycle import CLOSED, OPEN, PENDING, SKIPPED, SimParams, simulate

T0 = datetime(2026, 11, 1, tzinfo=UTC)
P = h4.H4Params(donchian_n=20, vol_period=20, vol_mult=2.0, range_mult=1.5)


def bar(i: int, o: float, high: float, low: float, c: float, v: float = 100.0) -> Candle:
    return Candle(
        T0 + timedelta(hours=4 * i), D(str(o)), D(str(high)), D(str(low)), D(str(c)), D(str(v))
    )


def quiet(n: int = 40, price: float = 100.0) -> list[Candle]:
    """A flat market: tiny alternating moves, constant volume."""
    return [bar(i, price, price + 1, price - 1, price + (0.2 if i % 2 else -0.2)) for i in range(n)]


def with_last(
    cs: list[Candle], o: float, high: float, low: float, c: float, v: float
) -> list[Candle]:
    return [*cs, bar(len(cs), o, high, low, c, v)]


# ------------------------------------------------------------------------------- detection


def test_a_close_above_the_donchian_high_on_heavy_volume_is_a_scored_long() -> None:
    cs = with_last(quiet(), 100.0, 104.0, 99.5, 103.8, 300.0)
    s = h4.detect(cs, P, [h4.DONCHIAN], "bullish", allow_short=False)
    assert s is not None and (s.strategy, s.side) == (h4.DONCHIAN, "LONG")
    assert s.entry == 103.8 and s.candle_open == cs[-1].timestamp and s.reference == 101.0
    assert 0 <= s.score <= 100 and s.components["btc"] == 20.0
    assert sum(s.components.values()) == pytest.approx(s.score, abs=1.0)


def test_nothing_fires_inside_the_range_or_without_enough_history() -> None:
    inside = with_last(quiet(), 100.0, 100.8, 99.2, 100.4, 100.0)
    assert h4.detect(inside, P, list(h4.STRATEGIES), "bullish", True) is None
    assert h4.detect(quiet(10), P, list(h4.STRATEGIES), "bullish", True) is None
    assert h4.min_history(P) == 22


def test_shorts_exist_only_when_allowed_and_the_channel_is_broken_downwards() -> None:
    cs = with_last(quiet(), 100.0, 100.5, 96.0, 96.3, 300.0)
    assert h4.detect(cs, P, [h4.DONCHIAN], "bearish", allow_short=False) is None
    s = h4.detect(cs, P, [h4.DONCHIAN], "bearish", allow_short=True)
    assert (
        s is not None and s.side == "SHORT" and s.reference == 99.0 and s.components["btc"] == 20.0
    )


def test_a_volume_spike_needs_volume_range_and_a_close_at_the_extreme() -> None:
    base = quiet()
    spike = with_last(
        base, 100.0, 103.0, 99.8, 102.8, 450.0
    )  # no new Donchian high at 103 > 101? it is
    only_spike = h4.detect(
        with_last(base, 100.0, 100.9, 98.0, 100.8, 450.0), P, [h4.SPIKE], "", True
    )
    assert only_spike is None  # big volume but the close is not near the top of the candle's range
    s = h4.detect(
        with_last(base, 99.0, 102.0, 98.8, 101.9, 450.0), P, [h4.SPIKE], "", allow_short=False
    )
    assert s is not None and s.strategy == h4.SPIKE and s.side == "LONG"
    low_vol = h4.detect(with_last(base, 99.0, 102.0, 98.8, 101.9, 150.0), P, [h4.SPIKE], "", False)
    assert low_vol is None  # 1.5x is below the 2x the owner asked for
    assert spike is not None  # the same bar is also a breakout, so the Donchian rule fires there


def test_at_most_one_signal_per_coin_and_candle_the_higher_score_wins() -> None:
    cs = with_last(quiet(), 99.0, 105.0, 98.8, 104.9, 600.0)
    both = h4.detect(cs, P, [h4.DONCHIAN, h4.SPIKE], "bullish", False)
    alone = {k: h4.detect(cs, P, [k], "bullish", False) for k in (h4.DONCHIAN, h4.SPIKE)}
    assert both is not None and both.score == max(v.score for v in alone.values() if v)


def test_the_score_rises_with_volume_and_btc_alignment_and_is_a_rank_not_a_probability() -> None:
    def score(volume: float, bias: str) -> int:
        cs = with_last(quiet(), 100.0, 104.0, 99.5, 103.8, volume)
        return h4.detect(cs, P, [h4.DONCHIAN], bias, False).score

    assert score(300.0, "bullish") - score(300.0, "") == 20
    assert score(300.0, "bearish") == score(
        300.0, ""
    )  # an opposed trend adds nothing, it is not punished here
    assert score(100.0, "") < score(200.0, "") < score(400.0, "")
    assert 0 <= score(10_000.0, "bullish") <= 100


def test_atr_is_wilders_and_levels_are_priced_from_it() -> None:
    flat = [bar(i, 100, 101, 99, 100) for i in range(30)]
    atrs = h4.atr_series(flat)
    assert atrs[13] is None and atrs[14] == pytest.approx(2.0) and atrs[-1] == pytest.approx(2.0)
    long_ = h4.levels("LONG", 100.0, 2.0, 2.5, (1.5, 2.5, 4.0))
    assert (
        long_["stop"] == 95.0
        and long_["tp1"] == 107.5
        and long_["tp3"] == 120.0
        and long_["risk"] == 5.0
    )
    short = h4.levels("SHORT", 100.0, 2.0, 2.5, (1.5, 2.5, 4.0))
    assert short["stop"] == 105.0 and short["tp1"] == 92.5 and short["tp3"] == 80.0
    assert h4.levels("LONG", 100.0, 0.0, 2.5, (1, 2, 3)) is None
    assert h4.levels("LONG", 10.0, 5.0, 3.0, (1, 2, 3)) is None  # the stop would be below zero


def test_the_signal_id_is_deterministic_and_unique_per_candle_coin_side_and_strategy() -> None:
    t = T0 + timedelta(hours=8)
    a = h4.signal_id(h4.DONCHIAN, "ETHUSDT", "LONG", t)
    assert (
        a
        == h4.signal_id(h4.DONCHIAN, "ETHUSDT", "LONG", t)
        == f"aidss4h-donchian-ETHUSDT-long-{int(t.timestamp())}"
    )
    others = {
        h4.signal_id(h4.SPIKE, "ETHUSDT", "LONG", t),
        h4.signal_id(h4.DONCHIAN, "BTCUSDT", "LONG", t),
        h4.signal_id(h4.DONCHIAN, "ETHUSDT", "SHORT", t),
        h4.signal_id(h4.DONCHIAN, "ETHUSDT", "LONG", t + h4.H4),
    }
    assert a not in others and len(others) == 4


# ----------------------------------------------------------------------------- lifecycle

FREE = SimParams(fee_pct=0.0, slippage_pct=0.0, drift_r=0.5, max_hold_bars=30)
COSTS = SimParams(fee_pct=0.1, slippage_pct=0.05, drift_r=0.5, max_hold_bars=30)
ENTRY, STOP, TPS = 100.0, 95.0, (107.5, 112.5, 120.0)  # R = 5: tp1 1.5R, tp2 2.5R, tp3 4R


def path(*bars: tuple[float, float, float, float]) -> list[Candle]:
    return [bar(i, *b) for i, b in enumerate(bars)]


def sim(side: str, after: list[Candle], params: SimParams = FREE, entry=ENTRY, stop=STOP, tps=TPS):
    return simulate(side, entry, stop, tps, after, params)


def test_no_candle_after_the_signal_means_pending() -> None:
    assert sim("LONG", []).state == PENDING


def test_all_three_targets_close_the_ladder_at_the_weighted_r() -> None:
    out = sim("LONG", path((100, 108, 100.5, 107), (107, 113, 106, 112), (112, 121, 111, 120)))
    assert (out.state, out.outcome, out.tp_hits) == (CLOSED, "TP3", 3)
    assert (
        out.gross_r == pytest.approx(0.5 * 1.5 + 0.3 * 2.5 + 0.2 * 4.0) and out.net_r == out.gross_r
    )
    assert out.fill_price == 100.0 and out.bars_held == 3 and out.closed_index == 2


def test_a_stop_before_the_first_target_loses_one_r_plus_costs() -> None:
    out = sim("LONG", path((100, 101, 94, 95)), COSTS)
    assert (out.outcome, out.tp_hits) == ("SL", 0)
    cost_r = (0.1 + 0.05) / 100 * 2 * out.fill_price / 5.0
    assert out.gross_r == pytest.approx(-1.0, abs=0.02)  # the fill carries the entry slippage
    assert out.net_r == pytest.approx(out.gross_r - cost_r, abs=1e-5)


def test_after_the_first_target_the_stop_moves_to_the_fill_and_a_retrace_is_a_small_win() -> None:
    out = sim("LONG", path((100, 108, 99.5, 107), (107, 107.5, 99, 100)))
    assert (out.outcome, out.tp_hits) == ("BE_AFTER_TP1", 1)
    assert out.gross_r == pytest.approx(0.5 * 1.5)  # the rest left at break-even


def test_the_order_inside_a_bar_is_pessimistic() -> None:
    both = sim("LONG", path((100, 108, 94, 100)))  # stop and the first target in one bar
    assert (both.outcome, both.tp_hits) == ("SL", 0) and both.gross_r == pytest.approx(-1.0)
    # bar 1 would reach the second target but its low also touches the break-even stop: the stop is
    # tested first, so the second target is never credited
    be_same_bar = sim("LONG", path((100, 108, 100.2, 107), (107, 113, 99.9, 112)))
    assert (be_same_bar.outcome, be_same_bar.tp_hits) == ("BE_AFTER_TP1", 1)
    assert be_same_bar.gross_r == pytest.approx(0.5 * 1.5)
    one_bar = sim("LONG", path((100, 108, 99, 107)))  # tp1 and a dip below the new stop in one bar
    assert (one_bar.outcome, one_bar.tp_hits) == ("BE_AFTER_TP1", 1)


def test_a_gap_through_the_stop_fills_at_the_open_not_at_the_stop() -> None:
    out = sim("LONG", path((100, 101, 99, 100), (90, 91, 89, 90)))
    assert out.outcome == "SL" and out.gross_r == pytest.approx(-2.0)  # filled at 90, two R down


def test_a_follower_does_not_trade_when_the_price_has_already_run_or_broken() -> None:
    far = sim("LONG", path((104, 110, 103, 109)))  # opens 0.8R above the signal entry: beyond 0.5R
    assert (far.state, far.outcome, far.net_r) == (SKIPPED, "SKIPPED_DRIFT", None)
    broken = sim("LONG", path((94, 96, 93, 95)))
    assert broken.outcome == "SKIPPED_DRIFT"
    near = sim("LONG", path((101, 102, 100.5, 101.5)))
    assert near.state == OPEN and near.fill_price == 101.0


def test_the_time_stop_closes_what_is_left_at_the_close() -> None:
    params = SimParams(0.0, 0.0, 0.5, max_hold_bars=3)
    out = sim(
        "LONG",
        path((100, 103, 99, 102), (102, 104, 101, 103), (103, 105, 102, 104), (104, 105, 90, 90)),
        params,
    )
    assert (out.outcome, out.bars_held) == ("EXPIRED", 3) and out.gross_r == pytest.approx(0.8)


def test_an_open_trade_is_marked_to_the_latest_close_and_is_not_final() -> None:
    out = sim("LONG", path((100, 104, 99, 103), (103, 105, 102, 104)))
    assert out.state == OPEN and out.outcome is None and out.closed_index is None
    assert out.gross_r == pytest.approx((104 - 100) / 5.0) and out.bars_held == 2


def test_a_short_is_the_mirror_image() -> None:
    entry, stop, tps = 100.0, 105.0, (92.5, 87.5, 80.0)
    win = sim(
        "SHORT",
        path((100, 99.5, 92, 93), (93, 94, 87, 88), (88, 89, 79, 80)),
        entry=entry,
        stop=stop,
        tps=tps,
    )
    assert (win.outcome, win.tp_hits) == ("TP3", 3) and win.gross_r == pytest.approx(
        0.5 * 1.5 + 0.3 * 2.5 + 0.2 * 4.0
    )
    loss = sim("SHORT", path((100, 106, 99, 105)), entry=entry, stop=stop, tps=tps)
    assert loss.outcome == "SL" and loss.gross_r == pytest.approx(-1.0)
    gap = sim(
        "SHORT", path((100, 101, 99, 100), (110, 111, 109, 110)), entry=entry, stop=stop, tps=tps
    )
    assert gap.gross_r == pytest.approx(-2.0)


def test_costs_reduce_the_result_and_free_costs_change_nothing() -> None:
    cs = path((100, 108, 100.5, 107), (107, 113, 106, 112), (112, 121, 111, 120))
    free, costly = sim("LONG", cs, FREE), sim("LONG", cs, COSTS)
    assert free.net_r == free.gross_r and costly.net_r < costly.gross_r
    assert costly.gross_r == pytest.approx(free.gross_r, abs=0.05)


def test_the_answer_is_recomputed_the_same_way_every_time_and_a_closed_trade_never_changes() -> (
    None
):
    cs = path((100, 101, 94, 95), (95, 130, 90, 125))
    a, b = sim("LONG", cs), sim("LONG", cs)
    assert a == b
    assert a.outcome == "SL" and a.closed_index == 0  # what happens after the stop is irrelevant
    assert sim("LONG", cs[:1]) == a
