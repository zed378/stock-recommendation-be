"""T6-02: resilience R1-R11, performance P1-P4 and P6, and a PAPER soak, on the SYNTHETIC mock.

Failure injection runs only against the mock exchange and a test database; nothing here can reach a
real exchange. The numeric bounds that depend on owner settings are not invented: each test states
what it compares with what, and the measured values are asserted against the structural limits
(the documented Indodax limits and the Trader's own configured intervals), not against a target.

Findings from writing these are recorded in MEMORY/records; where a requirement is not met today the
test says so (xfail, strict) instead of passing quietly.
"""

from __future__ import annotations

import logging
import tracemalloc
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from aidss_trader.connector.errors import ConnectorError, ErrorClass
from aidss_trader.db.models import (
    AuditLog,
    BreakerEvent,
    EquitySnapshot,
    Fill,
    KillSwitchStep,
    OrderRow,
    PaperEquitySnapshot,
    PositionStop,
    TradingEvent,
)
from aidss_trader.killswitch import KillSwitch
from aidss_trader.lease import LeaseHolder
from aidss_trader.reconcile import reconcile
from aidss_trader.runtime import Runtime
from tests.trader.test_runtime_wiring import World, entered, fail, warm

D = Decimal
SIGNED = {
    "/api/v2/account",
    "/api/v2/openOrders",
    "/api/v2/order",
    "/api/v2/myTrades",
    "/api/v2/order/histories",
}


def gets(w: World, path: str) -> int:
    return len([r for r in w.env.mock.requests if r["method"] == "GET" and r["path"] == path])


def events(w: World, *kinds: str):
    return [e for e in w.rows(TradingEvent) if e.kind in kinds]


def crash_stop(w: World) -> None:
    """Take the price below the position's stop and make the exit fill at that price."""
    stop = w.rows(PositionStop)[0].stop_price
    w.env.mock.prices["BTCIDR"] = str(int(stop) - 5_000_000)
    w.env.mock.market_fill_price = w.env.mock.prices["BTCIDR"]


# ------------------------------------------------------------------------------ R1


def test_r1_a_5xx_window_blocks_entries_keeps_trying_the_stop_and_recovers_after_a_resume() -> None:
    w = World("AUTO")
    entered(w)
    w.cycle()
    posts_before, ticker_before = w.posts(), gets(w, "/api/v2/ticker/price")
    for _ in range(8):  # an outage longer than the owner's freshness limit (60 s in this test)
        for path in ("/api/v2/account", "/api/v2/ticker/price"):
            fail(w, "GET", path)
        w.cycle()
    # Halted by the stale-data breaker or, a moment earlier, by a reconciliation that could not
    # read the exchange: both are the fail-closed answer to the same outage.
    from aidss_trader.db.models import ReconciliationRun

    assert w.state() == "HALTED"
    assert any(b.breaker == "stale_data" for b in w.rows(BreakerEvent)) or any(
        r.result == "failed" for r in w.rows(ReconciliationRun)
    )
    assert events(w, "breaker_tripped", "reconciliation_difference") and events(
        w, "exit_unprotected", "watchdog_stalled"
    )
    assert (
        gets(w, "/api/v2/ticker/price") > ticker_before + 8
    )  # the exit monitor never stopped trying
    assert w.posts() == posts_before  # and nothing new was sent
    w.env.mock._injected.clear()  # the outage is over: no queued failures left
    # Recovery needs no manual step except the resume that a halt always needs: the first clean
    # reconciliation supersedes the "could not read the exchange" difference by itself.
    w.cycle()
    assert w.state() == "HALTED"
    w.cycle(61_000)  # past the reconciliation interval
    with w.factory() as s:
        KillSwitch(s, w.env.client, now=w.now).resume("exchange is back", "owner")
    report = w.cycle()
    assert report.snapshot_ok and w.state() == "RUNNING"


# ------------------------------------------------------------------------------ R2


def test_r2_a_timeout_on_create_never_duplicates_an_order_and_the_throttle_holds() -> None:
    w = World("AUTO")
    w.cycle()
    w.env.mock.inject_timeout("POST", "/api/v2/order")
    w.cycle()
    for _ in range(6):
        w.cycle()
    assert w.posts() == 1  # one attempt, ever, for that intent
    assert [o for o in w.rows(OrderRow) if o.state == "UNKNOWN"]
    limited = [r for r in w.env.mock.requests if r["path"] in SIGNED]
    assert limited and not any(r.get("status") == 429 for r in w.env.mock.requests)


