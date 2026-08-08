"""Portfolio and Risk Analyzer agents (Phase 6, Section 14.2).

Both are marked ``SENSITIVE``. Portfolio positions and their valuations are
personal financial data, and Section 16.10 requires that such work route to
self-hosted inference when the investor has chosen high-privacy mode. Setting
it on the agent rather than at the call site means it cannot be forgotten by
whoever wires the next endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aidss.agents.base import Agent
from aidss.agents.memory import InvestorMemory
from aidss.llm.router import Sensitivity, TaskComplexity
from aidss.portfolio.metrics import PortfolioMetrics, Position
from aidss.portfolio.risk import RiskMetrics
from aidss.prompts.schemas import PortfolioOutput, RiskOutput


@dataclass(slots=True)
class PortfolioContext:
    """Everything the portfolio agents reason over, computed in advance."""

    portfolio_name: str
    base_currency: str
    memory: InvestorMemory
    positions: list[Position] = field(default_factory=list)
    metrics: PortfolioMetrics | None = None
    risk: RiskMetrics | None = None
    correlation: dict[str, Any] = field(default_factory=dict)

    @property
    def has_positions(self) -> bool:
        return bool(self.positions)

    def holdings_payload(self) -> list[dict[str, Any]]:
        """Positions as the model sees them.

        Weights are included because a list of quantities alone does not convey
        shape: 1,000 shares of one name and 1,000 of another are equal in count
        and can be nothing alike in exposure.
        """
        weights = self.metrics.weights if self.metrics else {}
        return [
            {
                "ticker": p.ticker,
                "sector": p.sector or "unclassified",
                "quantity": str(p.quantity),
                "average_price": str(p.average_price),
                "last_price": None if p.last_price is None else str(p.last_price),
                "market_value": str(p.market_value),
                "weight": round(weights.get(p.ticker, 0.0), 4),
                "valued_at_cost": p.last_price is None,
            }
            for p in self.positions
        ]

    def snapshot(self) -> dict[str, Any]:
        return {
            "portfolio": self.portfolio_name,
            "base_currency": self.base_currency,
            "holdings": self.holdings_payload(),
            "metrics": self.metrics.as_dict() if self.metrics else {},
            "risk": self.risk.as_dict() if self.risk else {},
            "correlation": self.correlation,
            "investor": self.memory.as_prompt_context(),
        }


class PortfolioAnalyzer(Agent):
    """Explains what the computed portfolio shape means for this investor."""

    name = "portfolio_analyzer"
    template_name = "portfolio_analysis"
    output_model = PortfolioOutput
    complexity = TaskComplexity.STANDARD
    sensitivity = Sensitivity.SENSITIVE

    def is_applicable(self, context: PortfolioContext) -> bool:
        return context.has_positions

    def skip_reason(self, context: PortfolioContext) -> str:
        return "the portfolio has no holdings to analyse"

    def prompt_context(self, context: PortfolioContext) -> dict[str, Any]:
        metrics = context.metrics
        return {
            "holdings": context.holdings_payload(),
            "concentration": {
                "position_count": metrics.position_count if metrics else 0,
                "concentration_hhi": round(metrics.concentration_hhi, 4) if metrics else None,
                "sector_concentration_hhi": (
                    round(metrics.sector_concentration_hhi, 4) if metrics else None
                ),
                "diversification_score": (
                    round(metrics.diversification_score, 1) if metrics else None
                ),
                "reading": metrics.concentration_reading if metrics else "unknown",
                "sector_weights": (
                    {k: round(v, 4) for k, v in metrics.sector_weights.items()} if metrics else {}
                ),
                "largest_position": metrics.largest_position if metrics else None,
                "positions_valued_at_cost": (
                    metrics.position_count - metrics.priced_positions if metrics else 0
                ),
                "correlation": context.correlation,
            },
        }


class RiskAnalyzer(Agent):
    """Interprets historical risk figures, including what they cannot say."""

    name = "risk_analyzer"
    template_name = "risk_evaluation"
    output_model = RiskOutput
    complexity = TaskComplexity.STANDARD
    sensitivity = Sensitivity.SENSITIVE

    def is_applicable(self, context: PortfolioContext) -> bool:
        # Without observations there is nothing to interpret, and a risk
        # narrative built on no data is worse than none at all.
        return context.risk is not None and context.risk.observations > 0

    def skip_reason(self, context: PortfolioContext) -> str:
        if not context.has_positions:
            return "the portfolio has no holdings"
        return "no holding has enough stored price history to measure risk from"

    def prompt_context(self, context: PortfolioContext) -> dict[str, Any]:
        return {
            "scope": f"portfolio {context.portfolio_name!r} ({context.base_currency})",
            "metrics": {
                **(context.risk.as_dict() if context.risk else {}),
                "concentration_hhi": (
                    round(context.metrics.concentration_hhi, 4) if context.metrics else None
                ),
                "largest_position": (
                    context.metrics.largest_position if context.metrics else None
                ),
                "correlation": context.correlation,
            },
        }
