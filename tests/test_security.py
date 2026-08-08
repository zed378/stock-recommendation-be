"""Password, token, and RBAC tests (Section 26)."""

from __future__ import annotations

import uuid
from datetime import UTC, timedelta

import jwt
import pytest

from aidss.config import Settings
from aidss.db.models import UserRole
from aidss.security.passwords import (
    PasswordPolicyError,
    hash_password,
    verify_password,
)
from aidss.security.rbac import Permission, has_permission, permissions_for
from aidss.security.tokens import TokenError, create_access_token, decode_access_token

# --- Passwords -------------------------------------------------------------


def test_password_round_trip() -> None:
    stored = hash_password("correct-horse-battery")
    assert verify_password("correct-horse-battery", stored)
    assert not verify_password("wrong-horse-battery", stored)


def test_hash_is_salted() -> None:
    assert hash_password("correct-horse-battery") != hash_password("correct-horse-battery")


def test_plaintext_never_appears_in_the_hash() -> None:
    assert "correct-horse-battery" not in hash_password("correct-horse-battery")


def test_short_passwords_are_rejected() -> None:
    with pytest.raises(PasswordPolicyError):
        hash_password("short")


def test_overlong_passwords_are_rejected_rather_than_truncated() -> None:
    """bcrypt silently ignores bytes past 72; refusing is safer than truncating."""
    with pytest.raises(PasswordPolicyError):
        hash_password("a" * 100)


def test_malformed_stored_hash_fails_closed() -> None:
    assert verify_password("correct-horse-battery", "not-a-bcrypt-hash") is False


# --- Tokens ----------------------------------------------------------------


#: At least 32 bytes, matching the HMAC-SHA256 recommendation.
TEST_SECRET = "unit-test-secret-0123456789abcdefghij"


@pytest.fixture
def settings() -> Settings:
    return Settings(jwt_secret=TEST_SECRET, access_token_ttl_minutes=60)


def test_token_round_trip(settings: Settings) -> None:
    user_id = uuid.uuid4()
    payload = decode_access_token(create_access_token(user_id, "investor", settings), settings)
    assert payload.user_id == user_id
    assert payload.role == "investor"


def test_token_signed_with_another_secret_is_rejected(settings: Settings) -> None:
    token = create_access_token(uuid.uuid4(), "investor", settings)
    other = Settings(jwt_secret="a-different-secret-0123456789abcdefghij")
    with pytest.raises(TokenError):
        decode_access_token(token, other)


def test_expired_token_is_rejected(settings: Settings) -> None:
    expired = Settings(jwt_secret=settings.jwt_secret, access_token_ttl_minutes=-1)
    token = create_access_token(uuid.uuid4(), "investor", expired)
    with pytest.raises(TokenError):
        decode_access_token(token, settings)


def test_token_without_a_type_claim_is_rejected(settings: Settings) -> None:
    """A refresh or ID token must not be usable as an access token."""
    from datetime import datetime

    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "admin",
            "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(TokenError):
        decode_access_token(forged, settings)


def test_token_with_a_non_uuid_subject_is_rejected(settings: Settings) -> None:
    from datetime import datetime

    forged = jwt.encode(
        {
            "sub": "administrator",
            "typ": "access",
            "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(TokenError):
        decode_access_token(forged, settings)


# --- RBAC ------------------------------------------------------------------


def test_viewer_is_read_only() -> None:
    assert has_permission(UserRole.VIEWER, Permission.READ_MARKET_DATA)
    assert not has_permission(UserRole.VIEWER, Permission.MANAGE_OWN_DATA)
    assert not has_permission(UserRole.VIEWER, Permission.MANAGE_PROVIDERS)


def test_investor_manages_own_data_but_not_system_configuration() -> None:
    assert has_permission(UserRole.INVESTOR, Permission.MANAGE_OWN_DATA)
    assert not has_permission(UserRole.INVESTOR, Permission.MANAGE_PROVIDERS)
    assert not has_permission(UserRole.INVESTOR, Permission.READ_AUDIT_LOG)


def test_admin_permissions_are_a_superset() -> None:
    assert permissions_for(UserRole.INVESTOR) <= permissions_for(UserRole.ADMIN)
    assert permissions_for(UserRole.VIEWER) <= permissions_for(UserRole.INVESTOR)


def test_unknown_role_gets_no_permissions() -> None:
    assert permissions_for("superuser") == frozenset()
