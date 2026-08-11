"""Running a reader's own screens on their own schedule.

A screen that has to be opened to be useful only tells you what you already
went looking for. On a schedule it can tell you something you were not looking
at - which is the whole reason a screener exists, applied to a filter the
reader wrote rather than to one the platform chose.

Three decisions worth stating.

**A run that matches nothing is recorded, not announced.** The row keeps
`last_run_at` and `last_match_count` either way, so the screen can say "ran an
hour ago, nothing met it" on its own line. A notification saying nothing
happened is how a feature gets muted, and once muted it stops delivering the
one that matters.

**A screen that can no longer run says why, on its own row.** The vocabulary
can change under a saved screen. Left silent, a screen naming a signal that
went away looks exactly like a screen that matches nothing - the same failure
the news sources chapter is built around.

**The notification carries facts, not prose.** Which screen, how many matched,
out of how many, and the first few tickers. The sentence is composed by the
client in whichever language is selected, the same rule every other event on
this platform follows.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from aidss.db.models import SavedScreen
from aidss.news.schedules import next_run_at
from aidss.reporting.notifications import NotificationEvent, NotificationService
from aidss.screener.custom import InvalidRule, parse, run

logger = logging.getLogger("aidss.screener")

#: Tickers carried in the notification context. Enough to recognise what the
#: screen caught without the payload becoming the results screen - the reader
#: opens the screen for the rest.
PREVIEW_TICKERS = 5


def due_screens(session: Session, *, now: datetime) -> list[SavedScreen]:
    """Scheduled screens whose time has come.

    A screen with a cron but no `next_run_at` is included: that is a schedule
    somebody just set, and making them wait a full cycle to see whether it
    works is how a feature feels broken on the day it is turned on.
    """
    return list(
        session.scalars(
            select(SavedScreen).where(
                SavedScreen.cron_expr != "",
                or_(SavedScreen.next_run_at.is_(None), SavedScreen.next_run_at <= now),
            )
        ).all()
    )


def _advance(screen: SavedScreen, now: datetime) -> None:
    try:
        screen.next_run_at = next_run_at(screen.cron_expr, after=now)
    except Exception as exc:  # noqa: BLE001 - the parser raises its own types
        # An expression that stops parsing disables the schedule rather than
        # raising every minute for the rest of the deployment's life.
        screen.cron_expr = ""
        screen.next_run_at = None
        screen.last_error = f"schedule disabled, cron is not usable: {exc}"


def run_due(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """Run every due screen, notify on matches, and advance each schedule.

    One screen failing does not stop the rest. A saved screen is one person's
    filter, and letting a broken one silence everybody else's is the same
    mistake as a single dead feed emptying the whole news sweep.
    """
    now = now or datetime.now(UTC)
    service = NotificationService(session)

    ran = 0
    notified = 0
    failed = 0

    for screen in due_screens(session, now=now):
        try:
            rules = parse(list(screen.rules or []))
        except InvalidRule as exc:
            screen.last_error = f"{exc}"
            screen.last_run_at = now
            _advance(screen, now)
            failed += 1
            continue

        try:
            result = run(session, rules, limit=PREVIEW_TICKERS)
        except Exception as exc:  # noqa: BLE001 - one screen must not stop the rest
            logger.warning(
                "scheduled screen failed",
                extra={"screen": screen.name, "error": f"{type(exc).__name__}: {exc}"},
            )
            screen.last_error = f"{type(exc).__name__}: {exc}"
            screen.last_run_at = now
            _advance(screen, now)
            failed += 1
            continue

        screen.last_error = None
        screen.last_run_at = now
        screen.last_match_count = result.matched
        _advance(screen, now)
        ran += 1

        if result.matched == 0:
            # Recorded above, deliberately not announced. See the module
            # docstring: a notification that nothing happened is how the ones
            # that matter get muted.
            continue

        tickers = [row.ticker for row in result.rows][:PREVIEW_TICKERS]
        service.notify(
            screen.user_id,
            NotificationEvent.SCREEN_MATCHED,
            # Stored as a record and as the fallback for a client that does not
            # know this event yet. The rendered sentence comes from `context`.
            f"{screen.name}: {result.matched} of {result.considered} issuers matched",
            context={
                "screen_id": str(screen.id),
                "screen_name": screen.name,
                "matched": result.matched,
                "considered": result.considered,
                "tickers": tickers,
                "session_date": result.on_date.isoformat() if result.on_date else None,
            },
        )
        notified += 1

    session.flush()
    logger.info(
        "scheduled screens finished",
        extra={"ran": ran, "notified": notified, "failed": failed},
    )
    return {"ran": ran, "notified": notified, "failed": failed}
