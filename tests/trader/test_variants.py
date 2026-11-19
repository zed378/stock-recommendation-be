"""One-change variants of the reference strategy, and the extra backtest metrics (ADR-063)."""

from __future__ import annotations

import random
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal as D

import pytest

from aidss_trader.backtest import run_backtest
from aidss_trader.connector.types import Candle
from aidss_trader.strategy import EmaAdxStrategy, PositionState, SignalKind
from aidss_trader.strategy.indicators import (
    adx,
    atr,
    directional_lines,
    efficiency_ratio,
)
from aidss_trader.strategy.kinds import KINDS, ParameterError, build_strategy
from aidss_trader.strategy.variants import (
    AtrFilterParams,
    DiParams,
    EmaAdxAtrFilter,
    EmaAdxDi,
    EmaAdxRegime,
    EmaAdxRising,
    EmaAdxTrail,
    RegimeParams,
    RisingParams,
    TrailParams,
)
from tests.trader.test_sizing_ledger_paper_backtest import PARAMS, T0, config

BASE = asdict(PARAMS)
FLAT = PositionState()
LONG = PositionState(True, None, None)


def walk(seed: int, n: int = 70) -> list[Candle]:
    rng = random.Random(seed)
    price, out = 1_000_000.0, []
    for i in range(n):
        price *= 1 + rng.uniform(-0.02, 0.025)
        high, low = price * 1.01, price * 0.99
        out.append(Candle(T0 + timedelta(hours=4 * i), D(price), D(high), D(low), D(price), D(1)))
    return out


def series(up: int, down_step: int, n_down: int) -> list[Candle]:
    closes = [1_200_000_000 + 4_000_000 * i for i in range(up)]
    top = closes[-1]
    closes += [top - down_step * i for i in range(1, n_down + 1)]
    return [
        Candle(T0 + timedelta(hours=4 * i), D(c), D(c + 2_000_000), D(c - 2_000_000), D(c), D(1))
        for i, c in enumerate(closes)
    ]


SEEDS = range(40)


def _entries(strategy, cs):
    """Every index at which the strategy says ENTRY for a flat account."""
    return {
        i
        for i in range(strategy.min_history(), len(cs) + 1)
        if strategy.evaluate(cs[:i], FLAT).kind is SignalKind.ENTRY
    }


# ----------------------------------------------------------------- indicators


def test_directional_lines_and_efficiency_ratio_are_sane() -> None:
    up = series(30, 0, 0)
    plus, minus = directional_lines(up, 3)
    assert plus[:3] == [None] * 3 and plus[-1] > minus[-1] >= 0
    ratio = efficiency_ratio([c.close for c in up], 5)
    assert ratio[:5] == [None] * 5 and ratio[-1] == 1  # a straight line is all progress
    flat = [D(100), D(101)] * 10
    assert efficiency_ratio(flat, 4)[-1] == 0  # back and forth, no net move


# -------------------------------------------------------------------- filters


@pytest.mark.parametrize("seed", SEEDS)
def test_each_filter_only_removes_entries_the_reference_would_make(seed: int) -> None:
    cs = walk(seed)
    core = EmaAdxStrategy(PARAMS)
    variants = [
        EmaAdxRising(RisingParams(**BASE, rise_bars=2)),
        EmaAdxDi(DiParams(**BASE, di_margin=D("0"))),
        EmaAdxAtrFilter(AtrFilterParams(**BASE, min_atr_pct=D("1.5"))),
        EmaAdxRegime(RegimeParams(**BASE, er_period=8, er_min=D("0.3"))),
    ]
    for v in variants:
        start = v.min_history()
        mine = {i for i in _entries(v, cs)}
        ref = {
            i
            for i in range(start, len(cs) + 1)
            if core.evaluate(cs[:i], FLAT).kind is SignalKind.ENTRY
        }
        assert mine <= ref, v.name


