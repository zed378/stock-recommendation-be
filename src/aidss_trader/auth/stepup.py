"""Step-up grants (ADR-046): a recent password re-entry, single use, short lived.

The Trader never keeps the password. It forwards it once to the analysis API's
`/auth/login` and requires the resulting token to resolve to the *same user* as the
session, so someone with a stolen session but not the password cannot mint a grant.
Grants are stored as hashes; a database read does not yield a usable grant.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss_trader.auth.verify import AuthFailed, Principal, TokenVerifier
from aidss_trader.db.models import StepUpGrant

SCOPES = frozenset({"FLATTEN", "PROMOTE_AUTO", "RAISE_LIMIT", "CREDENTIALS"})
GRANT_TTL = timedelta(minutes=5)


class StepUpRefused(Exception):
    pass


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class StepUp:
    def __init__(
        self,
        session: Session,
        analysis_api_url: str,
        verifier: TokenVerifier,
        *,
        now: Callable[[], datetime] = _now,
        timeout_s: float = 5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._s, self._verifier, self._now = session, verifier, now
        self._login = f"{analysis_api_url.rstrip('/')}/auth/login"
        self._http = httpx.Client(transport=transport, timeout=timeout_s)

    def issue(self, principal: Principal, email: str, password: str, scope: str) -> str:
        if scope not in SCOPES:
            raise StepUpRefused("unknown step-up scope")
        try:
            resp = self._http.post(self._login, json={"email": email, "password": password})
            if resp.status_code != 200:
                raise StepUpRefused("re-authentication failed")
            who = self._verifier.verify(str(resp.json().get("access_token", "")))
        except (httpx.HTTPError, ValueError, AuthFailed):
            raise StepUpRefused("re-authentication failed") from None
        if who.user_id != principal.user_id:
            raise StepUpRefused("re-authentication was for a different user")
        token = secrets.token_urlsafe(32)
        self._s.add(
            StepUpGrant(
                user_id=principal.user_id,
                scope=scope,
                token_hash=_hash(token),
                expires_at=self._now() + GRANT_TTL,
            )
        )
        self._s.commit()
        return token

    def consume(self, token: str, principal: Principal, scope: str) -> None:
        """Burn a grant. Raises unless it is unused, unexpired, and for this user and scope."""
        grant = self._s.scalar(select(StepUpGrant).where(StepUpGrant.token_hash == _hash(token)))
        if (
            grant is None
            or grant.used_at is not None
            or grant.user_id != principal.user_id
            or grant.scope != scope
            or _aware(grant.expires_at) <= self._now()
        ):
            raise StepUpRefused("step-up grant is missing, used, expired, or for something else")
        grant.used_at = self._now()
        self._s.commit()
