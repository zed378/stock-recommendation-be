"""The assembled runtime, against the synthetic mock exchange only.

Every number here is a TEST value declared in this file. Nothing touches a real
exchange, a real Telegram chat, or a real key.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import aidss_trader.db.models  # noqa: F401
from aidss_trader.api import ApiContext, create_app
from aidss_trader.approvals import ApprovalWorkflow, intent_hash
from aidss_trader.auth import TokenVerifier
from aidss_trader.auth.stepup import StepUp
from aidss_trader.config import RiskLimits, save_risk_limits
from aidss_trader.config.settings import TraderSettings
from aidss_trader.db.base import Base
from aidss_trader.db.models import (
    ApprovalRow,
    BreakerEvent,
    EquitySnapshot,
    Fill,
    OrderIntentRow,
    OrderRow,
    PositionStop,
    StrategyRow,
    TradingEvent,
)
from aidss_trader.killswitch import KillSwitch
from aidss_trader.lease import LeaseHolder
from aidss_trader.notify import Notifier, RecordingChannel
from aidss_trader.promotion import Thresholds
from aidss_trader.runtime import (
    Allowlist,
    LiquidityFilter,
    Runtime,
    accounting,
    set_allowlist,
    set_strategy_params,
)
from aidss_trader.runtime.assembly import build_api, build_client
from aidss_trader.runtime.settings_store import set_paper_settings
from aidss_trader.service import run
from aidss_trader.strategy import EmaAdxParams
from tests.trader.test_connector_contract import Env

D = Decimal
PARAMS = EmaAdxParams(3, 6, 3, D("30"), 3, D("2"), 0)
LIMITS = RiskLimits(
    risk_per_trade_pct=D("1"),
    max_daily_loss_idr=D("1000000"),
    max_drawdown_pct=D("20"),
    max_consecutive_losses=3,
    max_open_positions=2,
    max_exposure_per_pair_pct=D("100"),
    max_total_exposure_pct=D("100"),
    max_order_idr=D("100000000"),
    price_deviation_pct=D("2"),
    freshness_limit_s=60,
    cooldown_s=0,
    order_rate_limit=20,
)
TF = 4 * 3600
# TEST values for the paper cost model; the real ones are the owner's (OQ-5).
PAPER_VALUES = {
    "slippage_pct": D("0.1"),
    "partial_fill_fraction": D("1"),
    "maker_fee_pct": D("0.1"),
    "taker_fee_pct": D("0.2"),
    "tax_pct": D("0.1"),
    "clearing_pct": D("0.01"),
    "start_equity_idr": D("100000000"),
}


class World:
    """A mock exchange with a rising 4H market, a database, and a runtime wired to both."""

    def __init__(
        self,
        mode: str = "APPROVAL",
        *,
        running: bool = True,
        limits=LIMITS,
        configured: bool = True,
    ) -> None:
        self.env = Env()
        m = self.env.mock
        m.balances = {"IDR": ("100000000", "0")}
        now_s = m.now_ms // 1000
        last_open = now_s - TF - 600
        closes = [1_200_000_000 + 4_000_000 * i for i in range(30)]
        self.last_close = closes[-1]
        rows = []
        for i, c in enumerate(closes):
            ts = last_open - (len(closes) - 1 - i) * TF
            rows.append((ts, str(c), str(c + 2_000_000), str(c - 2_000_000), str(c), "1"))
        m.candles[("BTCIDR", "240")] = rows
        m.prices["BTCIDR"] = str(self.last_close)
        m.books["BTCIDR"] = (str(self.last_close), "0.5", str(self.last_close + 23_000), "0.5")
        self.engine = create_engine(
            "sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        ).execution_options(schema_translate_map={"trading": None})
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)
        self.chan = RecordingChannel()
        self.runtime = Runtime(
            self.factory,
            self.env.client,
            notifier=lambda s: Notifier(s, self.chan, now=self.now),
            now=self.now,
            price_poll_s=10,
            reconcile_s=60,
            candle_poll_s=1,
        )
        with self.factory() as s:
            ks = KillSwitch(s, None, now=self.now)
            ks.ensure_initialized()
            if limits is not None:
                save_risk_limits(s, limits, set_by="owner")
            if configured:
                version = set_strategy_params(s, "ema_adx", PARAMS, by="owner")
                set_allowlist(
                    s, Allowlist(("BTCIDR",), LiquidityFilter(D("1000000000"), D("1"))), by="owner"
                )
                if mode != "PAPER":
                    s.get(StrategyRow, "ema_adx").mode = mode
                set_paper_settings(s, PAPER_VALUES, by="owner")
                self.version = version
            s.commit()
            if running:
                ks.resume("test resume", "owner")

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.env.mock.now_ms / 1000, UTC)

    def cycle(self, advance_ms: int = 11_000):
        self.env.mock.advance(advance_ms)
        return self.runtime.cycle()

    def state(self) -> str:
        with self.factory() as s:
            return KillSwitch(s, None).state()

    def rows(self, model):
        with self.factory() as s:
            return list(s.scalars(select(model)))

    def posts(self) -> int:
        return len([r for r in self.env.mock.requests if r["method"] == "POST"])


def fail(w: World, method: str, path: str, n: int = 4) -> None:
    """Fail every attempt of one call, including the client's own read retries."""
    for _ in range(n):
        w.env.mock.inject_error(method, path, 500, -1001, "down")


