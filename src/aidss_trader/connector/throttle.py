"""Client-side throttle, kept below Indodax's documented limits (FR-T17).

Reaching a limit is a defect, not a retry opportunity: `-1003` from the exchange
means this throttle was set too high or does not cover the call. Time and sleep
are injected so the behaviour is testable without waiting.

Which limits bind (docs/06-INTEGRATIONS/08): the general table says 300 per
minute per IP for the order endpoints (5 per second sustained), the create
section says 20 per second per pair. Both apply; the stricter one binds.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass


class TokenBucket:
    def __init__(
        self,
        rate_per_s: float,
        burst: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate_per_s <= 0 or burst < 1:
            raise ValueError("rate must be positive and burst at least 1")
        self._rate, self._burst = rate_per_s, burst
        self._clock, self._sleep = clock, sleep
        self._tokens = burst
        self._last = clock()

    def acquire(self) -> float:
        """Take one token, sleeping if none is available. Returns seconds waited."""
        waited = 0.0
        while True:
            now = self._clock()
            self._tokens = min(self._burst, self._tokens + (now - self._last) * self._rate)
            self._last = now
            if self._tokens >= 1:
                self._tokens -= 1
                return waited
            need = (1 - self._tokens) / self._rate
            self._sleep(need)
            waited += need


@dataclass(frozen=True, slots=True)
class DocumentedLimits:
    """Indodax's documented limits (per minute unless stated)."""

    public_v2_per_min: int = 300
    legacy_public_per_min: int = 180
    private_general_per_min: int = 300
    create_per_s_per_pair: int = 20
    cancel_per_s: int = 30


class Throttle:
    """One bucket per scope, each a fraction of its documented limit.

    `headroom` is required (no default): how far below the limits to stay is a
    deliberate choice, and the strictest figure is used where two apply.
    """

    def __init__(
        self,
        headroom: float,
        *,
        limits: DocumentedLimits = DocumentedLimits(),  # noqa: B008 (frozen, immutable)
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 0 < headroom <= 1:
            raise ValueError("headroom must be in (0, 1]")
        self._clock, self._sleep = clock, sleep
        self._headroom = headroom
        self._limits = limits
        self._buckets: dict[str, TokenBucket] = {}

    def _bucket(self, scope: str, per_s: float) -> TokenBucket:
        if scope not in self._buckets:
            rate = per_s * self._headroom
            self._buckets[scope] = TokenBucket(
                rate, max(1.0, rate), clock=self._clock, sleep=self._sleep
            )
        return self._buckets[scope]

    def acquire(self, scope: str) -> float:
        lim = self._limits
        if scope == "public_v2":
            return self._bucket(scope, lim.public_v2_per_min / 60).acquire()
        if scope == "public_legacy":
            return self._bucket(scope, lim.legacy_public_per_min / 60).acquire()
        if scope == "private":
            return self._bucket(scope, lim.private_general_per_min / 60).acquire()
        if scope == "cancel":
            waited = self._bucket("cancel", lim.cancel_per_s).acquire()
            return waited + self.acquire("private")
        if scope.startswith("create:"):
            waited = self._bucket(scope, lim.create_per_s_per_pair).acquire()
            return waited + self.acquire("private")
        raise ValueError(f"unknown throttle scope {scope!r}")
