"""The 4-hour signals' settings, history and summary over the API (ADR-067). SQLite only.

The summary numbers are a simulation from public candles; these tests pin that they are labelled so
and that a correlation is withheld until there is enough data."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from aidss_trader.db.models import SignalTrade
from aidss_trader.signals_config import loosens, parse_settings, unset_fields
from aidss_trader.signals_stats import MIN_FOR_CORRELATION, Row, spearman, summarize
from tests.trader.test_runtime_wiring import World, api_for
from tests.trader.test_signals_settings_api import FULL, grant, put

H4 = {
    "enabled": True,
    "strategies": ["DONCHIAN", "SPIKE"],
    "donchian_n": 20,
    "vol_period": 20,
    "vol_mult": "2",
    "range_mult": "1.5",
    "min_score": 60,
    "allow_short": False,
    "max_hold_bars": 30,
    "fee_pct": "0.1",
    "slippage_pct": "0.05",
    "drift_r": "0.5",
}


def with_h4(**over) -> dict:
    return {**FULL, "h4": {**H4, **over}}


# ------------------------------------------------------------------------------- settings


def test_h4_is_off_by_default_and_then_needs_every_number() -> None:
    assert parse_settings(FULL).h4.enabled is False
    assert not [f for f in unset_fields(parse_settings(FULL)) if f.startswith("h4.")]
    bare = parse_settings({**FULL, "h4": {"enabled": True}})
    missing = {f for f in unset_fields(bare) if f.startswith("h4.")}
    assert {"h4.min_score", "h4.drift_r", "h4.fee_pct", "h4.donchian_n"} <= missing
    assert not [f for f in unset_fields(parse_settings(with_h4())) if f.startswith("h4.")]


def test_loosening_the_h4_rules_is_detected() -> None:
    base = parse_settings(with_h4())
    assert not loosens(base, base)
    for over in (
        {"min_score": 50},
        {"vol_mult": "1.5"},
        {"range_mult": "1"},
        {"donchian_n": 10},
        {"allow_short": True},
        {"strategies": ["DONCHIAN", "SPIKE"], "min_score": 1},
    ):
        assert loosens(base, parse_settings(with_h4(**over))), over
    for over in ({"min_score": 70}, {"vol_mult": "3"}, {"enabled": False}):
        assert not loosens(base, parse_settings(with_h4(**over))), over
    narrow = parse_settings(with_h4(strategies=["DONCHIAN"]))
    assert loosens(narrow, base)  # adding a strategy acts more readily


def test_bad_h4_values_are_refused() -> None:
    call = api_for(World("PAPER", configured=False))
    assert put(call, with_h4(strategies=["MOON"])).status_code == 400
    assert put(call, with_h4(min_score=500)).status_code == 400


def test_h4_settings_round_trip_and_loosening_needs_the_password() -> None:
    call = api_for(World("PAPER", configured=False))
    assert put(call, with_h4()).status_code == 200
    got = call("GET", "/signals/config").json()["data"]
    assert got["settings"]["h4"]["min_score"] == 60 and got["settings"]["h4"]["vol_mult"] == "2"
    assert got["ready"] is True
    r = put(call, with_h4(min_score=40))
    assert r.status_code in (401, 403)
    assert put(call, with_h4(min_score=40), **grant(call)).status_code == 200
    assert put(call, with_h4(min_score=90)).status_code == 200  # tighter: no password


# ------------------------------------------------------------------------------ statistics


def row(score, net, strategy="DONCHIAN", side="LONG", state="CLOSED", tp=0, outcome="SL") -> Row:
    return Row(strategy, side, score, state, outcome, tp, net)


def test_spearman_handles_ties_and_undefined_cases() -> None:
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 1, 1], [1, 2, 3]) is None
    assert spearman([1, 2], [1, 2]) is None
    assert spearman([1, 2, 2, 3], [1, 2, 3, 4]) == pytest.approx(0.9486833, rel=1e-5)


def test_summary_counts_only_closed_signals_and_gives_an_error_bar() -> None:
    rows = [
        row(90, 1.5, tp=1, outcome="TP3"),
        row(85, -1.1),
        row(70, 0.2, "SPIKE", tp=1, outcome="BE_AFTER_TP1"),
        row(65, None, state="PENDING", outcome=None),
        row(55, None, state="SKIPPED", outcome="SKIPPED_DRIFT"),
    ]
    out = summarize(rows)
    assert out["simulated"] is True and out["total"] == 5
    assert out["states"] == {"CLOSED": 3, "PENDING": 1, "SKIPPED": 1}
    o = out["overall"]
    assert o["closed"] == 3 and o["wins"] == 2 and o["win_rate"] == pytest.approx(2 / 3)
    assert o["tp1_rate"] == pytest.approx(2 / 3) and o["mean_net_r"] == pytest.approx(0.2)
    assert o["stderr_net_r"] is not None and o["stderr_net_r"] > 0
    assert out["by_strategy"]["SPIKE"]["closed"] == 1
    assert out["by_strategy"]["SPIKE"]["stderr_net_r"] is None  # one point has no error bar
    assert out["by_score"]["80-100"]["closed"] == 2 and out["by_score"]["0-59"]["closed"] == 0
    assert out["by_score"]["0-59"]["win_rate"] is None
    assert out["score_correlation"] is None


def test_the_correlation_appears_only_with_enough_closed_signals() -> None:
    few = [row(50 + i, float(i)) for i in range(MIN_FOR_CORRELATION - 1)]
    assert summarize(few)["score_correlation"] is None
    enough = [row(50 + i, float(i)) for i in range(MIN_FOR_CORRELATION)]
    assert summarize(enough)["score_correlation"] == pytest.approx(1.0)
    assert summarize([])["overall"]["closed"] == 0


# ---------------------------------------------------------------------------------- the API


def seed(w: World) -> None:
    now = datetime.now(UTC)
    with w.factory() as s:
        for i, (strategy, symbol, side, score, state, outcome, net) in enumerate(
            [
                ("DONCHIAN", "ETHUSDT", "LONG", 90, "CLOSED", "TP3", D("1.8")),
                ("SPIKE", "SOLUSDT", "LONG", 62, "CLOSED", "SL", D("-1.1")),
                ("DONCHIAN", "ADAUSDT", "SHORT", 75, "PENDING", None, None),
            ]
        ):
            s.add(
                SignalTrade(
                    id=uuid.uuid4(),
                    signal_id=f"aidss4h-{strategy.lower()}-{symbol}-{side.lower()}-{i}",
                    strategy=strategy,
                    symbol=symbol,
                    side=side,
                    mode="SHADOW",
                    published=False,
                    candle_open=now - timedelta(hours=8),
                    issued_at=now - timedelta(hours=4 * (3 - i)),
                    score=score,
                    components={"breakout": 30.0},
                    entry=D("100"),
                    stop=D("95"),
                    tp1=D("105"),
                    tp2=D("110"),
                    tp3=D("120"),
                    atr=D("2.5"),
                    btc_bias="bullish",
                    state=state,
                    outcome=outcome,
                    tp_hits=3 if outcome == "TP3" else 0,
                    net_r=net,
                    gross_r=None if net is None else net + D("0.05"),
                    bars_held=0 if net is None else 4,
                    updated_at=now,
                )
            )
        s.commit()


def test_the_trade_list_filters_and_is_labelled_simulated() -> None:
    w = World("PAPER", configured=False)
    call = api_for(w)
    seed(w)
    body = call("GET", "/signals/trades").json()
    assert body["data"]["total"] == 3 and body["data"]["simulated"] is True
    assert body["meta"]["origin"] == "PAPER"
    assert call("GET", "/signals/trades?strategy=spike").json()["data"]["items"][0]["symbol"] == (
        "SOLUSDT"
    )
    assert call("GET", "/signals/trades?state=pending").json()["data"]["total"] == 1
    assert call("GET", "/signals/trades?side=short&symbol=adausdt").json()["data"]["total"] == 1
    first = call("GET", "/signals/trades?limit=1").json()["data"]["items"][0]
    assert first["symbol"] == "ADAUSDT" and first["net_r"] is None  # newest first
    page = call("GET", "/signals/trades?limit=1&offset=2").json()["data"]
    assert page["total"] == 3 and page["items"][0]["symbol"] == "ETHUSDT"


def test_the_summary_endpoint_reports_what_the_rows_say() -> None:
    w = World("PAPER", configured=False)
    call = api_for(w)
    assert call("GET", "/signals/trades/summary").json()["data"]["total"] == 0
    seed(w)
    d = call("GET", "/signals/trades/summary").json()["data"]
    assert d["simulated"] is True and d["total"] == 3 and d["overall"]["closed"] == 2
    assert d["overall"]["mean_net_r"] == pytest.approx(0.35)
    assert d["states"] == {"CLOSED": 2, "PENDING": 1} and d["score_correlation"] is None
