"""A response must not promise a write the database has not accepted yet.

FastAPI ends a `yield` dependency after the response has been sent, so a
session committed in that teardown commits *behind* the client. Measured
against the running stack: the user row landed 9-51ms after the 201 that
announced it, and registering then signing in - which is precisely what the
sign-up form does, `AuthContext.signUp` calls `signIn` on the next line -
returned "Incorrect email or password" five times in eight.

Sign-up is only where it was loud. The interface refetches every query it just
invalidated, so the same race quietly drops freshly-written rows out of lists
that reload a few milliseconds too early - a class of bug that reads as
flakiness and never gets traced back to here.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.api.deps import CommitBeforeResponse
from aidss.db import base as db_base
from aidss.db.models import User


def test_the_route_commits_without_waiting_for_the_dependency_teardown(session) -> None:
    """The dependency here deliberately never commits.

    That is the whole test. `TestClient` runs the request to completion before
    returning, so it cannot show the real gap between "response sent" and
    "teardown ran" - a test that merely POSTs and then looks would pass with or
    without the fix and prove nothing. Removing the teardown commit entirely
    puts the burden on the route class alone: if it is not committing, nothing
    is, and the row will not be there.
    """
    sessions = db_base.get_sessionmaker()

    def never_commits(request: Request):  # noqa: ANN202
        db = sessions()
        # Publishing the session is the real `get_db`'s job; this stand-in does
        # only that part, and pointedly not the commit.
        request.state.db_session = db
        try:
            yield db
        finally:
            db.close()  # no commit, on purpose

    app = FastAPI()
    app.router.route_class = CommitBeforeResponse

    @app.post("/write")
    def write(db: Session = Depends(never_commits)) -> dict:
        db.add(User(email="committed@example.com", password_hash="x", full_name="C"))
        db.flush()
        return {"written": True}

    with TestClient(app) as client:
        assert client.post("/write").status_code == 200

    with sessions() as observer:
        found = observer.scalar(select(User).where(User.email == "committed@example.com"))

    assert found is not None, (
        "nothing committed the write, so the only thing that could have - the "
        "route class - did not; a client acting on this response would race the "
        "database and lose"
    )


def test_get_db_hands_its_session_to_the_route(session) -> None:
    """The route class can only commit a session it can reach. `get_db` puts it
    on `request.state`; drop that and the commit becomes a silent no-op while
    every test that merely checks the route class is installed still passes."""
    from aidss.api.deps import get_db

    class FakeState:
        pass

    class FakeRequest:
        state = FakeState()

    request = FakeRequest()
    generator = get_db(request)
    db = next(generator)
    assert getattr(request.state, "db_session", None) is db, (
        "get_db must publish its session to request.state for the route to commit it"
    )
    generator.close()


def test_the_route_class_is_applied_to_the_real_app() -> None:
    """The fix lives in one line of the app factory, and a router included
    before that line silently keeps the default class. Nothing else would
    notice: every endpoint still works, just with the race back."""
    from fastapi.routing import APIRoute

    from aidss.main import create_app

    app = create_app()
    plain = [
        route.path
        for route in app.routes
        if isinstance(route, APIRoute) and not isinstance(route, CommitBeforeResponse)
    ]
    assert not plain, f"these routes commit after their response: {plain}"
