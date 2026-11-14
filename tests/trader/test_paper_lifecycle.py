"""The paper lifecycle: simulated fills, stops, exits, and their separation from the live book.

All numbers are TEST values. Nothing here calls an exchange.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from aidss_trader.connector.types import Candle
from aidss_trader.db.models import (
    EquitySnapshot,
    Fill,
    OrderIntentRow,
    OrderRow,
    PaperEquitySnapshot,
    PositionStop,
    StrategyRow,
)
from aidss_trader.paper import CostModel, PaperConfig
from aidss_trader.runtime import accounting
from aidss_trader.runtime.paper_lifecycle import PaperBook
from aidss_trader.runtime.settings_store import (
    PaperSettings,
    get_paper_settings,
    set_paper_settings,
)
from tests.trader.test_runtime_wiring import PAPER_VALUES, TF, World, warm

D = Decimal
T0 = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(seconds=TF)

SETTINGS = PaperSettings(
    PaperConfig(D("0.1"), D("1"), CostModel(D("0.1"), D("0.2"), D("0.1"), D("0.01"))),
    D("100000000"),
)


def close(a: Decimal, b: Decimal) -> bool:
    """SQLite stores Numeric as a float; PostgreSQL is exact. Compare to a billionth."""
    return abs(a - b) < D("1e-9")


def candle(i: int, o, h, low, c) -> Candle:
    return Candle(T0 + i * STEP, D(o), D(h), D(low), D(c), D(1))


def put_intent(session, side="BUY", signal_candle=0, price="100", qty="2", stop="90"):
    identity = f"v1|BTCIDR|{(T0 + signal_candle * STEP).isoformat()}|{side}"
    session.add(
        OrderIntentRow(
            identity=identity,
            origin="PAPER",
            strategy_version="v1",
            pair="BTCIDR",
            side=side,
            entry_price=D(price),
            quantity=D(qty),
            stop_price=D(stop) if side == "BUY" else None,
            risk_amount_idr=None,
            rule_snapshot={},
            state="PAPER_RECORDED",
            created_at=T0,
        )
    )
    session.commit()
    return identity


def advance(session, candles, settings=SETTINGS):
    out = PaperBook(settings).advance(session, "BTCIDR", candles, None)
    session.commit()
    return out


def start(session, intent_kwargs=None):
    """Cursor set at candle 0 (the signal candle); the intent waits for candle 1."""
    advance(session, [candle(0, 100, 101, 99, 100)])
    return put_intent(session, **(intent_kwargs or {}))


def paper_position(session):
    positions, events = accounting.replay_origin(session, "PAPER")
    return positions.get("BTCIDR"), events


# ------------------------------------------------------------------ the cursor


def test_the_first_run_simulates_nothing_backwards(session) -> None:
    put_intent(session)
    out = advance(session, [candle(i, 100, 101, 99, 100) for i in range(5)])
    assert out.candles == 0 and session.scalars(select(Fill)).all() == []


def test_a_restart_neither_replays_nor_skips_a_candle(session) -> None:
    start(session)
    cs = [candle(0, 100, 101, 99, 100), candle(1, 100, 101, 95, 100)]
    assert advance(session, cs).entries == 1
    assert advance(session, cs).candles == 0  # a new PaperBook, same candles: nothing repeats
    assert len(session.scalars(select(Fill)).all()) == 1


def test_an_intent_that_missed_its_one_candle_expires(session) -> None:
    start(session)
    # Candle 1 never arrived (a gap); candle 2 is too late for a one-candle limit order.
    out = advance(session, [candle(0, 100, 101, 99, 100), candle(2, 100, 101, 90, 100)])
    assert out.entries == 0
    assert session.scalar(select(OrderIntentRow)).state == "PAPER_EXPIRED"


# ---------------------------------------------------------------------- entries


def test_a_limit_entry_fills_only_if_price_trades_through(session) -> None:
    start(session)
    advance(session, [candle(0, 100, 101, 99, 100), candle(1, 102, 103, 100, 102)])  # touches
    intent = session.scalar(select(OrderIntentRow))
    assert intent.state == "PAPER_UNFILLED" and session.scalars(select(Fill)).all() == []


def test_a_fill_is_a_paper_order_and_paper_fill_with_costs_and_a_stop(session) -> None:
    start(session)
    advance(session, [candle(0, 100, 101, 99, 100), candle(1, 102, 103, 98, 101)])
    order = session.scalar(select(OrderRow))
    fill = session.scalar(select(Fill))
    assert order.origin == "PAPER" and order.purpose == "ENTRY" and order.state == "FILLED"
    assert fill.origin == "PAPER" and fill.price == D("100") and fill.quantity == D("2")
    assert close(fill.commission, D("200") * D("0.21") / 100) and fill.is_maker is True
    assert fill.exchange_trade_id.startswith("paper-") and order.client_order_id.startswith("pp")
    stop = session.scalar(select(PositionStop))
    assert stop.origin == "PAPER" and stop.stop_price == D("90")
    assert session.scalar(select(OrderIntentRow)).state == "PAPER_FILLED"


def test_a_partial_fill_takes_the_configured_fraction_and_abandons_the_rest(session) -> None:
    half = PaperSettings(PaperConfig(D("0.1"), D("0.5"), SETTINGS.config.costs), D("100000000"))
    advance(session, [candle(0, 100, 101, 99, 100)], half)
    put_intent(session)
    advance(session, [candle(0, 100, 101, 99, 100), candle(1, 102, 103, 98, 101)], half)
    order = session.scalar(select(OrderRow))
    assert order.executed_qty == D("1") and order.state == "CANCELLED"


def test_only_one_paper_position_at_a_time(session) -> None:
    start(session)
    advance(session, [candle(0, 100, 101, 99, 100), candle(1, 102, 103, 98, 101)])
    put_intent(session, signal_candle=1, price="101", qty="1")
    advance(session, [candle(1, 102, 103, 98, 101), candle(2, 102, 103, 99, 101)])
    states = {i.state for i in session.scalars(select(OrderIntentRow))}
    assert "PAPER_VOID" in states
    pos, _ = paper_position(session)
    assert pos.quantity == D("2")


# ------------------------------------------------------------------------ stops


def filled(session):
    start(session)
    advance(session, [candle(0, 100, 101, 99, 100), candle(1, 102, 103, 98, 101)])


def test_a_stop_exits_at_the_stop_plus_slippage_and_the_loss_is_net_of_costs(session) -> None:
    filled(session)
    out = advance(
        session,
        [candle(0, 100, 101, 99, 100), candle(1, 102, 103, 98, 101), candle(2, 101, 101, 89, 95)],
    )
    assert out.exits == 1
    sell = session.scalars(select(Fill).where(Fill.side == "SELL")).one()
    assert close(sell.price, D("90") * D("0.999"))  # the stop, slipped against the trader
    assert sell.is_maker is False
    pos, events = paper_position(session)
    assert pos is None and len(events) == 1 and events[0].pnl < 0
    gross = (sell.price - D("100")) * D("2")
    assert events[0].pnl < gross  # costs only ever make it worse


def test_a_gap_through_the_stop_exits_at_the_open_not_at_the_stop(session) -> None:
    filled(session)
    advance(
        session,
        [candle(0, 100, 101, 99, 100), candle(1, 102, 103, 98, 101), candle(2, 80, 85, 78, 82)],
    )
    sell = session.scalars(select(Fill).where(Fill.side == "SELL")).one()
    assert close(sell.price, D("80") * D("0.999"))


def test_an_entry_and_a_stop_in_the_same_candle_assumes_the_stop_was_hit(session) -> None:
    start(session)
    advance(session, [candle(0, 100, 101, 99, 100), candle(1, 100, 100, 85, 95)])
    fills = session.scalars(select(Fill)).all()
    assert sorted(f.side for f in fills) == ["BUY", "SELL"]
    pos, events = paper_position(session)
    assert pos is None and events[0].pnl < 0  # buy-first replay despite the same instant


def test_the_stop_never_triggers_on_a_candle_that_stays_above_it(session) -> None:
    filled(session)
    out = advance(
        session,
        [candle(0, 100, 101, 99, 100), candle(1, 102, 103, 98, 101), candle(2, 101, 110, 91, 105)],
    )
    assert out.exits == 0 and paper_position(session)[0].quantity == D("2")


# ------------------------------------------------------------------ signal exit


def test_a_signal_exit_sells_at_the_next_open_with_taker_costs(session) -> None:
    filled(session)
    put_intent(session, side="SELL", signal_candle=1, price="105", qty="2")
    advance(
        session,
        [candle(1, 102, 103, 98, 101), candle(2, 110, 112, 109, 111)],
    )
    sell = session.scalars(select(Fill).where(Fill.side == "SELL")).one()
    assert close(sell.price, D("110") * D("0.999"))
    order = session.scalars(select(OrderRow).where(OrderRow.side == "SELL")).one()
    assert order.purpose == "EXIT" and order.origin == "PAPER"
    pos, events = paper_position(session)
    assert pos is None and events[0].pnl > 0


def test_a_signal_exit_with_nothing_to_sell_is_void(session) -> None:
    start(session, {"side": "SELL", "signal_candle": 0, "price": "100", "qty": "1"})
    advance(session, [candle(0, 100, 101, 99, 100), candle(1, 100, 101, 99, 100)])
    assert session.scalar(select(OrderIntentRow)).state == "PAPER_VOID"
    assert session.scalars(select(Fill)).all() == []


def test_the_stop_wins_when_it_and_a_signal_exit_share_a_candle(session) -> None:
    filled(session)
    put_intent(session, side="SELL", signal_candle=1, price="105", qty="2")
    advance(
        session,
        [candle(1, 102, 103, 98, 101), candle(2, 101, 101, 85, 90)],
    )
    sells = session.scalars(select(OrderRow).where(OrderRow.side == "SELL")).all()
    assert [o.purpose for o in sells] == ["STOP"]
    assert session.scalars(
        select(OrderIntentRow).where(OrderIntentRow.side == "SELL")
    ).one().state == ("PAPER_VOID")


# --------------------------------------------------------- separation from live


def test_paper_fills_never_appear_in_the_live_book_or_the_live_equity_series(session) -> None:
    filled(session)
    live_positions, live_events = accounting.replay_live(session)
    assert live_positions == {} and live_events == []
    accounting.record_paper_equity(session, D("1000"), T0)
    assert session.scalars(select(EquitySnapshot)).all() == []  # live peak untouched
    assert len(session.scalars(select(PaperEquitySnapshot)).all()) == 1
    assert accounting.drawdown_pct(session, D("500")) == 0  # live drawdown ignores paper


def test_paper_equity_marks_open_positions_and_carries_unpriced_ones_at_cost(session) -> None:
    filled(session)
    positions, events = accounting.replay_origin(session, "PAPER")
    start_equity = D("100000000")
    flat = accounting.paper_equity(start_equity, positions, events, {"BTCIDR": D("100")})
    up = accounting.paper_equity(start_equity, positions, events, {"BTCIDR": D("110")})
    assert close(up - flat, D("20"))  # 2 units x 10
    # A position with no price is carried at cost: dropping it would invent a loss.
    assert close(accounting.paper_equity(start_equity, positions, events, {}), start_equity)


def test_paper_drawdown_is_measured_from_stored_simulated_equity(session) -> None:
    assert accounting.paper_drawdown_pct(session, T0) is None  # no evidence is not zero
    for i, e in enumerate(["100", "120", "90", "110"]):
        accounting.record_paper_equity(session, D(e), T0 + timedelta(hours=i))
    assert accounting.paper_drawdown_pct(session, T0) == D("25")  # 120 -> 90
    assert accounting.paper_drawdown_pct(session, T0 + timedelta(hours=3)) == 0
    assert accounting.paper_drawdown_pct(session, T0 + timedelta(days=9)) is None


# ----------------------------------------------------------------- the settings


def test_paper_settings_need_every_number_and_valid_ranges(session) -> None:
    assert get_paper_settings(session) is None
    with pytest.raises(ValueError, match="missing"):
        set_paper_settings(session, {"slippage_pct": D("0.1")}, by="owner")
    with pytest.raises(ValueError):
        set_paper_settings(session, {**PAPER_VALUES, "partial_fill_fraction": D("0")}, by="owner")
    with pytest.raises(ValueError):
        set_paper_settings(session, {**PAPER_VALUES, "start_equity_idr": D("0")}, by="owner")
    set_paper_settings(session, PAPER_VALUES, by="owner")
    ps = get_paper_settings(session)
    assert ps.config.costs.taker_fee_pct == D("0.2") and ps.start_equity_idr == D("100000000")


# --------------------------------------------------------------- the runtime


def add_candle(w: World, o, h, low, c) -> None:
    rows = w.env.mock.candles[("BTCIDR", "240")]
    ts = rows[-1][0] + TF
    rows.append((ts, str(o), str(h), str(low), str(c), "1"))
    w.env.mock.advance(TF * 1000)


def test_without_the_owners_cost_model_nothing_is_simulated_or_recorded() -> None:
    w = World("PAPER")
    with w.factory() as s:
        s.get(
            __import__("aidss_trader.db.models", fromlist=["TraderSetting"]).TraderSetting,
            "paper_config",
        ).value = {}
        s.commit()
    report = warm(w, 3)
    assert w.rows(OrderIntentRow) == []
    assert any("paper cost model" in x for x in report.skipped)


def test_end_to_end_a_paper_signal_becomes_a_paper_fill_with_no_exchange_order() -> None:
    w = World("PAPER")
    warm(w, 2)
    intent = w.rows(OrderIntentRow)[0]
    assert intent.state == "PAPER_RECORDED" and intent.origin == "PAPER"
    price = intent.entry_price
    add_candle(w, price, price + 1_000_000, price - 5_000_000, price + 500_000)
    w.cycle()
    assert w.rows(OrderIntentRow)[0].state == "PAPER_FILLED"
    fills = w.rows(Fill)
    assert len(fills) == 1 and fills[0].origin == "PAPER"
    assert w.posts() == 0  # not one order request reached the exchange
    with w.factory() as s:
        assert accounting.replay_live(s) == ({}, [])
        assert s.scalars(select(PositionStop)).one().origin == "PAPER"


def test_end_to_end_a_paper_stop_closes_the_position_and_is_counted_for_promotion() -> None:
    w = World("PAPER")
    warm(w, 2)
    intent = w.rows(OrderIntentRow)[0]
    price = intent.entry_price
    add_candle(w, price, price + 1_000_000, price - 5_000_000, price)
    w.cycle()
    add_candle(w, price, price, intent.stop_price - 10_000_000, intent.stop_price - 5_000_000)
    w.cycle()
    sells = [f for f in w.rows(Fill) if f.side == "SELL"]
    assert len(sells) == 1 and sells[0].origin == "PAPER"
    with w.factory() as s:
        pos, events = accounting.replay_origin(s, "PAPER")
        assert pos == {} and events[0].pnl < 0
        assert s.get(StrategyRow, "ema_adx").mode == "PAPER"
    assert w.rows(PaperEquitySnapshot)  # equity is recorded for the drawdown gate


def test_a_halted_trader_still_simulates_paper_stops_but_makes_no_new_decisions() -> None:
    w = World("PAPER")
    warm(w, 2)
    intent = w.rows(OrderIntentRow)[0]
    price = intent.entry_price
    add_candle(w, price, price + 1_000_000, price - 5_000_000, price)
    w.cycle()
    from aidss_trader.killswitch import KillSwitch

    with w.factory() as s:
        KillSwitch(s, w.env.client, now=w.now).activate("HALT", "owner", "owner")
    add_candle(w, price, price, intent.stop_price - 10_000_000, intent.stop_price - 5_000_000)
    report = w.cycle()
    assert [f for f in w.rows(Fill) if f.side == "SELL"]  # the stop was simulated
    assert any("not RUNNING" in x for x in report.skipped)
    assert len(w.rows(OrderIntentRow)) == 1  # and no new intent was created


def test_the_paper_config_and_promotion_evidence_over_the_api() -> None:
    from tests.trader.test_runtime_wiring import api_for

    w = World("PAPER", configured=False)
    call = api_for(w)
    assert call("GET", "/paper-config").json()["data"] == {"configured": False, "paper_fills": 0}
    assert call("GET", "/paper-config").json()["meta"]["origin"] == "PAPER"
    cfg = {k: str(v) for k, v in PAPER_VALUES.items()}
    assert call("PUT", "/paper-config", cfg).status_code == 200
    got = call("GET", "/paper-config").json()["data"]
    assert got["configured"] is True and got["taker_fee_pct"] == "0.2"
    with w.factory() as s:
        from aidss_trader.promotion import Promotion

        Promotion(s).register("ema_adx", "v1")
        for i, e in enumerate(["100", "120", "90"]):
            accounting.record_paper_equity(s, D(e), datetime.now(UTC) + timedelta(seconds=i))
        s.commit()
    gates = call("GET", "/strategies/ema_adx/promotion").json()["data"]["gates"]
    dd = next(g for g in gates if g["name"] == "paper_drawdown")
    assert D(dd["measured"]) == D("25")  # computed from the stored series, not supplied by anyone


def test_paper_config_rejects_negative_or_absurd_costs_over_the_api() -> None:
    from tests.trader.test_runtime_wiring import api_for

    w = World("PAPER", configured=False)
    call = api_for(w)
    cfg = {k: str(v) for k, v in PAPER_VALUES.items()}
    for bad in (
        {"taker_fee_pct": "-0.1"},
        {"slippage_pct": "101"},
        {"tax_pct": "-1"},
        {"partial_fill_fraction": "1.5"},
        {"start_equity_idr": "-5"},
    ):
        assert call("PUT", "/paper-config", {**cfg, **bad}).status_code == 400, bad
    assert call("PUT", "/paper-config", cfg).status_code == 200


def test_flattering_the_cost_model_after_paper_fills_exist_needs_a_step_up() -> None:
    from tests.trader.test_runtime_wiring import api_for

    w = World("PAPER")
    call = api_for(w)
    cfg = {k: str(v) for k, v in PAPER_VALUES.items()}
    # No paper history yet: any change is free, because nothing has been simulated under it.
    assert call("PUT", "/paper-config", {**cfg, "taker_fee_pct": "0.05"}).status_code == 200
    assert call("GET", "/paper-config").json()["data"]["paper_fills"] == 0
    with w.factory() as s:
        start(s)
        advance(s, [candle(0, 100, 101, 99, 100), candle(1, 102, 103, 98, 101)])
    assert call("GET", "/paper-config").json()["data"]["paper_fills"] >= 1
    # Harsher assumptions never need a password; flattering ones do.
    harsher = {**cfg, "taker_fee_pct": "0.5", "slippage_pct": "0.3"}
    assert call("PUT", "/paper-config", harsher).status_code == 200
    flat = {**harsher, "slippage_pct": "0.0"}
    r = call("PUT", "/paper-config", flat)
    assert r.status_code == 403 and r.json()["error"]["code"] == "step_up_required"
    grant = call(
        "POST", "/stepup", {"email": "o@x", "password": "pw", "scope": "RAISE_LIMIT"}
    ).json()["data"]["grant"]
    ok = call("PUT", "/paper-config", flat, **{"X-Step-Up": grant})
    assert ok.status_code == 200
    # Start capital alone is not a flattery.
    assert (
        call("PUT", "/paper-config", {**flat, "start_equity_idr": "200000000"}).status_code == 200
    )
