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
import os
from datetime import UTC, datetime
from pathlib import Path
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


def chain_head(session: Session) -> tuple[int, str] | None:
    """(row count, head hash): the value to record somewhere the database owner cannot rewrite.

    A hash chain detects an altered or removed row, but whoever can rewrite the
    whole table can rewrite the chain. Recording the head outside the database
    (the scheduled job that does so is not built yet) closes that gap.
    """
    last = session.scalar(select(AuditLog).order_by(AuditLog.seq.desc()).limit(1))
    return None if last is None else (last.seq, last.hash)


def _read_anchors(anchor_path: Path) -> list[dict[str, Any]]:
    if not anchor_path.exists():
        return []
    anchors: list[dict[str, Any]] = []
    prev_seq = 0
    for lineno, raw in enumerate(anchor_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AuditChainBroken(
                prev_seq, f"malformed anchor line {lineno} in {anchor_path}"
            ) from exc
        if not isinstance(entry, dict) or "seq" not in entry or "head_hash" not in entry:
            raise AuditChainBroken(prev_seq, f"incomplete anchor line {lineno} in {anchor_path}")
        seq = entry["seq"]
        head_hash = entry["head_hash"]
        if not isinstance(seq, int) or isinstance(seq, bool) or seq <= prev_seq:
            raise AuditChainBroken(
                prev_seq, f"non-monotonic anchor seq at line {lineno} in {anchor_path}"
            )
        if not isinstance(head_hash, str) or len(head_hash) != 64:
            raise AuditChainBroken(seq, f"invalid anchor hash at line {lineno} in {anchor_path}")
        prev_seq = seq
        anchors.append(entry)
    return anchors


def _verify_latest_anchor(session: Session, anchors: list[dict[str, Any]]) -> tuple[int, str]:
    last = anchors[-1]
    anchored_seq = int(last["seq"])
    anchored_hash = str(last["head_hash"])
    row = session.scalar(select(AuditLog).where(AuditLog.seq == anchored_seq))
    if row is None:
        raise AuditChainBroken(
            anchored_seq, f"audit log truncated before anchored seq {anchored_seq}"
        )
    if row.hash != anchored_hash:
        raise AuditChainBroken(anchored_seq, f"audit log rewritten at anchored seq {anchored_seq}")
    return anchored_seq, anchored_hash


def verify_head_anchor(session: Session, anchor_path: Path) -> tuple[int, str] | None:
    """Verify the database audit chain against the latest external head-hash anchor."""
    verify_chain(session)
    head = chain_head(session)
    anchors = _read_anchors(anchor_path)
    if not anchors:
        if head is not None:
            raise AuditChainBroken(head[0], f"no external anchor recorded in {anchor_path}")
        return None
    if head is None:
        last_seq = int(anchors[-1]["seq"])
        raise AuditChainBroken(last_seq, "audit log is empty but external anchors exist")
    return _verify_latest_anchor(session, anchors)


def record_head_anchor(session: Session, anchor_path: Path) -> tuple[int, str] | None:
    """Verify the audit chain and append its head hash to an external JSONL anchor file.

    Idempotent when the chain head has not advanced since the last anchor.
    Raises AuditChainBroken if the database chain was truncated or rewritten
    relative to the previous external anchor.
    """
    verify_chain(session)
    head = chain_head(session)
    anchors = _read_anchors(anchor_path)
    if head is None:
        if anchors:
            last_seq = int(anchors[-1]["seq"])
            raise AuditChainBroken(last_seq, "audit log is empty but external anchors exist")
        return None
    seq, head_hash = head
    if anchors:
        anchored_seq, _ = _verify_latest_anchor(session, anchors)
        if seq < anchored_seq:
            raise AuditChainBroken(
                anchored_seq,
                f"audit log truncated: head seq {seq} < anchored seq {anchored_seq}",
            )
        if seq == anchored_seq:
            return seq, head_hash

    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "seq": seq,
        "head_hash": head_hash,
        "anchored_at": datetime.now(UTC).isoformat(),
    }
    with anchor_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(anchor_path, 0o600)
    except OSError:
        pass
    return seq, head_hash