def warm(w: World, cycles: int = 2):
    """Enough cycles for the first reconciliation to come back clean."""
    out = None
    for _ in range(cycles):
        out = w.cycle()
    return out


# ------------------------------------------------------------------- start-up


def test_a_fresh_install_starts_halted_and_sends_nothing() -> None:
    w = World(running=False)
    w.cycle()
    assert w.state() == "HALTED" and w.posts() == 0
    assert w.rows(OrderIntentRow) == []  # nothing was decided while halted


def test_unset_limits_mean_nothing_is_decided() -> None:
    w = World(limits=None)
    report = warm(w)
    assert w.rows(OrderIntentRow) == [] and w.posts() == 0
    assert any("limits unset" in s for s in report.skipped)


def test_no_strategy_parameters_or_allowlist_means_nothing_is_decided() -> None:
    w = World(configured=False)
    report = warm(w)
    assert w.rows(OrderIntentRow) == [] and any(
        "no strategy parameters" in s for s in report.skipped
    )


def test_the_liquidity_filter_must_be_configured_before_a_pair_is_active() -> None:
    w = World()
    with w.factory() as s:
        set_allowlist(s, Allowlist(("BTCIDR",), LiquidityFilter()), by="owner")
        s.commit()
    report = warm(w)
    assert w.rows(OrderIntentRow) == [] and any("liquidity filter" in s for s in report.skipped)


def test_a_pair_that_is_too_illiquid_is_not_traded() -> None:
    w = World()
    with w.factory() as s:
        set_allowlist(
            s, Allowlist(("BTCIDR",), LiquidityFilter(D("999999999999999"), D("1"))), by="owner"
        )
        s.commit()
    warm(w)
    assert w.rows(OrderIntentRow) == []


# ----------------------------------------------------------- the decision path


def test_paper_mode_records_the_intent_labelled_paper_and_sends_nothing() -> None:
    w = World("PAPER")
    warm(w)
    intents = w.rows(OrderIntentRow)
    assert intents and all(i.origin == "PAPER" and i.state == "PAPER_RECORDED" for i in intents)
    assert w.posts() == 0


def test_approval_mode_creates_a_card_and_sends_nothing_until_approved() -> None:
    w = World("APPROVAL")
    warm(w)
    intents = w.rows(OrderIntentRow)
    assert len(intents) == 1 and intents[0].state == "AWAITING_APPROVAL"
    cards = w.rows(ApprovalRow)
    assert len(cards) == 1 and cards[0].state == "AWAITING"
    assert w.posts() == 0
    assert any("awaiting approval" in m for m in w.chan.messages)


def test_the_same_candle_never_creates_a_second_intent() -> None:
    w = World("APPROVAL")
    warm(w, 4)
    assert len(w.rows(OrderIntentRow)) == 1 and len(w.rows(ApprovalRow)) == 1


