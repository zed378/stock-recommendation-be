"""Recommendation Engine (Phase 5, Section 5.4).

Produces the structured recommendation and persists it. The sequence matters:

  1. **Calibrate first**, from the analyzer outputs alone. The score is a
     property of the evidence, so it exists before the model has said anything
     and cannot be influenced by how confident the model sounds.
  2. **Ask the model** for the label and the narrative, showing it that
     calibration so it can choose a proportionate label rather than be
     corrected afterwards.
  3. **Check the Section 5.4 rules.** A violation is fed back as a correction
     and retried, using the same retry path every other agent uses.
  4. **Attach the measured prices.** Support, resistance, target, and the
     suggested stop come from the Indicator Engine with their method recorded.
  5. **Persist**, with the calibration breakdown stored alongside, so a score
     can be explained later rather than merely displayed.

The recommendation is only stored once it has passed the generic validator
(schema and execution-language) and these rules. Section 15 sets the Phase 5
deliverable as "recommendations pass schema validation 100%"; the way to
achieve that is to make storing an invalid one impossible.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from aidss.agents.base import AgentRun, AgentRunner
from aidss.agents.context import AnalysisContext
from aidss.db.models import Recommendation
from aidss.prompts.schemas import RecommendationOutput
from aidss.recommendations.agent import RecommendationAgent
from aidss.recommendations.calibration import (
    CalibrationResult,
    DerivedLevels,
    calibrate,
    derive_levels,
)
from aidss.recommendations.rules import RuleReport, check


class RecommendationRejected(Exception):
    """The model could not produce a recommendation meeting Section 5.4.

    Deliberately an error rather than a degraded result. A recommendation that
    fails these rules is one whose evidence has not been weighed, and storing
    it with a warning attached would put it in front of a user anyway.
    """

    def __init__(self, report: RuleReport) -> None:
        super().__init__("; ".join(v.detail for v in report.violations))
        self.report = report


@dataclass(slots=True)
class RecommendationResult:
    output: RecommendationOutput
    calibration: CalibrationResult
    levels: DerivedLevels
    run: AgentRun
    recommendation_id: uuid.UUID | None = None
    #: Which language the prose above is written in - the one that passed
    #: validation. Named so the renderings below read as renderings of it.
    language: str = "id"
    #: Renderings keyed by language, produced during the same run so a reader
    #: never waits for a translation of the page they are already on.
    translations: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        """The complete Section 5.4 structure, ready for the API."""
        return {
            "label": self.output.label.value,
            # The calibrated score, not the model's self-report.
            "confidence": self.calibration.confidence,
            "confidence_basis": self.calibration.as_dict(),
            "model_self_reported_confidence": self.output.confidence,
            "reasoning": self.output.reasoning,
            "supporting_factors": list(self.output.supporting_factors),
            "conflicting_factors": list(self.output.conflicting_factors),
            "risk_factors": list(self.output.risk_factors),
            "bullish_scenario": self.output.bullish_scenario,
            "bearish_scenario": self.output.bearish_scenario,
            "support_level": _str_or_none(self.levels.support),
            "resistance_level": _str_or_none(self.levels.resistance),
            "target_price": _str_or_none(self.levels.target_price),
            "target_price_method": self.levels.target_price_method,
            "suggested_stop": _str_or_none(self.levels.suggested_stop),
            "suggested_stop_method": self.levels.suggested_stop_method,
            "horizon": self.output.horizon.value,
            "prompt_version": self.run.template_version,
            "model": self.run.usage.model,
            "provider": self.run.usage.provider,
            "attempts": self.run.attempts,
            "language": self.language,
            "translations": dict(self.translations),
        }


def _str_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


class RecommendationEngine:
    def __init__(self, session: Session, runner: AgentRunner, *, max_rule_retries: int = 1) -> None:
        self._session = session
        self._runner = runner
        self._max_rule_retries = max_rule_retries

    def generate(
        self,
        context: AnalysisContext,
        analyzer_runs: list[AgentRun],
        synthesis: AgentRun | None,
        *,
        analysis_result_id: uuid.UUID | None = None,
        persist: bool = True,
    ) -> RecommendationResult:
        outputs = {run.agent: run.output for run in analyzer_runs}
        agent = RecommendationAgent(analyzer_runs, synthesis, _initial_calibration(outputs))

        last_report: RuleReport | None = None
        correction: str | None = None

        for _ in range(self._max_rule_retries + 1):
            run = self._runner.run(agent, context, extra_instruction=correction)
            output: RecommendationOutput = run.output  # type: ignore[assignment]

            # Recalibrated against the factors this answer actually listed, so
            # the balance component reflects the recommendation in hand.
            calibration = calibrate(
                outputs,
                supporting_count=len([f for f in output.supporting_factors if f.strip()]),
                conflicting_count=len([f for f in output.conflicting_factors if f.strip()]),
            )

            report = check(output, calibration)
            if report.ok:
                levels = derive_levels(context.indicator_snapshot, output.label)
                result = RecommendationResult(
                    output=output, calibration=calibration, levels=levels, run=run
                )
                # Recorded from what the prompt actually asked for, not
                # assumed. That is the difference between the column being a
                # fact about the text and a guess about it.
                result.language = self._runner.language.value
                if persist and analysis_result_id is not None:
                    result.recommendation_id = self._persist(analysis_result_id, result)
                return result

            last_report = report
            correction = report.corrective_instruction()

        assert last_report is not None
        raise RecommendationRejected(last_report)

    def _persist(self, analysis_result_id: uuid.UUID, result: RecommendationResult) -> uuid.UUID:
        row = Recommendation(
            analysis_result_id=analysis_result_id,
            label=result.output.label,
            confidence=result.calibration.confidence,
            reasoning=result.output.reasoning,
            supporting_factors=list(result.output.supporting_factors),
            conflicting_factors=list(result.output.conflicting_factors),
            risk_factors=list(result.output.risk_factors),
            bullish_scenario=result.output.bullish_scenario,
            bearish_scenario=result.output.bearish_scenario,
            support_level=result.levels.support,
            resistance_level=result.levels.resistance,
            target_price=result.levels.target_price,
            target_price_method=result.levels.target_price_method,
            suggested_stop=result.levels.suggested_stop,
            horizon=result.output.horizon,
            # Written from what the prompt actually asked for. Left out, the
            # column silently took the model's default of "id" whatever the
            # prompt had said - so English prose was stored labelled Indonesian,
            # the switch offered to translate it into the language it was
            # already in, and `render_translation` rendered "the other one"
            # into English as well. Two identical columns, one of them lying.
            language=result.language,
        )
        self._session.add(row)
        self._session.flush()
        return row.id


def _initial_calibration(outputs: dict[str, Any]) -> CalibrationResult:
    """Calibration shown to the model before it answers.

    The balance component needs factor counts that do not exist yet, so it is
    computed here from a neutral 1:1 assumption. Coverage and agreement - the
    parts that actually tell the model how thin its evidence is - are already
    final.
    """
    return calibrate(outputs, supporting_count=1, conflicting_count=1)
