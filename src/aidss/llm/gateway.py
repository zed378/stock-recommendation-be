"""LLM Gateway (Section 12).

Everything provider-specific stops here. Agents send a standard request and
receive a standard response; routing, retry, rate limiting, circuit breaking,
fallback, and cost accounting all happen inside, so no agent contains a
provider name or a retry loop.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from aidss.domain.types import ChatMessage
from aidss.llm.cost import CostTracker, Usage, estimate_cost
from aidss.llm.errors import AllProvidersFailedError, CircuitOpenError
from aidss.llm.resilience import (
    CircuitBreaker,
    Clock,
    RateLimiter,
    RetryPolicy,
    SystemClock,
    call_with_retry,
)
from aidss.llm.router import ModelRouter, ProviderBinding, Sensitivity, TaskComplexity
from aidss.plugins.errors import ProviderUnavailableError


@dataclass(frozen=True, slots=True)
class LLMRequest:
    messages: list[ChatMessage]
    complexity: TaskComplexity = TaskComplexity.STANDARD
    sensitivity: Sensitivity = Sensitivity.PUBLIC
    temperature: float = 0.2
    max_tokens: int | None = None
    #: When True the gateway asks for JSON and never streams, so the Output
    #: Validator sees a complete document (Sections 12.5, 12.6).
    expects_json: bool = False
    #: Attributed in the cost breakdown; also stored on ai_messages.
    agent: str | None = None


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    usage: Usage
    #: Providers that failed before this one succeeded. Empty on a clean first
    #: attempt; non-empty means a fallback was exercised and is worth surfacing.
    fallbacks_used: tuple[str, ...] = ()


class LLMGateway:
    def __init__(
        self,
        router: ModelRouter,
        *,
        retry_policy: RetryPolicy | None = None,
        cost_tracker: CostTracker | None = None,
        clock: Clock | None = None,
        circuit_failure_threshold: int = 3,
        circuit_reset_timeout: float = 30.0,
        rng: random.Random | None = None,
    ) -> None:
        self.router = router
        self.retry_policy = retry_policy or RetryPolicy()
        self.cost_tracker = cost_tracker or CostTracker()
        self._clock = clock or SystemClock()
        self._rng = rng
        self._circuit_config = (circuit_failure_threshold, circuit_reset_timeout)
        self._breakers: dict[str, CircuitBreaker] = {}
        self._limiters: dict[str, RateLimiter] = {}

    # --- per-provider state ---------------------------------------------

    def breaker(self, name: str) -> CircuitBreaker:
        if name not in self._breakers:
            threshold, timeout = self._circuit_config
            self._breakers[name] = CircuitBreaker(
                failure_threshold=threshold, reset_timeout=timeout, clock=self._clock
            )
        return self._breakers[name]

    def limiter(self, binding: ProviderBinding) -> RateLimiter:
        if binding.name not in self._limiters:
            self._limiters[binding.name] = RateLimiter(
                requests_per_minute=binding.requests_per_minute, clock=self._clock
            )
        return self._limiters[binding.name]

    # --- main entry point ------------------------------------------------

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Run the request down the fallback chain until one provider answers."""
        self.cost_tracker.check_budget()

        chain = self.router.chain(request.complexity, request.sensitivity)
        failures: dict[str, str] = {}
        attempted: list[str] = []

        for binding in chain:
            try:
                self.breaker(binding.name).ensure_closed(binding.name)
            except CircuitOpenError as exc:
                # Skipped without a call, which is the whole point of the
                # breaker: a provider known to be down must not add latency.
                failures[binding.name] = str(exc)
                continue

            self.limiter(binding).acquire()

            try:
                completion = call_with_retry(
                    lambda b=binding: b.provider.chat_completion(
                        request.messages,
                        model=b.model,
                        temperature=request.temperature,
                        max_tokens=request.max_tokens,
                        response_format=self._response_format(b, request),
                    ),
                    self.retry_policy,
                    clock=self._clock,
                    rng=self._rng,
                )
            except ProviderUnavailableError as exc:
                self.breaker(binding.name).record_failure()
                failures[binding.name] = str(exc)
                attempted.append(binding.name)
                continue

            self.breaker(binding.name).record_success()

            usage = Usage(
                provider=binding.name,
                model=completion.model,
                prompt_tokens=completion.prompt_tokens,
                completion_tokens=completion.completion_tokens,
                cost_estimate=estimate_cost(
                    completion.prompt_tokens,
                    completion.completion_tokens,
                    binding.input_cost_per_1k,
                    binding.output_cost_per_1k,
                ),
            )
            self.cost_tracker.record(usage, agent=request.agent)
            return LLMResponse(
                content=completion.content,
                usage=usage,
                fallbacks_used=tuple(attempted),
            )

        raise AllProvidersFailedError(failures)

    @staticmethod
    def _response_format(binding: ProviderBinding, request: LLMRequest) -> dict | None:
        """Ask for JSON mode only where the provider actually supports it.

        Where it does not, the prompt still demands JSON and the Output
        Validator still checks the result - the plan is explicit that provider
        support alone is not to be relied on (Section 12.5).
        """
        if not request.expects_json:
            return None
        if not binding.provider.supports_structured_output():
            return None
        return {"type": "json_object"}


# ---------------------------------------------------------------------------
# Construction from configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BindingSpec:
    """A binding as it appears in configuration, before the adapter is built."""

    name: str
    adapter: str
    model: str
    handles: frozenset[TaskComplexity]
    priority: int = 100
    self_hosted: bool = False
    input_cost_per_1k: str = "0"
    output_cost_per_1k: str = "0"
    requests_per_minute: int = 60


#: Default single-provider setup. Real deployments override this from the
#: `ai_providers` table so routing can change without a redeploy (Section 12.10).
DEFAULT_BINDINGS: tuple[BindingSpec, ...] = (
    BindingSpec(
        name="primary",
        adapter="openai_compatible",
        model="",  # empty means "whatever the adapter is configured with"
        handles=frozenset(TaskComplexity),
        priority=10,
    ),
)


@dataclass
class GatewayBuilder:
    """Assembles a gateway from adapters resolved through the plugin registry."""

    bindings: list[ProviderBinding] = field(default_factory=list)

    def add(self, binding: ProviderBinding) -> GatewayBuilder:
        self.bindings.append(binding)
        return self

    def build(self, **kwargs: object) -> LLMGateway:
        return LLMGateway(ModelRouter(self.bindings), **kwargs)  # type: ignore[arg-type]