def test_approving_sends_through_the_risk_engine_and_the_order_manager() -> None:
    w = World("APPROVAL")
    warm(w)
    with w.factory() as s:
        row = s.scalars(select(OrderIntentRow)).one()
        from aidss_trader.api.app import _cell  # noqa: F401

        intent = _intent(row)
        out = ApprovalWorkflow(s, now=w.now).approve(
            intent, "owner", intent_hash(intent), lambda: w.runtime.submit_approved(s, intent)
        )
    assert out.sent and w.posts() == 1
    order = w.rows(OrderRow)[0]
    assert order.origin == "LIVE" and order.purpose == "ENTRY" and order.state == "OPEN"
    assert order.time_in_force == "MOC"


def _intent(row):
    from aidss_trader.intents import intent_from_row

    return intent_from_row(row, mode="AUTO")


def test_an_approved_intent_is_rechecked_and_refused_if_the_world_changed() -> None:
    w = World("APPROVAL")
    warm(w)
    w.env.mock.books["BTCIDR"] = ("1000000000", "1", "1000100000", "1")  # the market fell
    with w.factory() as s:
        intent = _intent(s.scalars(select(OrderIntentRow)).one())
        result = w.runtime.submit_approved(s, intent)
    assert result.order is None
    assert {"price_deviation"} & {c.name for c in result.decision.failed}
    assert w.posts() == 0


def test_auto_mode_sends_an_entry_once_every_check_passes() -> None:
    w = World("AUTO")
    warm(w, 3)
    orders = w.rows(OrderRow)
    assert len(orders) == 1 and orders[0].purpose == "ENTRY" and w.posts() == 1
    assert w.rows(OrderIntentRow)[0].state == "SENT"
    warm(w, 3)
    assert w.posts() == 1  # the same candle is never decided again


def test_auto_mode_waits_for_a_clean_reconciliation_before_the_first_order() -> None:
    w = World("AUTO")
    w.cycle()
    assert w.posts() == 0  # no reconciliation has come back clean yet
    w.cycle()
    w.cycle()
    assert w.posts() == 1


def test_a_halted_trader_decides_and_sends_nothing() -> None:
    w = World("AUTO", running=False)
    warm(w, 3)
    assert w.posts() == 0


# -------------------------------------------------------------- fills and stops


def entered(w: World) -> OrderRow:
    warm(w, 3)
    with w.factory() as s:
        order = s.scalars(select(OrderRow)).one()
        w.env.mock.fill(order.exchange_order_id, str(order.quantity))
    w.cycle()
    return w.rows(OrderRow)[0]


def test_a_filled_entry_becomes_a_position_with_the_intents_stop() -> None:
    w = World("AUTO")
    order = entered(w)
    assert order.state == "FILLED"
    fills = w.rows(Fill)
    assert len(fills) == 1 and fills[0].origin == "LIVE"
    w.cycle()
    stops = w.rows(PositionStop)
    intent = w.rows(OrderIntentRow)[0]
    assert len(stops) == 1 and stops[0].stop_price == intent.stop_price
    with w.factory() as s:
        positions, _ = accounting.replay_live(s)
    assert positions["BTCIDR"].quantity == order.quantity


def test_a_stop_hit_sends_exactly_one_market_sell_under_the_emergency_profile() -> None:
    w = World("AUTO")
    entered(w)
    w.cycle()
    stop = w.rows(PositionStop)[0].stop_price
    w.env.mock.prices["BTCIDR"] = str(int(stop) - 5_000_000)
    w.env.mock.market_fill_price = w.env.mock.prices["BTCIDR"]
    w.cycle()
    sells = [o for o in w.rows(OrderRow) if o.purpose == "STOP"]
    assert len(sells) == 1 and sells[0].type == "MARKET" and sells[0].side == "SELL"
    w.cycle()
    w.cycle()
    assert len([o for o in w.rows(OrderRow) if o.purpose == "STOP"]) == 1  # no second sell
    assert any("stop triggered" in m for m in w.chan.messages)


def test_a_stop_is_sent_even_while_halted_and_over_the_loss_limit() -> None:
    w = World("AUTO")
    entered(w)
    w.cycle()
    with w.factory() as s:
        KillSwitch(s, w.env.client, now=w.now).activate("HALT", "owner", "owner")
    stop = w.rows(PositionStop)[0].stop_price
    w.env.mock.prices["BTCIDR"] = str(int(stop) - 5_000_000)
    w.env.mock.market_fill_price = w.env.mock.prices["BTCIDR"]
    w.cycle()
    assert [o for o in w.rows(OrderRow) if o.purpose == "STOP"]


