"""3-way Risk Committee Debate and Portfolio Manager (TradingAgents Phase)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aidss.agents.base import Agent, AgentRun, AgentRunner
from aidss.agents.context import AnalysisContext
from aidss.llm.router import TaskComplexity
from aidss.prompts.schemas import PortfolioManagerOutput, RiskDebateTurnOutput


class _RiskDebator(Agent):
    """Shared base for Aggressive, Conservative, and Neutral risk analysts."""

    output_model = RiskDebateTurnOutput
    complexity = TaskComplexity.STANDARD

    def __init__(
        self,
        trader_run: AgentRun,
        risk_history: list[dict[str, Any]],
    ) -> None:
        self._trader_proposal = trader_run.output.model_dump(mode="json")
        self._risk_history = risk_history

    def prompt_context(self, context: AnalysisContext) -> dict[str, Any]:
        investor = context.memory.as_prompt_context()
        return {
            "ticker": context.asset.ticker,
            "exchange": context.asset.exchange,
            "timeframe": context.timeframe.value,
            "investment_horizon": investor["investment_horizon"],
            "risk_appetite": investor["risk_appetite"],
            "trader_proposal": self._trader_proposal,
            "portfolio_context": context.portfolio_context
            or {"note": "No portfolio holdings recorded."},
            "risk_history": self._risk_history,
        }


class AggressiveRiskAnalyst(_RiskDebator):
    name = "aggressive_risk_analyst"
    template_name = "risk_aggressive"


class ConservativeRiskAnalyst(_RiskDebator):
    name = "conservative_risk_analyst"
    template_name = "risk_conservative"


class NeutralRiskAnalyst(_RiskDebator):
    name = "neutral_risk_analyst"
    template_name = "risk_neutral"


class PortfolioManager(Agent):
    name = "portfolio_manager"
    template_name = "portfolio_manager"
    output_model = PortfolioManagerOutput
    complexity = TaskComplexity.COMPLEX

    def __init__(
        self,
        trader_run: AgentRun,
        risk_history: list[dict[str, Any]],
        past_context: list[dict[str, Any]],
    ) -> None:
        self._trader_proposal = trader_run.output.model_dump(mode="json")
        self._risk_history = risk_history
        self._past_context = past_context

    def prompt_context(self, context: AnalysisContext) -> dict[str, Any]:
        investor = context.memory.as_prompt_context()
        return {
            "ticker": context.asset.ticker,
            "exchange": context.asset.exchange,
            "timeframe": context.timeframe.value,
            "investment_horizon": investor["investment_horizon"],
            "risk_appetite": investor["risk_appetite"],
            "trader_proposal": self._trader_proposal,
            "risk_history": self._risk_history,
            "portfolio_context": context.portfolio_context
            or {"note": "No portfolio holdings recorded."},
            "past_context": self._past_context
            or [{"note": "No settled past decisions available yet."}],
        }


@dataclass(slots=True)
class RiskDebateResult:
    turns: list[AgentRun] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    manager_run: AgentRun | None = None


def run_risk_debate(
    runner: AgentRunner,
    context: AnalysisContext,
    trader_run: AgentRun,
    past_context: list[dict[str, Any]],
    *,
    max_rounds: int = 1,
) -> RiskDebateResult:
    """Execute 3-way risk debate rounds followed by Portfolio Manager."""
    result = RiskDebateResult()
    speakers: tuple[tuple[str, type[_RiskDebator]], ...] = (
        ("Aggressive Risk Analyst", AggressiveRiskAnalyst),
        ("Conservative Risk Analyst", ConservativeRiskAnalyst),
        ("Neutral Risk Analyst", NeutralRiskAnalyst),
    )

    for round_idx in range(1, max(1, max_rounds) + 1):
        for label, agent_cls in speakers:
            turn_run = runner.run(agent_cls(trader_run, result.history), context)
            turn_out: RiskDebateTurnOutput = turn_run.output  # type: ignore[assignment]
            result.turns.append(turn_run)
            result.history.append(
                {
                    "round": round_idx,
                    "speaker": label,
                    "risk_posture": turn_out.risk_posture,
                    "evaluation": turn_out.evaluation,
                    "risk_arguments": list(turn_out.risk_arguments),
                    "recommended_adjustments": list(turn_out.recommended_adjustments),
                }
            )

    result.manager_run = runner.run(
        PortfolioManager(trader_run, result.history, past_context),
        context,
    )
    return result
