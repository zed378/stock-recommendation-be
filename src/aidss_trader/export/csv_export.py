"""CSV export of the ledger and the audit log for a date range (FR-T35).

Row counts equal the table's for the range. The audit log is already redacted at
write time, and no export reads a credential. Each export is itself audited.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss_trader.audit import AuditLogger
from aidss_trader.db.models import AuditLog, LedgerEntry

LEDGER_COLUMNS = ("at", "origin", "entry_type", "asset", "amount", "reason")
AUDIT_COLUMNS = ("seq", "at", "actor", "action", "subject_type", "subject_id", "mode")


def _csv(columns: tuple[str, ...], rows: list[Any]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        # A cell starting with a formula character is neutralised so a spreadsheet
        # opening the file cannot execute it.
        writer.writerow([_cell(getattr(row, c)) for c in columns])
    return buf.getvalue()


def _cell(value: Any) -> str:
    text = (
        "" if value is None else (value.isoformat() if isinstance(value, datetime) else str(value))
    )
    return "'" + text if text[:1] in ("=", "+", "-", "@") and not _is_number(text) else text


def _is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def export_ledger(session: Session, start: datetime, end: datetime, actor: str) -> tuple[str, int]:
    rows = list(
        session.scalars(
            select(LedgerEntry)
            .where(LedgerEntry.at >= start, LedgerEntry.at < end)
            .order_by(LedgerEntry.at)
        )
    )
    AuditLogger(session).record(
        actor=actor,
        action="export.ledger",
        subject_type="export",
        after={"rows": len(rows), "start": start.isoformat(), "end": end.isoformat()},
    )
    session.commit()
    return _csv(LEDGER_COLUMNS, rows), len(rows)


def export_audit(session: Session, start: datetime, end: datetime, actor: str) -> tuple[str, int]:
    rows = list(
        session.scalars(
            select(AuditLog).where(AuditLog.at >= start, AuditLog.at < end).order_by(AuditLog.seq)
        )
    )
    AuditLogger(session).record(
        actor=actor,
        action="export.audit",
        subject_type="export",
        after={"rows": len(rows), "start": start.isoformat(), "end": end.isoformat()},
    )
    session.commit()
    return _csv(AUDIT_COLUMNS, rows), len(rows)