def test_a_stale_price_leaves_the_position_unprotected_and_is_reported_once() -> None:
    w = World("AUTO")
    entered(w)
    w.cycle()
    for _ in range(4):
        fail(w, "GET", "/api/v2/ticker/price")
        w.cycle()
    critical = [
        e for e in w.rows(TradingEvent) if e.kind in {"exit_unprotected", "watchdog_stalled"}
    ]
    assert critical
    assert len([e for e in critical if e.kind == "watchdog_stalled"]) <= 1  # not every cycle


# ----------------------------------------------------------------- the breakers


def test_an_order_whose_outcome_is_unknown_halts_trading_at_once() -> None:
    w = World("AUTO")
    w.cycle()  # the first reconciliation has not come back yet: nothing is sent
    w.env.mock.inject_timeout("POST", "/api/v2/order")
    w.cycle()
    assert [o for o in w.rows(OrderRow) if o.state == "UNKNOWN"]
    w.cycle()
    assert w.state() == "HALTED"
    assert any(b.breaker == "unknown_order" for b in w.rows(BreakerEvent))
    assert any(e.kind == "order_unknown" and e.severity == "CRITICAL" for e in w.rows(TradingEvent))
    assert w.posts() == 1  # never resent


def test_an_order_on_the_exchange_we_do_not_know_halts_via_reconciliation() -> None:
    w = World("PAPER")
    warm(w, 2)
    w.env.client.create_order(
        symbol="BTCIDR",
        side="BUY",
        order_type="LIMIT",
        price=D("1000000000"),
        quantity=D("0.001"),
        client_order_id="foreign-1",
    )
    w.cycle(61_000)
    assert w.state() == "HALTED"
    assert any(e.kind == "reconciliation_difference" for e in w.rows(TradingEvent))


def test_a_withdraw_permission_halts() -> None:
    w = World("PAPER")
    warm(w, 2)
    w.env.mock.can_withdraw = True
    w.cycle()
    assert w.state() == "HALTED"
    assert any(b.breaker == "permissions" for b in w.rows(BreakerEvent))


def test_a_clock_beyond_tolerance_halts() -> None:
    w = World("PAPER")
    warm(w, 2)
    w.env.mock.now_ms += 0
    w.env.client._clock = w.env.mock.client_clock(5_000)  # type: ignore[attr-defined]
    w.env.client._last_clock_ok = None  # type: ignore[attr-defined]
    w.cycle()
    assert w.state() == "HALTED"
    assert any(b.breaker == "clock_skew" for b in w.rows(BreakerEvent))


def test_a_sustained_outage_trips_the_stale_data_breaker_but_one_failed_poll_does_not() -> None:
    w = World("PAPER")
    # The reconciler also reads the account and halts on a failed read. Its 60 s timer is moved
    # out of the way so the breaker under test is the one that trips: the clock check's throttle
    # waits advance the mock clock, which otherwise lets the reconciler get there first.
    w.runtime = Runtime(
        w.factory,
        w.env.client,
        notifier=lambda s: Notifier(s, w.chan, now=w.now),
        now=w.now,
        price_poll_s=10,
        reconcile_s=3600,
        candle_poll_s=1,
    )
    warm(w, 2)
    fail(w, "GET", "/api/v2/account")
    w.cycle()
    assert w.state() == "RUNNING"  # one failed poll is not an outage
    for _ in range(8):
        fail(w, "GET", "/api/v2/account")
        w.cycle()
    assert w.state() == "HALTED"
    assert any(b.breaker == "stale_data" for b in w.rows(BreakerEvent))


def test_a_loss_beyond_the_daily_limit_cancels_and_halts() -> None:
    w = World("PAPER")
    warm(w, 2)
    now = w.now()
    with w.factory() as s:
        order = OrderRow(
            origin="LIVE",
            pair="BTCIDR",
            side="BUY",
            type="LIMIT",
            quantity=D("1"),
            client_order_id="seed",
            executed_qty=D("1"),
            state="FILLED",
            purpose="ENTRY",
            submitted_at=now,
            updated_at=now,
        )
        s.add(order)
        s.flush()
        for i, (side, price) in enumerate([("BUY", "2000000000"), ("SELL", "998000000")]):
            s.add(
                Fill(
                    order_id=order.id,
                    origin="LIVE",
                    exchange_trade_id=f"seed{i}",
                    pair="BTCIDR",
                    side=side,
                    price=D(price),
                    quantity=D("1"),
                    quote_quantity=D(price),
                    commission=D("0"),
                    executed_at=now - timedelta(minutes=5 - i),
                )
            )
        s.commit()
    w.cycle()
    assert w.state() in {"CANCELLING", "HALTED"}
    assert any(b.breaker == "daily_loss" and b.tier == "CANCEL" for b in w.rows(BreakerEvent))