@pytest.mark.parametrize("seed", SEEDS)
def test_each_filter_matches_its_own_rule_computed_from_the_indicators(seed: int) -> None:
    cs = walk(seed)
    core = EmaAdxStrategy(PARAMS)
    rising = EmaAdxRising(RisingParams(**BASE, rise_bars=2))
    di = EmaAdxDi(DiParams(**BASE, di_margin=D("0.5")))
    vol = EmaAdxAtrFilter(AtrFilterParams(**BASE, min_atr_pct=D("1.5")))
    regime = EmaAdxRegime(RegimeParams(**BASE, er_period=8, er_min=D("0.3")))
    for i in range(30, len(cs) + 1):
        h = cs[:i]
        if core.evaluate(h, FLAT).kind is not SignalKind.ENTRY:
            continue
        a = adx(h, 3)
        want_rising = a[-1] is not None and a[-3] is not None and a[-1] > a[-3]
        assert (rising.evaluate(h, FLAT).kind is SignalKind.ENTRY) == want_rising
        p, m = directional_lines(h, 3)
        assert (di.evaluate(h, FLAT).kind is SignalKind.ENTRY) == (p[-1] - m[-1] > D("0.5"))
        share = atr(h, 3)[-1] / h[-1].close * 100
        assert (vol.evaluate(h, FLAT).kind is SignalKind.ENTRY) == (share >= D("1.5"))
        er = efficiency_ratio([c.close for c in h], 8)[-1]
        assert (regime.evaluate(h, FLAT).kind is SignalKind.ENTRY) == (er >= D("0.3"))


def test_a_blocked_entry_says_why_and_keeps_the_reference_numbers() -> None:
    # find a candle where the reference enters and a strict regime filter refuses
    strict = EmaAdxRegime(RegimeParams(**BASE, er_period=8, er_min=D("1")))
    core = EmaAdxStrategy(PARAMS)
    for seed in SEEDS:
        cs = walk(seed)
        for i in range(strict.min_history(), len(cs) + 1):
            if core.evaluate(cs[:i], FLAT).kind is SignalKind.ENTRY:
                blocked = strict.evaluate(cs[:i], FLAT)
                assert blocked.kind is SignalKind.NONE and blocked.reason == "ranging_market"
                assert blocked.inputs["adx"] == core.evaluate(cs[:i], FLAT).inputs["adx"]
                assert "efficiency_ratio" in blocked.inputs
                return
    pytest.fail("no entry found to refuse")


def test_a_filter_never_touches_the_exit() -> None:
    cs = series(30, 6_000_000, 10)
    core = EmaAdxStrategy(PARAMS)
    for v in (
        EmaAdxRising(RisingParams(**BASE, rise_bars=2)),
        EmaAdxDi(DiParams(**BASE, di_margin=D("0"))),
        EmaAdxAtrFilter(AtrFilterParams(**BASE, min_atr_pct=D("1"))),
        EmaAdxRegime(RegimeParams(**BASE, er_period=8, er_min=D("0.3"))),
    ):
        for i in range(max(v.min_history(), 12), len(cs) + 1):
            assert v.evaluate(cs[:i], LONG).kind == core.evaluate(cs[:i], LONG).kind


def test_variants_have_their_own_versions_and_reject_bad_numbers() -> None:
    a = EmaAdxRising(RisingParams(**BASE, rise_bars=2)).version_id()
    b = EmaAdxRising(RisingParams(**BASE, rise_bars=3)).version_id()
    assert a.startswith("ema_adx_rising-") and a != b != EmaAdxStrategy(PARAMS).version_id()
    for bad in (
        lambda: RisingParams(**BASE, rise_bars=0),
        lambda: DiParams(**BASE, di_margin=D("-1")),
        lambda: AtrFilterParams(**BASE, min_atr_pct=D("0")),
        lambda: TrailParams(**BASE, trail_atr_multiple=D("0")),
        lambda: RegimeParams(**BASE, er_period=1, er_min=D("0.3")),
        lambda: RegimeParams(**BASE, er_period=8, er_min=D("1.5")),
    ):
        with pytest.raises(ValueError):
            bad()


