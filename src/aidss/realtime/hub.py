"""One LISTEN connection per API process, fanned out to its own sockets.

A connection per browser would mean a PostgreSQL backend per open tab, and
those are a fixed and small resource. One dedicated connection listens; the hub
routes what arrives to whichever sockets belong to that user.

The listener is deliberately separate from the request-scoped sessions. LISTEN
occupies its connection for as long as it is listening, so borrowing one from
the pool would remove it from the pool for the lifetime of the process.

**A dropped listener must not silently stop the feature.** The loop reconnects
with backoff and says so; the interface keeps a slow poll underneath precisely
because a socket that quietly stops delivering looks exactly like a system with
nothing to report.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections import defaultdict
from typing import Any

import psycopg

from aidss.realtime.events import CHANNEL

logger = logging.getLogger("aidss.realtime")

#: How long to wait before reconnecting a dropped listener, and the ceiling it
#: backs off to. A tight retry against a database that is down is a second
#: outage on top of the first.
RECONNECT_DELAY_SECONDS = 1.0
MAX_RECONNECT_DELAY_SECONDS = 30.0

#: Per-socket queue depth. A client that stops reading - a suspended laptop,
#: a wedged tab - must not grow a queue without limit. Past this its oldest
#: events are dropped: these are hints to refetch, so the newest one is the
#: only one that matters.
QUEUE_SIZE = 32


class EventHub:
    """Subscriptions by user, and the listener that feeds them."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue[dict[str, Any]]]] = (
            defaultdict(set)
        )
        self._task: asyncio.Task[None] | None = None

    # --- subscription -----------------------------------------------------

    def subscribe(self, user_id: uuid.UUID) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subscribers[user_id].add(queue)
        return queue

    def unsubscribe(self, user_id: uuid.UUID, queue: asyncio.Queue[dict[str, Any]]) -> None:
        subscribers = self._subscribers.get(user_id)
        if not subscribers:
            return
        subscribers.discard(queue)
        # The empty set is removed rather than left behind: a long-lived process
        # would otherwise accumulate one key per user who ever connected.
        if not subscribers:
            self._subscribers.pop(user_id, None)

    def _deliver(self, message: dict[str, Any]) -> None:
        raw_user = message.get("user_id")
        if not raw_user:
            return
        try:
            user_id = uuid.UUID(raw_user)
        except ValueError:
            logger.warning("event carried an unusable user_id")
            return

        for queue in tuple(self._subscribers.get(user_id, ())):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # Drop the oldest and keep the newest: every event here is a
                # hint to refetch, and the latest hint supersedes the ones
                # behind it.
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(message)

    # --- the listener -----------------------------------------------------

    async def _listen_once(self) -> None:
        async with await psycopg.AsyncConnection.connect(
            self._dsn, autocommit=True
        ) as connection:
            await connection.execute(f"LISTEN {CHANNEL}")
            logger.info("listening for events", extra={"channel": CHANNEL})
            async for notify in connection.notifies():
                try:
                    self._deliver(json.loads(notify.payload))
                except json.JSONDecodeError:
                    logger.warning("event payload was not JSON")

    async def _run(self) -> None:
        delay = RECONNECT_DELAY_SECONDS
        while True:
            try:
                await self._listen_once()
                # A clean return means the connection closed without error.
                # Still a disconnection, so it backs off like any other.
                logger.warning("event listener closed; reconnecting")
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a listener must outlive its faults
                logger.warning("event listener failed; reconnecting", exc_info=True)

            await asyncio.sleep(delay)
            delay = min(delay * 2, MAX_RECONNECT_DELAY_SECONDS)

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None


def dsn_from_sqlalchemy_url(url: str) -> str:
    """`postgresql+psycopg://...` is SQLAlchemy's spelling; psycopg wants plain.

    Converted here rather than adding a second setting, so there is one place
    the database address is configured and no way for the two to disagree.
    """
    return url.replace("postgresql+psycopg://", "postgresql://", 1)