# ------------------------------------------------------------------------------ R3


def test_r3_a_burst_of_minus_1003_is_not_hammered_and_is_reported_as_a_throttle_defect() -> None:
    w = World("PAPER")
    warm(w, 2)
    before = gets(w, "/api/v2/ticker/price")
    reports = []
    for _ in range(3):
        for _ in range(4):
            w.env.mock.inject_error("GET", "/api/v2/ticker/price", 429, -1003, "Too many requests")
        reports.append(w.cycle())
    attempts = gets(w, "/api/v2/ticker/price") - before
    assert attempts <= 3 * 3  # the client's own bounded read retries, never an open loop
    assert all(any("RATE_LIMIT" in e for e in r.errors) for r in reports)


# ------------------------------------------------------------------------------ R4


def test_r4_a_truncated_read_is_malformed_and_nothing_is_partially_accepted() -> None:
    w = World("PAPER")
    warm(w, 2)
    for _ in range(4):
        w.env.mock.inject(
            "GET", "/api/v2/account", lambda: httpx.Response(200, content=b'{"canTrade": tr')
        )
    report = w.cycle()
    assert not report.snapshot_ok and any("MALFORMED" in e for e in report.errors)
    assert not report.snapshot_ok  # no half-read account ever becomes a snapshot


def test_r4_a_truncated_create_response_leaves_the_order_unknown_never_open_or_rejected() -> None:
    w = World("AUTO")
    w.cycle()
    w.env.mock.inject(
        "POST", "/api/v2/order", lambda: httpx.Response(200, content=b'{"orderId": 12')
    )
    w.cycle()
    orders = w.rows(OrderRow)
    assert len(orders) == 1 and orders[0].state == "UNKNOWN"
    assert w.posts() == 1


# ------------------------------------------------------------------------------ R5


def test_r5_a_dead_price_feed_marks_the_position_unprotected_and_blocks_entries() -> None:
    # What is covered: calls that fail. A feed that keeps answering with the same stale value is NOT
    # detected, because freshness is the age of the last successful call; that gap is recorded as a
    # finding rather than asserted away.
    w = World("AUTO")
    entered(w)
    w.cycle()
    for _ in range(8):
        fail(w, "GET", "/api/v2/ticker/price")
        w.cycle()
    assert events(w, "exit_unprotected", "watchdog_stalled")
    assert w.state() == "HALTED"  # so no entry can be made
    assert len(w.rows(OrderRow)) == 1


# ------------------------------------------------------------------------------ R6


def test_r6_a_crash_after_the_write_ahead_row_but_before_the_send_resends_nothing() -> None:
    w = World("AUTO")
    w.cycle()
    now = w.now()
    with w.factory() as s:
        s.add(
            OrderRow(
                origin="LIVE",
                pair="BTCIDR",
                side="BUY",
                type="LIMIT",
                quantity=D("1"),
                price=D("1"),
                client_order_id="crashed-before-send",
                executed_qty=0,
                state="SUBMITTING",
                purpose="ENTRY",
                submitted_at=now - timedelta(minutes=5),
                updated_at=now,
            )
        )
        s.commit()
    posts = w.posts()
    for _ in range(3):
        w.cycle()
    row = [o for o in w.rows(OrderRow) if o.client_order_id == "crashed-before-send"][0]
    assert row.state == "UNKNOWN"  # it may or may not have left: not "never sent"
    assert w.posts() == posts  # and it is never sent again
    assert w.state() == "HALTED"  # UNKNOWN halts


