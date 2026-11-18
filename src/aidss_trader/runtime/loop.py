"""The Trader's run loop: one cycle observes, protects, syncs, decides, and reconciles.

Order of work in a cycle is the order of importance, and each step is isolated so
a failure in one never skips a protective one:

1. State: a fresh install begins HALTED (the owner resumes with a note).
2. Snapshot: account, prices, books, clock. If it cannot be built, nothing that
   opens risk happens this cycle.
3. Breakers: permissions, clock, UNKNOWN order, reconciliation, loss limits,
   stale data. They HALT or CANCEL, never sell (ADR-036).
4. Protect: the exit monitor, one price call for every position (ADR-007).
5. Sync: orders, UNKNOWN resolution by query, fills, stops for new positions.
6. Decide: strategies, only while RUNNING, with a full snapshot and every
   required limit set. PAPER intents are recorded and never sent; APPROVAL
   entries become approval cards; AUTO and signal exits go through the Risk
   Engine and the order manager.
7. Housekeeping: approval expiry, notification retry, reconciliation.

Fail closed throughout: a value that cannot be computed (equity, drawdown) blocks
entries rather than being assumed.

PAPER intents are simulated forward by `paper_lifecycle` (fills, stops, exits) on the
owner's cost model; with none set, nothing is simulated or recorded. The liquidity
filter's 24-hour volume is derived from stored candles, not from an exchange call.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from aidss_trader.approvals import ApprovalWorkflow
from aidss_trader.config import load_risk_limits, unset_risk_fields
from aidss_trader.config.limits import RiskLimits
from aidss_trader.connector.client import canonical
from aidss_trader.connector.errors import ConnectorError, ErrorClass
from aidss_trader.connector.port import ExchangeClient
from aidss_trader.connector.types import Account, BookTicker
from aidss_trader.connector.types import Candle as ApiCandle
from aidss_trader.db.models import (
    BreakerEvent,
    Candle,
    Fill,
    OrderIntentRow,
    OrderRow,
    PositionStop,
    ReconciliationDifference,
    ReconciliationRun,
    StrategyRow,
)
from aidss_trader.exits import ExitMonitor, WatchedPosition
from aidss_trader.intents.builder import (
    Intent,
    build_entry_intent,
    build_exit_intent,
)
from aidss_trader.killswitch import KillSwitch
from aidss_trader.ledger.position import LedgerIntegrityError, Position
from aidss_trader.logsafe import safe_log
from aidss_trader.market_data.candles import TIMEFRAME_SECONDS, ingest_candles
from aidss_trader.market_data.pairs import PairRules, build_pair_rules, floor_to_increment
from aidss_trader.notify import Notifier
from aidss_trader.orders.manager import OrderManager, SubmitResult
from aidss_trader.orders.state import OrderState
from aidss_trader.reconcile import reconcile, windows
from aidss_trader.risk.engine import CheckResult, Decision, RiskContext, breakers
from aidss_trader.runtime import accounting
from aidss_trader.runtime.pair_selection import resolve_all
from aidss_trader.runtime.paper_lifecycle import PaperBook
from aidss_trader.runtime.settings_store import (
    MAX_HISTORY_BARS,
    Allowlist,
    get_allowlist,
    get_paper_settings,
    load_strategy,
)

logger = logging.getLogger("aidss_trader.runtime")

ZERO = Decimal(0)
# How often ALL is re-resolved from the exchange summary, and how long a stale selection may be
# kept when that fails. Candle refreshes per cycle are bounded so a long list cannot overrun one.
ALL_REFRESH_S = 300
ALL_MAX_AGE_S = 900
CANDLE_REFRESH_PER_CYCLE = 8
QUOTE = "IDR"
LIVE_OPEN = (
    OrderState.SUBMITTING.value,
    OrderState.UNKNOWN.value,
    OrderState.OPEN.value,
    OrderState.PARTIALLY_FILLED.value,
    OrderState.CANCEL_REQUESTED.value,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(v: datetime) -> datetime:
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


@dataclass(slots=True)
class Snapshot:
    at: datetime
    account: Account
    prices: dict[str, Decimal]
    books: dict[str, BookTicker]
    equity: Decimal | None  # None: something held could not be valued, so entries are blocked
    clock_ok: bool
    permissions_ok: bool


@dataclass(slots=True)
class CycleReport:
    snapshot_ok: bool = False
    tripped: list[str] = field(default_factory=list)
    stops_sent: int = 0
    intents: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _Inputs:
    """Breaker inputs; structurally a `BreakerInputs`."""

    limits: RiskLimits | None
    permissions_ok: bool
    clock_ok: bool
    unknown_orders: int
    reconciliation_clean: bool
    daily_realised_loss_idr: Decimal
    drawdown_pct: Decimal
    consecutive_losses: int
    market_data_age_s: float


class Runtime:
    def __init__(
        self,
        factory: sessionmaker[Session],
        client: ExchangeClient | None,
        *,
        notifier: Callable[[Session], Notifier] | None = None,
        now: Callable[[], datetime] = _now,
        timeframe: str = "4H",
        candle_bars: int = MAX_HISTORY_BARS,
        price_poll_s: float = 10,
        reconcile_s: float = 60,
        candle_poll_s: float = 300,
        rules_refresh_s: float = 3600,
        watchdog_cycles: int = 3,
    ) -> None:
        self._factory, self._client, self._now = factory, client, now
        self._notifier = notifier
        self._tf, self._bars = timeframe, candle_bars
        self._price_poll_s, self._reconcile_s = price_poll_s, reconcile_s
        self._candle_poll_s, self._rules_refresh_s = candle_poll_s, rules_refresh_s
        self._monitor = ExitMonitor(watchdog_cycles=watchdog_cycles)
        self._rules: dict[str, PairRules] = {}
        self._last: dict[str, datetime] = {}
        self._alerted: set[str] = set()
        self._clock_bad = False
        # ALL, resolved from the exchange's summary and refreshed on a timer (see _active_pairs).
        self._all_key: tuple | None = None
        self._all_pairs: tuple[str, ...] = ()
        self._all_at: datetime | None = None
        self._candle_at: dict[str, datetime] = {}
        self.last_snapshot_at: datetime | None = None
        self._last_snapshot: Snapshot | None = None

    # ----------------------------------------------------------------- public

    @property
    def client(self) -> ExchangeClient | None:
        return self._client

    @property
    def notifier_factory(self) -> Callable[[Session], Notifier] | None:
        return self._notifier

    def run_if_due(self) -> CycleReport | None:
        """One cycle per price-poll interval; the caller may loop faster (the lease needs it)."""
        if not self._due("cycle", self._price_poll_s):
            return None
        return self.cycle()

    def freshness(self) -> tuple[datetime, bool]:
        """(as_of, stale) for the API: stale with no snapshot or one older than 3 cycles."""
        now = self._now()
        at = self.last_snapshot_at
        if at is None:
            return now, True
        return at, (now - at).total_seconds() > 3 * self._price_poll_s

    def cycle(self) -> CycleReport:
        report = CycleReport()
        with self._factory() as s:
            ks = KillSwitch(s, self._client, now=self._now)
            ks.ensure_initialized()
            notifier = self._notifier(s) if self._notifier else None
            limits = load_risk_limits(s)
            try:
                positions, events = accounting.replay_live(s)
            except LedgerIntegrityError as exc:
                self._alert_once(
                    s,
                    notifier,
                    "ledger",
                    "reconciliation_difference",
                    "the ledger is inconsistent with the exchange's trades",
                )
                ks.activate("HALT", "service", "runtime")
                report.errors.append(f"ledger: {exc}")
                positions, events = {}, []
            # Prices come first and on their own: the stops depend on them, and they must not
            # wait on the account call, the clock check, or anything else that can fail (R1).
            prices = self._step(report, "prices", lambda: self._fetch_prices(s, positions))
            # No prices means the exchange is not answering: asking again for the same prices in the
            # snapshot would only double the requests during an outage (R3).
            snap = (
                None
                if prices is None
                else self._step(
                    report, "snapshot", lambda: self._snapshot(s, limits, prices=prices)
                )
            )
            report.snapshot_ok = snap is not None
            if snap is not None:
                self._last_snapshot, self.last_snapshot_at = snap, snap.at

            inputs = self._breaker_inputs(s, limits, snap, events)
            self._trip_breakers(s, ks, notifier, inputs, report)
            if self._client is not None:
                self._step(
                    report,
                    "protect",
                    lambda: self._protect(s, ks, notifier, snap, prices, positions, limits, report),
                )
            self._step(report, "sync", lambda: self._sync_orders(s, notifier, snap, ks))
            if self._client is not None:
                self._step(report, "candles", lambda: self._refresh_all_candles(s, report))
            self._step(report, "paper", lambda: self._paper_step(s, report))
            if snap is not None:
                self._step(report, "equity", lambda: self._record_equity(s, snap))
                if ks.state() == "RUNNING":
                    self._step(
                        report,
                        "decide",
                        lambda: self._decide(
                            s, ks, notifier, snap, limits, positions, events, report
                        ),
                    )
                else:
                    # A halted Trader makes no new decisions, not even cards or paper records.
                    report.skipped.append(f"not RUNNING ({ks.state()}): no decisions")
            self._step(report, "housekeeping", lambda: self._housekeeping(s, notifier, ks))
            s.commit()
        return report

    def submit_approved(self, s: Session, intent: Intent) -> SubmitResult:
        """Send an approved entry: risk is evaluated again now, against current data."""
        if self._client is None:
            return self._refused("exchange_client", "no exchange client configured")
        limits = load_risk_limits(s)
        try:
            snap = self._snapshot(s, limits, pairs=[intent.pair])
        except ConnectorError as exc:
            return self._refused("market_snapshot", f"{exc.error_class}")
        positions, events = accounting.replay_live(s)
        ks = KillSwitch(s, self._client, now=self._now)
        rules = self._rules.get(intent.pair)
        if rules is None or snap.equity is None or intent.pair not in snap.books:
            return self._refused("market_snapshot", "no rules, equity, or book for the pair")
        ctx = self._context(s, ks, snap, limits, rules, intent, positions, events, intent.mode)
        manager = self._manager(s)
        return manager.submit(intent, ctx, purpose="ENTRY")

    # ------------------------------------------------------------------ steps

    def _step(self, report: CycleReport, name: str, fn: Callable[[], object | None]) -> object:
        try:
            return fn()
        except ConnectorError as exc:
            report.errors.append(f"{name}: {exc.error_class}")
        except Exception as exc:  # a failed step must never stop the protective ones after it
            safe_log(logger, logging.ERROR, "runtime step %s failed", name, exc_info=True)
            report.errors.append(f"{name}: {type(exc).__name__}")
        return None

    def _active_pairs(self, s: Session, allow: Allowlist | None = None) -> tuple[str, ...]:
        """The pairs the runtime watches and decides on: the owner's named pairs, plus, when ALL
        is on with its number set, the liquid markets the exchange summary currently selects.
        Fail closed: if the selection cannot be refreshed it is kept for a while, then dropped,
        so ALL never keeps trading a stale list."""
        allow = allow or get_allowlist(s)
        if not allow.all_active or self._client is None:
            return allow.pairs
        assert allow.max_pairs is not None
        key = (
            allow.max_pairs,
            allow.liquidity.min_quote_volume_24h_idr,
            allow.liquidity.max_spread_pct,
        )
        now = self._now()
        age = None if self._all_at is None else (now - self._all_at).total_seconds()
        if key != self._all_key or age is None or age >= ALL_REFRESH_S:
            try:
                self._all_pairs = resolve_all(
                    self._client.get_pairs(),
                    self._client.get_market_summaries(),
                    allow.liquidity,
                    allow.max_pairs,
                )
                self._all_key, self._all_at = key, now
            except ConnectorError as exc:
                logger.warning("ALL could not be refreshed: %s", exc.error_class)
                if key != self._all_key or age is None or age >= ALL_MAX_AGE_S:
                    self._all_pairs, self._all_key, self._all_at = (), key, None
        return tuple(sorted({*allow.pairs, *self._all_pairs}))

    def _due(self, name: str, every_s: float) -> bool:
        now = self._now()
        last = self._last.get(name)
        if last is None or (now - last).total_seconds() >= every_s:
            self._last[name] = now
            return True
        return False

    def _alert_once(
        self, s: Session, notifier: Notifier | None, key: str, kind: str, message: str
    ) -> None:
        """Alert on the transition into a condition, not every cycle while it lasts."""
        if key in self._alerted:
            return
        self._alerted.add(key)
        if notifier:
            notifier.emit(kind, message)

    def _clear_alert(self, key: str) -> None:
        self._alerted.discard(key)

    def _manager(self, s: Session) -> OrderManager:
        assert self._client is not None
        # One query per cycle instead of five in a row: the loop must not sleep for half a
        # minute with positions unwatched. The cycle repeats the query, and UNKNOWN halts at once.
        return OrderManager(
            s,
            self._client,
            now=self._now,
            sleep=lambda _s: None,
            unknown_queries=1,
            unknown_window_s=0,
        )

    @staticmethod
    def _refused(name: str, why: str) -> SubmitResult:
        return SubmitResult(None, Decision(False, "ENTRY", [CheckResult(name, False, why)]))

    # --------------------------------------------------------------- snapshot

    def _fetch_prices(
        self, s: Session, positions: dict[str, Position]
    ) -> dict[str, Decimal] | None:
        """One price call for every allowlisted pair and every position held."""
        if self._client is None:
            return None
        wanted = sorted({canonical(p) for p in self._active_pairs(s)} | set(positions))
        if not wanted:
            return {}
        try:
            return self._client.get_last_prices(wanted)
        except ConnectorError:
            # One bad allowlist entry (an unknown or suspended pair) must not blind the stops:
            # ask again for only what is held.
            if positions and set(wanted) != set(positions):
                return self._client.get_last_prices(sorted(positions))
            raise

    def _snapshot(
        self,
        s: Session,
        limits: RiskLimits | None,
        pairs: list[str] | None = None,
        prices: dict[str, Decimal] | None = None,
    ) -> Snapshot | None:
        if self._client is None:
            return None
        client = self._client
        try:
            client.check_clock()
            self._clock_bad = False
        except ConnectorError as exc:
            # Signed calls would be refused anyway, so stop here; the breaker reads the flag.
            self._clock_bad = exc.error_class is ErrorClass.CLOCK_SKEW
            raise
        account = client.get_account()
        permissions_ok = (
            account.can_trade and not account.can_withdraw and not account.can_withdraw_fiat
        )
        allow = get_allowlist(s)
        active = self._active_pairs(s, allow)
        held = [
            a
            for a, (free, locked) in account.balances.items()
            if a != QUOTE and (free + locked) > 0
        ]
        wanted = sorted(
            {canonical(p) for p in (pairs or active)} | {f"{a}{QUOTE}" for a in held}
        )
        # Prices already fetched this cycle are reused; only what is still missing is asked for.
        prices = dict(prices or {})
        missing = [w for w in wanted if w not in prices]
        if missing:
            prices.update(client.get_last_prices(missing))
        books = client.get_book_tickers(wanted) if wanted else {}
        equity: Decimal | None = ZERO
        for asset, (free, locked) in account.balances.items():
            qty = free + locked
            if qty <= 0:
                continue
            if asset == QUOTE:
                equity += qty
            elif f"{asset}{QUOTE}" in prices:
                equity += qty * prices[f"{asset}{QUOTE}"]
            else:
                equity = None  # cannot value what is held: not zero, unknown
                break
        if self._due("rules", self._rules_refresh_s) or not self._rules:
            self._refresh_rules(s)
        return Snapshot(self._now(), account, prices, books, equity, True, permissions_ok)

    def _minimal_snapshot(self, prices: dict[str, Decimal]) -> Snapshot:
        """Just enough to send a protective sell when the full snapshot could not be built.

        Permissions are whatever the last good snapshot said, and unknown counts as fine: a
        stop only reduces risk, and the permission breaker has its own path to HALT.
        """
        last = self._last_snapshot
        account = last.account if last else Account(True, False, False, {})
        return Snapshot(
            self._now(),
            account,
            dict(prices),
            {},
            None,
            True,
            last.permissions_ok if last else True,
        )

    def _refresh_rules(self, s: Session) -> None:
        assert self._client is not None
        from aidss_trader.market_data.pairs import store_pair_rules

        rules = build_pair_rules(self._client.get_pairs(), self._client.get_price_increments())
        self._rules = rules
        store_pair_rules(s, rules, self._now())

    # --------------------------------------------------------------- breakers

    def _recon_state(self, s: Session) -> tuple[bool, bool]:
        """(clean enough to open risk, free of a known difference)."""
        last = s.scalar(select(ReconciliationRun).order_by(ReconciliationRun.started_at.desc()))
        open_diffs = (
            s.scalar(
                select(func.count())
                .select_from(ReconciliationDifference)
                .where(ReconciliationDifference.resolved_at.is_(None))
            )
            or 0
        )
        no_difference = open_diffs == 0 and (last is None or last.result == "clean")
        return (last is not None and last.result == "clean" and open_diffs == 0), no_difference

    def _unknown_count(self, s: Session) -> int:
        return (
            s.scalar(
                select(func.count())
                .select_from(OrderRow)
                .where(OrderRow.origin == "LIVE", OrderRow.state == OrderState.UNKNOWN.value)
            )
            or 0
        )

    def _breaker_inputs(
        self,
        s: Session,
        limits: RiskLimits | None,
        snap: Snapshot | None,
        events: list[accounting.Realised],
    ) -> _Inputs:
        now = self._now()
        _, no_difference = self._recon_state(s)
        equity = snap.equity if snap else None
        dd = accounting.drawdown_pct(s, equity) if equity is not None else ZERO
        # Age of the last *successful* snapshot, so one failed poll is not an outage but a
        # sustained one trips the stale-data breaker against the owner's freshness limit.
        seen = snap.at if snap else self.last_snapshot_at
        age = (now - seen).total_seconds() if seen else float("inf")
        return _Inputs(
            limits=limits,
            permissions_ok=snap.permissions_ok if snap else True,  # unknown is not a violation
            clock_ok=not self._clock_bad,
            unknown_orders=self._unknown_count(s),
            reconciliation_clean=no_difference,
            daily_realised_loss_idr=accounting.daily_loss(events, now),
            drawdown_pct=dd,
            consecutive_losses=accounting.consecutive_losses(events),
            market_data_age_s=age,
        )

    def _trip_breakers(
        self,
        s: Session,
        ks: KillSwitch,
        notifier: Notifier | None,
        inputs: _Inputs,
        report: CycleReport,
    ) -> None:
        if ks.state() != "RUNNING":
            return  # already stopped; repeating the activation every cycle would only add noise
        if self._client is None:
            return
        tripped = breakers(inputs)
        if not tripped:
            return
        worst = "CANCEL" if any(b.tier == "CANCEL" for b in tripped) else "HALT"
        for b in tripped:
            s.add(
                BreakerEvent(
                    breaker=b.name,
                    tier=b.tier,
                    observed=b.observed[:64],
                    limit=b.limit[:64],
                    tripped_at=self._now(),
                )
            )
            report.tripped.append(b.name)
            if notifier:
                notifier.emit(
                    "breaker_tripped",
                    f"breaker {b.name} tripped: {b.tier}",
                    {"breaker": b.name, "tier": b.tier},
                )
        s.commit()
        ks.activate(worst, "breaker", "runtime")

    # ----------------------------------------------------------------- protect

    def _protect(
        self,
        s: Session,
        ks: KillSwitch,
        notifier: Notifier | None,
        snap: Snapshot | None,
        prices: dict[str, Decimal] | None,
        positions: dict[str, Position],
        limits: RiskLimits | None,
        report: CycleReport,
    ) -> None:
        """`prices` is None when the price call failed: the monitor still runs, blind, so the
        position is reported unprotected and the watchdog counts the missed cycles. A missing
        `snap` (the account call failed) does not stop a stop: the prices are enough to decide,
        and a minimal snapshot carries the sell through the EMERGENCY profile."""
        self._ensure_stops(s, positions, notifier)
        stops = {
            p.pair: p for p in s.scalars(select(PositionStop).where(PositionStop.origin == "LIVE"))
        }
        watched = [
            WatchedPosition(pair, pos.quantity, stops[pair].stop_price)
            for pair, pos in positions.items()
            if pair in stops
        ]
        for pair in positions:
            if pair not in stops:
                self._alert_once(
                    s,
                    notifier,
                    f"nostop:{pair}",
                    "exit_unprotected",
                    f"{pair} has a position and no recorded stop",
                )
        report_c = self._monitor.cycle(
            watched,
            dict(prices) if prices is not None else None,
            price_time=self._now() if prices is not None else None,
            now=self._now(),
            max_age_s=self._price_poll_s * 3,
        )
        for pair in positions:
            if pair in report_c.unprotected:
                self._alert_once(
                    s,
                    notifier,
                    f"stale:{pair}",
                    "exit_unprotected",
                    f"{pair} has no fresh price: the stop is not being watched",
                )
            else:
                self._clear_alert(f"stale:{pair}")
                self._clear_alert(f"watchdog:{pair}")
        for message in report_c.alerts:
            # One alert per position per outage: the message carries a growing cycle count,
            # so it cannot be the key.
            pair = message.split(" has ")[0].split()[-1]
            self._alert_once(s, notifier, f"watchdog:{pair}", "watchdog_stalled", message)
        for req in report_c.exits:
            sent = self._send_stop(
                s,
                ks,
                notifier,
                snap or self._minimal_snapshot(prices or {}),
                positions[req.pair],
                req.pair,
                req.observed_price,
                limits,
            )
            if sent:
                report.stops_sent += 1
            else:
                self._monitor.clear(req.pair)  # try again next cycle

    def _ensure_stops(
        self, s: Session, positions: dict[str, Position], notifier: Notifier | None
    ) -> None:
        """Every position's stop comes from the intent that opened it, and never loosens."""
        now = self._now()
        for pair in positions:
            entry = s.scalar(
                select(OrderRow)
                .where(
                    OrderRow.origin == "LIVE",
                    OrderRow.pair == pair,
                    OrderRow.purpose == "ENTRY",
                    OrderRow.executed_qty > 0,
                )
                .order_by(OrderRow.updated_at.desc())
            )
            if entry is None or entry.intent_identity is None:
                continue
            intent = s.scalar(
                select(OrderIntentRow).where(OrderIntentRow.identity == entry.intent_identity)
            )
            if intent is None or intent.stop_price is None:
                continue
            row = s.scalar(
                select(PositionStop).where(PositionStop.pair == pair, PositionStop.origin == "LIVE")
            )
            if row is None:
                s.add(
                    PositionStop(
                        pair=pair, origin="LIVE", stop_price=intent.stop_price, updated_at=now
                    )
                )
            elif _aware(row.updated_at) < _aware(entry.submitted_at):
                row.stop_price, row.updated_at = intent.stop_price, now  # a new position
        s.flush()

    def _send_stop(
        self,
        s: Session,
        ks: KillSwitch,
        notifier: Notifier | None,
        snap: Snapshot,
        pos: Position,
        pair: str,
        observed: Decimal,
        limits: RiskLimits | None,
    ) -> bool:
        rules = self._rules.get(pair)
        if rules is None or rules.quantity_increment is None or rules.price_increment is None:
            self._alert_once(
                s,
                notifier,
                f"stopfail:{pair}",
                "exit_unprotected",
                f"{pair} stop triggered but its pair rules are unknown",
            )
            return False
        live_stop = s.scalar(
            select(OrderRow).where(
                OrderRow.origin == "LIVE",
                OrderRow.pair == pair,
                OrderRow.purpose == "STOP",
                OrderRow.state.in_(LIVE_OPEN),
            )
        )
        if live_stop is not None:
            return True  # a stop is already working; never stack a second sell
        qty = floor_to_increment(pos.quantity, rules.quantity_increment)
        price = floor_to_increment(observed, rules.price_increment)
        attempt = (
            s.scalar(
                select(func.count())
                .select_from(OrderRow)
                .where(OrderRow.pair == pair, OrderRow.purpose == "STOP")
            )
            or 0
        )
        intent = Intent(
            identity=f"stop|{pair}|{pos.avg_cost}|{pos.quantity}",
            strategy_version="stop",
            pair=pair,
            side="SELL",
            entry_price=price,
            quantity=qty,
            stop_price=None,
            risk_amount_idr=None,
            rule_snapshot={"observed": str(observed)},
            mode="AUTO",
            signal_candle_open=self._now(),
        )
        ctx = self._context(
            s, ks, snap, limits, rules, intent, {pair: pos}, [], "AUTO", has_position=True
        )
        result = self._manager(s).submit(
            intent, ctx, purpose="STOP", order_type="MARKET", attempt=attempt
        )
        if result.order is None:
            failed = ",".join(c.name for c in result.decision.failed)
            self._alert_once(
                s,
                notifier,
                f"stopfail:{pair}",
                "exit_unprotected",
                f"{pair} stop could not be sent: {failed}",
            )
            return False
        self._clear_alert(f"stopfail:{pair}")
        if notifier:
            notifier.emit(
                "stop_executed", f"{pair} stop triggered", {"pair": pair, "stop_price": str(price)}
            )
        return True

    # -------------------------------------------------------------------- sync

    def _sync_orders(
        self, s: Session, notifier: Notifier | None, snap: Snapshot | None, ks: KillSwitch
    ) -> None:
        if self._client is None:
            return
        manager = self._manager(s)
        now = self._now()
        for order in s.scalars(
            select(OrderRow).where(OrderRow.origin == "LIVE", OrderRow.state.in_(LIVE_OPEN))
        ):
            if (
                order.state == OrderState.SUBMITTING.value
                and (now - _aware(order.submitted_at)).total_seconds() > 30
            ):
                # The request may have left before a crash: that is UNKNOWN, not "never sent".
                order.state = OrderState.UNKNOWN.value
                s.flush()
            if order.state == OrderState.UNKNOWN.value:
                if manager.resolve_unknown(order):
                    self._clear_alert(f"unknown:{order.client_order_id}")
                else:
                    self._alert_once(
                        s,
                        notifier,
                        f"unknown:{order.client_order_id}",
                        "order_unknown",
                        f"{order.pair} order outcome unresolved",
                    )
            elif order.state != OrderState.SUBMITTING.value:
                manager.sync(order)
            if order.purpose == "STOP" and order.state in {
                OrderState.REJECTED.value,
                OrderState.CANCELLED.value,
            }:
                self._monitor.clear(order.pair)
        # Fills: fetch trades for any order that executed more than we have stored.
        for order in s.scalars(
            select(OrderRow).where(OrderRow.origin == "LIVE", OrderRow.executed_qty > 0)
        ):
            have = (
                s.scalar(
                    select(func.coalesce(func.sum(Fill.quantity), 0)).where(
                        Fill.order_id == order.id
                    )
                )
                or ZERO
            )
            if Decimal(have) >= order.executed_qty:
                continue
            start = _aware(order.submitted_at) - timedelta(minutes=1)
            end = now + timedelta(minutes=1)
            for w0, w1 in windows(start, end):
                trades = self._client.get_my_trades(
                    order.pair,
                    start_ms=int(w0.timestamp() * 1000),
                    end_ms=int(w1.timestamp() * 1000),
                )
                manager.ingest_fills(order, trades)
        s.flush()

    # ------------------------------------------------------------------ decide

    def _liquid(self, s: Session, pair: str, allow: Allowlist, snap: Snapshot) -> bool:
        f = allow.liquidity
        book = snap.books.get(pair)
        if not f.configured or book is None or book.bid_price <= 0:
            return False
        spread = (book.ask_price - book.bid_price) / book.bid_price * 100
        window = 24 * 3600 // TIMEFRAME_SECONDS[self._tf]
        recent = s.scalars(
            select(Candle)
            .where(Candle.pair == pair, Candle.timeframe == self._tf)
            .order_by(Candle.open_time.desc())
            .limit(window)
        ).all()
        if len(recent) < window:
            return False  # not enough stored history to measure 24 h volume: not liquid, unknown
        quote_volume = sum((c.volume * c.close for c in recent), ZERO)
        assert f.min_quote_volume_24h_idr is not None and f.max_spread_pct is not None
        return quote_volume >= f.min_quote_volume_24h_idr and spread <= f.max_spread_pct

    def _load_candles(self, s: Session, pair: str) -> list[ApiCandle]:
        rows = s.scalars(
            select(Candle)
            .where(Candle.pair == pair, Candle.timeframe == self._tf)
            .order_by(Candle.open_time.desc())
            .limit(self._bars)
        ).all()
        return [
            ApiCandle(_aware(r.open_time), r.open, r.high, r.low, r.close, r.volume)
            for r in reversed(rows)
        ]

    def _refresh_candles(self, s: Session, pair: str) -> None:
        assert self._client is not None
        now = self._now()
        span = self._bars * TIMEFRAME_SECONDS[self._tf]
        got = self._client.get_ohlc(
            pair, self._tf, int(now.timestamp()) - span, int(now.timestamp())
        )
        ingest_candles(s, pair, self._tf, got, now=now)

    def _decide(
        self,
        s: Session,
        ks: KillSwitch,
        notifier: Notifier | None,
        snap: Snapshot,
        limits: RiskLimits | None,
        positions: dict[str, Position],
        events: list[accounting.Realised],
        report: CycleReport,
    ) -> None:
        allow = get_allowlist(s)
        active = self._active_pairs(s, allow)
        strategy = load_strategy(s)
        if strategy is None or not active:
            report.skipped.append("no strategy parameters or empty allowlist")
            return
        row = s.get(StrategyRow, strategy.name)
        if row is None or row.version != strategy.version_id():
            report.skipped.append("strategy version is not registered")
            return
        if limits is None or unset_risk_fields(limits):
            report.skipped.append("required risk limits unset")
            return
        paper_equity: Decimal | None = None
        if row.mode == "PAPER":
            ps = get_paper_settings(s)
            if ps is None:
                report.skipped.append("paper cost model and start capital unset (owner)")
                return
            positions, events = accounting.replay_origin(s, "PAPER")
            closes = {p: c[-1].close for p in active if (c := self._load_candles(s, p))}
            paper_equity = accounting.paper_equity(ps.start_equity_idr, positions, events, closes)
        for pair in active:
            rules = self._rules.get(pair)
            if rules is None or not rules.tradable:
                report.skipped.append(f"{pair}: pair rules missing or blocked")
                continue
            if not self._liquid(s, pair, allow, snap):
                report.skipped.append(f"{pair}: liquidity filter unset or not met")
                continue
            candles = self._load_candles(s, pair)
            if len(candles) < strategy.min_history():
                report.skipped.append(f"{pair}: not enough candle history")
                continue
            tf_s = TIMEFRAME_SECONDS[self._tf]
            last = candles[-1]
            if (self._now() - last.open_time).total_seconds() > 2 * tf_s:
                report.skipped.append(f"{pair}: latest closed candle is stale")
                continue
            self._decide_pair(
                s,
                ks,
                notifier,
                snap,
                limits,
                positions,
                events,
                report,
                strategy,
                row.mode,
                pair,
                rules,
                candles,
                paper_equity,
            )

    def _decide_pair(
        self,
        s,
        ks,
        notifier,
        snap,
        limits,
        positions,
        events,
        report,
        strategy,
        mode,
        pair,
        rules,
        candles,
        equity_override: Decimal | None = None,
    ) -> None:
        from aidss_trader.strategy.base import PositionState, SignalKind

        pos = positions.get(pair)
        last_exit = next((e.at for e in reversed(events) if e.pair == pair), None)
        signal = strategy.evaluate(
            candles,
            PositionState(
                long=pos is not None,
                entry_price=pos.avg_cost if pos else None,
                last_exit_at=last_exit,
            ),
        )
        equity = equity_override if equity_override is not None else snap.equity
        if signal.kind is SignalKind.NONE or equity is None:
            return
        book = snap.books.get(pair)
        if book is None:
            return
        last = candles[-1]
        if signal.kind is SignalKind.ENTRY and pos is None:
            built = build_entry_intent(
                signal,
                strategy_version=strategy.version_id(),
                pair=pair,
                candle_open=last.open_time,
                equity_idr=equity,
                limits=limits,
                rules=rules,
                best_bid=book.bid_price,
                mode=mode,
            )
        elif signal.kind is SignalKind.EXIT and pos is not None:
            built = build_exit_intent(
                signal,
                strategy_version=strategy.version_id(),
                pair=pair,
                candle_open=last.open_time,
                position_qty=pos.quantity,
                rules=rules,
                best_ask=book.ask_price,
                mode=mode,
            )
        else:
            return
        if built.intent is None:
            report.skipped.append(f"{pair}: {'; '.join(built.reasons)}")
            return
        intent = built.intent
        if s.scalar(select(OrderIntentRow).where(OrderIntentRow.identity == intent.identity)):
            return  # this candle was already decided: a restart cannot create a second intent
        sends_now = mode == "AUTO" or (mode == "APPROVAL" and intent.side == "SELL")
        if sends_now and not self._recon_state(s)[0]:
            # Wait rather than decide: an intent refused for a transient reason would use up
            # this candle's identity and the entry would never be retried.
            report.skipped.append(f"{pair}: no clean reconciliation yet")
            return
        state = (
            "PAPER_RECORDED"
            if mode == "PAPER"
            else ("AWAITING_APPROVAL" if mode == "APPROVAL" and intent.side == "BUY" else "CREATED")
        )
        s.add(
            OrderIntentRow(
                identity=intent.identity,
                origin="PAPER" if mode == "PAPER" else "LIVE",
                strategy_version=intent.strategy_version,
                pair=pair,
                side=intent.side,
                entry_price=intent.entry_price,
                quantity=intent.quantity,
                stop_price=intent.stop_price,
                risk_amount_idr=intent.risk_amount_idr,
                rule_snapshot={**signal.inputs, "reason": signal.reason},
                state=state,
                created_at=self._now(),
            )
        )
        s.commit()
        report.intents.append(intent.identity)
        if mode == "PAPER":
            return  # recorded, labelled PAPER, never sent
        if state == "AWAITING_APPROVAL":
            ApprovalWorkflow(
                s, self._notifier(s) if self._notifier else None, now=self._now
            ).request(intent, {"reason": signal.reason})
            return
        ctx = self._context(s, ks, snap, limits, rules, intent, positions, events, mode)
        result = self._manager(s).submit(
            intent, ctx, purpose="ENTRY" if intent.side == "BUY" else "EXIT"
        )
        row = s.scalar(select(OrderIntentRow).where(OrderIntentRow.identity == intent.identity))
        if row is not None:
            row.state = "SENT" if result.order is not None else "REFUSED"

    # ----------------------------------------------------------------- context

    def _context(
        self,
        s: Session,
        ks: KillSwitch,
        snap: Snapshot,
        limits: RiskLimits | None,
        rules: PairRules,
        intent: Intent,
        positions: dict[str, Position],
        events: list[accounting.Realised],
        mode: str,
        has_position: bool | None = None,
    ) -> RiskContext:
        now = self._now()
        book = snap.books.get(intent.pair)
        ref = ZERO
        if book is not None:
            ref = book.bid_price if intent.side == "BUY" else book.ask_price
        elif intent.pair in snap.prices:
            ref = snap.prices[intent.pair]
        equity = snap.equity if snap.equity is not None else ZERO
        exposure = {
            p: pos.quantity * snap.prices.get(p, pos.avg_cost) for p, pos in positions.items()
        }
        last_order = s.scalar(
            select(func.max(OrderRow.submitted_at)).where(OrderRow.origin == "LIVE")
        )
        recent = (
            s.scalar(
                select(func.count())
                .select_from(OrderRow)
                .where(
                    OrderRow.origin == "LIVE", OrderRow.submitted_at >= now - timedelta(seconds=60)
                )
            )
            or 0
        )
        entry_clean, _ = self._recon_state(s)
        pos = positions.get(intent.pair)
        return RiskContext(
            now=now,
            trading_state=ks.state(),
            mode=mode,
            limits=limits,
            rules=rules,
            equity_idr=equity if snap.equity is not None else ZERO,
            reference_price=ref,
            market_data_age_s=(now - snap.at).total_seconds(),
            open_positions=len(positions),
            pair_exposure_idr=exposure.get(intent.pair, ZERO),
            total_exposure_idr=sum(exposure.values(), ZERO),
            daily_realised_loss_idr=accounting.daily_loss(events, now),
            drawdown_pct=accounting.drawdown_pct(s, equity),
            consecutive_losses=accounting.consecutive_losses(events),
            seconds_since_last_order=(
                None if last_order is None else (now - _aware(last_order)).total_seconds()
            ),
            orders_last_minute=recent,
            unknown_orders=self._unknown_count(s),
            reconciliation_clean=entry_clean,
            clock_ok=snap.clock_ok,
            permissions_ok=snap.permissions_ok,
            in_trading_window=self._in_window(limits, now),
            has_position=(pos is not None and pos.quantity >= intent.quantity)
            if has_position is None
            else has_position,
        )

    @staticmethod
    def _in_window(limits: RiskLimits | None, now: datetime) -> bool:
        window = None if limits is None else limits.trading_window
        if not window:
            return True
        try:
            a, b = window.split("-")
            start = datetime.strptime(a, "%H:%M").time()
            end = datetime.strptime(b, "%H:%M").time()
        except ValueError:
            return False  # an unreadable window is closed, not open
        local = (now + accounting.WIB).time()
        return start <= local <= end if start <= end else (local >= start or local <= end)

    # ------------------------------------------------------------------- paper

    def _refresh_all_candles(self, s: Session, report: CycleReport) -> None:
        """Keep stored candles current for every allowlisted pair, halted or not: the paper
        simulation and the strategies both read them, and neither may wait for a resume."""
        # At most CANDLE_REFRESH_PER_CYCLE pairs per cycle, oldest first, each when its candles
        # are older than the poll interval. With a few pairs this is the same sweep as before; with
        # ALL it spreads the requests over cycles instead of blocking one cycle on the throttle
        # (a cycle that overruns trips the watchdog).
        now = self._now()
        due = [
            p
            for p in self._active_pairs(s)
            if (at := self._candle_at.get(p)) is None
            or (now - at).total_seconds() >= self._candle_poll_s
        ]
        due.sort(key=lambda p: self._candle_at.get(p, datetime.min.replace(tzinfo=UTC)))
        for pair in due[:CANDLE_REFRESH_PER_CYCLE]:
            self._candle_at[pair] = now
            try:
                self._refresh_candles(s, pair)
            except ConnectorError as exc:
                report.errors.append(f"candles {pair}: {exc.error_class}")

    def _paper_step(self, s: Session, report: CycleReport) -> None:
        """Advance the simulated book over any candle that closed since the last cycle."""
        ps = get_paper_settings(s)
        if ps is None:
            return
        book = PaperBook(ps, self._tf)
        closes: dict[str, Decimal] = {}
        for pair in self._active_pairs(s):
            candles = self._load_candles(s, pair)
            if not candles:
                continue
            closes[pair] = candles[-1].close
            book.advance(s, pair, candles, self._rules.get(pair))
        if closes and self._due("paper_equity", 60):
            positions, events = accounting.replay_origin(s, "PAPER")
            accounting.record_paper_equity(
                s,
                accounting.paper_equity(ps.start_equity_idr, positions, events, closes),
                self._now(),
            )

    # ------------------------------------------------------------ housekeeping

    def _record_equity(self, s: Session, snap: Snapshot) -> None:
        if snap.equity is not None and self._due("equity", 60):
            accounting.record_equity(s, snap.equity, snap.at)

    def _housekeeping(self, s: Session, notifier: Notifier | None, ks: KillSwitch) -> None:
        ApprovalWorkflow(s, notifier, now=self._now).expire_due()
        if notifier:
            notifier.retry_pending()
        if self._client is not None and self._due("reconcile", self._reconcile_s):
            allow = get_allowlist(s)
            pairs = sorted(
                {
                    *self._active_pairs(s, allow),
                    *(p for (p,) in s.execute(select(OrderRow.pair).distinct())),
                }
            )
            # Reconcile only counts once the ledger is up to date, so a trade that settled
            # between two cycles is not reported as an unexplained difference.
            run = reconcile(s, self._client, pairs, now=self._now, killswitch=ks)
            if run.result != "clean" and notifier:
                notifier.emit(
                    "reconciliation_difference",
                    f"reconciliation {run.result}: {run.differences} differences",
                )