def test_breakers_never_sell_anything() -> None:
    w = World("PAPER")
    warm(w, 2)
    w.env.mock.can_withdraw = True
    w.cycle()
    assert not [o for o in w.env.mock.orders.values() if o["side"] == "SELL"]


# --------------------------------------------------------------- bookkeeping


def test_equity_snapshots_are_stored_and_drawdown_is_measured_from_the_peak(session) -> None:
    now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    assert accounting.drawdown_pct(session, D("100")) == 0
    accounting.record_equity(session, D("100"), now)
    accounting.record_equity(session, D("80"), now)
    assert accounting.drawdown_pct(session, D("80")) == D("20")
    assert accounting.drawdown_pct(session, D("120")) == 0  # a new peak
    assert session.scalars(select(EquitySnapshot)).all()


def test_the_loss_day_starts_at_local_midnight_wib() -> None:
    # 2026-11-14 18:00 UTC is 01:00 WIB on the 15th: the day began at 17:00 UTC.
    start = accounting.wib_day_start(datetime(2026, 11, 14, 18, 0, tzinfo=UTC))
    assert start == datetime(2026, 11, 14, 17, 0, tzinfo=UTC)
    events = [
        accounting.Realised(datetime(2026, 11, 14, 16, 0, tzinfo=UTC), "BTCIDR", D("-500")),
        accounting.Realised(datetime(2026, 11, 14, 17, 30, tzinfo=UTC), "BTCIDR", D("-200")),
        accounting.Realised(datetime(2026, 11, 14, 17, 45, tzinfo=UTC), "BTCIDR", D("50")),
    ]
    assert accounting.daily_loss(events, datetime(2026, 11, 14, 18, 0, tzinfo=UTC)) == D("150")
    assert accounting.daily_loss([accounting.Realised(start, "X", D("90"))], start) == 0
    assert accounting.consecutive_losses(events) == 0
    assert accounting.consecutive_losses(events[:2]) == 2


def test_paper_fills_never_move_a_live_figure(session) -> None:
    now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    order = OrderRow(
        origin="PAPER",
        pair="BTCIDR",
        side="BUY",
        type="LIMIT",
        quantity=D("1"),
        client_order_id="p",
        executed_qty=D("1"),
        state="FILLED",
        purpose="ENTRY",
        submitted_at=now,
        updated_at=now,
    )
    session.add(order)
    session.flush()
    session.add(
        Fill(
            order_id=order.id,
            origin="PAPER",
            exchange_trade_id="p1",
            pair="BTCIDR",
            side="BUY",
            price=D("1"),
            quantity=D("1"),
            quote_quantity=D("1"),
            executed_at=now,
        )
    )
    session.commit()
    positions, events = accounting.replay_live(session)
    assert positions == {} and events == []


# ----------------------------------------------------------- assembly and API


def test_no_exchange_urls_means_no_client_and_no_trading() -> None:
    settings = TraderSettings(database_url="sqlite://")
    assert build_client(settings, None, None) is None  # type: ignore[arg-type]
    rt = Runtime(None, None)  # type: ignore[arg-type]
    assert rt.client is None and rt.freshness()[1] is True


def test_the_operator_api_is_not_served_without_an_analysis_api_url() -> None:
    w = World("PAPER")
    assert build_api(TraderSettings(database_url="sqlite://"), w.factory, w.runtime) is None
    settings = TraderSettings(database_url="sqlite://", analysis_api_url="https://a.test")
    app = build_api(settings, w.factory, w.runtime)
    assert app is not None and any(r.path == "/trader/v1/kill" for r in app.routes)


USERS = {"tok": ("u1", "trader")}


