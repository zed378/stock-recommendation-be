"""The event socket.

Replaces polling for the things that finish on their own schedule: a queued
analysis, a monitoring pass, anything that produces a notification. The browser
holds one socket and is told; it no longer asks every few seconds whether
anything happened, and it no longer holds a request open for minutes waiting
for work that a proxy will cut off at a hundred seconds.

**Authentication is the first message, not the URL.** A browser cannot set
headers on a WebSocket handshake, so the usual alternative is a token in the
query string - where it lands in every access log, proxy log, and referrer
along the path. The socket is accepted, the first frame must be the token, and
anything else closes it.

**The socket grants no new access.** Every event is a pointer: an id and a
kind. The client fetches through the same authenticated endpoints it always
used, so nothing here becomes a second door into data the REST layer would have
refused.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from aidss.db.base import get_sessionmaker
from aidss.db.models import User
from aidss.security.tokens import TokenError, decode_access_token

logger = logging.getLogger("aidss.realtime")

router = APIRouter(tags=["realtime"])

#: How long the socket waits for its first frame. A connection that opens and
#: never authenticates is either broken or probing; either way it should not
#: occupy a slot indefinitely.
AUTH_TIMEOUT_SECONDS = 10.0

#: Sent when nothing has happened for this long. Idle WebSockets are closed by
#: proxies - Cloudflare gives them about a hundred seconds - and a heartbeat is
#: what keeps a quiet connection from being mistaken for a dead one.
HEARTBEAT_SECONDS = 25.0

#: Close codes. 1008 is "policy violation", which is what an unauthenticated or
#: unusable connection is.
CLOSE_UNAUTHENTICATED = 1008


def _resolve_user(token: str) -> User | None:
    """The account behind a token, or None if it cannot be used.

    Re-checks the account's status rather than trusting the token alone: a
    token stays cryptographically valid for its whole hour, and a socket opened
    with one issued before a ban would otherwise keep receiving events.
    """
    try:
        payload = decode_access_token(token)
    except TokenError:
        return None

    session: Session = get_sessionmaker()()
    try:
        user = session.get(User, payload.user_id)
        if user is None or user.sign_in_block() is not None:
            return None
        # Detached deliberately: the session closes here and the caller only
        # needs the identity, not a live row it might lazily load from a
        # connection that has gone.
        session.expunge(user)
        return user
    finally:
        session.close()


@router.websocket("/ws/events")
async def events_socket(websocket: WebSocket) -> None:
    hub = websocket.app.state.event_hub
    await websocket.accept()

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), AUTH_TIMEOUT_SECONDS)
    except (TimeoutError, WebSocketDisconnect):
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=CLOSE_UNAUTHENTICATED)
        return

    # Accepts a bare token or `{"token": "..."}`, because both are things a
    # client reasonably sends and rejecting one of them buys nothing.
    token = raw.strip()
    if token.startswith("{"):
        try:
            token = str(json.loads(token).get("token", "")).strip()
        except json.JSONDecodeError:
            token = ""

    user = _resolve_user(token) if token else None
    if user is None:
        await websocket.close(code=CLOSE_UNAUTHENTICATED)
        return

    queue = hub.subscribe(user.id)
    await websocket.send_json({"event": "ready"})

    try:
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
            except TimeoutError:
                # Nothing happened. Say so, rather than letting a silent socket
                # be closed by something in the middle for looking idle.
                await websocket.send_json({"event": "ping"})
                continue
            await websocket.send_json(message)
    except (WebSocketDisconnect, RuntimeError):
        # RuntimeError is what Starlette raises for a send on a socket the peer
        # has already closed - a disconnection by another name.
        pass
    finally:
        hub.unsubscribe(user.id, queue)
