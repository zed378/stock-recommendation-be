"""Trader Agent - translates Research Manager's plan into a stance proposal."""

from __future__ import annotations

from typing import Any

from aidss.agents.base import Agent, AgentRun
from aidss.agents.context import AnalysisContext
from aidss.agents.trading_agents.researchers import _serialize_analyses
from aidss.llm.router import TaskComplexity
from aidss.prompts.schemas import TraderProposalOutput


class TraderAgent(Agent):
    name = "trader_agent"
    template_name = "trader_proposal"
    output_model = TraderProposalOutput
    complexity = TaskComplexity.STANDARD

    def __init__(
        self,
        analyzer_runs: list[AgentRun],
        research_manager_run: AgentRun,
    ) -> None:
        self._analyses = _serialize_analyses(analyzer_runs)
        self._plan = research_manager_run.output.model_dump(mode="json")

    def prompt_context(self, context: AnalysisContext) -> dict[str, Any]:
        investor = context.memory.as_prompt_context()
        return {
            "ticker": context.asset.ticker,
            "exchange": context.asset.exchange,
            "timeframe": context.timeframe.value,
            "investment_horizon": investor["investment_horizon"],
            "risk_appetite": investor["risk_appetite"],
            "investment_plan": self._plan,
            "analyses": self._analyses,
        }
