"""Pull dated corporate events out of coverage the platform already stored.

The exchange does publish a calendar, but not on an endpoint that can be relied
on: probing its primary API returned JSON on one request and a Cloudflare
challenge page on the next, which is the same moving-target behaviour Section 9 records
elsewhere. A collector built on it would work in development and go quiet in
production without failing, which is the specific failure this codebase has
already paid for once in the news pipeline.

So the calendar is filled from what is already here. Every issuer-tagged
headline is scanned for a corporate-action word next to a date. That is a
weaker source than an exchange feed and it is treated as one: entries carry
`source=news` and a link back, and the reader sees where the date came from.

**Recall is deliberately sacrificed for precision.** A missing calendar entry
is a reader who checks elsewhere. A wrong one is a reader who plans around a
meeting that is not happening. Every rule below prefers the first.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.db.models import AgendaKind, AgendaSource, NewsItem, NewsItemIssuer
from aidss.monitoring.agenda import AgendaEntry, store_entries

_MONTHS = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11,
    "desember": 12,
    "january": 1, "february": 2, "march": 3, "may": 5, "june": 6, "july": 7,
    "august": 8, "october": 10, "december": 12,
}

#: Words that name a scheduled corporate event, mapped to what it is. Longest
#: phrases first so "rups luar biasa" is not read as a bare "rups".
_KEYWORDS: tuple[tuple[str, AgendaKind], ...] = (
    ("rups luar biasa", AgendaKind.RUPS),
    ("rupslb", AgendaKind.RUPS),
    ("rupst", AgendaKind.RUPS),
    ("rups", AgendaKind.RUPS),
    ("cum dividen", AgendaKind.EX_DATE),
    ("cum date", AgendaKind.EX_DATE),
    ("ex dividen", AgendaKind.EX_DATE),
    ("ex-dividen", AgendaKind.EX_DATE),
    ("ex date", AgendaKind.EX_DATE),
    ("stock split", AgendaKind.STOCK_SPLIT),
    ("pemecahan saham", AgendaKind.STOCK_SPLIT),
    ("rights issue", AgendaKind.RIGHTS_ISSUE),
    ("right issue", AgendaKind.RIGHTS_ISSUE),
    ("hmetd", AgendaKind.RIGHTS_ISSUE),
    ("dividen", AgendaKind.DIVIDEND),
    ("laporan keuangan", AgendaKind.EARNINGS),
    ("public expose", AgendaKind.OTHER),
    ("paparan publik", AgendaKind.OTHER),
)

#: "14 Agustus 2026" and "14 Agustus". The year is optional because coverage
#: routinely omits it for a date inside the current year.
_DATE_WORDS = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(_MONTHS) + r")(?:\s+(\d{4}))?\b",
    re.IGNORECASE,
)

#: How far ahead of the article a date may sit and still be read as the same
#: event. A headline in August naming "12 Januari" is next January; one naming
#: a date eighteen months out is almost always a different kind of statement.
MAX_MONTHS_AHEAD = 14

#: How far *behind* publication a date may sit. Coverage reports events that
#: already happened at least as often as it announces future ones, and a past
#: date on a calendar of upcoming events is simply wrong.
MAX_DAYS_BEHIND = 2

#: How far ahead a date may land *after being rolled into the next year*, when
#: the article omitted the year.
#:
#: Load-bearing, and the reason is a case that looks identical to the good one.
#: A December article naming "20 Januari" means next January - fifty-one days
#: out, and rolling is right. An August article naming "20 Juli" means the July
#: that just passed; rolling it produces a date eleven months out, which is
#: inside the ordinary look-ahead window and would be published as a scheduled
#: event nobody scheduled. A rolled date is only believable when it is near.
MAX_ROLLOVER_DAYS = 120


def _resolve(day: int, month: int, year: int | None, published: date) -> date | None:
    """Turn a matched date into a real one, or reject it.

    The year is the interesting case. Absent, it has to be inferred, and the
    inference is anchored on the article's publication date rather than on
    today: re-running the extractor months later must not silently move every
    date it already found.
    """
    if year is not None:
        try:
            return date(year, month, day)
        except ValueError:
            return None

    try:
        same_year = date(published.year, month, day)
    except ValueError:
        return None
    if (same_year - published).days >= -MAX_DAYS_BEHIND:
        return same_year

    # The month-day is behind publication, so the article either means next
    # year or means the one that just went past. Only the near case is
    # believable - see MAX_ROLLOVER_DAYS.
    try:
        next_year = date(published.year + 1, month, day)
    except ValueError:
        return None
    return next_year if (next_year - published).days <= MAX_ROLLOVER_DAYS else None


def _kind(text: str) -> tuple[AgendaKind, str] | None:
    lowered = text.lower()
    for phrase, kind in _KEYWORDS:
        if phrase in lowered:
            return kind, phrase
    return None


def entries_from(item: NewsItem, tickers: list[str]) -> list[AgendaEntry]:
    """Every event this one article states, for each issuer it is tagged to."""
    text = " ".join(filter(None, [item.headline, item.body_summary]))
    found = _kind(text)
    if found is None:
        return []
    kind, phrase = found

    published = (item.published_at or item.created_at or datetime.now()).date()
    dates: list[date] = []
    for day, month_name, year in _DATE_WORDS.findall(text):
        month = _MONTHS[month_name.lower()]
        resolved = _resolve(int(day), month, int(year) if year else None, published)
        if resolved is None:
            continue
        ahead = (resolved.year - published.year) * 12 + resolved.month - published.month
        if ahead > MAX_MONTHS_AHEAD or (resolved - published).days < -MAX_DAYS_BEHIND:
            continue
        dates.append(resolved)

    if len(dates) != 1:
        # Zero means the article named an event without a date. More than one
        # means it named several - a dividend timetable lists cum, ex, record
        # and payment - and picking one of four would be a coin flip printed as
        # a calendar entry. Both cases are left to a human.
        return []

    return [
        AgendaEntry(
            ticker=ticker,
            kind=kind,
            scheduled_for=dates[0],
            title=(item.headline or phrase)[:400],
            source=AgendaSource.NEWS,
            detail=f"Extracted from coverage matching {phrase!r}.",
            source_url=item.source_url,
        )
        for ticker in tickers
    ]


def extract(session: Session, *, limit: int = 500) -> dict[str, Any]:
    """Scan recently tagged coverage and store what it found.

    Only tagged items. An article nobody could attribute to an issuer cannot
    produce a calendar entry for one, and guessing here would put a date on the
    wrong company - the same failure mode the tagging rules in Section 12 are built to
    avoid, arriving through a different door.
    """
    rows = session.execute(
        select(NewsItem, NewsItemIssuer.ticker)
        .join(NewsItemIssuer, NewsItemIssuer.news_item_id == NewsItem.id)
        .order_by(NewsItem.published_at.desc())
        .limit(limit)
    ).all()

    by_item: dict[Any, tuple[NewsItem, list[str]]] = {}
    for item, ticker in rows:
        by_item.setdefault(item.id, (item, []))[1].append(ticker)

    entries: list[AgendaEntry] = []
    for item, tickers in by_item.values():
        entries.extend(entries_from(item, tickers))

    if not entries:
        return {"scanned": len(by_item), "added": 0, "updated": 0}

    stored = store_entries(session, entries)
    return {"scanned": len(by_item), **stored}
