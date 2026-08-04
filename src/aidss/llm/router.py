"""Model Router and provider bindings (Section 12.10).

Routing is by task complexity and by privacy. Sending a light extraction job to
an expensive reasoning model wastes money; sending portfolio data to a hosted
model when the user asked for high-privacy mode breaks a promise. Both are
policy decisions, so both live in configuration rather than in agent code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from aidss.llm.errors import NoEligibleProviderError
from aidss.plugins.interfaces import AIProvider


class TaskComplexity(StrEnum):
    """What kind of thinking a call needs, not which model it should use."""

    #: Extraction, classification, short summaries - cheap and fast is enough.
    LIGHT = "light"
    #: Ordinary interpretation of prepared figures.
    STANDARD = "standard"
    #: Multi-source synthesis and research - quality matters more than cost.
    COMPLEX = "complex"


class Sensitivity(StrEnum):
    PUBLIC = "public"
    #: Portfolio positions, journal entries - personal financial data. When the
    #: user has chosen high-privacy mode these must not leave self-hosted
    #: infrastructure (Sections 12.10, 13).
    SENSITIVE = "sensitive"


@dataclass(frozen=True, slots=True)
class ProviderBinding:
    """One usable (provider, model) pair with its routing policy and pricing."""

    name: str
    provider: AIProvider
    model: str
    #: Which complexities this binding is allowed to serve.
    handles: frozenset[TaskComplexity]
    #: Lower runs first in the fallback chain.
    priority: int = 100
    #: True for Ollama/vLLM/LM Studio and other infrastructure we control.
    self_hosted: bool = False
    input_cost_per_1k: Decimal = Decimal("0")
    output_cost_per_1k: Decimal = Decimal("0")
    requests_per_minute: int = 60

    def can_serve(self, complexity: TaskComplexity, sensitivity: Sensitivity) -> bool:
        if complexity not in self.handles:
            return False
        if sensitivity is Sensitivity.SENSITIVE and not self.self_hosted:
            return False
        return True


@dataclass
class ModelRouter:
    """Builds the ordered fallback chain for a request."""

    bindings: list[ProviderBinding] = field(default_factory=list)

    def chain(
        self,
        complexity: TaskComplexity,
        sensitivity: Sensitivity = Sensitivity.PUBLIC,
    ) -> list[ProviderBinding]:
        eligible = [b for b in self.bindings if b.can_serve(complexity, sensitivity)]
        if not eligible:
            raise NoEligibleProviderError(
                f"No provider is configured for complexity={complexity.value!r} "
                f"and sensitivity={sensitivity.value!r}. "
                f"Configured: {[b.name for b in self.bindings]}"
            )
        # Stable sort, so bindings sharing a priority keep configuration order
        # and the chain is reproducible across runs.
        return sorted(eligible, key=lambda b: b.priority)

    def get(self, name: str) -> ProviderBinding | None:
        return next((b for b in self.bindings if b.name == name), None)