def api_for(w: World):
    def me(req: httpx.Request) -> httpx.Response:
        who = USERS.get(req.headers.get("authorization", "")[7:])
        if req.url.path == "/auth/login":
            return httpx.Response(200, json={"access_token": "tok"})
        return (
            httpx.Response(200, json={"id": who[0], "role": who[1]}) if who else httpx.Response(401)
        )

    t = httpx.MockTransport(me)
    verifier = TokenVerifier("https://a.test", timeout_s=2, transport=t)
    ctx = ApiContext(
        session_factory=w.factory,
        verifier=verifier,
        stepup=lambda s: StepUp(s, "https://a.test", verifier, transport=t),
        notifier=lambda s: Notifier(s, w.chan),
        killswitch=lambda s: KillSwitch(s, w.env.client),
        submit_approved=w.runtime.submit_approved,
        thresholds=lambda: Thresholds(),
        freshness=w.runtime.freshness,
    )
    from fastapi.testclient import TestClient

    client = TestClient(create_app(ctx))
    counter = {"n": 0}

    def call(method, path, body=None, **headers):
        counter["n"] += 1
        h = {"Authorization": "Bearer tok", "Idempotency-Key": f"k{counter['n']}", **headers}
        return client.request(method, "/trader/v1" + path, json=body, headers=h)

    return call


