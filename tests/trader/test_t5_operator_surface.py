"""T5: approvals, notifier, step-up, promotion, export, operator API.

Thresholds and limits are TEST values declared here. The channel is a recording fake;
no test sends a message or touches a real exchange.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import aidss_trader.db.models  # noqa: F401
from aidss_trader.api import ROLE_PERMISSIONS, ApiContext, allowed, create_app, loosens
from aidss_trader.approvals import EXPIRY, ApprovalRefused, ApprovalWorkflow, intent_hash
from aidss_trader.audit import verify_chain
from aidss_trader.auth import TokenVerifier
from aidss_trader.auth.stepup import StepUp, StepUpRefused
from aidss_trader.auth.verify import Principal
from aidss_trader.config import RiskLimits, save_risk_limits
from aidss_trader.db.base import Base
from aidss_trader.db.models import (
    ApprovalRow,
    AuditLog,
    BreakerEvent,
    Fill,
    LedgerEntry,
    ModeChange,
    OrderIntentRow,
    OrderRow,
    ReconciliationDifference,
    ReconciliationRun,
    StepUpGrant,
    StrategyRow,
    TradingEvent,
)
from aidss_trader.export import export_audit, export_ledger
from aidss_trader.intents import Intent
from aidss_trader.killswitch import KillSwitch
from aidss_trader.notify import (
    CATALOGUE,
    ChannelError,
    MobilePolicy,
    Notifier,
    RecordingChannel,
    TelegramChannel,
    UnsafePayload,
)
from aidss_trader.promotion import (
    MIN_DURATION,
    Promotion,
    PromotionRefused,
    SuppliedEvidence,
    Thresholds,
)
from tests.trader.test_connector_contract import Env

D = Decimal
T0 = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.t = T0

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw) -> None:
        self.t += timedelta(**kw)


def intent(**kw) -> Intent:
    base = dict(
        identity="v1|BTCIDR|c1|BUY",
        strategy_version="v1",
        pair="BTCIDR",
        side="BUY",
        entry_price=D("1236777000"),
        quantity=D("0.01"),
        stop_price=D("1200000000"),
        risk_amount_idr=D("367770"),
        rule_snapshot={},
        mode="APPROVAL",
        signal_candle_open=T0,
    )
    base.update(kw)
    return Intent(**base)


class Sent:
    def __init__(self, ok: bool = True) -> None:
        self.calls = 0
        self.ok = ok

    def __call__(self):
        self.calls += 1
        ok = self.ok

        class Decision:
            failed = [] if ok else [type("C", (), {"name": "daily_loss"})()]

        class Result:
            order = type("O", (), {"state": "OPEN"})() if ok else None
            decision = Decision()

        return Result()


# ------------------------------------------------------------------ approvals


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def wf(session, clock):
    chan = RecordingChannel()
    notifier = Notifier(session, chan, now=clock)
    return ApprovalWorkflow(session, notifier, now=clock), chan


def test_an_approval_is_bound_to_the_exact_intent(wf) -> None:
    flow, _ = wf
    flow.request(intent())
    shown = intent_hash(intent())
    send = Sent()
    with pytest.raises(ApprovalRefused):  # the order changed after the card was shown
        flow.approve(intent(entry_price=D("1236778000")), "owner", shown, send)
    with pytest.raises(ApprovalRefused):  # a stale hash from the client
        flow.approve(intent(), "owner", "0" * 64, send)
    assert send.calls == 0
    out = flow.approve(intent(), "owner", shown, send)
    assert out.state == "APPROVED" and out.sent and send.calls == 1


def test_the_hash_survives_a_database_round_trip_of_padded_decimals() -> None:
    padded = intent(
        entry_price=D("1236777000.000000000000000000"), quantity=D("0.010000000000000000")
    )
    assert intent_hash(padded) == intent_hash(intent())


def test_each_field_of_the_hash_matters() -> None:
    base = intent_hash(intent())
    for change in (
        {"pair": "ETHIDR"},
        {"side": "SELL"},
        {"quantity": D("0.02")},
        {"stop_price": D("1100000000")},
        {"entry_price": D("1")},
    ):
        assert intent_hash(intent(**change)) != base


def test_one_decision_per_intent_and_a_second_approval_sends_nothing(wf) -> None:
    flow, _ = wf
    flow.request(intent())
    send = Sent()
    flow.approve(intent(), "owner", intent_hash(intent()), send)
    again = flow.approve(intent(), "owner", intent_hash(intent()), send)
    assert again.already_decided and send.calls == 1
    assert flow.deny(intent().identity, "owner").already_decided


def test_an_expired_intent_is_never_sent(wf, clock) -> None:
    flow, _ = wf
    row = flow.request(intent())
    assert row.expires_at - row.created_at == EXPIRY == timedelta(hours=1)
    clock.advance(hours=1, seconds=1)
    send = Sent()
    out = flow.approve(intent(), "owner", intent_hash(intent()), send)
    assert out.state == "EXPIRED" and not out.sent and send.calls == 0


def test_a_denial_stores_its_reason_and_is_final(wf, session) -> None:
    flow, _ = wf
    flow.request(intent())
    assert flow.deny(intent().identity, "owner", "spread looks wrong").state == "DENIED"
    row = session.scalar(select(ApprovalRow))
    assert row.reason == "spread looks wrong" and row.decided_by == "owner"
    send = Sent()
    assert flow.approve(intent(), "owner", intent_hash(intent()), send).already_decided
    assert send.calls == 0


def test_a_risk_recheck_failure_at_send_time_is_reported_and_not_retried(wf) -> None:
    flow, chan = wf
    flow.request(intent())
    send = Sent(ok=False)
    out = flow.approve(intent(), "owner", intent_hash(intent()), send)
    assert out.state == "APPROVED" and not out.sent and "daily_loss" in out.detail
    assert send.calls == 1
    assert any("approved but not sent" in m for m in chan.messages)


def test_no_automated_actor_can_decide(wf) -> None:
    flow, _ = wf
    flow.request(intent())
    for actor in ("system", "strategy:ema", "job-scheduler", "killswitch", ""):
        with pytest.raises(ApprovalRefused):
            flow.deny(intent().identity, actor)


def test_requesting_the_same_intent_twice_makes_one_card(wf, session) -> None:
    flow, chan = wf
    flow.request(intent())
    flow.request(intent())
    assert len(session.scalars(select(ApprovalRow)).all()) == 1
    assert len(chan.messages) == 1


def test_decisions_are_audited_and_the_chain_verifies(wf, session) -> None:
    flow, _ = wf
    flow.request(intent())
    flow.approve(intent(), "owner", intent_hash(intent()), Sent())
    actions = [a.action for a in session.scalars(select(AuditLog))]
    assert "approval.approved" in actions
    assert verify_chain(session) >= 1


def test_expire_due_marks_old_cards(wf, clock, session) -> None:
    flow, _ = wf
    flow.request(intent())
    clock.advance(hours=2)
    assert flow.expire_due() == 1
    assert session.scalar(select(ApprovalRow)).state == "EXPIRED"


# ------------------------------------------------------------------- notifier


def test_an_event_is_stored_before_delivery_and_survives_a_failed_send(session, clock) -> None:
    chan = RecordingChannel()
    chan.fail = True
    n = Notifier(session, chan, now=clock)
    ev = n.emit("order_unknown", "BTCIDR order unresolved", {"pair": "BTCIDR"})
    assert ev.mobile == "failed" and ev.attempts == 1
    assert session.scalar(select(TradingEvent)) is not None  # the in-app event is intact


def test_critical_is_retried_with_backoff_until_delivered(session, clock) -> None:
    chan = RecordingChannel()
    chan.fail = True
    n = Notifier(session, chan, now=clock, backoff=(30, 120))
    ev = n.emit("reconciliation_difference", "difference on BTCIDR")
    assert n.retry_pending() == 0  # too soon
    chan.fail = False
    clock.advance(seconds=31)
    assert n.retry_pending() == 1 and ev.mobile == "sent" and len(chan.messages) == 1


def test_critical_stays_unacknowledged_until_the_owner_acknowledges(session, clock) -> None:
    n = Notifier(session, RecordingChannel(), now=clock)
    ev = n.emit("kill_switch_used", "kill switch HALT used")
    assert ev.acked_at is None
    n.acknowledge(ev.id, "owner")
    assert ev.acked_by == "owner" and ev.acked_at is not None


def test_critical_cannot_be_silenced_but_other_severities_can(session, clock) -> None:
    chan = RecordingChannel()
    policy = MobilePolicy(severities=frozenset())  # the owner tried to turn everything off
    n = Notifier(session, chan, policy=policy, now=clock)
    n.emit("order_filled", "BTCIDR filled")
    n.emit("mode_changed", "ema is now APPROVAL")
    n.emit("watchdog_stalled", "exit monitor stalled")
    assert chan.messages == ["[CRITICAL] exit monitor stalled"]


def test_identical_warn_events_collapse_but_critical_never_does(session, clock) -> None:
    n = Notifier(session, RecordingChannel(), now=clock)
    n.emit("mode_changed", "ema is now APPROVAL")
    n.emit("mode_changed", "ema is now APPROVAL")
    n.emit("order_unknown", "BTCIDR unresolved")
    n.emit("order_unknown", "BTCIDR unresolved")
    assert len(session.scalars(select(TradingEvent)).all()) == 3


@pytest.mark.parametrize(
    "payload",
    [
        {"api_key": "x"},
        {"secret": "x"},
        {"signature": "x"},
        {"uid": 1},
        {"balance_idr": 1},
        {"total_equity": 1},
        {"nested": {"token": "x"}},
        {"password": "x"},
    ],
)
def test_notification_has_no_secret_or_balance(session, clock, payload) -> None:
    n = Notifier(session, RecordingChannel(), now=clock)
    with pytest.raises(UnsafePayload):
        n.emit("order_filled", "BTCIDR filled", payload)
    assert session.scalars(select(TradingEvent)).all() == []


def test_a_message_states_facts_never_a_recommendation(session, clock) -> None:
    n = Notifier(session, RecordingChannel(), now=clock)
    with pytest.raises(UnsafePayload):
        n.emit("order_filled", "you should buy now")


def test_every_catalogue_event_has_a_known_severity_and_routes(session, clock) -> None:
    chan = RecordingChannel()
    n = Notifier(session, chan, now=clock, collapse_window=timedelta(0))
    for kind, (severity, mobile) in CATALOGUE.items():
        assert severity in {"INFO", "WARN", "CRITICAL"}
        ev = n.emit(kind, f"{kind} fact")
        should = severity == "CRITICAL" or (mobile is True and severity != "INFO")
        assert (ev.mobile != "none") == should, kind
    assert not any(re.search(r"key|secret|balance", m, re.I) for m in chan.messages)


def test_the_telegram_channel_posts_outbound_only_and_hides_the_token() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"ok": True, "result": {}})

    ch = TelegramChannel("TEST-TOKEN", "42", transport=httpx.MockTransport(handler))
    ch.send("hello")
    assert seen[0].url.path == "/botTEST-TOKEN/sendMessage" and seen[0].method == "POST"

    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to https://api.telegram.org/botTEST-TOKEN/")

    bad = TelegramChannel("TEST-TOKEN", "42", transport=httpx.MockTransport(boom))
    with pytest.raises(ChannelError) as err:
        bad.send("x")
    assert "TEST-TOKEN" not in str(err.value)

    def limited(req: httpx.Request) -> httpx.Response:
        body = {"ok": False, "error_code": 429, "parameters": {"retry_after": 7}}
        return httpx.Response(429, json=body)

    with pytest.raises(ChannelError) as err:
        TelegramChannel("t", "1", transport=httpx.MockTransport(limited)).send("x")
    assert err.value.retry_after_s == 7


def test_the_notifier_module_has_no_inbound_path() -> None:
    root = Path(__file__).resolve().parents[2]
    src = (root / "src/aidss_trader/notify/notifier.py").read_text("utf-8")
    assert "getUpdates" not in src and "webhook" not in src.lower()


# -------------------------------------------------------------------- step-up


def _stepup(session, clock, *, login_user="u1", login_ok=True):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/auth/login":
            if login_ok:
                return httpx.Response(200, json={"access_token": "t2"})
            return httpx.Response(401)
        return httpx.Response(200, json={"id": login_user, "role": "trader"})

    transport = httpx.MockTransport(handler)
    verifier = TokenVerifier("https://a.test", timeout_s=2, transport=transport)
    return StepUp(session, "https://a.test", verifier, now=clock, transport=transport)


ME = Principal("u1", "trader")


def test_a_grant_is_single_use_scoped_and_expires(session, clock) -> None:
    su = _stepup(session, clock)
    grant = su.issue(ME, "o@x", "pw", "FLATTEN")
    with pytest.raises(StepUpRefused):
        su.consume(grant, ME, "PROMOTE_AUTO")  # wrong scope
    su.consume(grant, ME, "FLATTEN")
    with pytest.raises(StepUpRefused):
        su.consume(grant, ME, "FLATTEN")  # a reusable approval token is the abuse case
    g2 = su.issue(ME, "o@x", "pw", "FLATTEN")
    clock.advance(minutes=5, seconds=1)
    with pytest.raises(StepUpRefused):
        su.consume(g2, ME, "FLATTEN")


def test_a_grant_for_another_user_or_a_wrong_password_is_refused(session, clock) -> None:
    with pytest.raises(StepUpRefused):
        _stepup(session, clock, login_ok=False).issue(ME, "o@x", "bad", "FLATTEN")
    with pytest.raises(StepUpRefused):
        _stepup(session, clock, login_user="someone-else").issue(ME, "o@x", "pw", "FLATTEN")
    su = _stepup(session, clock)
    g = su.issue(ME, "o@x", "pw", "FLATTEN")
    with pytest.raises(StepUpRefused):
        su.consume(g, Principal("u2", "trader"), "FLATTEN")
    with pytest.raises(StepUpRefused):
        su.issue(ME, "o@x", "pw", "WITHDRAW")


def test_only_a_hash_of_the_grant_is_stored(session, clock) -> None:
    grant = _stepup(session, clock).issue(ME, "o@x", "pw", "FLATTEN")
    row = session.scalar(select(StepUpGrant))
    assert grant not in (row.token_hash, row.scope, row.user_id) and len(row.token_hash) == 64


# ------------------------------------------------------------------ promotion

THRESHOLDS = Thresholds(
    min_paper_trades=3,
    max_paper_drawdown_pct=D("15"),
    backtest_min_return_pct=D("1"),
    max_live_capital_idr=D("5000000"),
    max_slippage_pct=D("0.5"),
)
GOOD = SuppliedEvidence(
    backtest_return_pct=D("4"),
    paper_drawdown_pct=D("8"),
    live_capital_used_idr=D("1000000"),
    slippage_vs_paper_pct=D("0.1"),
)


def paper_sells(session, n: int, when: datetime) -> None:
    order = OrderRow(
        origin="PAPER",
        pair="BTCIDR",
        side="SELL",
        type="LIMIT",
        quantity=D("1"),
        client_order_id="p1",
        executed_qty=D("0"),
        state="FILLED",
        purpose="EXIT",
        submitted_at=when,
        updated_at=when,
    )
    session.add(order)
    session.flush()
    for i in range(n):
        session.add(
            Fill(
                order_id=order.id,
                origin="PAPER",
                exchange_trade_id=f"pt{i}",
                pair="BTCIDR",
                side="SELL",
                price=D("1"),
                quantity=D("1"),
                quote_quantity=D("1"),
                executed_at=when,
            )
        )
    session.commit()


@pytest.fixture
def promo(session, clock):
    p = Promotion(session, now=clock)
    p.register("ema_adx", "v1")
    return p


def ready(session, clock, trades: int = 5) -> None:
    clock.advance(weeks=5)
    paper_sells(session, trades, clock.t - timedelta(days=1))


def test_promotion_requires_all_gates_and_has_no_override(promo, session, clock) -> None:
    paper_sells(session, 3, T0)
    with pytest.raises(PromotionRefused) as e:  # too soon
        promo.promote("ema_adx", "owner", THRESHOLDS, GOOD)
    assert any("duration" in r for r in e.value.reasons)
    clock.advance(weeks=4)
    assert promo.promote("ema_adx", "owner", THRESHOLDS, GOOD, "ok").mode == "APPROVAL"


def test_an_unset_threshold_blocks_promotion(promo, session, clock) -> None:
    ready(session, clock)
    with pytest.raises(PromotionRefused) as e:
        promo.promote("ema_adx", "owner", Thresholds(), GOOD)
    assert any("threshold unset" in r for r in e.value.reasons)


def test_missing_evidence_blocks_even_with_thresholds_set(promo, session, clock) -> None:
    ready(session, clock)
    with pytest.raises(PromotionRefused) as e:
        promo.promote("ema_adx", "owner", THRESHOLDS, SuppliedEvidence())
    assert any("no evidence" in r for r in e.value.reasons)


def test_each_failing_value_blocks(promo, session, clock) -> None:
    ready(session, clock, trades=2)  # below the 3-trade minimum
    with pytest.raises(PromotionRefused) as e:
        promo.promote("ema_adx", "owner", THRESHOLDS, GOOD)
    assert any(r.startswith("paper_activity") for r in e.value.reasons)


def test_an_unresolved_reconciliation_difference_blocks(promo, session, clock) -> None:
    ready(session, clock)
    run = ReconciliationRun(started_at=T0, result="differences", differences=1)
    session.add(run)
    session.flush()
    session.add(ReconciliationDifference(run_id=run.id, kind="x", reference="r"))
    session.commit()
    with pytest.raises(PromotionRefused) as e:
        promo.promote("ema_adx", "owner", THRESHOLDS, GOOD)
    assert any(r.startswith("data_integrity") for r in e.value.reasons)


def test_promotion_records_the_evidence_and_a_mode_change(promo, session, clock) -> None:
    ready(session, clock)
    promo.promote("ema_adx", "owner", THRESHOLDS, GOOD, "all gates met")
    mc = session.scalar(select(ModeChange))
    assert (mc.from_mode, mc.to_mode, mc.by, mc.note) == (
        "PAPER",
        "APPROVAL",
        "owner",
        "all gates met",
    )
    assert {g["name"] for g in mc.evidence["gates"]} >= {"duration", "backtest", "paper_activity"}


def test_paper_cannot_skip_to_auto_and_auto_needs_a_step_up(promo, session, clock) -> None:
    ready(session, clock)
    promo.promote("ema_adx", "owner", THRESHOLDS, GOOD)
    clock.advance(weeks=5)
    with pytest.raises(PromotionRefused, match="step-up"):
        promo.promote("ema_adx", "owner", THRESHOLDS, GOOD)
    assert promo.promote("ema_adx", "owner", THRESHOLDS, GOOD, step_up_ok=True).mode == "AUTO"


def test_a_breaker_during_approval_blocks_auto(promo, session, clock) -> None:
    ready(session, clock)
    promo.promote("ema_adx", "owner", THRESHOLDS, GOOD)
    clock.advance(weeks=5)
    session.add(
        BreakerEvent(
            breaker="daily_loss",
            tier="CANCEL",
            observed="1",
            limit="1",
            tripped_at=clock.t - timedelta(days=1),
        )
    )
    session.commit()
    with pytest.raises(PromotionRefused) as e:
        promo.promote("ema_adx", "owner", THRESHOLDS, GOOD, step_up_ok=True)
    assert any(r.startswith("no_breaker") for r in e.value.reasons)


def test_demotion_is_always_allowed_and_a_new_version_returns_to_paper(
    promo, session, clock
) -> None:
    ready(session, clock)
    promo.promote("ema_adx", "owner", THRESHOLDS, GOOD)
    assert promo.demote("ema_adx", "owner", "PAPER", "pause").mode == "PAPER"
    session.get(StrategyRow, "ema_adx").mode = "APPROVAL"
    session.commit()
    promo.register("ema_adx", "v2")
    assert session.get(StrategyRow, "ema_adx").mode == "PAPER"
    with pytest.raises(PromotionRefused):
        promo.demote("ema_adx", "owner", "AUTO")


def test_an_automated_actor_cannot_promote(promo) -> None:
    for actor in ("system", "job-x", ""):
        with pytest.raises(PromotionRefused):
            promo.promote("ema_adx", actor, THRESHOLDS, GOOD)


def test_min_duration_is_the_one_decided_number() -> None:
    assert MIN_DURATION == timedelta(weeks=4)


# --------------------------------------------------------------------- export


def test_export_row_count_matches_and_is_audited(session) -> None:
    for i in range(5):
        session.add(
            LedgerEntry(
                origin="LIVE",
                entry_type="FILL",
                asset="IDR",
                amount=D(i),
                at=T0 + timedelta(minutes=i),
            )
        )
    session.add(
        LedgerEntry(
            origin="LIVE", entry_type="FILL", asset="IDR", amount=D(1), at=T0 + timedelta(days=9)
        )
    )
    session.commit()
    text, n = export_ledger(session, T0 - timedelta(hours=1), T0 + timedelta(days=1), "owner")
    assert n == 5 and len(text.strip().splitlines()) == 6  # header + rows
    assert any(a.action == "export.ledger" for a in session.scalars(select(AuditLog)))
    end = datetime.now(UTC) + timedelta(days=1)
    text, n = export_audit(session, T0 - timedelta(days=1), end, "owner")
    assert n == len(text.strip().splitlines()) - 1


def test_a_spreadsheet_formula_in_a_cell_is_neutralised(session) -> None:
    session.add(
        LedgerEntry(
            origin="LIVE",
            entry_type="ADJUSTMENT",
            asset="IDR",
            amount=D(1),
            reason='=HYPERLINK("x")',
            at=T0,
        )
    )
    session.commit()
    text, _ = export_ledger(session, T0 - timedelta(hours=1), T0 + timedelta(hours=1), "owner")
    assert "'=HYPERLINK" in text and ",=HYPERLINK" not in text


# ------------------------------------------------------------------------ API

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
    cooldown_s=60,
    order_rate_limit=5,
)
USERS = {
    "tok-trader": ("u1", "trader"),
    "tok-admin": ("u2", "admin"),
    "tok-viewer": ("u3", "viewer"),
}
RANGE = {"start": "2026-11-01T00:00:00Z", "end": "2026-12-01T00:00:00Z"}


class Api:
    def __init__(self, *, stale: bool = False) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        ).execution_options(schema_translate_map={"trading": None})
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)
        self.env = Env()
        self.chan = RecordingChannel()
        self.sent = Sent()
        self.stale = stale

        def me(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/auth/login":
                return httpx.Response(200, json={"access_token": "tok-trader"})
            who = USERS.get(req.headers.get("authorization", "")[7:])
            if who is None:
                return httpx.Response(401)
            return httpx.Response(200, json={"id": who[0], "role": who[1]})

        self.transport = httpx.MockTransport(me)
        verifier = TokenVerifier("https://a.test", timeout_s=2, transport=self.transport)
        ctx = ApiContext(
            session_factory=self.factory,
            verifier=verifier,
            stepup=lambda s: StepUp(s, "https://a.test", verifier, transport=self.transport),
            notifier=lambda s: Notifier(s, self.chan),
            killswitch=lambda s: KillSwitch(s, self.env.client),
            submit_approved=lambda s, i: self.sent(),
            thresholds=lambda: THRESHOLDS,
            freshness=lambda: (T0, self.stale),
        )
        self.app = create_app(ctx)
        self.http = TestClient(self.app)
        self.n = 0

    def call(
        self,
        method: str,
        path: str,
        token: str | None = "tok-trader",
        *,
        body=None,
        step_up: str | None = None,
        **params,
    ):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if method != "GET":
            self.n += 1
            headers["Idempotency-Key"] = f"k{self.n}"
        if step_up:
            headers["X-Step-Up"] = step_up
        return self.http.request(
            method, "/trader/v1" + path, headers=headers, json=body, params=params or None
        )

    def grant(self, scope: str) -> str:
        r = self.call("POST", "/stepup", body={"email": "o@x", "password": "pw", "scope": scope})
        assert r.status_code == 200, r.text
        return r.json()["data"]["grant"]

    def seed_intent(self) -> str:
        with self.factory() as s:
            i = intent()
            s.add(
                OrderIntentRow(
                    identity=i.identity,
                    origin="LIVE",
                    strategy_version="v1",
                    pair="BTCIDR",
                    side="BUY",
                    entry_price=i.entry_price,
                    quantity=i.quantity,
                    stop_price=i.stop_price,
                    risk_amount_idr=i.risk_amount_idr,
                    rule_snapshot={},
                    state="AWAITING_APPROVAL",
                    created_at=T0,
                )
            )
            s.commit()
            ApprovalWorkflow(s).request(i)
        return intent_hash(intent())


@pytest.fixture
def api() -> Api:
    return Api()


def test_every_route_declares_a_permission_and_none_is_forbidden_by_name(api) -> None:
    from fastapi.routing import APIRoute

    names = []
    for route in api.app.routes:
        if not isinstance(route, APIRoute):
            continue
        perms: list[str] = []

        def walk(dep, perms=perms):
            for sub in dep.dependencies:
                p = getattr(sub.call, "__permission__", None)
                if p:
                    perms.append(p)
                walk(sub)

        walk(route.dependant)
        assert perms, f"{route.path} has no permission dependency"
        names.append(route.path.lower())
    assert names
    for banned in ("withdraw", "deposit", "fiat"):
        assert not any(banned in n for n in names)


def test_there_is_no_order_entry_route(api) -> None:
    for route in api.app.routes:
        if getattr(route, "path", "").endswith("/orders"):
            assert getattr(route, "methods", set()) <= {"GET"}, "orders may only be read"
    assert api.call("POST", "/orders", body={"pair": "BTCIDR"}).status_code in (404, 405)


def test_no_response_schema_names_a_secret(api) -> None:
    doc = api.http.get("/openapi.json").json()
    # Responses: nothing a caller receives may carry a secret-like field.
    responses = json.dumps(
        [op.get("responses") for p in doc["paths"].values() for op in p.values()]
    )
    for word in ("api_key", "secret", "signature", "password_hash", "uid"):
        assert f'"{word}"' not in responses.lower()
    # Requests: only the one write-only credential body may name a key or secret.
    for name, schema in doc["components"]["schemas"].items():
        if name == "CredentialBody":
            continue
        props = json.dumps(schema.get("properties", {})).lower()
        assert '"secret"' not in props and '"api_key"' not in props, name
    assert "/trader/v1/kill" in json.dumps(doc["paths"])


def test_authentication_and_permissions_are_enforced_server_side(api) -> None:
    assert api.call("GET", "/status", token=None).status_code == 401
    assert api.call("GET", "/status", token="nope").status_code == 401
    assert api.call("GET", "/status", token="tok-viewer").status_code == 200
    assert api.call("GET", "/audit", token="tok-viewer").status_code == 403
    assert api.call("GET", "/audit", token="tok-admin").status_code == 200
    # admin holds every trader permission (ADR-048); a viewer holds none of the write ones.
    assert api.call("POST", "/resume", token="tok-admin", body={"note": "x"}).status_code == 200
    r = api.call("POST", "/resume", token="tok-viewer", body={"note": "x"})
    assert r.status_code == 403 and r.json()["error"]["class"] == "FORBIDDEN"


def test_role_matrix_matches_the_document() -> None:
    assert ROLE_PERMISSIONS["admin"] == ROLE_PERMISSIONS["trader"]  # ADR-048
    assert allowed("admin", "trade:kill") and allowed("admin", "trade:approve")
    assert not allowed("viewer", "trade:approve") and not allowed("investor", "trade:halt")
    assert ROLE_PERMISSIONS["trader"] >= {"trade:approve", "trade:promote", "trade:kill"}
    assert not allowed("nobody", "trade:view")


def test_mutations_need_an_idempotency_key(api) -> None:
    r = api.http.post(
        "/trader/v1/kill", headers={"Authorization": "Bearer tok-trader"}, json={"tier": "HALT"}
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "idempotency_key_required"


def test_dashboard_marks_stale_data() -> None:
    body = Api(stale=True).call("GET", "/dashboard").json()
    assert body["meta"]["stale"] is True and body["meta"]["origin"] == "LIVE"
    assert body["meta"]["as_of"].startswith("2026-11-14")
    assert Api().call("GET", "/dashboard").json()["meta"]["stale"] is False


def test_unset_limits_are_shown_as_unset(api) -> None:
    data = api.call("GET", "/limits").json()["data"]
    assert data["limits"] is None and "max_order_idr" in data["unset"]


def test_kill_works_for_an_admin_at_every_tier_but_flatten_still_needs_a_step_up(api) -> None:
    assert api.call("POST", "/kill", token="tok-admin", body={"tier": "HALT"}).status_code == 200
    assert api.call("GET", "/status").json()["data"]["trading_state"] == "HALTED"
    ok = api.call(
        "POST",
        "/kill",
        token="tok-admin",
        body={"tier": "CANCEL", "confirmation": "CANCEL ALL OPEN ORDERS"},
    )
    assert ok.status_code == 200
    flat = api.call(
        "POST",
        "/kill",
        token="tok-admin",
        body={"tier": "FLATTEN", "confirmation": "SELL ALL HOLDINGS AT MARKET"},
    )
    assert flat.status_code == 403 and flat.json()["error"]["code"] == "step_up_required"
    viewer = api.call("POST", "/kill", token="tok-viewer", body={"tier": "HALT"})
    assert viewer.status_code == 403
    assert any("kill switch HALT" in m for m in api.chan.messages)


def test_cancel_and_flatten_need_confirmation_and_flatten_needs_step_up(api) -> None:
    assert api.call("POST", "/kill", body={"tier": "CANCEL"}).status_code == 400
    bad = api.call("POST", "/kill", body={"tier": "CANCEL", "confirmation": "yes"})
    assert bad.status_code == 400
    ok = api.call(
        "POST", "/kill", body={"tier": "CANCEL", "confirmation": "CANCEL ALL OPEN ORDERS"}
    )
    assert ok.status_code == 200
    flat = {"tier": "FLATTEN", "confirmation": "SELL ALL HOLDINGS AT MARKET"}
    r = api.call("POST", "/kill", body=flat)
    assert r.status_code == 403 and r.json()["error"]["code"] == "step_up_required"
    assert not [o for o in api.env.mock.orders.values() if o["side"] == "SELL"]
    assert api.call("POST", "/kill", body=flat, step_up=api.grant("FLATTEN")).status_code == 200
    assert [o for o in api.env.mock.orders.values() if o["side"] == "SELL"]
    assert api.call("POST", "/kill", body=flat, step_up="reused-or-forged").status_code == 403


def test_kill_works_with_nothing_else_running(api) -> None:
    # This app instance has no strategy, intents, or approvals: the route needs only the
    # kill switch and the exchange client.
    assert api.call("POST", "/kill", body={"tier": "HALT"}).status_code == 200


def test_resume_needs_a_note(api) -> None:
    api.call("POST", "/kill", body={"tier": "HALT"})
    assert api.call("POST", "/resume", body={"note": "  "}).status_code == 409
    assert api.call("POST", "/resume", body={"note": "checked"}).status_code == 200


def test_approval_is_bound_to_exact_intent_over_the_api(api) -> None:
    h = api.seed_intent()
    path = f"/intents/{intent().identity}/approve"
    assert api.call("POST", path, body={}).status_code == 400
    stale = api.call("POST", path, body={"intent_hash": "0" * 64})
    assert stale.status_code == 409 and api.sent.calls == 0
    ok = api.call("POST", path, body={"intent_hash": h})
    assert ok.status_code == 200 and ok.json()["data"]["sent"] is True
    twice = api.call("POST", path, body={"intent_hash": h})
    assert twice.json()["data"]["already_decided"] is True and api.sent.calls == 1


def test_only_the_trader_and_admin_roles_may_approve_or_deny(api) -> None:
    h = api.seed_intent()
    path = f"/intents/{intent().identity}/approve"
    assert api.call("POST", path, token="tok-viewer", body={"intent_hash": h}).status_code == 403
    deny = api.call("POST", path.replace("approve", "deny"), token="tok-viewer", body={})
    assert deny.status_code == 403
    assert api.sent.calls == 0
    assert api.call("POST", path, token="tok-admin", body={"intent_hash": h}).status_code == 200
    assert api.sent.calls == 1


def test_deny_records_the_reason(api) -> None:
    api.seed_intent()
    r = api.call("POST", f"/intents/{intent().identity}/deny", body={"reason": "no"})
    assert r.status_code == 200 and r.json()["data"]["state"] == "DENIED"


def test_raising_a_limit_needs_step_up_and_lowering_does_not(api) -> None:
    with api.factory() as s:
        save_risk_limits(s, LIMITS, set_by="owner")
        s.commit()
    lower = api.call("PUT", "/limits", body={"limits": {"max_order_idr": "1000000"}})
    assert lower.status_code == 200
    up = api.call("PUT", "/limits", body={"limits": {"max_order_idr": "90000000"}})
    assert up.status_code == 403 and up.json()["error"]["code"] == "step_up_required"
    ok = api.call(
        "PUT",
        "/limits",
        body={"limits": {"max_order_idr": "90000000"}},
        step_up=api.grant("RAISE_LIMIT"),
    )
    assert ok.status_code == 200
    assert api.call("PUT", "/limits", body={"limits": {"bogus": 1}}).status_code == 400
    assert api.call("PUT", "/limits", body={"limits": {"max_order_idr": "abc"}}).status_code == 400


def test_loosens_direction_rules() -> None:
    def with_(**kw):
        return replace(LIMITS, **kw)

    assert loosens(LIMITS, with_(max_open_positions=5))
    assert not loosens(LIMITS, with_(max_open_positions=1))
    assert loosens(LIMITS, with_(cooldown_s=5))
    assert not loosens(LIMITS, with_(cooldown_s=600))
    assert loosens(RiskLimits(), LIMITS)  # turning trading on from unset is the loosest change
    assert not loosens(LIMITS, with_(max_order_idr=None))


def test_promotion_over_the_api_enforces_gates(api) -> None:
    with api.factory() as s:
        Promotion(s).register("ema_adx", "v1")
    r = api.call("POST", "/strategies/ema_adx/promote", body={})
    assert r.status_code == 409 and "duration" in r.json()["error"]["message"]
    gates = api.call("GET", "/strategies/ema_adx/promotion").json()["data"]
    assert gates["next"] == "APPROVAL" and not all(g["passed"] for g in gates["gates"])
    assert api.call("POST", "/strategies/nope/promote", body={}).status_code == 404


def test_promotion_to_auto_needs_a_step_up_before_anything_else(api) -> None:
    with api.factory() as s:
        Promotion(s).register("ema_adx", "v1")
        s.get(StrategyRow, "ema_adx").mode = "APPROVAL"
        s.commit()
    r = api.call("POST", "/strategies/ema_adx/promote", body={})
    assert r.status_code == 403 and r.json()["error"]["code"] == "step_up_required"


def test_events_can_be_acknowledged(api) -> None:
    with api.factory() as s:
        ev = Notifier(s, None).emit("kill_switch_used", "kill switch HALT used")
    assert api.call("POST", f"/events/{ev.id}/ack", token="tok-viewer").status_code == 200
    assert api.call("POST", "/events/not-a-uuid/ack").status_code == 404


def test_export_row_count_matches_over_the_api_and_the_audit_is_guarded(api) -> None:
    with api.factory() as s:
        s.add(LedgerEntry(origin="LIVE", entry_type="FILL", asset="IDR", amount=D(1), at=T0))
        s.commit()
    r = api.call("GET", "/export", kind="ledger", **RANGE)
    assert r.status_code == 200 and r.headers["x-row-count"] == "1"
    assert api.call("GET", "/export", token="tok-viewer", kind="audit", **RANGE).status_code == 403
    assert api.call("GET", "/export", kind="secrets", **RANGE).status_code == 400


def test_the_intent_list_carries_the_hash_and_approval_state_the_card_needs(api) -> None:
    h = api.seed_intent()
    row = api.call("GET", "/intents").json()["data"][0]
    assert row["intent_hash"] == h and row["approval"]["state"] == "AWAITING"
    assert row["entry_price"] == "1236777000" and row["quantity"] == "0.01"  # not padded
    assert row["approval"]["expires_at"]


def test_timestamps_are_always_utc_with_an_offset_so_a_browser_cannot_misread_them(api) -> None:
    api.seed_intent()
    row = api.call("GET", "/intents").json()["data"][0]
    assert row["created_at"].endswith("+00:00") and row["approval"]["expires_at"].endswith("+00:00")


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("risk_per_trade_pct", "0"),
        ("risk_per_trade_pct", "101"),
        ("max_order_idr", "-5"),
        ("max_open_positions", "0"),
        ("freshness_limit_s", "-1"),
        ("cooldown_s", "-1"),
        ("daily_loss_day_boundary", "UTC"),
        ("trading_window", "25:00-26:00"),
        ("trading_window", "9-17"),
    ],
)
def test_a_limit_outside_its_range_is_refused_by_the_api(api, name, value) -> None:
    r = api.call("PUT", "/limits", body={"limits": {name: value}})
    assert r.status_code == 400 and name in r.json()["error"]["message"]


def test_clearing_a_limit_is_accepted_and_reads_back_as_unset(api) -> None:
    with api.factory() as s:
        save_risk_limits(s, LIMITS, set_by="owner")
        s.commit()
    r = api.call("PUT", "/limits", body={"limits": {"max_order_idr": None, "trading_window": ""}})
    assert r.status_code == 200 and "max_order_idr" in r.json()["data"]["unset"]
    got = api.call("GET", "/limits").json()["data"]
    assert got["limits"]["max_order_idr"] is None and got["limits"]["max_drawdown_pct"] == "20"
    ok = api.call("PUT", "/limits", body={"limits": {"trading_window": "08:00-22:30"}})
    assert ok.status_code == 200
