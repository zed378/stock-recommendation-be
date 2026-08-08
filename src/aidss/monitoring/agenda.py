"""Dated issuer events, and the notice that one is coming.

The calendar answers a question the rest of the platform cannot: *is something
scheduled*. Every other surface here reads the past - prices that settled,
filings that were published, coverage that was written. A general meeting on
the 14th is the one kind of fact that is known in advance, and it is knowable
without predicting anything.

**The alert states the date and stops.** "TLKM reports in three days" is a
fact. Adding what that usually does to a price would be a forecast, and adding
what to do about it would be a trading signal - and an agenda entry is a
uniquely tempting place to put either, because a date feels like it implies an
action. It does not, and nothing in this module will say it does.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.db.models import (
    AgendaKind,
    AgendaSource,
    Alert,
    AlertKind,
    Asset,
    IssuerAgenda,
    Watchlist,
    WatchlistItem,
)

logger = logging.getLogger("aidss.monitoring")

#: How far ahead an event is worth mentioning. Seven days is a judgement, not a
#: published figure: long enough that a reader who only opens the platform
#: weekly still sees it once, short enough that the notice is about something
#: imminent rather than a standing reminder.
NOTICE_DAYS = 7

#: Kinds whose date is mechanical rather than informational - an ex-date moves
#: the quote by the dividend regardless of what anybody thinks. Given a longer
#: window because being surprised by one is a different kind of problem: the
#: price gap is arithmetic, and a reader who did not know is looking at a chart
#: that appears to have fallen for no reason.
MECHANICAL_KINDS = frozenset({AgendaKind.EX_DATE, AgendaKind.STOCK_SPLIT})
MECHANICAL_NOTICE_DAYS = 14


@dataclass(frozen=True, slots=True)
class AgendaEntry:
    """One event as a collector produces it, before it is stored."""

    ticker: str
    kind: AgendaKind
    scheduled_for: date
    title: str
    source: AgendaSource
    detail: str | None = None
    source_url: str | None = None


def notice_window(kind: AgendaKind) -> int:
    return MECHANICAL_NOTICE_DAYS if kind in MECHANICAL_KINDS else NOTICE_DAYS


def store_entries(session: Session, entries: list[AgendaEntry]) -> dict[str, int]:
    """Upsert on (ticker, kind, date). Re-importing a calendar corrects it.

    Corrections are the normal case rather than the exception: a meeting moves,
    a reporting date slips, and an import that inserted a second row would
    leave the calendar showing both with nothing to say which is current.
    """
    added = 0
    updated = 0
    for entry in entries:
        row = session.scalar(
            select(IssuerAgenda).where(
                IssuerAgenda.ticker == entry.ticker.upper(),
                IssuerAgenda.kind == entry.kind,
                IssuerAgenda.scheduled_for == entry.scheduled_for,
            )
        )
        if row is None:
            row = IssuerAgenda(
                ticker=entry.ticker.upper(),
                kind=entry.kind,
                scheduled_for=entry.scheduled_for,
            )
            session.add(row)
            added += 1
        else:
            updated += 1
        row.title = entry.title
        row.detail = entry.detail
        row.source = entry.source
        row.source_url = entry.source_url

    session.flush()
    return {"added": added, "updated": updated}


def upcoming(
    session: Session,
    *,
    tickers: list[str] | None = None,
    on_date: date | None = None,
    days: int = 30,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[IssuerAgenda], int]:
    """Events from today forward, nearest first."""
    from sqlalchemy import func

    today = on_date or datetime.now(UTC).date()
    stmt = select(IssuerAgenda).where(
        IssuerAgenda.scheduled_for >= today,
        IssuerAgenda.scheduled_for <= today + timedelta(days=days),
    )
    if tickers is not None:
        stmt = stmt.where(IssuerAgenda.ticker.in_([t.upper() for t in tickers] or [""]))

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        session.scalars(
            stmt.order_by(IssuerAgenda.scheduled_for, IssuerAgenda.ticker)
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return rows, total


def _watched(session: Session) -> dict[str, list[tuple[uuid.UUID, uuid.UUID]]]:
    """Ticker to the (user_id, asset_id) pairs following it."""
    rows = session.execute(
        select(Asset.ticker, Watchlist.user_id, Asset.id)
        .join(WatchlistItem, WatchlistItem.asset_id == Asset.id)
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .distinct()
    ).all()
    out: dict[str, list[tuple[uuid.UUID, uuid.UUID]]] = {}
    for ticker, user_id, asset_id in rows:
        out.setdefault(ticker, []).append((user_id, asset_id))
    return out


def raise_notices(session: Session, *, on_date: date | None = None) -> dict[str, Any]:
    """Raise one alert per watching user per upcoming event.

    Only for tickers somebody follows. The calendar itself covers the whole
    exchange and is browsable in full, but an unsolicited notice about a
    company nobody here has expressed interest in is not information, it is
    noise arriving on its own schedule.
    """
    today = on_date or datetime.now(UTC).date()
    watched = _watched(session)
    if not watched:
        return {"raised": 0, "considered": 0}

    horizon = today + timedelta(days=MECHANICAL_NOTICE_DAYS)
    events = session.scalars(
        select(IssuerAgenda).where(
            IssuerAgenda.scheduled_for >= today,
            IssuerAgenda.scheduled_for <= horizon,
            IssuerAgenda.ticker.in_(list(watched)),
        )
    ).all()

    raised = 0
    for event in events:
        days_away = (event.scheduled_for - today).days
        if days_away > notice_window(event.kind):
            continue

        for user_id, asset_id in watched.get(event.ticker, []):
            # Keyed on the event rather than the day, so one meeting produces
            # one notice instead of one per day for a week. The date is in the
            # key because a rescheduled event is a different fact and deserves
            # saying again. The user is in the key because `dedup_key` is
            # globally unique: a shared key would mean whoever is polled second
            # is never told at all.
            key = (
                f"agenda:{user_id}:{event.ticker}:{event.kind.value}"
                f":{event.scheduled_for.isoformat()}"
            )
            existing = session.scalar(select(Alert).where(Alert.dedup_key == key))
            if existing is not None:
                continue

            session.add(
                Alert(
                    user_id=user_id,
                    asset_id=asset_id,
                    kind=AlertKind.AGENDA_UPCOMING,
                    dedup_key=key,
                    # A sentence of fact. No implication, no suggested action -
                    # see the module docstring for why this one is tempting.
                    message=(
                        f"{event.ticker}: {event.title} is scheduled for "
                        f"{event.scheduled_for.isoformat()}"
                    ),
                    context={
                        "ticker": event.ticker,
                        "agenda_kind": event.kind.value,
                        "scheduled_for": event.scheduled_for.isoformat(),
                        "days_away": days_away,
                        "title": event.title,
                        "source": event.source.value,
                        "source_url": event.source_url,
                    },
                )
            )
            raised += 1

    session.flush()
    logger.info("agenda notices raised", extra={"raised": raised, "events": len(events)})
    return {"raised": raised, "considered": len(events)}
