"""Administration of accounts (Section 13).

The interesting cases are not "can an admin ban someone" - they are the ways an
administrator can destroy access for everyone, including themselves, with one
click on a button that looks like every other button.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from aidss.db.models import User, UserRole, UserStatus
from aidss.security.passwords import hash_password

PASSWORD = "correct-horse-battery"


def make_user(session, email: str, role: UserRole = UserRole.INVESTOR) -> User:
    row = User(email=email, password_hash=hash_password(PASSWORD), role=role)
    session.add(row)
    session.flush()
    return row


def token_for(client: TestClient, email: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin_headers(client: TestClient, session) -> dict[str, str]:
    make_user(session, "root@example.com", UserRole.ADMIN)
    session.commit()
    return token_for(client, "root@example.com")


@pytest.fixture
def victim(client: TestClient, session) -> User:
    user = make_user(session, "victim@example.com")
    session.commit()
    return user


# --- listing ---------------------------------------------------------------


def test_an_investor_cannot_list_accounts(client: TestClient, auth_headers) -> None:
    """The account list is every user's email. It is an admin surface."""
    assert client.get("/admin/users", headers=auth_headers).status_code == 403


def test_the_listing_reports_the_status_the_auth_gate_enforces(
    client: TestClient, session, admin_headers, victim
) -> None:
    """An expired suspension is still recorded as suspended. Showing only the
    stored value would have an admin chasing a lock that no longer exists."""
    victim.status = UserStatus.SUSPENDED
    victim.suspended_until = datetime.now(UTC) - timedelta(hours=1)
    session.commit()

    rows = client.get("/admin/users", headers=admin_headers).json()
    row = next(r for r in rows if r["email"] == "victim@example.com")
    assert row["status"] == "suspended"
    assert row["effective_status"] == "active"


# --- suspend, ban, reinstate ----------------------------------------------


def test_a_suspended_user_cannot_sign_in_and_is_told_why(
    client: TestClient, session, admin_headers, victim
) -> None:
    until = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    response = client.post(
        f"/admin/users/{victim.id}/suspend",
        json={"until": until, "reason": "Under review."},
        headers=admin_headers,
    )
    assert response.status_code == 200
    session.commit()

    denied = client.post(
        "/auth/login", json={"email": "victim@example.com", "password": PASSWORD}
    )
    assert denied.status_code == 403
    # The reason reaches the account holder. Being locked out with no
    # explanation leaves them nothing to act on.
    assert "Under review." in denied.json()["detail"]


def test_a_suspension_lifts_itself_when_its_deadline_passes(
    client: TestClient, session, admin_headers, victim
) -> None:
    """No job sweeps these up: a suspension that outlives its own deadline
    because a worker was down is a punishment nobody chose."""
    victim.status = UserStatus.SUSPENDED
    victim.suspended_until = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()

    allowed = client.post(
        "/auth/login", json={"email": "victim@example.com", "password": PASSWORD}
    )
    assert allowed.status_code == 200


def test_a_suspension_deadline_in_the_past_is_refused(
    client: TestClient, admin_headers, victim
) -> None:
    """It would be a no-op dressed as an action: applied, and immediately over."""
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    response = client.post(
        f"/admin/users/{victim.id}/suspend", json={"until": past}, headers=admin_headers
    )
    assert response.status_code == 422


def test_a_ban_is_never_lifted_by_the_clock(
    client: TestClient, session, admin_headers, victim
) -> None:
    client.post(f"/admin/users/{victim.id}/ban", json={"reason": "Abuse."}, headers=admin_headers)
    session.commit()
    # The request ran in its own session; this one still holds the row it
    # loaded earlier, so without expiring it we would assert against a copy
    # made before the ban.
    session.expire_all()

    stored = session.get(User, victim.id)
    assert stored.status is UserStatus.BANNED
    assert stored.suspended_until is None
    assert stored.sign_in_block() is not None


def test_an_existing_token_stops_working_the_moment_a_ban_lands(
    client: TestClient, session, admin_headers, victim
) -> None:
    """A token stays cryptographically valid for its whole hour. A ban that
    only guarded the login page would not take effect until the banned user
    happened to sign out."""
    headers = token_for(client, "victim@example.com")
    assert client.get("/auth/me", headers=headers).status_code == 200

    client.post(f"/admin/users/{victim.id}/ban", json={"reason": "Abuse."}, headers=admin_headers)
    session.commit()

    assert client.get("/auth/me", headers=headers).status_code == 401


