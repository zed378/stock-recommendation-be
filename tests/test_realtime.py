"""Server-pushed events: what is published, and what the socket will accept.

The two properties that matter are both about what an event is *not*. It is not
the data - so the socket cannot become a second way to read something REST
would have refused - and it is not load-bearing, so a failure to publish must
never take down the work that produced it.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from aidss.db.models import Notification, User
from aidss.realtime.events import MAX_PAYLOAD_BYTES, publish
from aidss.realtime.hub import EventHub, dsn_from_sqlalchemy_url
from aidss.reporting.notifications import NotificationEvent, NotificationService
from aidss.security.passwords import hash_password


@pytest.fixture
def user(session) -> User:
    row = User(email="socket@example.com", password_hash=hash_password("correct-horse-battery"))
    session.add(row)
    session.flush()
    return row


# --- publishing --------------------------------------------------------------


def test_publishing_never_fails_the_work_that_produced_it(session, user, monkeypatch) -> None:
    """An event is a convenience over polling. Losing one is a slower
    interface; raising here would lose the analysis that had just finished."""
    from aidss.realtime import events as events_module

    def explode(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("the channel is gone")

    monkeypatch.setattr(events_module.Session, "execute", explode, raising=False)
    # No assertion beyond "returns": the point is that it does not raise.
    publish(session, user_id=user.id, event="analysis_ready", data={"ticker": "BBCA"})


def test_an_oversized_payload_is_dropped_rather_than_thrown(session, user) -> None:
    """PostgreSQL refuses a NOTIFY payload above 8000 bytes, and that refusal
    would surface from inside somebody else's commit."""
    publish(
        session,
        user_id=user.id,
        event="analysis_ready",
        data={"padding": "x" * (MAX_PAYLOAD_BYTES + 100)},
    )


def test_a_notification_publishes_an_event(session, user, monkeypatch) -> None:
    """The one place that already knows something worth telling somebody about
    has happened - so it is the place that announces it, rather than every
    producer of work remembering to."""
    published: list[dict] = []

    def capture(_session, *, user_id, event, data=None):  # noqa: ANN001, ANN202
        published.append({"user_id": user_id, "event": event, "data": data or {}})

    monkeypatch.setattr("aidss.reporting.notifications.publish", capture)

    NotificationService(session).notify(
        user.id,
        NotificationEvent.ANALYSIS_READY,
        "Analysis for BBCA finished.",
        context={"ticker": "BBCA", "analysis_result_id": "abc"},
    )

    assert len(published) == 1
    assert published[0]["user_id"] == user.id
    assert published[0]["event"] == "analysis_ready"
    assert published[0]["data"]["ticker"] == "BBCA"


def test_the_event_carries_pointers_not_content(session, user, monkeypatch) -> None:
    """Every field is an id or a short scalar. If the analysis text itself ever
    started travelling on the socket, authorisation would have quietly moved
    from the REST layer to a channel that never checks it."""
    published: list[dict] = []
    monkeypatch.setattr(
        "aidss.reporting.notifications.publish",
        lambda _s, *, user_id, event, data=None: published.append(data or {}),
    )

    NotificationService(session).notify(
        user.id,
        NotificationEvent.ANALYSIS_READY,
        "Analysis for BBCA finished.",
        context={"ticker": "BBCA", "stance": "hold", "confidence": 83.0},
    )

    [data] = published
    assert "notification_id" in data
    for value in data.values():
        assert not isinstance(value, dict), "an event must not carry a nested payload"
        if isinstance(value, str):
            assert len(value) < 200, "an event must not carry prose"


def test_an_undelivered_notification_publishes_nothing(session, user) -> None:
    """A channel that failed means nobody was told. Announcing it anyway would
    send the interface to fetch something the reader was never shown."""
    from aidss.reporting.notifications import NotificationChannel

    class BrokenChannel(NotificationChannel):
        name = "broken"

        def deliver(self, user, subject, message) -> bool:  # noqa: ANN001, ARG002
            return False

    published: list[str] = []
    service = NotificationService(session, channels=[BrokenChannel()])

    import aidss.reporting.notifications as module

    original = module.publish
    module.publish = lambda *a, **k: published.append("published")  # noqa: ARG005
    try:
        service.notify(user.id, NotificationEvent.REPORT_READY, "Report ready.")
    finally:
        module.publish = original

    assert published == []
    # ...and the notification is still stored, so nothing was lost.
    assert session.scalar(select(Notification)) is not None


