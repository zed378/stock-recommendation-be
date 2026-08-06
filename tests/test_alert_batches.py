"""Acting on many alerts at once.

The interesting part is not the counting. It is that an alert id is a bearer
token for the row it names: anybody who has one can put it in a list. Every
statement here is scoped by user id in the same WHERE clause as the ids, and
these tests exist mainly to hold that in place - a batch endpoint that filters
by ownership loosely is one request away from clearing somebody else's alerts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from aidss.db.base import get_sessionmaker
from aidss.db.models import Alert, AlertDirection, AlertKind, Asset, User
from aidss.security.passwords import hash_password


def make_alert(db, user_id: uuid.UUID, asset_id: uuid.UUID, *, seen: bool = False) -> Alert:
    alert = Alert(
        user_id=user_id,
        asset_id=asset_id,
        # Unique per alert: the column exists to stop one condition notifying
        # the same person repeatedly, so a shared value here would collapse the
        # fixtures into one row and quietly make every count wrong.
        dedup_key=f"test-{uuid.uuid4()}",
        kind=AlertKind.LEVEL_CROSSED,
        direction=AlertDirection.UP,
        message="Price crossed a stored level",
        triggered_at=datetime.now(UTC),
        acknowledged_at=datetime.now(UTC) if seen else None,
    )
    db.add(alert)
    # Flushed here so `.id` is populated: the default assigns it at flush,
    # and reading it before produced ids of the literal string "None".
    db.flush()
    return alert


@pytest.fixture
def alerts(client: TestClient, auth_headers) -> dict:
    """Three alerts for the signed-in investor, one for somebody else."""
    db = get_sessionmaker()()
    try:
        asset = Asset(ticker="BBRI", exchange="IDX", name="Bank Rakyat Indonesia")
        db.add(asset)
        mine = db.scalar(select(User).where(User.email == "investor@example.com"))
        stranger = User(
            email="stranger@example.com", password_hash=hash_password("correct-horse-battery")
        )
        db.add(stranger)
        db.flush()

        ids = [str(make_alert(db, mine.id, asset.id).id) for _ in range(3)]
        theirs = make_alert(db, stranger.id, asset.id)
        db.flush()
        result = {"mine": ids, "theirs": str(theirs.id), "stranger": stranger.id}
        db.commit()
        return result
    finally:
        db.close()


def unacknowledged(user_email: str) -> int:
    db = get_sessionmaker()()
    try:
        user = db.scalar(select(User).where(User.email == user_email))
        return len(
            db.scalars(
                select(Alert).where(
                    Alert.user_id == user.id, Alert.acknowledged_at.is_(None)
                )
            ).all()
        )
    finally:
        db.close()


def total(user_email: str) -> int:
    db = get_sessionmaker()()
    try:
        user = db.scalar(select(User).where(User.email == user_email))
        return len(db.scalars(select(Alert).where(Alert.user_id == user.id)).all())
    finally:
        db.close()


# --- acknowledging ----------------------------------------------------------


def test_selected_alerts_are_acknowledged(client, auth_headers, alerts) -> None:
    response = client.post(
        "/alerts/acknowledge", headers=auth_headers, json={"ids": alerts["mine"][:2]}
    )

    assert response.status_code == 200, response.json()
    assert response.json()["affected"] == 2
    assert unacknowledged("investor@example.com") == 1


def test_acknowledging_does_not_reach_another_user_s_alerts(
    client, auth_headers, alerts
) -> None:
    """An id is enough to name a row; it must not be enough to change one."""
    response = client.post(
        "/alerts/acknowledge",
        headers=auth_headers,
        json={"ids": [*alerts["mine"], alerts["theirs"]]},
    )

    assert response.json()["affected"] == 3, "the stranger's alert must not be counted"
    assert unacknowledged("stranger@example.com") == 1


def test_the_count_reports_what_changed_not_what_was_asked(
    client, auth_headers, alerts
) -> None:
    """Ids already acknowledged, or belonging to nobody, are skipped. A caller
    who selected five and changed three should be able to tell."""
    client.post("/alerts/acknowledge", headers=auth_headers, json={"ids": alerts["mine"][:1]})

    again = client.post(
        "/alerts/acknowledge",
        headers=auth_headers,
        json={"ids": [*alerts["mine"], str(uuid.uuid4())]},
    )

    assert again.json()["affected"] == 2


def test_acknowledge_all_clears_only_this_user(client, auth_headers, alerts) -> None:
    response = client.post("/alerts/acknowledge-all", headers=auth_headers)

    assert response.json()["affected"] == 3
    assert unacknowledged("investor@example.com") == 0
    assert unacknowledged("stranger@example.com") == 1


# --- deleting ---------------------------------------------------------------


def test_selected_alerts_are_deleted(client, auth_headers, alerts) -> None:
    response = client.post(
        "/alerts/delete", headers=auth_headers, json={"ids": alerts["mine"][:2]}
    )

    assert response.json()["affected"] == 2
    assert total("investor@example.com") == 1


def test_deleting_does_not_reach_another_user_s_alerts(client, auth_headers, alerts) -> None:
    client.post(
        "/alerts/delete", headers=auth_headers, json={"ids": [alerts["theirs"]]}
    )

    assert total("stranger@example.com") == 1, "another user's alert was deleted"


def test_delete_all_clears_only_this_user(client, auth_headers, alerts) -> None:
    response = client.post("/alerts/delete-all", headers=auth_headers)

    assert response.json()["affected"] == 3
    assert total("investor@example.com") == 0
    assert total("stranger@example.com") == 1


# --- the shape of the request itself ----------------------------------------


def test_an_empty_selection_is_refused_rather_than_meaning_everything(
    client, auth_headers, alerts
) -> None:
    """The reason "all" has its own endpoint. If an empty list meant everything,
    the difference between acknowledging a selection and clearing the whole list
    would rest on whether a client's filter happened to return anything."""
    for path in ("/alerts/acknowledge", "/alerts/delete"):
        response = client.post(path, headers=auth_headers, json={"ids": []})
        assert response.status_code == 422, path
    assert total("investor@example.com") == 3


def test_a_batch_is_bounded(client, auth_headers) -> None:
    """An unbounded id list is an unbounded IN clause built from user input."""
    response = client.post(
        "/alerts/delete",
        headers=auth_headers,
        json={"ids": [str(uuid.uuid4()) for _ in range(501)]},
    )
    assert response.status_code == 422


def test_the_batch_endpoints_require_authentication(client, alerts) -> None:
    for path in ("/alerts/acknowledge-all", "/alerts/delete-all"):
        assert client.post(path).status_code == 401, path
    assert total("investor@example.com") == 3
