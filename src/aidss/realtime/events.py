"""Server-pushed events, carried over PostgreSQL LISTEN/NOTIFY.

The work that matters here happens in the worker, and the browser is connected
to the API - two processes that share nothing but a database. So the event has
to cross a process boundary, and the question is what carries it.

PostgreSQL does, for the same reason the job queue and the leader lease do:
this platform already depends on it absolutely, and adding a broker would mean
a second system to run, monitor, and explain. `NOTIFY` is transactional - it
fires when the transaction commits and not before - which is exactly the
property needed. An event announcing an analysis that then rolled back would
send the interface to fetch something that does not exist.

**The payload is a pointer, not the data.** NOTIFY has an 8000-byte ceiling and
a full analysis is far past it, so an event says what changed and the client
fetches it through the ordinary authenticated endpoint. That also keeps
authorisation in one place: the socket never becomes a second way to read data
that the REST layer would have refused.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("aidss.realtime")

#: One channel for everything. Filtering happens on the subscriber side, where
#: the user identity already lives; a channel per user would mean issuing a
#: LISTEN per connection and re-issuing them all after a reconnect.
CHANNEL = "aidss_events"

#: PostgreSQL refuses a payload above 8000 bytes. Well under it by design -
#: these carry ids, not content - but a guard is cheaper than an exception
#: thrown from inside a commit.
MAX_PAYLOAD_BYTES = 7000


def publish(
    session: Session,
    *,
    user_id: uuid.UUID | None,
    event: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Announce that something changed. Never raises.

    Fires with the surrounding transaction, so a subscriber that reacts by
    fetching always finds the row the event is about. A failure to publish is
    logged and swallowed: the event is a convenience over polling, and losing
    one must not take down the work that produced it.
    """
    payload = json.dumps(
        {
            "event": event,
            "user_id": str(user_id) if user_id else None,
            "data": data or {},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        logger.warning("event payload too large to publish", extra={"event": event})
        return

    try:
        # Bound as a parameter rather than interpolated: `pg_notify` is the
        # function form of NOTIFY precisely so the payload does not have to be
        # escaped into a statement.
        session.execute(
            text("SELECT pg_notify(:channel, :payload)"),
            {"channel": CHANNEL, "payload": payload},
        )
    except Exception:  # noqa: BLE001 - publishing must not fail the caller
        logger.warning("event not published", extra={"event": event}, exc_info=True)
