"""Append-only, hash-chained audit log (docs/09-SECURITY-PRIVACY/04).

Each row stores the hash of its own content plus the previous row's hash, so
changing or removing an earlier row breaks every hash after it. That detects
tampering; it does not prevent a database owner from rewriting the whole chain,
which is why the head hash is meant to be recorded outside the database too
(a scheduled job, still to be built).

Two honest deviations from the design document, recorded rather than hidden:

* The timestamp comes from the Trader process, not the database. The hash needs
  the value before the row exists, and an UPDATE to add it later is exactly
  what the role's privileges forbid.
* Appends assume a single writer. That holds because only the lease holder
  trades (ADR-027); with two writers the chain could fork.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss_trader.audit.redact import redact
from aidss_trader.db.models import AuditLog

GENESIS = "0" * 64


class AuditChainBroken(RuntimeError):
    def __init__(self, seq: int, reason: str) -> None:
        super().__init__(f"audit chain broken at seq {seq}: {reason}")
        self.seq = seq


def _canonical(fields: dict[str, Any]) -> str:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)


def _hash(prev_hash: str, fields: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + _canonical(fields)).encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    # SQLite hands back naive datetimes. `astimezone` would read those as local
    # time and change the hash, so a naive value is taken as UTC (which is what
    # was stored). PostgreSQL returns aware values and is unaffected.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _fields(row: AuditLog) -> dict[str, Any]:
    return {
        "at": _utc(row.at).isoformat(),
        "actor": row.actor,
        "action": row.action,
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "before": row.before,
        "after": row.after,
        "mode": row.mode,
        "correlation_id": row.correlation_id,
    }


class AuditLogger:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        actor: str,
        action: str,
        subject_type: str | None = None,
        subject_id: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        mode: str | None = None,
        correlation_id: str | None = None,
        at: datetime | None = None,
    ) -> AuditLog:
        last = self._session.scalar(select(AuditLog).order_by(AuditLog.seq.desc()).limit(1))
        prev = last.hash if last is not None else GENESIS
        row = AuditLog(
            at=at or datetime.now(UTC),
            actor=actor,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            before=redact(before),
            after=redact(after),
            mode=mode,
            correlation_id=correlation_id,
            prev_hash=prev,
            hash="",
        )
        row.hash = _hash(prev, _fields(row))
        self._session.add(row)
        self._session.flush()
        return row


def verify_chain(session: Session) -> int:
    """Return the number of rows verified, or raise AuditChainBroken at the first bad one."""
    prev = GENESIS
    count = 0
    for row in session.scalars(select(AuditLog).order_by(AuditLog.seq)):
        if row.prev_hash != prev:
            raise AuditChainBroken(row.seq, "previous hash does not match (a row was removed?)")
        if row.hash != _hash(prev, _fields(row)):
            raise AuditChainBroken(row.seq, "content does not match its hash (row was altered?)")
        prev = row.hash
        count += 1
    return count
