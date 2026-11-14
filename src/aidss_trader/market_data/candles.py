"""Candle ingest: idempotent, closed candles only, bad data rejected not repaired.

The unfinished candle is never stored or used for a decision. That is also what
prevents look-ahead in a backtest (FR-T29): a decision at a candle's close sees
only candles that were already complete.

Boundary alignment (where a 4H or daily candle starts, in what time zone) is
unverified (OQ-4), so it is an opt-in check and the default records candles as
the exchange sent them without asserting where they should start.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss_trader.connector.types import Candle as ApiCandle
from aidss_trader.db.models import Candle

TIMEFRAME_SECONDS = {"4H": 4 * 3600, "1D": 24 * 3600}


@dataclass(slots=True)
class IngestResult:
    inserted: int = 0
    duplicates: int = 0
    unfinished: int = 0
    #: Same candle, different values. Recorded, never overwritten.
    conflicts: list[datetime] = field(default_factory=list)
    rejected: list[tuple[datetime, str]] = field(default_factory=list)


def _utc(value: datetime) -> datetime:
    # SQLite returns naive datetimes; PostgreSQL aware ones. Compare in UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def validate_candle(
    c: ApiCandle, timeframe: str | None = None, *, check_alignment: bool = False
) -> str | None:
    """Why a candle is structurally invalid, or None. Never repairs it."""
    values = (c.open, c.high, c.low, c.close)
    if any(v <= 0 for v in values):
        return "non-positive price"
    if c.volume < 0:
        return "negative volume"
    if c.high < c.low:
        return "high below low"
    if not (c.low <= c.open <= c.high and c.low <= c.close <= c.high):
        return "open or close outside the high-low range"
    if check_alignment and timeframe is not None:
        if int(_utc(c.open_time).timestamp()) % TIMEFRAME_SECONDS[timeframe] != 0:
            return "open time not aligned to the timeframe"
    return None


def is_finished(c: ApiCandle, timeframe: str, now: datetime) -> bool:
    return _utc(c.open_time) + timedelta(seconds=TIMEFRAME_SECONDS[timeframe]) <= _utc(now)


def _same(row: Candle, c: ApiCandle) -> bool:
    return (row.open, row.high, row.low, row.close, row.volume) == (
        c.open,
        c.high,
        c.low,
        c.close,
        c.volume,
    )


def ingest_candles(
    session: Session,
    pair: str,
    timeframe: str,
    candles: list[ApiCandle],
    *,
    now: datetime,
    check_alignment: bool = False,
) -> IngestResult:
    if timeframe not in TIMEFRAME_SECONDS:
        raise ValueError(f"timeframe must be one of {sorted(TIMEFRAME_SECONDS)}")
    result = IngestResult()
    existing = {
        _utc(row.open_time): row
        for row in session.scalars(
            select(Candle).where(Candle.pair == pair, Candle.timeframe == timeframe)
        )
    }
    seen: set[datetime] = set()
    for c in sorted(candles, key=lambda x: x.open_time):
        opened = _utc(c.open_time)
        if not is_finished(c, timeframe, now):
            result.unfinished += 1
            continue
        reason = validate_candle(c, timeframe, check_alignment=check_alignment)
        if reason is not None:
            result.rejected.append((opened, reason))
            continue
        row = existing.get(opened)
        if row is not None or opened in seen:
            if row is None or _same(row, c):
                result.duplicates += 1
            else:
                result.conflicts.append(opened)
            continue
        session.add(
            Candle(
                pair=pair,
                timeframe=timeframe,
                open_time=opened,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
                fetched_at=_utc(now),
            )
        )
        seen.add(opened)
        result.inserted += 1
    session.flush()
    return result


def find_gaps(session: Session, pair: str, timeframe: str) -> list[datetime]:
    """Open times missing between the first and last stored candle.

    A gap is not zero: it blocks decisions on the pair until backfilled.
    """
    step = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    times = sorted(
        _utc(t)
        for t in session.scalars(
            select(Candle.open_time).where(Candle.pair == pair, Candle.timeframe == timeframe)
        )
    )
    gaps: list[datetime] = []
    for prev, nxt in zip(times, times[1:], strict=False):
        cursor = prev + step
        while cursor < nxt:
            gaps.append(cursor)
            cursor += step
    return gaps
