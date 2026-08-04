"""The operator CLI, and why role changes live there rather than in the API.

The bootstrapping argument is the load-bearing one: registration creates
`investor` accounts, so an API-only promotion path means the first admin can
never exist unless the code ships a back door. Shell access is the authority
instead, and every change it makes is written to the audit log.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from aidss.cli import main
from aidss.db.models import ActorType, AuditLog, User, UserRole
from aidss.security.passwords import hash_password


@pytest.fixture
def investor(session) -> User:
    user = User(
        email="operator@example.com",
        password_hash=hash_password("correct-horse-battery"),
        full_name="Operator",
    )
    session.add(user)
    session.commit()
    return user


def reload_role(session, email: str) -> UserRole:
    session.expire_all()
    return session.scalar(select(User).where(User.email == email)).role


def test_a_new_account_is_an_investor_not_an_admin(investor, session) -> None:
    """The premise the CLI exists for."""
    assert reload_role(session, "operator@example.com") == UserRole.INVESTOR


def test_granting_admin_promotes_the_account(investor, session, capsys) -> None:
    assert main(["grant-admin", "operator@example.com"]) == 0
    assert reload_role(session, "operator@example.com") == UserRole.ADMIN
    assert "investor -> admin" in capsys.readouterr().out


def test_the_email_is_matched_case_insensitively(investor, session) -> None:
    """Emails are stored lower case at registration; an operator typing the
    address as they remember it should not get "no such user"."""
    assert main(["grant-admin", "OPERATOR@Example.com"]) == 0
    assert reload_role(session, "operator@example.com") == UserRole.ADMIN


def test_revoking_returns_the_account_to_investor(investor, session) -> None:
    main(["grant-admin", "operator@example.com"])
    assert main(["revoke-admin", "operator@example.com"]) == 0
    assert reload_role(session, "operator@example.com") == UserRole.INVESTOR


def test_an_unknown_email_fails_rather_than_passing_quietly(session, capsys) -> None:
    """Exit code 1, so a provisioning script that mistypes an address stops
    instead of reporting success and leaving nobody able to administer."""
    assert main(["grant-admin", "nobody@example.com"]) == 1
    assert "No user" in capsys.readouterr().err


def test_granting_twice_is_a_quiet_no_op(investor, session, capsys) -> None:
    main(["grant-admin", "operator@example.com"])
    assert main(["grant-admin", "operator@example.com"]) == 0
    assert "already admin" in capsys.readouterr().out


def test_a_role_change_is_written_to_the_audit_log(investor, session) -> None:
    """A change made outside the application is exactly the kind of event
    someone later has to account for."""
    main(["grant-admin", "operator@example.com"])

    session.expire_all()
    entry = session.scalar(
        select(AuditLog).where(AuditLog.action == "role_change", AuditLog.entity == "users")
    )
    assert entry is not None
    assert entry.actor_type == ActorType.SYSTEM
    assert entry.before == {"role": "investor"}
    assert entry.after == {"role": "admin"}


def test_a_no_op_writes_no_audit_entry(investor, session) -> None:
    """Otherwise a re-run of a provisioning script fills the log with changes
    that never happened."""
    main(["grant-admin", "operator@example.com"])
    main(["grant-admin", "operator@example.com"])

    session.expire_all()
    entries = session.scalars(
        select(AuditLog).where(AuditLog.action == "role_change")
    ).all()
    assert len(entries) == 1


def test_listing_users_shows_their_roles(investor, session, capsys) -> None:
    main(["grant-admin", "operator@example.com"])
    assert main(["list-users"]) == 0
    assert "operator@example.com" in capsys.readouterr().out


def test_listing_with_no_users_says_what_to_do(session, capsys) -> None:
    assert main(["list-users"]) == 0
    assert "Sign up" in capsys.readouterr().out
