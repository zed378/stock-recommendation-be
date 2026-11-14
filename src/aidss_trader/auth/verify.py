"""Verify a bearer token through the analysis API's `GET /auth/me` (ADR-028).

The Trader does not hold the platform's JWT signing secret: a compromised Trader
could otherwise mint tokens for the analysis platform. The analysis API
re-checks the user's status on every request, so a suspended user's token stops
working at once.

Fails closed. Any failure to get a clear "yes" (network error, timeout, a
non-200, an unexpected body) is a refusal, never a guess. The consequence is
that the operator *screens* are unavailable while the analysis API is down; the
command-line kill tool does not depend on this path.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

# The roles the analysis platform knows. Anything else is refused.
_KNOWN_ROLES = frozenset({"viewer", "investor", "admin", "trader"})


class AuthFailed(Exception):
    """The token could not be verified. The reason is for logs, not for the caller."""


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    role: str


class TokenVerifier:
    def __init__(
        self,
        analysis_api_url: str,
        *,
        timeout_s: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._url = analysis_api_url.rstrip("/") + "/auth/me"
        self._http = httpx.Client(timeout=timeout_s, transport=transport)

    def verify(self, token: str) -> Principal:
        if not token:
            raise AuthFailed("empty token")
        try:
            response = self._http.get(self._url, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            raise AuthFailed("the analysis API could not be reached") from exc
        if response.status_code != 200:
            raise AuthFailed(f"the analysis API answered {response.status_code}")
        try:
            body = response.json()
            user_id, role = str(body["id"]), str(body["role"])
        except (ValueError, KeyError, TypeError) as exc:
            raise AuthFailed("unexpected response from the analysis API") from exc
        if role not in _KNOWN_ROLES:
            raise AuthFailed("unknown role")
        return Principal(user_id=user_id, role=role)
