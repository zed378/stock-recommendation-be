"""Retry, rate limiting, and circuit breaking (Section 12.8).

Time is injected through a ``Clock`` rather than read from the module. Without
that, testing a backoff schedule means actually waiting for it, and testing a
circuit breaker's reset window means sleeping for the window - which produces
slow tests that people then delete.

Scope note: this state lives in process memory, which is correct for a single
worker. Running several replicas means a shared store (Redis) so limits and
breaker state are global rather than per-process; that belongs with Phase 9.
"""

from __future__ import annotations

import random
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, TypeVar

from aidss.llm.errors import CircuitOpenError
from aidss.plugins.errors import ProviderUnavailableError

T = TypeVar("T")


class Clock(Protocol):
    """The two time operations this module needs."""

    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Exponential backoff for transient failures only.

    A non-retryable failure (a 4xx, a malformed response) is re-raised
    immediately. Retrying it would waste the caller's time and, worse, delay
    the fallback to a provider that might actually work.
    """

    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    #: Jitter fraction, to stop simultaneous failures from retrying in lockstep.
    jitter: float = 0.1

    def delay_for(self, attempt: int, rng: random.Random | None = None) -> float:
        """Backoff before ``attempt`` (1-based), capped and jittered."""
        raw = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        if self.jitter <= 0:
            return raw
        rng = rng or random
        return raw * (1.0 + rng.uniform(-self.jitter, self.jitter))


def call_with_retry(
    operation: Callable[[], T],
    policy: RetryPolicy,
    *,
    clock: Clock | None = None,
    rng: random.Random | None = None,
) -> T:
    clock = clock or SystemClock()
    last: ProviderUnavailableError | None = None

    for attempt in range(1, policy.max_attempts + 1):
        try:
            return operation()
        except ProviderUnavailableError as exc:
            if not exc.retryable:
                raise
            last = exc
            if attempt == policy.max_attempts:
                break
            clock.sleep(policy.delay_for(attempt, rng))

    assert last is not None
    raise last


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


@dataclass
class RateLimiter:
    """Sliding-window limiter, one window per provider.

    Respecting a provider's published limit locally is cheaper than being
    throttled by it: a 429 costs a round trip and, under a circuit breaker,
    can take a healthy provider out of rotation (Section 9 analogue for AI
    providers).
    """

    requests_per_minute: int
    window_seconds: float = 60.0
    clock: Clock = field(default_factory=SystemClock)
    _hits: deque[float] = field(default_factory=deque, init=False)

    def _prune(self, now: float) -> None:
        while self._hits and now - self._hits[0] >= self.window_seconds:
            self._hits.popleft()

    def time_until_free(self) -> float:
        now = self.clock.monotonic()
        self._prune(now)
        if len(self._hits) < self.requests_per_minute:
            return 0.0
        return self.window_seconds - (now - self._hits[0])

    def acquire(self) -> float:
        """Block until a slot is free. Returns how long it waited."""
        waited = 0.0
        while True:
            delay = self.time_until_free()
            if delay <= 0:
                self._hits.append(self.clock.monotonic())
                return waited
            self.clock.sleep(delay)
            waited += delay


# ---------------------------------------------------------------------------
# Circuit breaking
# ---------------------------------------------------------------------------


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Stops hammering a provider that is already down (Section 12.8).

    After ``failure_threshold`` consecutive failures the circuit opens and
    calls are refused outright, so the fallback chain moves on immediately
    instead of waiting out a timeout per request. After ``reset_timeout`` one
    trial call is allowed; success closes the circuit, failure reopens it.
    """

    failure_threshold: int = 3
    reset_timeout: float = 30.0
    clock: Clock = field(default_factory=SystemClock)

    _failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)

    @property
    def state(self) -> CircuitState:
        if self._state is CircuitState.OPEN and self._elapsed_since_open() >= self.reset_timeout:
            self._state = CircuitState.HALF_OPEN
        return self._state

    def _elapsed_since_open(self) -> float:
        if self._opened_at is None:
            return 0.0
        return self.clock.monotonic() - self._opened_at

    def ensure_closed(self, provider: str) -> None:
        """Raise ``CircuitOpenError`` when the provider is being skipped."""
        if self.state is CircuitState.OPEN:
            raise CircuitOpenError(provider, self.reset_timeout - self._elapsed_since_open())

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        # A failed trial call in half-open state reopens immediately: one
        # success is required to trust the provider again, not one attempt.
        if self._state is CircuitState.HALF_OPEN:
            self._opened_at = self.clock.monotonic()
            self._state = CircuitState.OPEN
            return

        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = self.clock.monotonic()
            self._state = CircuitState.OPEN
