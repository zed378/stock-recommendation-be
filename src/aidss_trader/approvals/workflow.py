"""Approval workflow (docs/05-MODULE-SPECIFICATIONS/07).

* An approval is bound to the intent's hash (pair, side, price, quantity, stop). A
  card showing an older price cannot approve a changed order.
* Expiry is real: an expired approval is never sent. One hour (ADR-042).
* One decision per intent: the unique intent identity plus a state check make a
  second decision return the first one's outcome, never a second order.
* The Risk Engine runs again at send time inside `OrderManager.submit`; if it now
  refuses, nothing is sent and the owner is told. There is no retry from one approval.
* Stops and kill-switch exits never come through here.
* The permission (`trade:approve`) is enforced by the API layer; this module also
  refuses an actor that is not a named human (no automated actor can approve).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss_trader.audit import AuditLogger
from aidss_trader.db.models import ApprovalRow
from aidss_trader.intents.builder import Intent
from aidss_trader.notify import Notifier

EXPIRY = timedelta(hours=1)  # ADR-042
AWAITING, APPROVED, DENIED, EXPIRED = "AWAITING", "APPROVED", "DENIED", "EXPIRED"
_AUTOMATED_PREFIXES = ("system", "strategy", "job", "service", "reconciler", "killswitch")


class ApprovalRefused(Exception):
    pass


def _plain(value: Decimal | None) -> str:
    # The database pads Decimals to the column scale (1236777000.000000000000000000),
    # so the same price must hash the same before and after a round trip.
    return "none" if value is None else format(value.normalize(), "f")


def intent_hash(intent: Intent) -> str:
    parts = [
        intent.pair,
        intent.side,
        _plain(intent.entry_price),
        _plain(intent.quantity),
        _plain(intent.stop_price),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Outcome:
    state: str
    sent: bool
    detail: str = ""
    already_decided: bool = False


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(v: datetime) -> datetime:
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v


class ApprovalWorkflow:
    def __init__(
        self,
        session: Session,
        notifier: Notifier | None = None,
        *,
        now: Callable[[], datetime] = _now,
    ) -> None:
        self._s, self._notifier, self._now = session, notifier, now
        self._audit = AuditLogger(session)

    def request(self, intent: Intent, context: dict[str, Any] | None = None) -> ApprovalRow:
        existing = self._s.scalar(
            select(ApprovalRow).where(ApprovalRow.intent_identity == intent.identity)
        )
        if existing is not None:
            return existing  # re-evaluating the same candle never creates a second card
        now = self._now()
        row = ApprovalRow(
            intent_identity=intent.identity,
            intent_hash=intent_hash(intent),
            state=AWAITING,
            created_at=now,
            expires_at=now + EXPIRY,
            context=context,
        )
        self._s.add(row)
        self._s.commit()
        if self._notifier:
            self._notifier.emit(
                "intent_awaiting_approval",
                f"{intent.pair} {intent.side} awaiting approval",
                {
                    "pair": intent.pair,
                    "side": intent.side,
                    "expires_at": row.expires_at.isoformat(),
                },
            )
        return row

    def _expire_if_due(self, row: ApprovalRow) -> None:
        if row.state == AWAITING and _aware(row.expires_at) <= self._now():
            row.state, row.decided_at, row.decided_by = EXPIRED, self._now(), "system"
            self._audit.record(
                actor="system",
                action="approval.expired",
                subject_type="intent",
                subject_id=row.intent_identity,
                after={"intent_hash": row.intent_hash},
            )
            self._s.commit()

    def expire_due(self) -> int:
        n = 0
        for row in self._s.scalars(select(ApprovalRow).where(ApprovalRow.state == AWAITING)):
            self._expire_if_due(row)
            n += row.state == EXPIRED
        return n

    def _guard(self, actor: str) -> None:
        if not actor or actor.lower().startswith(_AUTOMATED_PREFIXES):
            raise ApprovalRefused("only a named human may decide an approval")

    def deny(self, intent_identity: str, actor: str, reason: str | None = None) -> Outcome:
        self._guard(actor)
        row = self._get(intent_identity)
        self._expire_if_due(row)
        if row.state != AWAITING:
            return Outcome(row.state, False, "already decided", already_decided=True)
        row.state, row.decided_at, row.decided_by, row.reason = (
            DENIED,
            self._now(),
            actor,
            (reason or "")[:200] or None,
        )
        self._audit.record(
            actor=actor,
            action="approval.denied",
            subject_type="intent",
            subject_id=intent_identity,
            after={"intent_hash": row.intent_hash, "reason": row.reason},
        )
        self._s.commit()
        return Outcome(DENIED, False)

    def approve(
        self,
        intent: Intent,
        actor: str,
        presented_hash: str,
        send: Callable[[], Any],
        *,
        headroom: dict[str, Any] | None = None,
    ) -> Outcome:
        """`send` performs the risk re-check and order submission and returns a SubmitResult."""
        self._guard(actor)
        row = self._get(intent.identity)
        self._expire_if_due(row)
        if row.state != AWAITING:
            return Outcome(row.state, False, "already decided", already_decided=True)
        current = intent_hash(intent)
        if presented_hash != row.intent_hash or current != row.intent_hash:
            raise ApprovalRefused(
                "the intent changed since the card was shown; a new approval is needed"
            )
        row.state, row.decided_at, row.decided_by = APPROVED, self._now(), actor
        self._audit.record(
            actor=actor,
            action="approval.approved",
            subject_type="intent",
            subject_id=intent.identity,
            after={"intent_hash": current, "headroom": headroom},
        )
        self._s.commit()  # the decision is durable before anything is sent
        result = send()
        order = getattr(result, "order", None)
        if order is None:
            failed = [c.name for c in result.decision.failed]
            if self._notifier:
                self._notifier.emit(
                    "approval_not_sent",
                    f"{intent.pair} approved but not sent: risk re-check failed",
                    {"pair": intent.pair, "failed_checks": failed},
                )
            return Outcome(APPROVED, False, "risk re-check failed: " + ", ".join(failed))
        return Outcome(APPROVED, True, order.state)

    def _get(self, identity: str) -> ApprovalRow:
        row = self._s.scalar(select(ApprovalRow).where(ApprovalRow.intent_identity == identity))
        if row is None:
            raise ApprovalRefused("no such approval")
        return row
