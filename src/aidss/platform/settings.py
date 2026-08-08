"""Operator choices stored in the database rather than the environment.

Each key has a default in code, so an empty table is a working system and a
fresh install needs no seeding.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.db.models import PlatformSetting

#: Whether anybody may create an account right now.
#:
#: Open by default, because a platform that refuses its first user is a
#: platform nobody can set up. The switch exists for afterwards: an invitation
#: link gets forwarded, a demo instance ends up indexed, and the operator needs
#: to close the door without redeploying.
REGISTRATION_OPEN = "registration_open"

#: Cron for the sweep that reads every configured news feed.
#:
#: Empty by default rather than a guessed schedule: reading somebody else's
#: feeds on a timer nobody asked for is a decision the operator makes.
NEWS_SWEEP_CRON = "news_sweep_cron"

#: Cron for importing the exchange session record and re-scanning the market.
#:
#: Unlike the news sweep this has a default, because the difference matters:
#: reading somebody else's feeds on a timer nobody asked for is a decision, but
#: this reads the exchange's own end-of-session publication about its own
#: market. A platform whose whole screener depends on that data should not sit
#: idle until an operator discovers a setting.
#:
#: 18:00 in exchange time, an hour after the close, on weekdays only. Late
#: enough that the session record is published and revised, early enough that a
#: failure still leaves the evening to notice it.
MARKET_SCAN_CRON = "market_scan_cron"

#: Seconds of random delay added to each firing.
#:
#: The endpoint publishes no rate limit, so the risk is not a documented quota
#: but looking like a bot: a request landing at 18:00:00.000 every weekday is a
#: schedule, and a schedule is what rate limiting is for. Spreading the actual
#: call across a window costs nothing - the data does not change in fifteen
#: minutes - and makes the traffic look like a person.
MARKET_SCAN_JITTER = "market_scan_jitter_seconds"

DEFAULTS: dict[str, Any] = {
    REGISTRATION_OPEN: True,
    NEWS_SWEEP_CRON: "",
    MARKET_SCAN_CRON: "0 18 * * 1-5",
    MARKET_SCAN_JITTER: 900,
}


def get_setting(session: Session, key: str) -> Any:
    """The stored value, or the default in code.

    Reads fall back rather than raise: a key added in a release that has not
    been written to yet is the normal case, not an error.
    """
    if key not in DEFAULTS:
        raise KeyError(f"unknown platform setting {key!r}; known: {sorted(DEFAULTS)}")
    row = session.get(PlatformSetting, key)
    if row is None or "value" not in (row.value or {}):
        return DEFAULTS[key]
    return row.value["value"]


def set_setting(session: Session, key: str, value: Any, *, by: uuid.UUID | None = None) -> Any:
    """Store a value, wrapped so scalars survive a JSON column.

    Wrapped in `{"value": ...}` rather than stored bare: a JSON column holding
    `false` and a JSON column holding SQL NULL are hard to tell apart through
    an ORM, and "registration is closed" must never be readable as "nobody has
    set this".
    """
    if key not in DEFAULTS:
        raise KeyError(f"unknown platform setting {key!r}; known: {sorted(DEFAULTS)}")
    row = session.get(PlatformSetting, key)
    if row is None:
        row = PlatformSetting(key=key)
        session.add(row)
    row.value = {"value": value}
    row.updated_by = by
    session.flush()
    return value


def all_settings(session: Session) -> dict[str, Any]:
    stored = {row.key: row.value.get("value") for row in session.scalars(select(PlatformSetting))}
    return {key: stored.get(key, default) for key, default in DEFAULTS.items()}