def test_reinstating_clears_the_reason_as_well_as_the_status(
    client: TestClient, session, admin_headers, victim
) -> None:
    client.post(f"/admin/users/{victim.id}/ban", json={"reason": "Abuse."}, headers=admin_headers)
    client.post(f"/admin/users/{victim.id}/reinstate", headers=admin_headers)
    session.commit()

    stored = session.get(User, victim.id)
    assert stored.status is UserStatus.ACTIVE
    assert stored.status_reason is None
    assert (
        client.post(
            "/auth/login", json={"email": "victim@example.com", "password": PASSWORD}
        ).status_code
        == 200
    )


# --- roles -----------------------------------------------------------------


def test_an_account_can_be_promoted_and_demoted(
    client: TestClient, session, admin_headers, victim
) -> None:
    promoted = client.patch(
        f"/admin/users/{victim.id}/role", json={"role": "admin"}, headers=admin_headers
    )
    assert promoted.json()["role"] == "admin"

    demoted = client.patch(
        f"/admin/users/{victim.id}/role", json={"role": "viewer"}, headers=admin_headers
    )
    assert demoted.json()["role"] == "viewer"


# --- the guards that matter ------------------------------------------------


def test_an_admin_cannot_act_on_their_own_account(
    client: TestClient, session, admin_headers
) -> None:
    me = client.get("/auth/me", headers=admin_headers).json()["id"]
    for path, body in (
        (f"/admin/users/{me}/suspend", {}),
        (f"/admin/users/{me}/ban", {}),
    ):
        assert client.post(path, json=body, headers=admin_headers).status_code == 409
    assert (
        client.patch(
            f"/admin/users/{me}/role", json={"role": "viewer"}, headers=admin_headers
        ).status_code
        == 409
    )
    assert client.delete(f"/admin/users/{me}", headers=admin_headers).status_code == 409


