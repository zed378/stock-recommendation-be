"""Bull/Bear Researcher Debate and Research Manager (TradingAgents Phase)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aidss.agents.base import Agent, AgentRun, AgentRunner
from aidss.agents.context import AnalysisContext
from aidss.llm.router import TaskComplexity
from aidss.prompts.schemas import DebateTurnOutput, ResearchManagerOutput


def _serialize_analyses(runs: list[AgentRun]) -> list[dict[str, Any]]:
    return [
        {
            "agent": run.agent,
            "confidence": run.output.confidence,
            "data_sufficiency": run.output.data_sufficiency.value,
            **run.output.model_dump(mode="json", exclude={"confidence", "data_sufficiency"}),
        }
        for run in runs
    ]


class _DebateResearcher(Agent):
    """Shared base for Bull and Bear researchers."""

    output_model = DebateTurnOutput
    complexity = TaskComplexity.STANDARD

    def __init__(
        self,
        analyzer_runs: list[AgentRun],
        debate_history: list[dict[str, Any]],
        opponent_argument: str,
    ) -> None:
        self._analyses = _serialize_analyses(analyzer_runs)
        self._debate_history = debate_history
        self._opponent_argument = opponent_argument

    def prompt_context(self, context: AnalysisContext) -> dict[str, Any]:
        return {
            "ticker": context.asset.ticker,
            "exchange": context.asset.exchange,
            "timeframe": context.timeframe.value,
            "analyses": self._analyses,
            "debate_history": self._debate_history,
            "opponent_argument": self._opponent_argument or "None yet (opening statement).",
        }


class BullResearcher(_DebateResearcher):
    name = "bull_researcher"
    template_name = "bull_researcher"


class BearResearcher(_DebateResearcher):
    name = "bear_researcher"
    template_name = "bear_researcher"


class ResearchManager(Agent):
    name = "research_manager"
    template_name = "research_manager"
    output_model = ResearchManagerOutput
    complexity = TaskComplexity.COMPLEX

    def __init__(
        self,
        analyzer_runs: list[AgentRun],
        debate_history: list[dict[str, Any]],
    ) -> None:
        self._analyses = _serialize_analyses(analyzer_runs)
        self._debate_history = debate_history

    def prompt_context(self, context: AnalysisContext) -> dict[str, Any]:
        return {
            "ticker": context.asset.ticker,
            "exchange": context.asset.exchange,
            "timeframe": context.timeframe.value,
            "analyses": self._analyses,
            "debate_history": self._debate_history,
        }


@dataclass(slots=True)
class ResearchDebateResult:
    turns: list[AgentRun] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    manager_run: AgentRun | None = None


def run_research_debate(
    runner: AgentRunner,
    context: AnalysisContext,
    analyzer_runs: list[AgentRun],
    *,
    max_rounds: int = 2,
) -> ResearchDebateResult:
    """Execute alternating Bull/Bear debate rounds followed by Research Manager."""
    result = ResearchDebateResult()
    last_bull = ""
    last_bear = ""

    for round_idx in range(1, max(1, max_rounds) + 1):
        bull_run = runner.run(
            BullResearcher(analyzer_runs, result.history, last_bear),
            context,
        )
        bull_out: DebateTurnOutput = bull_run.output  # type: ignore[assignment]
        last_bull = bull_out.thesis
        result.turns.append(bull_run)
        result.history.append(
            {
                "round": round_idx,
                "speaker": "Bull Researcher",
                "stance": bull_out.stance.value,
                "thesis": bull_out.thesis,
                "key_arguments": list(bull_out.key_arguments),
                "counter_points": list(bull_out.counter_points),
            }
        )

        bear_run = runner.run(
            BearResearcher(analyzer_runs, result.history, last_bull),
            context,
        )
        bear_out: DebateTurnOutput = bear_run.output  # type: ignore[assignment]
        last_bear = bear_out.thesis
        result.turns.append(bear_run)
        result.history.append(
            {
                "round": round_idx,
                "speaker": "Bear Researcher",
                "stance": bear_out.stance.value,
                "thesis": bear_out.thesis,
                "key_arguments": list(bear_out.key_arguments),
                "counter_points": list(bear_out.counter_points),
            }
        )

    result.manager_run = runner.run(
        ResearchManager(analyzer_runs, result.history),
        context,
    )
    return result