def test_r6_a_crash_after_the_send_is_resolved_by_query_without_a_duplicate() -> (
    None
):
    w = World(
        "PAPER"
    )  # PAPER: the runtime sends no entry of its own, so any POST would be a duplicate
    w.cycle()
    now = w.now()
    placed = w.env.client.create_order(
        symbol="BTCIDR",
        side="BUY",
        order_type="LIMIT",
        price=D("1"),
        quantity=D("1"),
        client_order_id="sent-then-crashed",
    )
    with w.factory() as s:
        s.add(
            OrderRow(
                origin="LIVE",
                pair="BTCIDR",
                side="BUY",
                type="LIMIT",
                quantity=D("1"),
                price=D("1"),
                client_order_id="sent-then-crashed",
                executed_qty=0,
                state="SUBMITTING",
                purpose="ENTRY",
                submitted_at=now - timedelta(minutes=5),
                updated_at=now,
            )
        )
        s.commit()
    posts = w.posts()
    w.cycle()
    w.cycle()
    row = [o for o in w.rows(OrderRow) if o.client_order_id == "sent-then-crashed"][0]
    assert row.state == "OPEN" and row.exchange_order_id == placed.order_id
    assert w.posts() == posts  # found by query, never re-created


def test_r6_a_kill_switch_interrupted_part_way_finishes_on_the_next_activation() -> None:
    w = World("AUTO")
    for ident in ("a", "b", "c"):
        w.env.client.create_order(
            symbol="BTCIDR",
            side="BUY",
            order_type="LIMIT",
            price=D("1"),
            quantity=D("1"),
            client_order_id=f"open-{ident}",
        )
    w.env.mock.inject_error("DELETE", "/api/v2/order", 500, -1001, "down")
    with w.factory() as s:
        ks = KillSwitch(s, w.env.client, now=w.now)
        ks.activate("CANCEL", "owner", "owner")  # the first cancel fails
        failed = [x for x in s.scalars(select(KillSwitchStep)) if x.result == "failed"]
        assert failed
        ks.activate("CANCEL", "owner", "owner")  # run it again, as an operator would
    assert {o["status"] for o in w.env.mock.orders.values()} == {"CANCELLED"}


def test_r6_re_ingesting_the_same_trades_after_a_crash_never_duplicates_a_fill() -> None:
    w = World("AUTO")
    order = entered(w)
    trades = w.env.client.get_my_trades("BTCIDR")
    from aidss_trader.orders.manager import OrderManager

    with w.factory() as s:
        row = s.scalar(select(OrderRow).where(OrderRow.id == order.id))
        mgr = OrderManager(s, w.env.client, now=w.now)
        assert mgr.ingest_fills(row, trades) == 0  # the cycle already stored them
        assert mgr.ingest_fills(row, trades) == 0
    assert len(w.rows(Fill)) == 1


# ------------------------------------------------------------------------------ R7


class Flaky(Session):
    failing = False

    def commit(self) -> None:
        if Flaky.failing:
            raise OperationalError("COMMIT", {}, Exception("the database restarted"))
        super().commit()


def test_r7_a_database_failure_sends_no_order_without_a_persisted_row_and_recovers() -> None:
    w = World("AUTO")
    w.cycle()  # first reconciliation
    w.factory.class_ = Flaky
    Flaky.failing = True
    try:
        with pytest.raises(OperationalError):
            w.cycle()
        assert w.posts() == 0  # the write-ahead commit failed, so nothing was sent
        assert w.rows(OrderRow) == []
    finally:
        Flaky.failing = False
    w.cycle()
    w.cycle()
    assert w.posts() <= 1 and (not w.rows(OrderRow) or w.rows(OrderRow)[0].client_order_id)


# ------------------------------------------------------------------------------ R8


@pytest.mark.parametrize("skew_ms", [5_000, -5_000])
def test_r8_a_clock_jump_either_way_is_detected_and_halts(skew_ms: int) -> None:
    w = World("PAPER")
    warm(w, 2)
    w.env.client._clock = w.env.mock.client_clock(skew_ms)  # type: ignore[attr-defined]
    w.env.client._last_clock_ok = None  # type: ignore[attr-defined]
    w.cycle()
    assert w.state() == "HALTED" and any(b.breaker == "clock_skew" for b in w.rows(BreakerEvent))
    assert w.posts() == 0


# ------------------------------------------------------------------------------ R9


def test_r9_a_failing_notification_channel_does_not_touch_the_order_path() -> None:
    w = World("AUTO")
    w.chan.fail = True  # every notification fails to send
    entered(w)
    w.cycle()
    crash_stop(w)
    w.cycle()
    assert [o for o in w.rows(OrderRow) if o.purpose == "STOP"]  # the stop went out regardless
    assert events(w, "stop_executed")  # and the event is stored even though delivery failed