# --- the hub -----------------------------------------------------------------


def test_the_dsn_is_derived_from_the_one_database_setting() -> None:
    """A second setting for the same address is two things that can disagree."""
    assert (
        dsn_from_sqlalchemy_url("postgresql+psycopg://u:p@host:5432/db")
        == "postgresql://u:p@host:5432/db"
    )


@pytest.mark.anyio
async def test_events_reach_only_their_own_subscriber() -> None:
    """Filtering happens here, on the subscriber side, because one channel
    carries everybody's events."""
    hub = EventHub("postgresql://unused")
    mine, theirs = uuid.uuid4(), uuid.uuid4()

    my_queue = hub.subscribe(mine)
    their_queue = hub.subscribe(theirs)

    hub._deliver({"event": "analysis_ready", "user_id": str(mine), "data": {}})  # noqa: SLF001

    assert my_queue.get_nowait()["event"] == "analysis_ready"
    assert their_queue.empty()


@pytest.mark.anyio
async def test_a_client_that_stopped_reading_drops_its_oldest_events() -> None:
    """A suspended laptop must not grow an unbounded queue. Every event here is
    a hint to refetch, so the newest one supersedes the ones behind it."""
    from aidss.realtime.hub import QUEUE_SIZE

    hub = EventHub("postgresql://unused")
    user_id = uuid.uuid4()
    queue = hub.subscribe(user_id)

    for index in range(QUEUE_SIZE + 10):
        hub._deliver(  # noqa: SLF001
            {"event": "analysis_ready", "user_id": str(user_id), "data": {"n": index}}
        )

    assert queue.qsize() <= QUEUE_SIZE
    # The most recent survived; the earliest did not.
    drained = [queue.get_nowait()["data"]["n"] for _ in range(queue.qsize())]
    assert drained[-1] == QUEUE_SIZE + 9
    assert 0 not in drained


@pytest.mark.anyio
async def test_unsubscribing_leaves_no_entry_behind() -> None:
    """A long-lived process would otherwise accumulate one key per user who
    ever connected."""
    hub = EventHub("postgresql://unused")
    user_id = uuid.uuid4()
    queue = hub.subscribe(user_id)
    hub.unsubscribe(user_id, queue)

    assert user_id not in hub._subscribers  # noqa: SLF001


@pytest.mark.anyio
async def test_an_event_without_a_user_is_not_broadcast() -> None:
    """There is no such thing as an event for everybody here: every one of them
    concerns one person's data."""
    hub = EventHub("postgresql://unused")
    queue = hub.subscribe(uuid.uuid4())

    hub._deliver({"event": "analysis_ready", "user_id": None, "data": {}})  # noqa: SLF001
    hub._deliver({"event": "analysis_ready", "user_id": "not-a-uuid", "data": {}})  # noqa: SLF001

    assert queue.empty()


# --- the socket ---------------------------------------------------------------


def test_the_socket_refuses_a_connection_with_no_token(client) -> None:
    """The token arrives in the first frame, not the URL - a query parameter
    would put a bearer token into every access log along the way."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/events") as socket:
        socket.send_text("")
        socket.receive_json()


def test_the_socket_refuses_a_forged_token(client) -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/events") as socket:
        socket.send_text(json.dumps({"token": "not.a.token"}))
        socket.receive_json()


def test_a_valid_token_is_accepted(client, auth_headers) -> None:
    token = auth_headers["Authorization"].removeprefix("Bearer ")
    with client.websocket_connect("/ws/events") as socket:
        socket.send_text(json.dumps({"token": token}))
        assert socket.receive_json() == {"event": "ready"}
