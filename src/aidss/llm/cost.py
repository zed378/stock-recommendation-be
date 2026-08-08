"""Token usage and cost estimation (Section 16.9).

Costs are estimates derived from the configured price table, not billed
amounts. They are still worth recording: the plan's risk register lists AI
spend growing with scale, and a per-agent, per-user breakdown is what turns
that from a surprise on an invoice into something observable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from aidss.llm.errors import BudgetExceededError

_COST_QUANT = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class Usage:
    """Token counts and the estimated cost of a single completed call."""

    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_estimate: Decimal

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    input_cost_per_1k: Decimal,
    output_cost_per_1k: Decimal,
) -> Decimal:
    cost = (
        Decimal(prompt_tokens) / 1000 * input_cost_per_1k
        + Decimal(completion_tokens) / 1000 * output_cost_per_1k
    )
    return cost.quantize(_COST_QUANT, rounding=ROUND_HALF_UP)


@dataclass
class CostTracker:
    """Running spend for one process, with an optional hard ceiling.

    The ceiling is checked *before* a call rather than after. A budget that
    only reports overspending is a report, not a budget.
    """

    ceiling: Decimal | None = None
    _spent: Decimal = field(default=Decimal("0"), init=False)
    _by_agent: dict[str, Decimal] = field(default_factory=dict, init=False)
    _by_provider: dict[str, Decimal] = field(default_factory=dict, init=False)

    @property
    def spent(self) -> Decimal:
        return self._spent

    def check_budget(self) -> None:
        if self.ceiling is not None and self._spent >= self.ceiling:
            raise BudgetExceededError(float(self._spent), float(self.ceiling))

    def record(self, usage: Usage, *, agent: str | None = None) -> None:
        self._spent += usage.cost_estimate
        self._by_provider[usage.provider] = (
            self._by_provider.get(usage.provider, Decimal("0")) + usage.cost_estimate
        )
        if agent:
            self._by_agent[agent] = self._by_agent.get(agent, Decimal("0")) + usage.cost_estimate

    def breakdown(self) -> dict[str, dict[str, str]]:
        """Spend per agent and per provider, for the admin dashboard."""
        return {
            "by_agent": {k: str(v) for k, v in sorted(self._by_agent.items())},
            "by_provider": {k: str(v) for k, v in sorted(self._by_provider.items())},
        }