def test_an_admin_may_step_down_while_another_remains(
    client: TestClient, session
) -> None:
    """Stepping down is a real thing an administrator does."""
    make_user(session, "chief@example.com", UserRole.ADMIN)
    make_user(session, "deputy@example.com", UserRole.ADMIN)
    session.commit()
    headers = token_for(client, "chief@example.com")

    me = client.get("/auth/me", headers=headers).json()["id"]
    response = client.patch(
        f"/admin/users/{me}/role", json={"role": "investor"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["role"] == "investor"


def test_the_last_administrator_cannot_step_down(client: TestClient, session) -> None:
    """The guard that matters. There is no endpoint that grants admin -
    promotion is a shell command by design, precisely so a route cannot be an
    escalation surface - so an organisation whose only admin demotes itself
    cannot recover from inside the product at all."""
    make_user(session, "solo@example.com", UserRole.ADMIN)
    session.commit()
    headers = token_for(client, "solo@example.com")

    me = client.get("/auth/me", headers=headers).json()["id"]
    response = client.patch(
        f"/admin/users/{me}/role", json={"role": "investor"}, headers=headers
    )
    assert response.status_code == 409
    assert "only administrator" in response.json()["detail"]


def test_the_last_administrator_cannot_be_demoted_by_another_admin(
    client: TestClient, session
) -> None:
    """Reachable while two admins exist and one has already stepped down in the
    same session: the count is what decides, not who is asking."""
    make_user(session, "one@example.com", UserRole.ADMIN)
    two = make_user(session, "two@example.com", UserRole.ADMIN)
    session.commit()
    headers = token_for(client, "one@example.com")

    # `one` steps down first, leaving `two` alone at the top.
    me = client.get("/auth/me", headers=headers).json()["id"]
    client.patch(f"/admin/users/{me}/role", json={"role": "investor"}, headers=headers)
    session.commit()

    # `one` is no longer an admin, so it can no longer reach the endpoint -
    # which is itself the protection. Verified rather than assumed.
    assert (
        client.patch(
            f"/admin/users/{two.id}/role", json={"role": "investor"}, headers=headers
        ).status_code
        == 403
    )


# --- deletion ---------------------------------------------------------------


def test_deleting_an_account_takes_its_personal_data_with_it(
    client: TestClient, session, admin_headers, victim
) -> None:
    """Watchlists, portfolios, and journal entries cascade. That is what
    deletion means here, and it is why ban exists beside it."""
    from aidss.db.models import Watchlist

    session.add(Watchlist(user_id=victim.id, name="Default"))
    session.commit()

    victim_id = victim.id
    assert client.delete(f"/admin/users/{victim.id}", headers=admin_headers).status_code == 204
    session.commit()
    # Expunged, not expired: this session still holds the instance the request
    # deleted, and refreshing a row that is gone raises rather than returning
    # None. Dropping it from the identity map is what makes the next read a
    # real query.
    session.expunge_all()

    assert session.get(User, victim_id) is None
    assert (
        session.scalars(select(Watchlist).where(Watchlist.user_id == victim.id)).all() == []
    )


def test_a_deletion_is_audited_with_the_email_before_the_row_goes(
    client: TestClient, session, admin_headers, victim
) -> None:
    """"Some account was deleted" answers nothing six months later."""
    from aidss.db.models import AuditLog

    client.delete(f"/admin/users/{victim.id}", headers=admin_headers)
    session.commit()

    entry = session.scalar(
        select(AuditLog).where(AuditLog.action == "delete_user").order_by(
            AuditLog.created_at.desc()
        )
    )
    assert entry is not None
    assert entry.after["email"] == "victim@example.com"


# --- editing a source ------------------------------------------------------


@pytest.fixture
def source(client: TestClient, admin_headers) -> dict:
    return client.post(
        "/admin/news-sources",
        json={"name": "Pasar Modal", "feed_url": "https://example.com/a.xml"},
        headers=admin_headers,
    ).json()


def test_a_source_can_be_renamed_and_repointed(
    client: TestClient, admin_headers, source
) -> None:
    """Editing used to be impossible: a typo in a URL meant deleting the row and
    losing its fetch history to recreate it one character different."""
    response = client.patch(
        f"/admin/news-sources/{source['id']}",
        json={"name": "Bisnis", "feed_url": "https://example.com/b.xml"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Bisnis"
    assert response.json()["feed_url"] == "https://example.com/b.xml"


def test_repointing_onto_another_source_url_is_refused(
    client: TestClient, admin_headers, source
) -> None:
    """Left to the unique constraint this would be a 500 with a database
    message in it."""
    other = client.post(
        "/admin/news-sources",
        json={"name": "Kontan", "feed_url": "https://example.com/b.xml"},
        headers=admin_headers,
    ).json()

    response = client.patch(
        f"/admin/news-sources/{other['id']}",
        json={"feed_url": source["feed_url"]},
        headers=admin_headers,
    )
    assert response.status_code == 409


def test_keeping_the_same_url_is_not_a_clash_with_itself(
    client: TestClient, admin_headers, source
) -> None:
    response = client.patch(
        f"/admin/news-sources/{source['id']}",
        json={"name": "Renamed", "feed_url": source["feed_url"]},
        headers=admin_headers,
    )
    assert response.status_code == 200


def test_a_binding_can_be_added_and_removed(
    client: TestClient, admin_headers, source, session
) -> None:
    """Null and absent mean different things here: one unbinds, the other
    leaves the binding alone. A plain optional field cannot say both."""
    from aidss.db.models import Asset

    session.add(Asset(ticker="BBCA", exchange="IDX"))
    session.commit()

    bound = client.patch(
        f"/admin/news-sources/{source['id']}", json={"ticker": "BBCA"}, headers=admin_headers
    )
    assert bound.json()["ticker"] == "BBCA"

    # Omitting the key leaves it alone...
    untouched = client.patch(
        f"/admin/news-sources/{source['id']}", json={"name": "Still bound"}, headers=admin_headers
    )
    assert untouched.json()["ticker"] == "BBCA"

    # ...sending it as null removes it.
    unbound = client.patch(
        f"/admin/news-sources/{source['id']}", json={"ticker": None}, headers=admin_headers
    )
    assert unbound.json()["ticker"] is None


def test_binding_to_an_unknown_ticker_is_refused(
    client: TestClient, admin_headers, source
) -> None:
    response = client.patch(
        f"/admin/news-sources/{source['id']}", json={"ticker": "NOPE"}, headers=admin_headers
    )
    assert response.status_code == 404


def test_re_enabling_clears_the_failure_count(
    client: TestClient, admin_headers, source, session
) -> None:
    """A feed switched back on should not be one failure away from switching
    off again."""
    from aidss.db.models import NewsSource

    row = session.get(NewsSource, uuid.UUID(source["id"]))
    row.consecutive_failures = 19
    row.is_active = False
    session.commit()

    response = client.patch(
        f"/admin/news-sources/{source['id']}", json={"is_active": True}, headers=admin_headers
    )
    assert response.json()["is_active"] is True
    assert response.json()["consecutive_failures"] == 0


def test_a_feed_url_must_be_http(client: TestClient, admin_headers, source) -> None:
    """An admin is trusted, but `file://` here would turn a configuration field
    into a way to read the container's filesystem through the feed parser."""
    response = client.patch(
        f"/admin/news-sources/{source['id']}",
        json={"feed_url": "file:///etc/passwd"},
        headers=admin_headers,
    )
    assert response.status_code == 422
