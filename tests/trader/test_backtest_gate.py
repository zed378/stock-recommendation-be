"""The backtest promotion gate reads stored BACKTEST runs, never a typed figure (ADR-059)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D

import pytest

from aidss_trader.backtest import backtest_evidence
from aidss_trader.promotion import Promotion, SuppliedEvidence, Thresholds
from tests.trader.test_t5_operator_surface import Api, Clock, paper_sells, store_backtest

THRESHOLDS = Thresholds(
    min_paper_trades=3,
    max_paper_drawdown_pct=D("20"),
    backtest_min_return_pct=D("0"),
    max_live_capital_idr=D("5000000"),
    max_slippage_pct=D("0.5"),
)


@pytest.fixture
def clock() -> Clock:
    return Clock()


def gate(promo, name: str = "backtest", typed: str | None = None):
    supplied = SuppliedEvidence(
        backtest_return_pct=None if typed is None else D(typed), paper_drawdown_pct=D("1")
    )
    gates = promo.gates("ema_adx", "APPROVAL", THRESHOLDS, supplied)
    return next(g for g in gates if g.name == name)


def fresh(session, clock) -> Promotion:
    promo = Promotion(session, now=clock)
    promo.register("ema_adx", "v1")
    clock.advance(weeks=5)
    paper_sells(session, 5, clock.t - timedelta(days=1))
    return promo


def test_no_stored_run_means_no_evidence(session, clock) -> None:
    g = gate(fresh(session, clock))
    assert not g.passed and g.reason == "no evidence"


def test_the_figure_is_the_sum_of_the_latest_run_of_each_pair(session, clock) -> None:
    promo = fresh(session, clock)
    t = clock.t
    store_backtest(session, "v1", "AAAIDR", D("3"), t - timedelta(days=3), trades=2)
    store_backtest(session, "v1", "AAAIDR", D("-9"), t - timedelta(days=1), trades=4)  # newest wins
    store_backtest(session, "v1", "BBBIDR", D("2"), t - timedelta(days=2), trades=1)
    evidence = backtest_evidence(session, "ema_adx", "v1")
    assert evidence is not None
    assert (evidence.return_pct, evidence.pairs, evidence.trades) == (D("-7"), 2, 5)
    g = gate(promo)
    assert not g.passed and "sum over 2 pairs, 5 trades" in (g.measured or "")


def test_a_typed_figure_changes_nothing(session, clock) -> None:
    promo = fresh(session, clock)
    store_backtest(session, "v1", "AAAIDR", D("-5"), clock.t)
    assert not gate(promo, typed="99").passed  # the typed 99 is ignored: the stored -5 decides
    store_backtest(session, "v1", "AAAIDR", D("6"), clock.t + timedelta(seconds=1))
    assert gate(promo, typed="-99").passed  # and a typed loss does not fail a stored gain


def test_another_strategy_version_has_no_evidence(session, clock) -> None:
    promo = fresh(session, clock)
    store_backtest(session, "v0-older", "AAAIDR", D("50"), clock.t)
    assert backtest_evidence(session, "ema_adx", "v1") is None
    assert gate(promo).reason == "no evidence"


def test_runs_from_a_different_start_equity_are_not_mixed_in(session, clock) -> None:
    from aidss_trader.db.models import BacktestRunRow

    fresh(session, clock)
    store_backtest(session, "v1", "AAAIDR", D("2"), clock.t - timedelta(days=1))
    store_backtest(session, "v1", "BBBIDR", D("40"), clock.t)  # newest: sets the start equity
    row = session.query(BacktestRunRow).filter_by(pair="AAAIDR").one()
    row.start_equity_idr = D("50000")  # an older run on another capital
    session.flush()
    evidence = backtest_evidence(session, "ema_adx", "v1")
    assert evidence is not None and (evidence.return_pct, evidence.pairs) == (D("40"), 1)


def test_the_api_refuses_a_typed_backtest_figure() -> None:
    api = Api()
    r = api.call(
        "POST",
        "/strategies/ema_adx/promote",
        "tok-admin",
        body={"backtest_return_pct": "50"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "typed_evidence_refused"
