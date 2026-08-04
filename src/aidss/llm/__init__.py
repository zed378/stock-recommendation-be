"""LLM Gateway (Phase 4, Section 12).

The single place where provider differences are absorbed: routing, retry,
rate limiting, circuit breaking, fallback, and cost accounting.
"""

from aidss.llm.cost import CostTracker, Usage, estimate_cost
from aidss.llm.errors import (
    AllProvidersFailedError,
    BudgetExceededError,
    CircuitOpenError,
    GatewayError,
    NoEligibleProviderError,
)
from aidss.llm.gateway import GatewayBuilder, LLMGateway, LLMRequest, LLMResponse
from aidss.llm.provisioning import build_bindings, build_gateway
from aidss.llm.resilience import (
    CircuitBreaker,
    CircuitState,
    Clock,
    RateLimiter,
    RetryPolicy,
    SystemClock,
)
from aidss.llm.router import ModelRouter, ProviderBinding, Sensitivity, TaskComplexity

__all__ = [
    "AllProvidersFailedError",
    "BudgetExceededError",
    "CircuitBreaker",
    "CircuitOpenError",
    "CircuitState",
    "Clock",
    "CostTracker",
    "GatewayBuilder",
    "GatewayError",
    "LLMGateway",
    "LLMRequest",
    "LLMResponse",
    "ModelRouter",
    "NoEligibleProviderError",
    "ProviderBinding",
    "RateLimiter",
    "RetryPolicy",
    "Sensitivity",
    "SystemClock",
    "TaskComplexity",
    "Usage",
    "build_bindings",
    "build_gateway",
    "estimate_cost",
]
