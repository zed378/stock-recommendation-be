"""Order manager: the only code that creates or cancels orders on the exchange (ADR-009).

Rules enforced here:

* Risk first. `submit` evaluates the Risk Engine and refuses on any failed check;
  there is no argument that skips it.
* Write-ahead. The order row (`SUBMITTING`, with its `clientOrderId`) is committed
  before the request leaves, so a crash after sending still leaves a record to
  resolve.
* Never blind-retry (ADR-024). A timeout or 5xx on create leaves the order
  `UNKNOWN`; `resolve_unknown` queries by `clientOrderId` and never sends the
  create again. An order still not found after the configured queries stays
  `UNKNOWN`, which the caller treats as a HALT condition.
* `PAPER` intents never reach the exchange here: paper fills are produced by the
  paper executor and are labelled as such.
* `MARKET` is accepted only for emergency purposes (stop, flatten).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss_trader.connector.client import IndodaxClient
from aidss_trader.connector.errors import ConnectorError, ErrorClass
from aidss_trader.connector.types import OrderInfo, TradeFill
from aidss_trader.db.models import Fill, OrderEvent, OrderRow
from aidss_trader.intents.builder import Intent, client_order_id
from aidss_trader.orders.state import (
    TERMINAL,
    OrderState,
    from_exchange,
    require_transition,
)
from aidss_trader.risk.engine import Decision, Profile, RiskContext, evaluate, persist

EMERGENCY_PURPOSES = frozenset({"STOP", "FLATTEN"})
PURPOSES = frozenset({"ENTRY", "EXIT", "STOP", "FLATTEN", "REPRICE"})


class OrderRefused(RuntimeError):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("order refused: " + ", ".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True, slots=True)
class SubmitResult:
    order: OrderRow | None
    decision: Decision


def _now() -> datetime:
    return datetime.now(UTC)


class OrderManager:
    def __init__(
        self,
        session: Session,
        client: IndodaxClient,
        *,
        now: Callable[[], datetime] = _now,
        sleep: Callable[[float], None] = time.sleep,
        unknown_queries: int = 5,
        unknown_window_s: float = 30.0,
    ) -> None:
        self._s, self._client, self._now, self._sleep = session, client, now, sleep
        self._queries, self._window = unknown_queries, unknown_window_s

    # ---------------------------------------------------------------- create

    def submit(
        self,
        intent: Intent,
        ctx: RiskContext,
        *,
        purpose: str = "ENTRY",
        order_type: str = "LIMIT",
        attempt: int = 0,
    ) -> SubmitResult:
        if purpose not in PURPOSES:
            raise ValueError(f"unknown purpose {purpose!r}")
        if order_type not in {"LIMIT", "MARKET"}:
            raise ValueError("order_type must be LIMIT or MARKET")
        emergency = purpose in EMERGENCY_PURPOSES
        if order_type == "MARKET" and not emergency:
            raise OrderRefused(["MARKET is allowed only for a stop or a flatten"])
        if intent.mode == "PAPER":
            raise OrderRefused(["a PAPER intent never reaches the exchange"])

        profile: Profile = "EMERGENCY" if emergency else "ENTRY"
        decision = evaluate(intent, ctx, profile)
        persist(self._s, intent, decision, self._now())
        if not decision.approved:
            self._s.commit()  # keep the refusal explanation
            return SubmitResult(None, decision)

        order = self._write_ahead(intent, purpose, order_type, attempt)
        self._send(order, intent)
        return SubmitResult(order, decision)

    def _write_ahead(self, intent: Intent, purpose: str, order_type: str, attempt: int) -> OrderRow:
        now = self._now()
        cid = client_order_id(intent.identity, attempt)
        existing = self._s.scalar(select(OrderRow).where(OrderRow.client_order_id == cid))
        if existing is not None:
            raise OrderRefused(
                [f"an order with this clientOrderId already exists ({existing.state})"]
            )
        order = OrderRow(
            intent_identity=intent.identity,
            origin="LIVE",
            pair=intent.pair,
            side=intent.side,
            type=order_type,
            time_in_force="MOC" if order_type == "LIMIT" and purpose == "ENTRY" else None,
            price=intent.entry_price if order_type == "LIMIT" else None,
            quantity=intent.quantity,
            client_order_id=cid,
            executed_qty=Decimal(0),
            state=OrderState.SUBMITTING.value,
            purpose=purpose,
            reprices=attempt,
            submitted_at=now,
            updated_at=now,
        )
        self._s.add(order)
        self._s.flush()
        self._event(order, None, OrderState.SUBMITTING, "system", "write-ahead")
        self._s.commit()  # durable before the request is sent
        return order

    def _send(self, order: OrderRow, intent: Intent) -> None:
        try:
            info = self._client.create_order(
                symbol=order.pair,
                side=order.side,
                order_type=order.type,
                client_order_id=order.client_order_id,
                price=order.price if order.type == "LIMIT" else None,
                quantity=order.quantity
                if not (order.type == "MARKET" and order.side == "BUY")
                else None,
                quote_order_qty=(
                    order.quantity * intent.entry_price
                    if order.type == "MARKET" and order.side == "BUY"
                    else None
                ),
                time_in_force=order.time_in_force,
                stp_mode="EXPIRE_TAKER",
            )
        except ConnectorError as exc:
            if exc.outcome_unknown:
                self._move(
                    order, OrderState.UNKNOWN, "system", f"{exc.error_class}: outcome unknown"
                )
            elif exc.error_class in {
                ErrorClass.REJECTED,
                ErrorClass.VALIDATION,
                ErrorClass.MARKET_SUSPENDED,
                ErrorClass.PERMISSION,
            }:
                order.cancel_reason = str(exc.error_class)
                self._move(order, OrderState.REJECTED, "system", str(exc))
            else:
                # Not a known rejection and not known to be unsent: treat as unknown.
                self._move(order, OrderState.UNKNOWN, "system", f"{exc.error_class}: unclassified")
            self._s.commit()
            return
        self._apply(order, info, "system", "create accepted")
        self._s.commit()

    # ------------------------------------------------------- state and fills

    def _event(
        self, order: OrderRow, frm: OrderState | None, to: OrderState, actor: str, why: str
    ) -> None:
        self._s.add(
            OrderEvent(
                order_id=order.id,
                from_state=frm.value if frm else None,
                to_state=to.value,
                at=self._now(),
                actor=actor,
                reason=why,
            )
        )

    def _move(self, order: OrderRow, to: OrderState, actor: str, why: str) -> None:
        current = OrderState(order.state)
        if current is to:
            return
        require_transition(current, to)
        order.state, order.updated_at = to.value, self._now()
        self._event(order, current, to, actor, why)

    def _apply(self, order: OrderRow, info: OrderInfo, actor: str, why: str) -> None:
        if info.order_id is not None:
            order.exchange_order_id = info.order_id
        if info.full_order_id:
            order.full_order_id = info.full_order_id
        order.executed_qty = info.executed_qty
        order.exchange_status = info.status
        if info.cancel_reason:
            order.cancel_reason = info.cancel_reason
        # A create response carries no status: an accepted order is open until proven otherwise.
        target = from_exchange(info.status) if info.status else OrderState.OPEN
        self._move(order, target, actor, why)

    def sync(self, order: OrderRow, actor: str = "system") -> OrderRow:
        """Read the order from the exchange and bring the local row in line."""
        if OrderState(order.state) in TERMINAL:
            return order
        info = self._lookup(order)
        if info is not None:
            self._apply(order, info, actor, "poll")
            self._s.commit()
        return order

    def _lookup(self, order: OrderRow) -> OrderInfo | None:
        try:
            if order.exchange_order_id is not None:
                return self._client.get_order(order.pair, order_id=order.exchange_order_id)
            return self._client.get_order(order.pair, client_order_id=order.client_order_id)
        except ConnectorError as exc:
            if exc.error_class is ErrorClass.NOT_FOUND:
                return None
            raise

    def resolve_unknown(self, order: OrderRow) -> bool:
        """Learn the fate of an UNKNOWN order by querying, never re-sending. True if resolved."""
        if OrderState(order.state) is not OrderState.UNKNOWN:
            return True
        pause = self._window / max(self._queries - 1, 1)
        for attempt in range(self._queries):
            info = None
            try:
                info = self._client.get_order(order.pair, client_order_id=order.client_order_id)
            except ConnectorError as exc:
                if exc.error_class is not ErrorClass.NOT_FOUND:
                    pass  # an error is not an answer; ask again
            if info is not None:
                self._apply(order, info, "system", "resolved UNKNOWN by clientOrderId")
                self._s.commit()
                return True
            if attempt < self._queries - 1:
                self._sleep(pause)
        return False  # still unknown: the caller halts

    def ingest_fills(self, order: OrderRow, trades: list[TradeFill]) -> int:
        """Store exchange trades for this order, idempotent by trade id."""
        stored = 0
        for t in trades:
            if (
                t.client_order_id != order.client_order_id
                and t.full_order_id != order.full_order_id
            ):
                continue
            if (
                self._s.scalar(
                    select(Fill).where(Fill.exchange_trade_id == t.trade_id, Fill.origin == "LIVE")
                )
                is not None
            ):
                continue
            self._s.add(
                Fill(
                    order_id=order.id,
                    origin="LIVE",
                    exchange_trade_id=t.trade_id,
                    pair=order.pair,
                    side="BUY" if t.is_buyer else "SELL",
                    price=t.price,
                    quantity=t.qty,
                    quote_quantity=t.quote_qty,
                    is_maker=t.is_maker,
                    commission=t.commission,
                    executed_at=datetime.fromtimestamp(t.time_ms / 1000, UTC),
                )
            )
            stored += 1
        if stored:
            self._s.commit()
        return stored

    # ---------------------------------------------------------------- cancel

    def cancel(self, order: OrderRow, reason: str, actor: str = "system") -> OrderRow:
        state = OrderState(order.state)
        if state in TERMINAL or state is OrderState.SUBMITTING:
            return order
        if state is not OrderState.CANCEL_REQUESTED:
            self._move(order, OrderState.CANCEL_REQUESTED, actor, reason)
            self._s.commit()
        try:
            if order.exchange_order_id is not None:
                self._client.cancel_order(order.pair, order_id=order.exchange_order_id)
            else:
                self._client.cancel_order(order.pair, client_order_id=order.client_order_id)
        except ConnectorError as exc:
            if exc.error_class is not ErrorClass.NOT_FOUND and not exc.outcome_unknown:
                raise
        # The exchange is the source of truth: confirm by reading, never assume it worked.
        info = self._lookup(order)
        if info is not None:
            order.cancel_reason = reason
            self._apply(order, info, actor, reason)
        self._s.commit()
        return order
