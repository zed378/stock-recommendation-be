"""One analysis pass over the whole exchange.

Alerts and the screener used to answer their own questions their own ways: the
monitoring poller evaluated conditions for whatever a user happened to watch,
and the stock-pick screener applied a separate list of rules to a separate set
of candidates. Two consequences, both bad. A criterion could mean one thing on
the monitoring screen and something subtly different on the picks screen. And a
screener that only ever sees what somebody already follows cannot surface
anything new - which is the one thing a screener is for.

This runs the same criteria over every issuer with enough history and stores
the result. Alerts read it for the tickers a user watches; the screener reads it
for the whole market. One pass, one vocabulary, two readers.

The bars come from the exchange's own session records rather than from
per-ticker price backfills: one request per session yields OHLCV for all 963
issuers, so a trading year of whole-market history costs a few hundred requests
instead of a few hundred thousand.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Text, cast, select
from sqlalchemy.dialects.postgresql import JSONB, array
from sqlalchemy.orm import Session

from aidss.collectors.trading_summary import (
    candles_from_summaries,
    foreign_flow_history,
    summaries_for,
    tickers_with_history,
)
from aidss.db.models import AlertKind, MarketScanResult
from aidss.domain.types import Candle
from aidss.indicators import core
from aidss.indicators.engine import candles_to_frame
from aidss.monitoring.alerts import (
    AlertCandidate,
    evaluate_foreign_flow,
    evaluate_geometry,
    evaluate_signals,
)
from aidss.monitoring.signals import TechnicalSignals, compute_signals

logger = logging.getLogger("aidss.monitoring")

#: Traded sessions an issuer needs before it is scanned at all. Below this the
#: longer averages do not exist, and a screener ranking a two-week listing
#: beside a five-year one is comparing two different measurements.
MINIMUM_SESSIONS = 60

#: Issuers per chunk when the scan is split across jobs. Sized so one chunk is
#: seconds of work rather than minutes: the point of chunking is that a failure
#: costs a chunk, and a chunk nobody can afford to lose is too big.
SCAN_CHUNK = 100


@dataclass
class ScanReport:
    """What one pass looked at."""

    session_date: date | None = None
    scanned: int = 0
    skipped: int = 0
    with_matches: int = 0
    matches_by_kind: dict[str, int] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "session_date": self.session_date.isoformat() if self.session_date else None,
            "scanned": self.scanned,
            "skipped": self.skipped,
            "with_matches": self.with_matches,
            "matches_by_kind": dict(
                sorted(self.matches_by_kind.items(), key=lambda item: -item[1])
            ),
        }


def scan_tickers(
    session: Session, tickers: list[str], *, on_date: date | None = None
) -> ScanReport:
    """Evaluate every criterion for each ticker and store the result.

    The asset id passed to the rules is a deterministic placeholder rather than
    a real one, because most issuers here have no `Asset` row - the whole point
    is scanning names nobody tracks yet. It only ever appears inside dedup keys,
    which the scan does not use; alerts re-key against the real asset when they
    read this.
    """
    # One date for the whole run, rather than each ticker's own last traded
    # session. Keyed per ticker, the screener could only ever return names that
    # traded on the single most recent date - which silently drops every
    # illiquid issuer, the part of the market a screener is most useful for.
    # How fresh each row's bars are is kept in `signals.as_of`.
    run_date = on_date or datetime.now(UTC).date()
    report = ScanReport(session_date=run_date)

    for ticker in tickers:
        summaries = summaries_for(session, ticker)
        bars = candles_from_summaries(summaries)
        if len(bars) < MINIMUM_SESSIONS:
            report.skipped += 1
            continue

        signals = compute_signals(bars)
        price = bars[-1].close
        levels = _levels(bars)
        placeholder = uuid.uuid5(uuid.NAMESPACE_OID, ticker)

        candidates: list[AlertCandidate] = [
            *evaluate_signals(
                asset_id=placeholder,
                ticker=ticker,
                price=price,
                signals=signals,
                support_levels=levels["support"],
            ),
            *evaluate_geometry(
                asset_id=placeholder,
                ticker=ticker,
                price=price,
                support_levels=levels["support"],
                resistance_levels=levels["resistance"],
            ),
            *evaluate_foreign_flow(
                asset_id=placeholder,
                ticker=ticker,
                price=price,
                history=foreign_flow_history(session, ticker),
            ),
        ]

        matched = sorted({candidate.kind.value for candidate in candidates})
        for value in matched:
            report.matches_by_kind[value] = report.matches_by_kind.get(value, 0) + 1

        _store(session, ticker, run_date, price, matched, signals)
        report.scanned += 1
        if matched:
            report.with_matches += 1

    session.flush()
    logger.info("market scan chunk finished", extra=report.as_payload())
    return report


def _levels(bars: list[Candle]) -> dict[str, list[Decimal]]:
    """The nearest confirmed swing levels on either side.

    From the same pivot detector the per-asset analysis uses, which is the
    point: a "support level" has to mean one thing across the product.

    The first version of this used the 52-week low and the 200-day average as
    stand-ins, on the theory that running a pivot scan for a thousand issuers
    was too expensive. It was cheap - the whole scan is seconds - and it was
    wrong in a way the cost argument hid: the yearly extremes are the *furthest*
    levels, not the nearest, so every stock trading in the middle of its range
    showed a reward-to-risk above two. Forty-four percent of the market matched,
    which is not a filter.
    """
    frame = candles_to_frame(bars)
    found = core.support_resistance(frame["high"], frame["low"], frame["close"])
    return {
        "support": [Decimal(str(value)) for value in found.get("support", [])],
        "resistance": [Decimal(str(value)) for value in found.get("resistance", [])],
    }


def _store(
    session: Session,
    ticker: str,
    on_date: date,
    price: Decimal,
    matched: list[str],
    signals: TechnicalSignals,
) -> None:
    """Upsert one result. Re-scanning a session replaces rather than duplicates."""
    row = session.scalar(
        select(MarketScanResult).where(
            MarketScanResult.ticker == ticker, MarketScanResult.session_date == on_date
        )
    )
    if row is None:
        row = MarketScanResult(ticker=ticker, session_date=on_date)
        session.add(row)

    row.close = price
    row.matched = matched
    row.matched_count = len(matched)
    row.signals = _serialisable(signals)
    row.scanned_at = datetime.now(UTC)


def _serialisable(signals: TechnicalSignals) -> dict[str, Any]:
    """The computed values, as JSON.

    Stored so a result can be explained without recomputing it - a reader
    seeing a ticker on the list should be able to find out *why* rather than
    only that it is there.
    """
    out: dict[str, Any] = {}
    for field_name in signals.__slots__:
        value = getattr(signals, field_name)
        if value is None or isinstance(value, bool):
            out[field_name] = value
        elif isinstance(value, Decimal):
            out[field_name] = str(value.quantize(Decimal("0.0001")))
        elif isinstance(value, date):
            out[field_name] = value.isoformat()
        else:
            out[field_name] = str(value)
    return out


def scannable_tickers(session: Session) -> list[str]:
    return tickers_with_history(session, minimum=MINIMUM_SESSIONS)


def latest_scan_date(session: Session) -> date | None:
    return session.scalar(select(MarketScanResult.session_date).order_by(
        MarketScanResult.session_date.desc()
    ))


def results_for(
    session: Session,
    *,
    on_date: date | None = None,
    tickers: list[str] | None = None,
    matched_any: list[AlertKind] | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MarketScanResult], int]:
    """Scan results, filtered the way both readers need.

    `tickers` is what the monitoring screen passes to narrow to a watchlist;
    omitting it is what the screener passes to see the whole market. Same
    query, same data, one filter apart - which is the point of the rewrite.
    """
    from sqlalchemy import func

    on_date = on_date or latest_scan_date(session)
    if on_date is None:
        return [], 0

    stmt = select(MarketScanResult).where(MarketScanResult.session_date == on_date)
    if tickers is not None:
        # An explicit empty list means "nothing is watched", which is a real
        # answer and not the same as "no filter".
        stmt = stmt.where(MarketScanResult.ticker.in_([t.upper() for t in tickers] or [""]))
    if search and search.strip():
        # The code, not the signals. Nine hundred rows is too many to scroll,
        # and the ticker is the thing a reader arrives already knowing.
        stmt = stmt.where(MarketScanResult.ticker.like(f"%{search.strip().upper()}%"))
    wanted = [kind.value for kind in matched_any or []]
    postgres = bool(session.bind) and session.bind.dialect.name == "postgresql"
    if wanted and postgres:
        # Any overlap, not all: a reader ticking three criteria is asking for
        # anything that shows one of them, not for the rare name showing all.
        #
        # `?|` wants a text[] on its right-hand side. Passing the list plainly
        # makes SQLAlchemy bind it as JSONB, and PostgreSQL then reports that
        # no operator matches jsonb ?| jsonb - which reads like the column is
        # wrong rather than the parameter.
        stmt = stmt.where(
            cast(MarketScanResult.matched, JSONB).has_any(array(wanted, type_=Text))
        )

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        session.scalars(
            stmt.order_by(
                MarketScanResult.matched_count.desc(), MarketScanResult.ticker
            )
            .limit(limit)
            .offset(offset)
        ).all()
    )

    # SQLite has no JSON containment operator, so the same filter runs in
    # Python there. Correct on both; the production path stays in the database.
    if wanted and not postgres:
        wanted_set = set(wanted)
        rows = [row for row in rows if wanted_set & set(row.matched or [])]
        total = len(rows)

    return rows, total