def test_the_builder_offers_every_variant_with_the_reference_fields_first() -> None:
    plain = {f.name: f.suggested for f in KINDS["ema_adx"].fields}
    extras = {
        "ema_adx_rising": {"rise_bars": "2"},
        "ema_adx_di": {"di_margin": "0"},
        "ema_adx_atr_filter": {"min_atr_pct": "0.5"},
        "ema_adx_trail": {"trail_atr_multiple": "3"},
        "ema_adx_regime": {"er_period": "10", "er_min": "0.3"},
    }
    for kind, extra in extras.items():
        names = [f.name for f in KINDS[kind].fields]
        assert names[: len(plain)] == list(plain) and set(names[len(plain) :]) == set(extra)
        assert build_strategy(kind, {**{**BASE, **{k: str(v) for k, v in BASE.items()}}, **extra})
    with pytest.raises(ParameterError, match="rise_bars"):
        build_strategy("ema_adx_rising", {k: str(v) for k, v in BASE.items()})  # no default


# --------------------------------------------------------------- trailing stop


def test_the_trailing_stop_travels_as_a_hint_while_long_and_exit_stays_the_references() -> None:
    cs = series(30, 0, 0)
    trail = EmaAdxTrail(TrailParams(**BASE, trail_atr_multiple=D("1")))
    held = trail.evaluate(cs, LONG)
    assert held.kind is SignalKind.NONE and held.reason == "trail"
    assert held.stop_hint == cs[-1].close - atr(cs, 3)[-1]
    falling = series(30, 6_000_000, 10)
    core = EmaAdxStrategy(PARAMS)
    for i in range(12, len(falling) + 1):
        if core.evaluate(falling[:i], LONG).kind is SignalKind.EXIT:
            assert trail.evaluate(falling[:i], LONG).kind is SignalKind.EXIT
            break
    else:
        pytest.fail("the reference never exited on this series")
    assert trail.evaluate(cs, FLAT).stop_hint == core.evaluate(cs, FLAT).stop_hint


def test_a_backtest_trails_the_stop_up_and_exits_no_lower_than_the_reference() -> None:
    cs = series(30, 2_500_000, 20)
    ref = run_backtest(cs, config())
    trail = run_backtest(
        cs, config(strategy=EmaAdxTrail(TrailParams(**BASE, trail_atr_multiple=D("1"))))
    )
    assert ref.trades[0].exit_reason == "stop" and trail.trades[0].exit_reason == "stop"
    assert trail.trades[0].exit_price > ref.trades[0].exit_price  # the stop rose above the first
    assert trail.trades[0].entry_price == ref.trades[0].entry_price  # same entry: one change


def test_the_trailing_stop_is_not_applied_without_a_position_and_never_lowers() -> None:
    cs = series(30, 0, 5)
    never_lower = run_backtest(
        cs, config(strategy=EmaAdxTrail(TrailParams(**BASE, trail_atr_multiple=D("5"))))
    )
    plain = run_backtest(cs, config())
    # a wide trail would sit below the entry stop; the stop must stay where the entry set it
    assert [t.exit_price for t in never_lower.trades][:1] == [t.exit_price for t in plain.trades][
        :1
    ]


# --------------------------------------------------------------------- metrics


def test_the_extra_metrics_are_raw_sums_that_agree_with_the_trades() -> None:
    cs = series(30, 6_000_000, 25)
    r = run_backtest(cs, config())
    m = r.metrics
    assert r.trades
    assert m["closed_pnl_idr"] == sum(t.pnl_net for t in r.trades)
    assert m["win_sum_idr"] + m["loss_sum_idr"] == m["closed_pnl_idr"]
    assert m["fees_idr"] == sum(t.fees for t in r.trades) > 0
    hours = sum((t.exit_time - t.entry_time).total_seconds() for t in r.trades) / 3600
    assert float(m["hold_hours_total"]) == pytest.approx(hours)
    # costs are inside the net result: gross = net + fees, and fees are never negative
    assert all(t.fees >= 0 for t in r.trades)


# ------------------------------------------------------------- API and paper


