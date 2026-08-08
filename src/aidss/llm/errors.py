"""Exceptions raised by the LLM Gateway (Section 16)."""

from __future__ import annotations


class GatewayError(Exception):
    """Base class for every gateway error."""


class NoEligibleProviderError(GatewayError):
    """Routing produced an empty chain.

    Usually a configuration problem rather than an outage: no provider is
    marked as able to serve this task's complexity, or a privacy-sensitive
    request found no self-hosted provider (Section 16.10).
    """


class AllProvidersFailedError(GatewayError):
    """Every provider in the fallback chain failed.

    Carries the per-provider reasons so the caller can tell an outage apart
    from a misconfiguration.
    """

    def __init__(self, failures: dict[str, str]) -> None:
        detail = "; ".join(f"{name}: {reason}" for name, reason in failures.items())
        super().__init__(f"All providers in the fallback chain failed - {detail}")
        self.failures = failures


class CircuitOpenError(GatewayError):
    """The circuit breaker is open for this provider, so no call was attempted."""

    def __init__(self, provider: str, retry_after: float) -> None:
        super().__init__(
            f"Circuit breaker open for {provider!r}; retry in {retry_after:.1f}s"
        )
        self.provider = provider
        self.retry_after = retry_after


class BudgetExceededError(GatewayError):
    """The configured spend ceiling has been reached (Section 16.9).

    Raised before the call is made: the point of a budget is to stop spending,
    not to report it afterwards.
    """

    def __init__(self, spent: float, ceiling: float) -> None:
        super().__init__(
            f"Estimated spend {spent:.4f} has reached the configured ceiling {ceiling:.4f}"
        )
        self.spent = spent
        self.ceiling = ceiling
