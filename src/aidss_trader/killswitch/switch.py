"""Kill switch (ADR-036). Deliberately independent of everything that decides to trade.

It imports only the database models, the connector, and the order state machine:
not strategies, intents, the analysis platform, or the approval queue, so a bug
or outage in any of those cannot disable it (guarded by a test).

Tiers:

* HALT: stop opening anything. Existing orders and positions are left alone.
* CANCEL: HALT, then cancel every open order, confirmed against the exchange.
* FLATTEN: CANCEL, then MARKET-sell every held asset. **Owner-triggered only.**
  No automatic trigger can reach FLATTEN.

`activate` is idempotent: repeating it re-runs the steps without duplicating an
event's effect, and every step is recorded, including failures. Resuming needs a
note and is blocked by an UNKNOWN order or an unresolved reconciliation difference.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aidss_trader.connector.errors import ConnectorError
from aidss_trader.connector.port import ExchangeClient
from aidss_trader.db.models import (
    KillSwitchEvent,
    KillSwitchStep,
    OrderRow,
    ReconciliationDifference,
    TradingStateRow,
)
from aidss_trader.orders.state import TERMINAL, OrderState

TIERS = ("HALT", "CANCEL", "FLATTEN")
AUTOMATIC_TRIGGERS = frozenset({"breaker", "reconciler", "watchdog", "service"})
STATE_FOR = {"HALT": "HALTED", "CANCEL": "CANCELLING", "FLATTEN": "FLATTENING"}
QUOTE = "IDR"


class KillSwitchRefused(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class KillSwitch:
    def __init__(
        self, session: Session, client: ExchangeClient | None, *, now: Callable[[], datetime] = _now
    ) -> None:
        self._s, self._client, self._now = session, client, now

    # ----------------------------------------------------------------- state

    def state(self) -> str:
        row = self._s.get(TradingStateRow, "trader")
        return row.state if row else "RUNNING"

    def ensure_initialized(self) -> bool:
        """First start: begin HALTED, so nothing trades until the owner resumes with a note.

        Without this a database with no state row reads as RUNNING, and a fresh install would
        be one `PUT /limits` away from trading. Returns True if it had to create the row.
        """
        if self._s.get(TradingStateRow, "trader") is not None:
            return False
        self._set_state("HALTED", "initial state: awaiting the owner's resume", "system")
        self._s.commit()
        return True

    def _set_state(self, state: str, reason: str, by: str) -> None:
        row = self._s.get(TradingStateRow, "trader")
        if row is None:
            self._s.add(
                TradingStateRow(
                    name="trader", state=state, reason=reason, since=self._now(), changed_by=by
                )
            )
        else:
            row.state, row.reason, row.since, row.changed_by = state, reason, self._now(), by
        self._s.flush()

    def _step(
        self, event: KillSwitchEvent, kind: str, target: str, result: str, detail: str = ""
    ) -> None:
        self._s.add(
            KillSwitchStep(
                event_id=event.id,
                kind=kind,
                target=target,
                result=result,
                detail=detail[:200],
                at=self._now(),
            )
        )
        self._s.flush()

    # -------------------------------------------------------------- activate

    def activate(self, tier: str, trigger: str, requested_by: str) -> KillSwitchEvent:
        if tier not in TIERS:
            raise KillSwitchRefused(f"unknown tier {tier!r}")
        if tier == "FLATTEN" and trigger in AUTOMATIC_TRIGGERS:
            raise KillSwitchRefused(
                "FLATTEN is owner-triggered only; no automatic trigger may sell"
            )
        event = KillSwitchEvent(
            tier=tier, trigger=trigger, requested_by=requested_by, started_at=self._now()
        )
        self._s.add(event)
        self._s.flush()
        # Halting comes first and is committed before anything that can fail on the network.
        if self.state() == "RUNNING" or TIERS.index(tier) > TIERS.index(
            self._tier_of(self.state())
        ):
            self._set_state(STATE_FOR[tier], f"{tier} by {trigger}", requested_by)
        self._s.commit()
        if tier in {"CANCEL", "FLATTEN"}:
            self._cancel_all(event)
        if tier == "FLATTEN":
            self._flatten(event)
        event.finished_at = self._now()
        self._s.commit()
        return event

    @staticmethod
    def _tier_of(state: str) -> str:
        return {"HALTED": "HALT", "CANCELLING": "CANCEL", "FLATTENING": "FLATTEN"}.get(
            state, "HALT"
        )

    def _cancel_all(self, event: KillSwitchEvent) -> None:
        if self._client is None:
            # HALT never needs the exchange. The heavier tiers say plainly that they could not act.
            self._step(event, "list_open", "exchange", "failed", "no exchange client configured")
            return
        try:
            open_orders = self._client.get_open_orders()
        except ConnectorError as exc:
            self._step(event, "list_open", "exchange", "failed", str(exc))
            return
        for o in open_orders:
            ref = o.full_order_id or str(o.order_id)
            try:
                self._client.cancel_order(
                    o.symbol, order_id=o.order_id
                ) if o.order_id is not None else self._client.cancel_order(
                    o.symbol, client_order_id=str(o.client_order_id)
                )
                self._step(event, "cancel", ref, "ok")
            except ConnectorError as exc:
                self._step(event, "cancel", ref, "failed", f"{exc.error_class}")
            self._mark_cancelled(o.client_order_id)

    def _mark_cancelled(self, cid: str | None) -> None:
        row = (
            self._s.scalar(select(OrderRow).where(OrderRow.client_order_id == cid)) if cid else None
        )
        if row is not None and OrderState(row.state) not in TERMINAL:
            row.state, row.updated_at, row.cancel_reason = (
                OrderState.CANCEL_REQUESTED.value,
                self._now(),
                "killswitch",
            )

    def _flatten(self, event: KillSwitchEvent) -> None:
        if self._client is None:
            self._step(event, "account", "exchange", "failed", "no exchange client configured")
            return
        try:
            account = self._client.get_account()
        except ConnectorError as exc:
            self._step(event, "account", "exchange", "failed", str(exc))
            return
        for asset, (free, _locked) in sorted(account.balances.items()):
            if asset.upper() == QUOTE or free <= 0:
                continue
            pair = f"{asset.upper()}{QUOTE}"
            cid = "k" + hashlib.sha256(f"{event.id}|{pair}".encode()).hexdigest()[:34]
            try:
                self._client.create_order(
                    symbol=pair,
                    side="SELL",
                    order_type="MARKET",
                    client_order_id=cid,
                    quantity=Decimal(free),
                )
                self._step(event, "flatten", pair, "ok", f"qty {free}")
            except ConnectorError as exc:
                self._step(event, "flatten", pair, "failed", f"{exc.error_class}")

    # ---------------------------------------------------------------- resume

    def resume(self, note: str, requested_by: str) -> None:
        if not note or not note.strip():
            raise KillSwitchRefused("resuming needs a note")
        unknown = self._s.scalar(
            select(func.count())
            .select_from(OrderRow)
            .where(OrderRow.state == OrderState.UNKNOWN.value)
        )
        if unknown:
            raise KillSwitchRefused(f"{unknown} UNKNOWN order(s) must be resolved first")
        open_diffs = self._s.scalar(
            select(func.count())
            .select_from(ReconciliationDifference)
            .where(ReconciliationDifference.resolved_at.is_(None))
        )
        if open_diffs:
            raise KillSwitchRefused(f"{open_diffs} unresolved reconciliation difference(s)")
        self._set_state("RUNNING", note.strip()[:200], requested_by)
        self._s.commit()