def test_the_owner_can_set_the_allowlist_and_parameters_through_the_api_and_it_is_audited() -> None:
    w = World("PAPER", configured=False)
    call = api_for(w)
    assert call("GET", "/allowlist").json()["data"]["active"] is False
    r = call(
        "PUT",
        "/allowlist",
        {"pairs": ["btcidr"], "min_quote_volume_24h_idr": "1000000000", "max_spread_pct": "1"},
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "step_up_required"  # enabling
    grant = call(
        "POST", "/stepup", {"email": "o@x", "password": "pw", "scope": "RAISE_LIMIT"}
    ).json()["data"]["grant"]
    ok = call(
        "PUT",
        "/allowlist",
        {"pairs": ["btcidr"], "min_quote_volume_24h_idr": "1000000000", "max_spread_pct": "1"},
        **{"X-Step-Up": grant},
    )
    assert ok.status_code == 200 and ok.json()["data"]["active"] is True
    # Tightening needs no step-up.
    tight = call(
        "PUT",
        "/allowlist",
        {"pairs": ["btcidr"], "min_quote_volume_24h_idr": "2000000000", "max_spread_pct": "0.5"},
    )
    assert tight.status_code == 200
    params = {
        "ema_fast": 3,
        "ema_slow": 6,
        "adx_period": 3,
        "adx_threshold": "30",
        "atr_period": 3,
        "atr_stop_multiple": "2",
        "cooldown_s": 0,
    }
    cfg = {k: str(v) for k, v in PAPER_VALUES.items()}
    assert call("PUT", "/paper-config", cfg).status_code == 200
    assert call("PUT", "/paper-config", {**cfg, "partial_fill_fraction": "0"}).status_code == 400
    out = call("PUT", "/strategies/ema_adx/parameters", params).json()["data"]
    assert out["mode"] == "PAPER" and out["version"].startswith("ema_adx-")
    assert (
        call("PUT", "/strategies/ema_adx/parameters", {**params, "ema_fast": 9}).status_code == 400
    )
    warm(w, 2)
    assert w.rows(OrderIntentRow)  # configured through the API alone, the runtime now decides


def test_loosening_the_allowlist_is_detected() -> None:
    from aidss_trader.api.app import allowlist_loosens

    base = Allowlist(("BTCIDR",), LiquidityFilter(D("100"), D("1")))
    assert allowlist_loosens(base, Allowlist(("BTCIDR", "ETHIDR"), base.liquidity))
    assert allowlist_loosens(base, Allowlist(("BTCIDR",), LiquidityFilter(D("50"), D("1"))))
    assert allowlist_loosens(base, Allowlist(("BTCIDR",), LiquidityFilter(D("100"), D("2"))))
    assert allowlist_loosens(Allowlist(("BTCIDR",)), base)
    assert not allowlist_loosens(base, Allowlist(("BTCIDR",), LiquidityFilter(D("200"), D("0.5"))))
    assert not allowlist_loosens(base, Allowlist((), LiquidityFilter()))


def test_the_service_loop_runs_the_runtime_only_while_it_holds_the_lease(key_file) -> None:
    w = World("PAPER")
    settings = TraderSettings(
        database_url="sqlite://", master_key_file=key_file, heartbeat_file=key_file.parent / "hb"
    )
    ticks = iter([False, True])
    run(settings, w.factory, sleep=lambda s: None, stop=lambda: next(ticks), runtime=w.runtime)
    assert w.runtime.last_snapshot_at is not None  # it held the lease, so it cycled
    # Another instance holds the lease in this database: this one must not cycle.
    other = World("PAPER")
    with other.factory() as s:
        assert LeaseHolder("someone-else", 60).acquire(s)
        s.commit()
    ticks2 = iter([False, True])
    run(
        settings,
        other.factory,
        sleep=lambda s: None,
        stop=lambda: next(ticks2),
        runtime=other.runtime,
    )
    assert other.runtime.last_snapshot_at is None


def test_any_idr_pair_can_be_added_but_not_other_quote_currencies() -> None:
    w = World("PAPER", configured=False)
    call = api_for(w)
    grant = call(
        "POST", "/stepup", {"email": "o@x", "password": "pw", "scope": "RAISE_LIMIT"}
    ).json()["data"]["grant"]
    body = {
        "pairs": ["BTCIDR", "ETHIDR", "SOLIDR"],
        "min_quote_volume_24h_idr": "1000000000",
        "max_spread_pct": "1",
    }
    ok = call("PUT", "/allowlist", body, **{"X-Step-Up": grant})
    assert ok.status_code == 200 and ok.json()["data"]["pairs"] == ["BTCIDR", "ETHIDR", "SOLIDR"]
    for bad in (["BTCUSDT"], ["BTC_IDR"], ["IDR"], ["BTCEUR"]):
        r = call("PUT", "/allowlist", {**body, "pairs": bad})
        assert r.status_code in (400, 403)
    assert call("PUT", "/allowlist", {**body, "pairs": ["BTCUSDT"]}).status_code == 400


def test_strategy_parameters_can_be_read_back_and_bad_ones_are_refused() -> None:
    w = World("PAPER", configured=False)
    call = api_for(w)
    first = call("GET", "/strategies/ema_adx/parameters").json()["data"]
    assert (
        first["configured"] is False
        and first["params"] is None
        and first["max_history_bars"] == 300
    )
    params = {
        "ema_fast": 3,
        "ema_slow": 6,
        "adx_period": 3,
        "adx_threshold": "30",
        "atr_period": 3,
        "atr_stop_multiple": "2",
        "cooldown_s": 0,
    }
    out = call("PUT", "/strategies/ema_adx/parameters", params).json()["data"]
    got = call("GET", "/strategies/ema_adx/parameters").json()["data"]
    assert got["configured"] is True and got["params"]["ema_slow"] == "6"
    assert got["version"] == out["version"] and got["mode"] == "PAPER"
    for bad in (
        {"adx_threshold": "0"},
        {"adx_threshold": "101"},
        {"ema_slow": 3},
        {"atr_stop_multiple": "0"},
        {"cooldown_s": -1},
        {"adx_period": 0},
        {"ema_slow": 400},
    ):
        r = call("PUT", "/strategies/ema_adx/parameters", {**params, **bad})
        assert r.status_code == 400, bad
    assert (
        "history"
        in call("PUT", "/strategies/ema_adx/parameters", {**params, "ema_slow": 400}).json()[
            "error"
        ]["message"]
    )
    assert call("GET", "/strategies/nope/parameters").status_code == 404


def test_saving_new_parameters_returns_a_promoted_strategy_to_paper() -> None:
    w = World("AUTO")
    call = api_for(w)
    with w.factory() as s:
        assert s.get(StrategyRow, "ema_adx").mode == "AUTO"
    params = {
        "ema_fast": 4,
        "ema_slow": 8,
        "adx_period": 3,
        "adx_threshold": "25",
        "atr_period": 3,
        "atr_stop_multiple": "2",
        "cooldown_s": 0,
    }
    out = call("PUT", "/strategies/ema_adx/parameters", params).json()["data"]
    with w.factory() as s:
        row = s.get(StrategyRow, "ema_adx")
        assert row.mode == "PAPER" and row.version == out["version"]
    same = call("PUT", "/strategies/ema_adx/parameters", params).json()["data"]
    assert same["version"] == out["version"]  # unchanged numbers are not a new version
