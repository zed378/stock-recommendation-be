"""Issuing and verifying JWT access tokens (Section 26)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from aidss.config import Settings, get_settings


class TokenError(Exception):
    """The token is invalid, expired, or does not match the expected schema."""


@dataclass(frozen=True, slots=True)
class TokenPayload:
    user_id: uuid.UUID
    role: str
    expires_at: datetime


def create_access_token(
    user_id: uuid.UUID, role: str, settings: Settings | None = None
) -> str:
    settings = settings or get_settings()
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings | None = None) -> TokenPayload:
    settings = settings or get_settings()
    try:
        data = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    # Requiring the type claim stops a refresh or ID token from being replayed
    # as an access token.
    if data.get("typ") != "access":
        raise TokenError("Token type is not an access token")
    try:
        user_id = uuid.UUID(data["sub"])
    except (KeyError, ValueError) as exc:
        raise TokenError("The `sub` claim is not a valid UUID") from exc

    return TokenPayload(
        user_id=user_id,
        role=str(data.get("role", "viewer")),
        expires_at=datetime.fromtimestamp(int(data["exp"]), tz=UTC),
    )