def _row(strategy_id, version, pair, *, trades, wins, extra, ran_at=None):
    from datetime import UTC, datetime

    from aidss_trader.db.models import BacktestRunRow

    return BacktestRunRow(
        origin="BACKTEST",
        strategy_id=strategy_id,
        strategy_version=version,
        pair=pair,
        timeframe="4H",
        candles_used=300,
        trades=trades,
        wins=wins,
        win_rate_pct=D("0"),
        total_return_pct=D("-1"),
        max_drawdown_pct=D(pair == "AAAIDR" and 2 or 5),
        profit_factor=D("0.5"),
        start_equity_idr=D("1000"),
        final_equity_idr=D("990"),
        cost_model={},
        parameters={},
        data_fingerprint="x",
        extra_metrics=extra,
        ran_at=ran_at or datetime.now(UTC),
        ran_by="test",
    )


def test_the_summary_adds_raw_sums_and_is_blank_when_a_run_predates_them() -> None:
    from tests.trader.test_runtime_wiring import World, api_for

    w = World("PAPER", configured=True)
    call = api_for(w)
    params = {k: str(v) for k, v in BASE.items()}
    made = call(
        "POST",
        "/strategy-defs",
        {"id": "dd", "label": "dd", "kind": "ema_adx_di", "params": {**params, "di_margin": "0"}},
    )
    assert made.status_code == 201
    version = made.json()["data"]["version"]
    full = {
        "closed_pnl_idr": "-30",
        "win_sum_idr": "20",
        "loss_sum_idr": "-50",
        "hold_hours_total": "40",
        "fees_idr": "10",
    }
    with w.factory() as s:
        s.add(_row("dd", version, "AAAIDR", trades=4, wins=1, extra=full))
        s.add(
            _row(
                "dd",
                version,
                "BBBIDR",
                trades=6,
                wins=3,
                extra={**full, "closed_pnl_idr": "10", "win_sum_idr": "40", "loss_sum_idr": "-30"},
            )
        )
        s.commit()
    got = call("GET", "/strategy-defs/dd/backtests").json()["data"]["summary"]
    # 10 trades, 4 wins; PnL -20 -> expectancy -2; wins 60/4 = 15; losses -80/6; PF 60/80
    assert (got["trades"], got["wins"], got["win_rate_pct"]) == (10, 4, "40.00")
    assert got["expectancy_idr"] == "-2.00" and got["avg_win_idr"] == "15.00"
    assert got["avg_loss_idr"] == "-13.33" and got["profit_factor"] == "0.75"
    assert got["avg_hold_hours"] == "8.0" and got["worst_drawdown_pct"] == "5.000"
    assert got["fees_pct_of_start"] == "2.000" and got["complete"] is True  # 10/1000 twice
    listed = {d["id"]: d for d in call("GET", "/strategy-defs").json()["data"]}
    assert listed["dd"]["backtest_expectancy_idr"] == "-2.00"
    with w.factory() as s:
        s.add(_row("dd", version, "CCCIDR", trades=1, wins=0, extra=None))
        s.commit()
    part = call("GET", "/strategy-defs/dd/backtests").json()["data"]["summary"]
    assert part["complete"] is False and part["expectancy_idr"] is None
    assert part["trades"] == 11  # the figures every run has are still shown


def test_the_paper_stop_follows_a_trailing_strategy_up_and_never_down() -> None:
    from datetime import UTC, datetime

    from aidss_trader.db.models import PositionStop
    from tests.trader.test_runtime_wiring import World

    w = World("PAPER")
    now = datetime.now(UTC)
    with w.factory() as s:
        s.add(PositionStop(pair="AAAIDR", origin="PAPER", stop_price=D("100"), updated_at=now))
        s.add(PositionStop(pair="AAAIDR", origin="LIVE", stop_price=D("100"), updated_at=now))
        s.commit()
    with w.factory() as s:
        w.runtime._trail_paper_stop(s, "AAAIDR", D("110"))
        w.runtime._trail_paper_stop(s, "AAAIDR", D("105"))  # lower: ignored
        stops = {x.origin: x.stop_price for x in s.query(PositionStop)}
    assert stops == {"PAPER": D("110"), "LIVE": D("100")}  # the live stop is never touched
