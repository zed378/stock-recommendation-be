"""T4: risk engine, order manager, exit monitor, kill switch, reconciliation.

Every limit below is a TEST value declared here; none is a default or the owner's.
All exchange traffic goes to the synthetic mock.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from aidss_trader.config.limits import RiskLimits
from aidss_trader.connector.types import PairInfo
from aidss_trader.db.models import (
    Fill,
    KillSwitchStep,
    OrderRow,
    ReconciliationDifference,
    RiskCheckResult,
)
from aidss_trader.exits import ExitMonitor, StopWidenRefused, WatchedPosition
from aidss_trader.intents import Intent, client_order_id
from aidss_trader.killswitch import KillSwitch, KillSwitchRefused
from aidss_trader.market_data import build_pair_rules
from aidss_trader.orders import OrderState
from aidss_trader.orders.manager import OrderManager, OrderRefused
from aidss_trader.reconcile import reconcile, windows
from aidss_trader.risk import RiskContext, breakers, evaluate, persist
from tests.trader.test_connector_contract import Env

D = Decimal
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)

LIMITS = RiskLimits(
    risk_per_trade_pct=D("1"),
    max_daily_loss_idr=D("1000000"),
    max_drawdown_pct=D("20"),
    max_consecutive_losses=3,
    max_open_positions=2,
    max_exposure_per_pair_pct=D("50"),
    max_total_exposure_pct=D("80"),
    max_order_idr=D("50000000"),
    price_deviation_pct=D("2"),
    freshness_limit_s=60,
    cooldown_s=0,
    order_rate_limit=5,
)
PAIR = PairInfo(
    pair="BTCIDR",
    ticker_id="btc_idr",
    base_asset="IDR",
    quote_asset="BTC",
    quantity_increment=D("0.00000001"),
    min_base_idr=D("50000"),
    min_traded_qty=D("0.0001"),
    maintenance=False,
    suspended=False,
    maker_fee_pct=None,
    taker_fee_pct=None,
    raw={"pricescale": 1000},
)
RULES = build_pair_rules([PAIR], {"btc_idr": D("1000")})["BTCIDR"]


def intent(**kw) -> Intent:
    base = dict(
        identity="v1|BTCIDR|2026-11-14T08:00:00+00:00|BUY",
        strategy_version="v1",
        pair="BTCIDR",
        side="BUY",
        entry_price=D("1236777000"),
        quantity=D("0.01"),
        stop_price=D("1200000000"),
        risk_amount_idr=D("367770"),
        rule_snapshot={},
        mode="AUTO",
        signal_candle_open=NOW,
    )
    base.update(kw)
    return Intent(**base)


def ctx(**kw) -> RiskContext:
    base = dict(
        now=NOW,
        trading_state="RUNNING",
        mode="AUTO",
        limits=LIMITS,
        rules=RULES,
        equity_idr=D("100000000"),
        reference_price=D("1236777000"),
        market_data_age_s=5.0,
        open_positions=0,
        pair_exposure_idr=D("0"),
        total_exposure_idr=D("0"),
        daily_realised_loss_idr=D("0"),
        drawdown_pct=D("0"),
        consecutive_losses=0,
        seconds_since_last_order=None,
        orders_last_minute=0,
        unknown_orders=0,
        reconciliation_clean=True,
        clock_ok=True,
        permissions_ok=True,
        has_position=True,
    )
    base.update(kw)
    return RiskContext(**base)


def failed(decision) -> set[str]:
    return {c.name for c in decision.failed}


# ------------------------------------------------------------------------ risk


def test_a_clean_entry_passes_every_check() -> None:
    d = evaluate(intent(), ctx(), "ENTRY")
    assert d.approved and not d.failed


@pytest.mark.parametrize(
    ("override", "check"),
    [
        ({"trading_state": "HALTED"}, "trading_state"),
        ({"market_data_age_s": 61.0}, "market_data_fresh"),
        ({"reference_price": D("1000000000")}, "price_deviation"),
        ({"open_positions": 2}, "open_positions"),
        ({"total_exposure_idr": D("80000000")}, "total_exposure"),
        ({"pair_exposure_idr": D("50000000")}, "pair_exposure"),
        ({"daily_realised_loss_idr": D("1000000")}, "daily_loss"),
        ({"drawdown_pct": D("20")}, "drawdown"),
        ({"consecutive_losses": 3}, "consecutive_losses"),
        ({"orders_last_minute": 5}, "order_rate"),
        ({"unknown_orders": 1}, "unknown_orders"),
        ({"reconciliation_clean": False}, "reconciliation_clean"),
        ({"clock_ok": False}, "clock"),
        ({"permissions_ok": False}, "permissions"),
        ({"in_trading_window": False}, "trading_window"),
    ],
)
def test_each_entry_check_can_refuse_on_its_own(override, check) -> None:
    d = evaluate(intent(), ctx(**override), "ENTRY")
    assert not d.approved and check in failed(d)


def test_cooldown_refuses_a_too_soon_order() -> None:
    limits = replace(LIMITS, cooldown_s=300)
    assert "cooldown" in failed(
        evaluate(intent(), ctx(limits=limits, seconds_since_last_order=10), "ENTRY")
    )
    assert evaluate(intent(), ctx(limits=limits, seconds_since_last_order=301), "ENTRY").approved


def test_an_oversized_order_and_an_oversized_risk_are_refused() -> None:
    assert "order_value" in failed(evaluate(intent(quantity=D("0.5")), ctx(), "ENTRY"))
    assert "risk_per_trade" in failed(
        evaluate(intent(risk_amount_idr=D("5000000")), ctx(), "ENTRY")
    )


def test_an_unset_limit_fails_the_entry_and_names_it() -> None:
    d = evaluate(intent(), ctx(limits=replace(LIMITS, max_order_idr=None)), "ENTRY")
    assert not d.approved
    assert next(c for c in d.checks if c.name == "limits_set").observed == "max_order_idr"
    assert not evaluate(intent(), ctx(limits=None), "ENTRY").approved


def test_an_entry_without_a_stop_is_refused() -> None:
    assert "stop_present" in failed(evaluate(intent(stop_price=None), ctx(), "ENTRY"))


def test_emergency_profile_ignores_loss_limits_but_not_malformed_orders() -> None:
    stop = intent(side="SELL", stop_price=None)
    hot = ctx(
        daily_realised_loss_idr=D("9999999"),
        drawdown_pct=D("90"),
        consecutive_losses=99,
        trading_state="HALTED",
        limits=None,
    )
    assert evaluate(
        stop, hot, "EMERGENCY"
    ).approved  # a stop must never be refused for a loss limit
    assert not evaluate(intent(side="BUY"), hot, "EMERGENCY").approved  # emergencies only sell
    assert not evaluate(stop, ctx(has_position=False), "EMERGENCY").approved
    assert not evaluate(intent(side="SELL", quantity=D("0.00001")), ctx(), "EMERGENCY").approved


def test_every_check_is_persisted_including_passes(session) -> None:
    d = evaluate(intent(), ctx(open_positions=2), "ENTRY")
    persist(session, intent(), d, NOW)
    rows = session.scalars(select(RiskCheckResult)).all()
    assert len(rows) == len(d.checks)
    assert any(not r.passed and r.check == "open_positions" for r in rows)


def test_breakers_halt_or_cancel_and_never_flatten() -> None:
    hits = breakers(
        ctx(
            daily_realised_loss_idr=D("2000000"),
            drawdown_pct=D("30"),
            consecutive_losses=5,
            unknown_orders=1,
            permissions_ok=False,
            market_data_age_s=999.0,
        )
    )
    assert {b.name for b in hits} >= {
        "daily_loss",
        "drawdown",
        "consecutive_losses",
        "unknown_order",
        "permissions",
        "stale_data",
    }
    assert {b.tier for b in hits} <= {"HALT", "CANCEL"}
    assert breakers(ctx()) == []


# --------------------------------------------------------------- order manager


@pytest.fixture
def world(session):
    env = Env()
    env.mock.books["BTCIDR"] = ("1236777000", "0.5", "1236800000", "0.5")
    mgr = OrderManager(session, env.client, now=lambda: NOW, sleep=lambda s: env.sleeps.append(s))
    return env, mgr, session


def test_an_approved_entry_is_written_ahead_then_sent_and_open(world) -> None:
    env, mgr, session = world
    res = mgr.submit(intent(), ctx())
    assert res.order is not None and res.order.state == OrderState.OPEN.value
    assert res.order.client_order_id == client_order_id(intent().identity)
    assert res.order.exchange_order_id and res.order.time_in_force == "MOC"
    creates = [r for r in env.mock.requests if r["method"] == "POST"]
    assert len(creates) == 1


def test_the_order_row_is_committed_before_the_request_is_sent(world) -> None:
    env, mgr, session = world
    seen: list[str] = []
    original = env.client.create_order

    def spy(**kw):
        seen.append(
            session.scalar(
                select(OrderRow.state).where(OrderRow.client_order_id == kw["client_order_id"])
            )
        )
        return original(**kw)

    env.client.create_order = spy  # type: ignore[method-assign]
    mgr.submit(intent(), ctx())
    assert seen == [OrderState.SUBMITTING.value]


def test_a_risk_refusal_sends_nothing_and_keeps_the_explanation(world) -> None:
    env, mgr, session = world
    res = mgr.submit(intent(), ctx(trading_state="HALTED"))
    assert res.order is None and not res.decision.approved
    assert not [r for r in env.mock.requests if r["method"] == "POST"]
    assert session.scalars(select(RiskCheckResult)).all()
    assert session.scalars(select(OrderRow)).all() == []


def test_paper_intents_and_non_emergency_market_never_reach_the_exchange(world) -> None:
    env, mgr, _ = world
    with pytest.raises(OrderRefused):
        mgr.submit(intent(mode="PAPER"), ctx())
    with pytest.raises(OrderRefused):
        mgr.submit(intent(), ctx(), order_type="MARKET")
    assert not [r for r in env.mock.requests if r["method"] == "POST"]


def test_a_timeout_on_create_leaves_unknown_and_is_never_resent(world) -> None:
    env, mgr, session = world
    env.mock.inject_timeout("POST", "/api/v2/order")
    res = mgr.submit(intent(), ctx())
    assert res.order.state == OrderState.UNKNOWN.value
    assert len([r for r in env.mock.requests if r["method"] == "POST"]) == 1  # one attempt only


def test_unknown_resolves_to_open_by_querying_when_the_exchange_did_create_it(world) -> None:
    env, mgr, session = world
    env.mock.inject_timeout("POST", "/api/v2/order")
    order = mgr.submit(intent(), ctx()).order
    # The request actually reached the exchange before the timeout: place it there, then resolve.
    env.client.create_order(
        symbol="BTCIDR",
        side="BUY",
        order_type="LIMIT",
        price=D("1236777000"),
        quantity=D("0.01"),
        client_order_id=order.client_order_id,
    )
    posts_before = len([r for r in env.mock.requests if r["method"] == "POST"])
    assert mgr.resolve_unknown(order) is True
    assert order.state == OrderState.OPEN.value
    assert len([r for r in env.mock.requests if r["method"] == "POST"]) == posts_before  # no resend


def test_unknown_stays_unknown_when_never_found_after_the_configured_queries(world) -> None:
    env, mgr, session = world
    env.mock.inject_timeout("POST", "/api/v2/order")
    order = mgr.submit(intent(), ctx()).order
    gets_before = len([r for r in env.mock.requests if r["method"] == "GET"])
    assert mgr.resolve_unknown(order) is False
    assert order.state == OrderState.UNKNOWN.value
    assert len([r for r in env.mock.requests if r["method"] == "GET"]) - gets_before >= 5
    assert not [r for r in env.mock.requests if r["method"] == "POST"][1:]


def test_an_exchange_rejection_marks_rejected_with_a_reason(world) -> None:
    env, mgr, _ = world
    env.mock.balances["IDR"] = ("1", "0")
    res = mgr.submit(intent(), ctx())
    assert res.order.state == OrderState.REJECTED.value and res.order.cancel_reason


def test_the_same_intent_cannot_be_submitted_twice(world) -> None:
    env, mgr, _ = world
    mgr.submit(intent(), ctx())
    with pytest.raises(OrderRefused):
        mgr.submit(intent(), ctx())
    assert len([r for r in env.mock.requests if r["method"] == "POST"]) == 1


def test_sync_follows_partial_and_full_fills_and_fills_are_stored_once(world) -> None:
    env, mgr, session = world
    order = mgr.submit(intent(), ctx()).order
    env.mock.fill(order.exchange_order_id, "0.004")
    mgr.sync(order)
    assert order.state == OrderState.PARTIALLY_FILLED.value and order.executed_qty == D("0.004")
    env.mock.fill(order.exchange_order_id, "0.006")
    mgr.sync(order)
    assert order.state == OrderState.FILLED.value
    trades = env.client.get_my_trades("BTCIDR")
    assert mgr.ingest_fills(order, trades) == 2
    assert mgr.ingest_fills(order, trades) == 0  # idempotent by trade id
    assert len(session.scalars(select(Fill)).all()) == 2


def test_cancel_is_confirmed_by_reading_the_exchange(world) -> None:
    env, mgr, _ = world
    order = mgr.submit(intent(), ctx()).order
    mgr.cancel(order, "reprice")
    assert order.state == OrderState.CANCELLED.value and order.cancel_reason == "reprice"
    assert mgr.cancel(order, "again").state == OrderState.CANCELLED.value  # terminal: a no-op


def test_a_stop_goes_out_as_market_under_the_emergency_profile(world) -> None:
    env, mgr, _ = world
    stop = intent(side="SELL", identity="stop|BTCIDR", stop_price=None)
    res = mgr.submit(
        stop,
        ctx(trading_state="HALTED", daily_realised_loss_idr=D("99999999")),
        purpose="STOP",
        order_type="MARKET",
    )
    assert res.order is not None and res.order.type == "MARKET"
    assert res.order.state in {OrderState.FILLED.value, OrderState.OPEN.value}


# ----------------------------------------------------------------- exit monitor


def watch() -> list[WatchedPosition]:
    return [WatchedPosition("BTCIDR", D("0.01"), D("1200000000"))]


def test_a_stop_hit_requests_exactly_one_exit_until_cleared() -> None:
    m = ExitMonitor(watchdog_cycles=3)
    r1 = m.cycle(watch(), {"BTCIDR": D("1199000000")}, price_time=NOW, now=NOW, max_age_s=30)
    assert len(r1.exits) == 1 and r1.exits[0].observed_price == D("1199000000")
    r2 = m.cycle(watch(), {"BTCIDR": D("1190000000")}, price_time=NOW, now=NOW, max_age_s=30)
    assert r2.exits == []  # a sell is already pending
    m.clear("BTCIDR")
    assert (
        len(
            m.cycle(
                watch(), {"BTCIDR": D("1190000000")}, price_time=NOW, now=NOW, max_age_s=30
            ).exits
        )
        == 1
    )


def test_a_price_above_the_stop_does_nothing() -> None:
    r = ExitMonitor(3).cycle(
        watch(), {"BTCIDR": D("1300000000")}, price_time=NOW, now=NOW, max_age_s=30
    )
    assert r.exits == [] and r.unprotected == [] and r.alerts == []


def test_a_failed_or_stale_price_leaves_the_position_unprotected_and_alerts_on_the_third_miss() -> (
    None
):
    m = ExitMonitor(watchdog_cycles=3)
    stale = NOW - timedelta(seconds=300)
    r = m.cycle(watch(), {"BTCIDR": D("1300000000")}, price_time=stale, now=NOW, max_age_s=30)
    assert r.unprotected == ["BTCIDR"] and r.alerts == []
    m.cycle(watch(), None, price_time=None, now=NOW, max_age_s=30)
    r = m.cycle(watch(), None, price_time=None, now=NOW, max_age_s=30)
    assert r.alerts and "BTCIDR" in r.alerts[0]
    ok = m.cycle(watch(), {"BTCIDR": D("1300000000")}, price_time=NOW, now=NOW, max_age_s=30)
    assert ok.unprotected == [] and ok.alerts == []  # a good price resets the count


def test_a_stop_can_tighten_but_never_widen() -> None:
    m = ExitMonitor(3)
    assert m.tighten_stop(D("1200"), D("1250")) == D("1250")
    with pytest.raises(StopWidenRefused):
        m.tighten_stop(D("1200"), D("1100"))


# ------------------------------------------------------------------ kill switch


def test_halt_changes_state_and_touches_no_order(world) -> None:
    env, mgr, session = world
    order = mgr.submit(intent(), ctx()).order
    ks = KillSwitch(session, env.client, now=lambda: NOW)
    ks.activate("HALT", "owner", "owner")
    assert ks.state() == "HALTED"
    assert OrderState(order.state) is OrderState.OPEN
    assert not [r for r in env.mock.requests if r["method"] == "DELETE"]


def test_cancel_tier_cancels_every_open_order_and_records_each_step(world) -> None:
    env, mgr, session = world
    mgr.submit(intent(), ctx())
    mgr.submit(intent(identity="v1|BTCIDR|other|BUY"), ctx())
    ks = KillSwitch(session, env.client, now=lambda: NOW)
    ks.activate("CANCEL", "owner", "owner")
    assert len([r for r in env.mock.requests if r["method"] == "DELETE"]) == 2
    steps = session.scalars(select(KillSwitchStep).where(KillSwitchStep.kind == "cancel")).all()
    assert len(steps) == 2 and all(s.result == "ok" for s in steps)
    assert {o["status"] for o in env.mock.orders.values()} == {"CANCELLED"}


def test_flatten_sells_held_assets_and_only_the_owner_can_trigger_it(world) -> None:
    env, _, session = world
    ks = KillSwitch(session, env.client, now=lambda: NOW)
    for trigger in ("breaker", "reconciler", "watchdog", "service"):
        with pytest.raises(KillSwitchRefused):
            ks.activate("FLATTEN", trigger, "system")
    ks.activate("FLATTEN", "owner", "owner")
    sells = [o for o in env.mock.orders.values() if o["side"] == "SELL" and o["type"] == "MARKET"]
    assert len(sells) == 1 and sells[0]["symbol"] == "BTCIDR"


def test_the_kill_switch_is_idempotent(world) -> None:
    env, _, session = world
    ks = KillSwitch(session, env.client, now=lambda: NOW)
    ks.activate("HALT", "owner", "owner")
    ks.activate("HALT", "owner", "owner")
    assert ks.state() == "HALTED"
    ks.activate("CANCEL", "owner", "owner")
    ks.activate("HALT", "owner", "owner")  # a lower tier never downgrades the state
    assert ks.state() == "CANCELLING"


def test_a_failed_cancel_is_recorded_not_hidden(world) -> None:
    env, mgr, session = world
    mgr.submit(intent(), ctx())
    env.mock.inject_error("DELETE", "/api/v2/order", 400, -1130, "no")
    KillSwitch(session, env.client, now=lambda: NOW).activate("CANCEL", "owner", "owner")
    assert [s.result for s in session.scalars(select(KillSwitchStep))] == ["failed"]


def test_resume_needs_a_note_and_is_blocked_by_unknown_orders_and_differences(world) -> None:
    env, mgr, session = world
    ks = KillSwitch(session, env.client, now=lambda: NOW)
    ks.activate("HALT", "owner", "owner")
    with pytest.raises(KillSwitchRefused):
        ks.resume("  ", "owner")
    env.mock.inject_timeout("POST", "/api/v2/order")
    mgr.submit(intent(), ctx())
    with pytest.raises(KillSwitchRefused, match="UNKNOWN"):
        ks.resume("checked", "owner")
    session.query(OrderRow).delete()
    session.commit()
    run = reconcile(session, env.client, ["BTCIDR"], now=lambda: NOW)
    assert run.result == "clean"
    ks.resume("all clear", "owner")
    assert ks.state() == "RUNNING"


# -------------------------------------------------------------- reconciliation


def test_a_clean_account_reconciles_clean_and_does_not_halt(world) -> None:
    env, mgr, session = world
    ks = KillSwitch(session, env.client, now=lambda: NOW)
    mgr.submit(intent(), ctx())
    run = reconcile(session, env.client, ["BTCIDR"], now=lambda: NOW, killswitch=ks)
    assert run.result == "clean" and run.differences == 0 and ks.state() == "RUNNING"


def test_an_order_on_the_exchange_we_do_not_know_halts_and_is_not_corrected(world) -> None:
    env, _, session = world
    env.client.create_order(
        symbol="BTCIDR",
        side="BUY",
        order_type="LIMIT",
        price=D("1236777000"),
        quantity=D("0.01"),
        client_order_id="foreign-1",
    )
    ks = KillSwitch(session, env.client, now=lambda: NOW)
    run = reconcile(session, env.client, ["BTCIDR"], now=lambda: NOW, killswitch=ks)
    assert run.result == "differences" and ks.state() == "HALTED"
    assert session.scalars(select(OrderRow)).all() == []  # nothing silently imported
    assert any(
        d.kind == "order_missing_locally" for d in session.scalars(select(ReconciliationDifference))
    )


def test_a_local_order_gone_from_the_exchange_is_a_difference(world) -> None:
    env, mgr, session = world
    order = mgr.submit(intent(), ctx()).order
    env.mock.orders.pop(order.exchange_order_id)
    run = reconcile(
        session,
        env.client,
        ["BTCIDR"],
        now=lambda: NOW,
        killswitch=KillSwitch(session, env.client, now=lambda: NOW),
    )
    assert run.result == "differences"


def test_a_trade_we_never_recorded_is_a_difference(world) -> None:
    env, mgr, session = world
    order = mgr.submit(intent(), ctx()).order
    env.mock.fill(order.exchange_order_id, "0.01")
    env.mock.now_ms = int(NOW.timestamp() * 1000)
    mgr.sync(order)
    run = reconcile(session, env.client, ["BTCIDR"], now=lambda: NOW)
    assert any(
        d.kind == "trade_missing_locally" for d in session.scalars(select(ReconciliationDifference))
    )
    assert run.result == "differences"


def test_a_withdraw_permission_is_a_difference_and_halts(world) -> None:
    env, _, session = world
    env.mock.can_withdraw = True
    ks = KillSwitch(session, env.client, now=lambda: NOW)
    run = reconcile(session, env.client, ["BTCIDR"], now=lambda: NOW, killswitch=ks)
    assert run.result == "differences" and ks.state() == "HALTED"


def test_an_unreadable_exchange_is_a_failed_run_and_halts(world) -> None:
    env, _, session = world
    env.mock.inject_error("GET", "/api/v2/openOrders", 500, -1001, "down")
    env.mock.inject_error("GET", "/api/v2/openOrders", 500, -1001, "down")
    env.mock.inject_error("GET", "/api/v2/openOrders", 500, -1001, "down")
    ks = KillSwitch(session, env.client, now=lambda: NOW)
    run = reconcile(session, env.client, ["BTCIDR"], now=lambda: NOW, killswitch=ks)
    assert run.result == "failed" and ks.state() == "HALTED"


def test_history_windows_never_exceed_seven_days() -> None:
    ws = windows(NOW - timedelta(days=20), NOW)
    assert len(ws) == 3 and all(b - a <= timedelta(days=7) for a, b in ws)
    assert ws[0][0] == NOW - timedelta(days=20) and ws[-1][1] == NOW


# ------------------------------------------------------------- architecture


SRC = Path(__file__).resolve().parents[2] / "src" / "aidss_trader"
MUTATORS = {"create_order", "cancel_order"}
ALLOWED_MUTATOR_DIRS = {"connector", "orders", "killswitch"}


def _py_files(root: Path):
    return [p for p in root.rglob("*.py")]


def test_only_connector_orders_and_killswitch_can_create_or_cancel_orders() -> None:
    offenders = []
    for path in _py_files(SRC):
        rel = path.relative_to(SRC).parts[0]
        if rel in ALLOWED_MUTATOR_DIRS:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in MUTATORS:
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert offenders == []


def test_the_killswitch_does_not_depend_on_anything_that_decides_to_trade() -> None:
    forbidden = {"strategy", "intents", "backtest", "paper", "auth", "risk", "exits", "reconcile"}
    for path in _py_files(SRC / "killswitch"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            mods = []
            if isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            for m in mods:
                parts = m.split(".")
                assert not (
                    parts[0] == "aidss"
                    or (len(parts) > 1 and parts[0] == "aidss_trader" and parts[1] in forbidden)
                ), m


def test_market_orders_are_only_possible_on_emergency_paths() -> None:
    src = (SRC / "orders" / "manager.py").read_text(encoding="utf-8")
    assert "EMERGENCY_PURPOSES" in src and "MARKET is allowed only for a stop or a flatten" in src
    for path in _py_files(SRC):
        rel = path.relative_to(SRC).parts[0]
        if rel in {"connector", "orders", "killswitch", "backtest", "paper"}:
            continue
        assert '"MARKET"' not in path.read_text(encoding="utf-8"), path
