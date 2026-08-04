"""The Recommendation Agent (Phase 5, Section 5.4)."""

from __future__ import annotations

from typing import Any

from aidss.agents.base import Agent, AgentRun
from aidss.agents.context import AnalysisContext
from aidss.llm.router import TaskComplexity
from aidss.prompts.schemas import RecommendationOutput
from aidss.recommendations.calibration import CalibrationResult


class RecommendationAgent(Agent):
    """Turns the analyzers' readings into one graded, defensible stance.

    Given the calibration up front, so the model can see how thin or broad its
    evidence actually is before choosing a label. Telling it afterwards that
    the label was too strong wastes a call; showing it the coverage first
    usually prevents the mistake.
    """

    name = "recommendation_agent"
    template_name = "recommendation"
    output_model = RecommendationOutput
    #: The output a user acts on, so it gets the strongest routing tier.
    complexity = TaskComplexity.COMPLEX

    def __init__(
        self,
        analyzer_runs: list[AgentRun],
        synthesis: AgentRun | None,
        calibration: CalibrationResult,
    ) -> None:
        self._analyzer_runs = analyzer_runs
        self._synthesis = synthesis
        self._calibration = calibration

    def is_applicable(self, context: AnalysisContext) -> bool:
        # A recommendation with no analyzer behind it would be a label attached
        # to nothing.
        return bool(self._analyzer_runs)

    def skip_reason(self, context: AnalysisContext) -> str:
        return "no analyzer produced output, so there is nothing to base a recommendation on"

    def prompt_context(self, context: AnalysisContext) -> dict[str, Any]:
        return {
            "ticker": context.asset.ticker,
            "exchange": context.asset.exchange,
            "timeframe": context.timeframe.value,
            "investment_horizon": context.memory.horizon,
            "risk_appetite": context.memory.risk_appetite,
            "analyses": [
                {
                    "agent": run.agent,
                    "data_sufficiency": run.output.data_sufficiency.value,
                    **run.output.model_dump(mode="json", exclude={"data_sufficiency"}),
                }
                for run in self._analyzer_runs
            ],
            "synthesis": (
                self._synthesis.output.model_dump(mode="json")
                if self._synthesis
                else "(no synthesis was produced)"
            ),
            "calibration": {
                "measured_confidence": self._calibration.confidence,
                "coverage": round(self._calibration.coverage, 3),
                "agreement": round(self._calibration.agreement, 3),
                "explanation": self._calibration.explanation,
            },
        }