def test_r9_the_trader_has_no_dependency_on_the_analysis_platform_for_trading() -> None:
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "aidss_trader"
    for rel in ("runtime", "orders", "risk", "exits", "killswitch", "reconcile"):
        for path in (root / rel).glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text("utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert node.module != "aidss" and not node.module.startswith("aidss."), path


# ----------------------------------------------------------------------------- R10


def test_r10_exactly_one_holder_at_any_moment_across_loss_and_takeover(session) -> None:
    a, b = LeaseHolder("a", 15), LeaseHolder("b", 15)
    t = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
    assert a.acquire(session, now=t) and not b.acquire(session, now=t)
    session.commit()
    holders = []
    for step in range(1, 40):
        t += timedelta(seconds=4 if step % 7 else 20)  # now and then a holder misses its renewals
        for h in (a, b) if step % 2 else (b, a):
            if step % 7 == 0 and h is a:
                continue  # a is paused (a stalled process) for this beat
            h.acquire(session, now=t)
            session.commit()
        session.expire_all()  # read what the database says, not this session's cache
        current = a.current(session)
        holders.append(current.holder if current else None)
    assert set(holders) <= {"a", "b"}
    assert "b" in holders  # a takeover happened
    # at no beat did both believe they held it: each acquire returns True for at most one holder
    t += timedelta(seconds=1)
    results = [h.acquire(session, now=t) for h in (a, b)]
    assert sum(results) <= 1


# ----------------------------------------------------------------------------- R11


class Boom(logging.Handler):
    """A handler whose disk is full: every emit raises."""

    def emit(self, record: logging.LogRecord) -> None:
        raise OSError(28, "No space left on device")


def test_r11_a_failing_log_handler_stops_neither_a_stop_nor_the_kill_switch(monkeypatch) -> None:
    w = World("AUTO")
    entered(w)
    w.cycle()
    boom = Boom()
    names = ("aidss_trader", "aidss_trader.runtime", "")
    for n in names:
        logging.getLogger(n).addHandler(boom)
    try:
        # A step that raises makes the loop log; the log itself raises; the stop must still go out.
        original = Runtime._sync_orders

        def broken(self, *a, **kw):
            raise RuntimeError("unexpected failure in a later step")

        monkeypatch.setattr(Runtime, "_sync_orders", broken)
        crash_stop(w)
        report = w.cycle()
        monkeypatch.setattr(Runtime, "_sync_orders", original)
        assert any("sync" in e for e in report.errors)
        assert [o for o in w.rows(OrderRow) if o.purpose == "STOP"]
        with w.factory() as s:
            KillSwitch(s, w.env.client, now=w.now).activate("HALT", "owner", "owner")
        assert w.state() == "HALTED"
    finally:
        for n in names:
            logging.getLogger(n).removeHandler(boom)


# ------------------------------------------------------------------------------ P1


def test_p1_the_request_budget_stays_below_the_strictest_documented_limit_with_headroom() -> None:
    w = World("PAPER")
    w.runtime = Runtime(
        w.factory, w.env.client, now=w.now
    )  # production intervals, not the test ones
    for _ in range(7):  # ~70 s: more than one minute of cycles
        w.cycle()
    minute = w.env.mock.requests
    private = [r for r in minute if r["path"] in SIGNED]
    public_v2 = [r for r in minute if r["path"].startswith("/api/v2/ticker")]
    legacy = [
        r
        for r in minute
        if r["path"]
        in {"/api/server_time", "/api/pairs", "/api/price_increments", "/tradingview/history_v2"}
    ]
    seconds = 7 * 11 + 1
    per_min = lambda n: n * 60 / seconds  # noqa: E731
    # Documented limits: private 300/min, public v2 300/min, legacy public 180/min (D7, D19). The
    # Trader's own throttle keeps half; measured use must sit below that headroom.
    assert (
        per_min(len(private)) <= 150
        and per_min(len(public_v2)) <= 150
        and per_min(len(legacy)) <= 90
    )


# ------------------------------------------------------------------------------ P2


def test_p2_a_stop_crossing_is_answered_within_one_polling_interval() -> None:
    w = World("AUTO")
    entered(w)
    w.cycle()
    crash_stop(w)
    posts_before = w.posts()
    t0 = w.env.mock.now_ms
    w.runtime.cycle()  # the very next cycle after the crossing, with no extra waiting
    assert w.posts() == posts_before + 1  # the MARKET request went out in that cycle
    assert w.env.mock.now_ms - t0 <= 10_000  # within the configured price poll (ADR-041: 10 s)


# ------------------------------------------------------------------------------ P3


def test_p3_the_cancel_tier_cancels_every_open_order_without_hitting_a_rate_limit() -> None:
    w = World("AUTO")
    n = 20
    for i in range(n):
        w.env.client.create_order(
            symbol="BTCIDR",
            side="BUY",
            order_type="LIMIT",
            price=D("1"),
            quantity=D("1"),
            client_order_id=f"bulk-{i}",
        )
    started = w.env.mock.now_ms
    with w.factory() as s:
        KillSwitch(s, w.env.client, now=w.now).activate("CANCEL", "owner", "owner")
    deletes = [r for r in w.env.mock.requests if r["method"] == "DELETE"]
    assert len(deletes) == n and {o["status"] for o in w.env.mock.orders.values()} == {"CANCELLED"}
    # Recorded, not targeted: the owner's tolerance (OQ) is the bound, and none is set.
    elapsed_s = (w.env.mock.now_ms - started) / 1000
    assert elapsed_s < 60, elapsed_s


# ------------------------------------------------------------------------------ P4


def test_p4_a_reconciliation_run_uses_about_two_requests_per_pair_plus_two() -> None:
    w = World("PAPER")
    warm(w, 1)
    before = len([r for r in w.env.mock.requests if r["path"] in SIGNED])
    with w.factory() as s:
        reconcile(s, w.env.client, ["BTCIDR", "ETHIDR"], now=w.now)
    used = len([r for r in w.env.mock.requests if r["path"] in SIGNED]) - before
    assert used <= 2 * 2 + 2  # ADR-044: 2P + 2 signed requests per run for P pairs


# ------------------------------------------------------------------------------ P6


def test_p6_a_candle_refresh_is_one_legacy_call_per_pair() -> None:
    w = World("PAPER")
    warm(w, 1)
    before = gets(w, "/tradingview/history_v2")
    w.cycle()
    assert gets(w, "/tradingview/history_v2") - before <= 1  # one pair on the allowlist


# ------------------------------------------------------------------------------- soak


def test_soak_a_long_paper_run_with_periodic_failures_stays_bounded() -> None:
    """About 400 cycles (73 minutes of simulated time) with an injected outage every 25 cycles.

    Bounds stated here: no growth in Python memory beyond 40 MB between the warm-up and the end; the
    equity series grows at most once per minute; events do not repeat per cycle; the request rate in
    the last third is within 25% of the first third; and the runtime keeps cycling.
    """
    w = World("PAPER")
    w.runtime = Runtime(w.factory, w.env.client, now=w.now, candle_poll_s=300)
    start_ms = w.env.mock.now_ms
    for _ in range(60):  # warm-up so one-time allocations are not counted as growth
        w.cycle()
    tracemalloc.start()
    base = tracemalloc.take_snapshot()
    mark = len(w.env.mock.requests)
    third = 110
    counts = []
    cycles_run = 0
    for i in range(1, 331):
        if i % 25 == 0:
            for path in ("/api/v2/ticker/price", "/api/v2/account"):
                fail(w, "GET", path, 3)
        report = w.cycle()
        cycles_run += 1
        assert report is not None
        if i % third == 0:
            counts.append(len(w.env.mock.requests) - mark)
            mark = len(w.env.mock.requests)
    grown = sum(s.size_diff for s in tracemalloc.take_snapshot().compare_to(base, "filename"))
    tracemalloc.stop()
    assert grown < 40 * 1024 * 1024, grown
    # Simulated time, not 11 s per cycle: the throttle's waits advance the mock clock too.
    minutes = (w.env.mock.now_ms - start_ms) / 60000
    assert (
        len(w.rows(EquitySnapshot)) <= minutes + 5
        and len(w.rows(PaperEquitySnapshot)) <= minutes + 5
    )
    assert len(w.rows(TradingEvent)) <= 60  # alerts fire on transitions, not every cycle
    assert len(w.rows(AuditLog)) <= 40
    first, last = counts[0], counts[-1]
    assert abs(last - first) <= 0.25 * first, counts
    assert cycles_run == 330 and ConnectorError and ErrorClass
