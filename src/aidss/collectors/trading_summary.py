"""The exchange's own end-of-session record, stored per issuer per day.

Exists for one thing the price feeds do not carry: **foreign participation**.
IDX publishes foreign buy and foreign sell value per stock per session, which
is the only free, public basis for the "bandarmologi" question of whether
foreign money is accumulating or distributing a name.

What it is not: a broker summary. Which brokers did the buying, and whether the
top few dominated the session, is a different dataset that IDX does not publish
without a subscription. Nothing here should be read as answering that.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.db.models import DailyTradingSummary

logger = logging.getLogger("aidss.market")


@dataclass
class SummarySync:
    """What one day's import did."""

    session_date: date | None = None
    added: int = 0
    updated: int = 0
    skipped: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return {
            "session_date": self.session_date.isoformat() if self.session_date else None,
            "added": self.added,
            "updated": self.updated,
            "skipped": self.skipped[:20],
        }


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    # NaN and infinities survive Decimal() and poison every later comparison.
    return number if number.is_finite() else None


def _session_date(raw: Any) -> date | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def sync_summaries(session: Session, rows: list[dict[str, Any]]) -> SummarySync:
    """Upsert one session's rows.

    Idempotent on `(ticker, session_date)`, so re-running a day updates rather
    than duplicates - which matters because the exchange revises the same
    session's figures after the close.
    """
    report = SummarySync()
    if not rows:
        return report

    dates = {d for d in (_session_date(row.get("Date")) for row in rows) if d}
    report.session_date = max(dates) if dates else None

    tickers = [str(row.get("StockCode") or "").upper() for row in rows]
    existing = {
        (row.ticker, row.session_date): row
        for row in session.scalars(
            select(DailyTradingSummary).where(DailyTradingSummary.ticker.in_(tickers))
        ).all()
        if row.session_date in dates
    }

    for row in rows:
        ticker = str(row.get("StockCode") or "").strip().upper()
        on_date = _session_date(row.get("Date"))
        if not ticker or on_date is None:
            report.skipped.append(str(row.get("StockCode") or "?"))
            continue

        fields = {
            "close": _decimal(row.get("Close")),
            "previous_close": _decimal(row.get("Previous")),
            "volume": _decimal(row.get("Volume")),
            "value": _decimal(row.get("Value")),
            "frequency": int(row["Frequency"]) if _decimal(row.get("Frequency")) else None,
            "foreign_buy": _decimal(row.get("ForeignBuy")),
            "foreign_sell": _decimal(row.get("ForeignSell")),
        }

        current = existing.get((ticker, on_date))
        if current is None:
            session.add(DailyTradingSummary(ticker=ticker, session_date=on_date, **fields))
            report.added += 1
            continue

        if any(getattr(current, key) != value for key, value in fields.items()):
            for key, value in fields.items():
                setattr(current, key, value)
            current.fetched_at = datetime.now(datetime.now().astimezone().tzinfo)
            report.updated += 1

    session.flush()
    logger.info("trading summaries stored", extra=report.as_payload())
    return report


def foreign_flow_history(
    session: Session, ticker: str, *, limit: int = 20
) -> list[Decimal]:
    """Recent net foreign flow for one issuer, newest first.

    Sessions where the exchange published no foreign figures are dropped rather
    than counted as zero: absent and balanced are different, and averaging a
    missing day in as zero drags the baseline towards nothing.
    """
    rows = session.scalars(
        select(DailyTradingSummary)
        .where(DailyTradingSummary.ticker == ticker.upper())
        .order_by(DailyTradingSummary.session_date.desc())
        .limit(limit)
    ).all()
    return [row.net_foreign for row in rows if row.net_foreign is not None]
