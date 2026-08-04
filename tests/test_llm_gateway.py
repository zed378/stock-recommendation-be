"""LLM Gateway tests (Section 12).

Time is faked throughout. A test that genuinely waits out a 30-second circuit
reset is a test someone eventually deletes, and the behaviour it covered goes
with it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from aidss.domain.types import ChatCompletion, ChatMessage
from aidss.llm.cost import CostTracker, Usage, estimate_cost
from aidss.llm.errors import (
    AllProvidersFailedError,
    BudgetExceededError,
    NoEligibleProviderError,
)
from aidss.llm.gateway import LLMGateway, LLMRequest
from aidss.llm.resilience import (
    CircuitBreaker,
    CircuitState,
    RateLimiter,
    RetryPolicy,
    call_with_retry,
)
from aidss.llm.router import ModelRouter, ProviderBinding, Sensitivity, TaskComplexity
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.interfaces import AIProvider


@dataclass
class FakeClock:
    """Virtual time: sleeping advances a counter instead of blocking."""

    now: float = 0.0
    slept: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class StubProvider(AIProvider):
    """An AIProvider whose behaviour each test scripts explicitly."""

    name = "stub"

    def __init__(
        self,
        *,
        content: str = '{"ok": true}',
        fail_times: int = 0,
        retryable: bool = True,
        prompt_tokens: int = 100,
        completion_tokens: int = 50,
        structured: bool = False,
    ) -> None:
        self.content = content
        self.fail_times = fail_times
        self.retryable = retryable
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.structured = structured
        self.call_count = 0
        self.last_response_format: dict | None = None

    def chat_completion(self, messages, **kwargs) -> ChatCompletion:
        self.call_count += 1
        self.last_response_format = kwargs.get("response_format")
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ProviderUnavailableError(self.name, "scripted", retryable=self.retryable)
        return ChatCompletion(
            content=self.content,
            model=kwargs.get("model") or "stub-model",
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
        )

    def embed(self, texts, **kwargs):
        return [[0.0] * 4 for _ in texts]

    def supports_structured_output(self) -> bool:
        return self.structured


def binding(name: str, provider: AIProvider, **kwargs) -> ProviderBinding:
    defaults = {
        "handles": frozenset(TaskComplexity),
        "priority": 100,
        "model": "m",
    }
    return ProviderBinding(name=name, provider=provider, **{**defaults, **kwargs})


def request(**kwargs) -> LLMRequest:
    return LLMRequest(messages=[ChatMessage(role="user", content="hello")], **kwargs)


# --- Retry -----------------------------------------------------------------


def test_transient_failure_is_retried_then_succeeds() -> None:
    provider = StubProvider(fail_times=2)
    clock = FakeClock()
    result = call_with_retry(
        lambda: provider.chat_completion([]), RetryPolicy(max_attempts=3), clock=clock
    )
    assert result.content == '{"ok": true}'
    assert provider.call_count == 3
    assert len(clock.slept) == 2


def test_non_retryable_failure_is_not_retried() -> None:
    """Retrying a 4xx wastes time and delays the fallback that might work."""
    provider = StubProvider(fail_times=5, retryable=False)
    with pytest.raises(ProviderUnavailableError):
        call_with_retry(
            lambda: provider.chat_completion([]), RetryPolicy(max_attempts=3), clock=FakeClock()
        )
    assert provider.call_count == 1


def test_retry_gives_up_after_max_attempts() -> None:
    provider = StubProvider(fail_times=99)
    with pytest.raises(ProviderUnavailableError):
        call_with_retry(
            lambda: provider.chat_completion([]), RetryPolicy(max_attempts=3), clock=FakeClock()
        )
    assert provider.call_count == 3


def test_backoff_grows_exponentially_and_is_capped() -> None:
    policy = RetryPolicy(base_delay=1.0, max_delay=4.0, jitter=0.0)
    assert [policy.delay_for(n) for n in (1, 2, 3, 4, 5)] == [1.0, 2.0, 4.0, 4.0, 4.0]


def test_jitter_keeps_delay_near_the_nominal_value() -> None:
    policy = RetryPolicy(base_delay=2.0, jitter=0.1)
    rng = random.Random(7)
    for attempt in (1, 2, 3):
        nominal = min(2.0 * 2 ** (attempt - 1), policy.max_delay)
        delay = policy.delay_for(attempt, rng)
        assert nominal * 0.9 <= delay <= nominal * 1.1


# --- Rate limiting ---------------------------------------------------------


def test_rate_limiter_allows_up_to_the_limit_without_waiting() -> None:
    clock = FakeClock()
    limiter = RateLimiter(requests_per_minute=3, clock=clock)
    assert [limiter.acquire() for _ in range(3)] == [0.0, 0.0, 0.0]


def test_rate_limiter_blocks_once_the_window_is_full() -> None:
    clock = FakeClock()
    limiter = RateLimiter(requests_per_minute=2, clock=clock)
    limiter.acquire()
    limiter.acquire()
    waited = limiter.acquire()
    assert waited == pytest.approx(60.0)


def test_rate_limiter_window_slides() -> None:
    clock = FakeClock()
    limiter = RateLimiter(requests_per_minute=2, clock=clock)
    limiter.acquire()
    limiter.acquire()
    clock.now += 61
    assert limiter.acquire() == 0.0


# --- Circuit breaker -------------------------------------------------------


def test_circuit_opens_after_the_failure_threshold() -> None:
    breaker = CircuitBreaker(failure_threshold=3, clock=FakeClock())
    for _ in range(2):
        breaker.record_failure()
    assert breaker.state is CircuitState.CLOSED
    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN


def test_success_resets_the_failure_count() -> None:
    breaker = CircuitBreaker(failure_threshold=3, clock=FakeClock())
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    assert breaker.state is CircuitState.CLOSED


def test_circuit_half_opens_after_the_reset_timeout() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=30.0, clock=clock)
    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN
    clock.now += 30.0
    assert breaker.state is CircuitState.HALF_OPEN


def test_a_failed_trial_call_reopens_the_circuit_immediately() -> None:
    """One success is required to trust a provider again, not one attempt."""
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=3, reset_timeout=10.0, clock=clock)
    for _ in range(3):
        breaker.record_failure()
    clock.now += 10.0
    assert breaker.state is CircuitState.HALF_OPEN
    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN


# --- Routing ---------------------------------------------------------------


def test_chain_is_ordered_by_priority() -> None:
    router = ModelRouter(
        [
            binding("c", StubProvider(), priority=30),
            binding("a", StubProvider(), priority=10),
            binding("b", StubProvider(), priority=20),
        ]
    )
    assert [b.name for b in router.chain(TaskComplexity.STANDARD)] == ["a", "b", "c"]


def test_a_provider_that_cannot_serve_the_complexity_is_excluded() -> None:
    router = ModelRouter(
        [
            binding("cheap", StubProvider(), handles=frozenset({TaskComplexity.LIGHT})),
            binding("strong", StubProvider(), handles=frozenset({TaskComplexity.COMPLEX})),
        ]
    )
    assert [b.name for b in router.chain(TaskComplexity.COMPLEX)] == ["strong"]


def test_sensitive_work_only_routes_to_self_hosted_providers() -> None:
    """Portfolio data must not leave our infrastructure in high-privacy mode."""
    router = ModelRouter(
        [
            binding("cloud", StubProvider(), priority=1, self_hosted=False),
            binding("local", StubProvider(), priority=99, self_hosted=True),
        ]
    )
    public = [b.name for b in router.chain(TaskComplexity.STANDARD, Sensitivity.PUBLIC)]
    sensitive = [b.name for b in router.chain(TaskComplexity.STANDARD, Sensitivity.SENSITIVE)]
    assert public == ["cloud", "local"]
    # Priority does not override the privacy constraint.
    assert sensitive == ["local"]


def test_no_eligible_provider_is_a_clear_error() -> None:
    router = ModelRouter([binding("cloud", StubProvider(), self_hosted=False)])
    with pytest.raises(NoEligibleProviderError, match="sensitivity"):
        router.chain(TaskComplexity.STANDARD, Sensitivity.SENSITIVE)


# --- Gateway end to end ----------------------------------------------------


def test_gateway_returns_the_first_healthy_provider() -> None:
    primary = StubProvider(content='{"a": 1}')
    gateway = LLMGateway(ModelRouter([binding("primary", primary, priority=1)]), clock=FakeClock())
    response = gateway.complete(request())
    assert response.content == '{"a": 1}'
    assert response.fallbacks_used == ()


def test_gateway_falls_back_when_the_primary_fails() -> None:
    primary = StubProvider(fail_times=99)
    secondary = StubProvider(content='{"from": "secondary"}')
    gateway = LLMGateway(
        ModelRouter(
            [
                binding("primary", primary, priority=1),
                binding("secondary", secondary, priority=2),
            ]
        ),
        retry_policy=RetryPolicy(max_attempts=2),
        clock=FakeClock(),
    )
    response = gateway.complete(request())
    assert response.content == '{"from": "secondary"}'
    assert response.fallbacks_used == ("primary",)


def test_gateway_reports_every_failure_when_the_whole_chain_is_down() -> None:
    gateway = LLMGateway(
        ModelRouter(
            [
                binding("a", StubProvider(fail_times=99), priority=1),
                binding("b", StubProvider(fail_times=99), priority=2),
            ]
        ),
        retry_policy=RetryPolicy(max_attempts=1),
        clock=FakeClock(),
    )
    with pytest.raises(AllProvidersFailedError) as excinfo:
        gateway.complete(request())
    assert set(excinfo.value.failures) == {"a", "b"}


def test_an_open_circuit_skips_the_provider_without_calling_it() -> None:
    broken = StubProvider(fail_times=99)
    healthy = StubProvider(content='{"ok": 1}')
    clock = FakeClock()
    gateway = LLMGateway(
        ModelRouter(
            [binding("broken", broken, priority=1), binding("healthy", healthy, priority=2)]
        ),
        retry_policy=RetryPolicy(max_attempts=1),
        clock=clock,
        circuit_failure_threshold=2,
    )

    gateway.complete(request())
    gateway.complete(request())
    calls_before = broken.call_count

    gateway.complete(request())
    # The whole point: a provider known to be down adds no latency at all.
    assert broken.call_count == calls_before
    assert healthy.call_count == 3


def test_cost_is_estimated_from_the_configured_price_table() -> None:
    provider = StubProvider(prompt_tokens=1000, completion_tokens=500)
    gateway = LLMGateway(
        ModelRouter(
            [
                binding(
                    "priced",
                    provider,
                    input_cost_per_1k=Decimal("0.01"),
                    output_cost_per_1k=Decimal("0.03"),
                )
            ]
        ),
        clock=FakeClock(),
    )
    response = gateway.complete(request())
    # 1000/1000 * 0.01 + 500/1000 * 0.03
    assert response.usage.cost_estimate == Decimal("0.025000")


def test_cost_is_attributed_per_agent() -> None:
    gateway = LLMGateway(
        ModelRouter(
            [binding("p", StubProvider(prompt_tokens=1000, completion_tokens=0),
                     input_cost_per_1k=Decimal("0.10"))]
        ),
        clock=FakeClock(),
    )
    gateway.complete(request(agent="technical_analyzer"))
    gateway.complete(request(agent="news_analyzer"))
    breakdown = gateway.cost_tracker.breakdown()
    assert set(breakdown["by_agent"]) == {"technical_analyzer", "news_analyzer"}


def test_budget_ceiling_stops_further_calls() -> None:
    """A budget that only reports overspending is a report, not a budget."""
    tracker = CostTracker(ceiling=Decimal("0.05"))
    gateway = LLMGateway(
        ModelRouter(
            [binding("p", StubProvider(prompt_tokens=1000, completion_tokens=0),
                     input_cost_per_1k=Decimal("0.10"))]
        ),
        cost_tracker=tracker,
        clock=FakeClock(),
    )
    gateway.complete(request())
    with pytest.raises(BudgetExceededError):
        gateway.complete(request())


def test_json_mode_is_only_requested_where_the_provider_supports_it() -> None:
    """Section 12.5: provider support is uneven, so it is asked for, not assumed."""
    capable = StubProvider(structured=True)
    incapable = StubProvider(structured=False)

    LLMGateway(ModelRouter([binding("a", capable)]), clock=FakeClock()).complete(
        request(expects_json=True)
    )
    LLMGateway(ModelRouter([binding("b", incapable)]), clock=FakeClock()).complete(
        request(expects_json=True)
    )

    assert capable.last_response_format == {"type": "json_object"}
    assert incapable.last_response_format is None


def test_estimate_cost_is_zero_when_no_pricing_is_configured() -> None:
    assert estimate_cost(5000, 5000, Decimal("0"), Decimal("0")) == Decimal("0.000000")


def test_usage_totals_tokens() -> None:
    usage = Usage("p", "m", prompt_tokens=10, completion_tokens=7, cost_estimate=Decimal("0"))
    assert usage.total_tokens == 17
