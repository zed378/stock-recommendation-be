"""Model Router and provider bindings (Section 16.10).

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
    #: infrastructure (Section 16.10, 13).
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
            raise NoEligibleProviderError(self._why_nothing_matched(complexity, sensitivity))
        # Stable sort, so bindings sharing a priority keep configuration order
        # and the chain is reproducible across runs.
        return sorted(eligible, key=lambda b: b.priority)

    def _why_nothing_matched(
        self, complexity: TaskComplexity, sensitivity: Sensitivity
    ) -> str:
        """Name the actual cause, because the two look identical from outside.

        "No provider configured" was true and useless: a provider *was*
        configured, and it was excluded on privacy grounds by a rule the reader
        has no reason to know exists. Someone hitting this had to read the
        router to find out that a hostname heuristic had decided their own
        server belonged to a third party.
        """
        if not self.bindings:
            return "No AI provider is configured at all."

        handles_complexity = [b for b in self.bindings if complexity in b.handles]
        if not handles_complexity:
            roles = ", ".join(
                f"{b.name} (handles {sorted(c.value for c in b.handles)})"
                for b in self.bindings
            )
            return (
                f"No provider handles complexity={complexity.value!r}. Configured: {roles}."
            )

        # Providers can serve the complexity, so privacy is what excluded them.
        names = ", ".join(b.name for b in handles_complexity)
        return (
            f"This request handles personal financial data (sensitivity="
            f"{sensitivity.value!r}) and no configured provider is marked as "
            f"self-hosted, so it was refused rather than sent to a third party. "
            f"Configured: {names}. If the endpoint runs on infrastructure you "
            f"control, say so with AIDSS_AI_SELF_HOSTED=true - the platform "
            f"cannot tell that from a URL."
        )

    def get(self, name: str) -> ProviderBinding | None:
        return next((b for b in self.bindings if b.name == name), None)
