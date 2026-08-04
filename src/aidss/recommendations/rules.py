"""Recommendation-specific validation rules (Section 5.4).

The generic Output Validator already guarantees that a response is valid JSON,
matches its schema, and contains no execution instruction. These rules add the
checks that only make sense for a recommendation:

  * **Completeness** - every mandatory Section 5.4 field is actually populated.
    Pydantic proves a field exists; it does not prove someone filled it in with
    something. An empty list satisfies the type and fails the requirement.
  * **Conflicting factors are non-empty.** Section 5.4 makes this mandatory
    precisely because a recommendation that can find nothing against itself has
    not been examined. This is the single rule most worth enforcing here.
  * **The label must not contradict its own evidence.** Only fires when the
    usable analyzers are unanimous, so it catches a genuine contradiction
    rather than second-guessing every judgement call.
  * **A strong label must be backed by calibrated confidence.** "Strong Buy" on
    thin, one-sided evidence is exactly the misleading output the plan's
    AI-quality risk describes (Section 17).

Each failure carries a corrective instruction, so the runner's existing retry
path can tell the model precisely what to fix.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aidss.domain.types import RecommendationLabel
from aidss.prompts.schemas import RecommendationOutput
from aidss.recommendations.calibration import (
    STRONG_LABEL_MIN_CONFIDENCE,
    CalibrationResult,
    evidence_direction,
)

#: Fields Section 5.4 requires to carry actual content, not just to exist.
REQUIRED_NARRATIVE_FIELDS = ("reasoning", "bullish_scenario", "bearish_scenario")

_DIRECTION_WORD = {1: "constructive", 0: "neutral", -1: "cautious"}


@dataclass(slots=True)
class RuleViolation:
    rule: str
    detail: str
    correction: str


@dataclass(slots=True)
class RuleReport:
    violations: list[RuleViolation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def corrective_instruction(self) -> str:
        lines = [
            "Your previous recommendation did not meet the required structure. "
            "Fix the following and reply again with a corrected JSON object:"
        ]
        lines.extend(f"- {v.correction}" for v in self.violations)
        return "\n".join(lines)

    def as_dict(self) -> list[dict[str, str]]:
        return [{"rule": v.rule, "detail": v.detail} for v in self.violations]


def check(output: RecommendationOutput, calibration: CalibrationResult) -> RuleReport:
    report = RuleReport()

    _check_narrative_completeness(output, report)
    _check_conflicting_factors(output, report)
    _check_supporting_factors(output, report)
    _check_risk_factors(output, report)
    _check_label_consistency(output, calibration, report)
    _check_label_strength(output, calibration, report)

    return report


def _check_narrative_completeness(output: RecommendationOutput, report: RuleReport) -> None:
    for name in REQUIRED_NARRATIVE_FIELDS:
        value = getattr(output, name, "") or ""
        if not value.strip():
            report.violations.append(
                RuleViolation(
                    rule="completeness",
                    detail=f"{name} is empty",
                    correction=(
                        f"`{name}` must be filled in. Section 5.4 requires both scenarios "
                        "and the reasoning behind the label."
                    ),
                )
            )


def _check_conflicting_factors(output: RecommendationOutput, report: RuleReport) -> None:
    if not [f for f in output.conflicting_factors if f.strip()]:
        report.violations.append(
            RuleViolation(
                rule="conflicting_factors_required",
                detail="conflicting_factors is empty",
                correction=(
                    "`conflicting_factors` must not be empty. State at least one piece of "
                    "evidence that argues against your label. If you genuinely cannot find "
                    "one, your label is too strong for the evidence - choose a weaker one "
                    "and explain what is missing."
                ),
            )
        )


def _check_supporting_factors(output: RecommendationOutput, report: RuleReport) -> None:
    if not [f for f in output.supporting_factors if f.strip()]:
        report.violations.append(
            RuleViolation(
                rule="supporting_factors_required",
                detail="supporting_factors is empty",
                correction=(
                    "`supporting_factors` must not be empty. State the evidence that led "
                    "to this label."
                ),
            )
        )


def _check_risk_factors(output: RecommendationOutput, report: RuleReport) -> None:
    if not [f for f in output.risk_factors if f.strip()]:
        report.violations.append(
            RuleViolation(
                rule="risk_factors_required",
                detail="risk_factors is empty",
                correction=(
                    "`risk_factors` must not be empty. Name at least one specific risk "
                    "relevant to this asset."
                ),
            )
        )


def _check_label_consistency(
    output: RecommendationOutput, calibration: CalibrationResult, report: RuleReport
) -> None:
    direction = evidence_direction(calibration.signals)
    if direction is None or direction == 0:
        # Split or neutral evidence supports any measured label; only a
        # unanimous reading can be contradicted.
        return

    label_direction = output.label.direction
    if label_direction != 0 and label_direction != direction:
        report.violations.append(
            RuleViolation(
                rule="label_contradicts_evidence",
                detail=(
                    f"label {output.label.value!r} is {_DIRECTION_WORD[label_direction]} "
                    f"while every usable analyzer is {_DIRECTION_WORD[direction]}"
                ),
                correction=(
                    f"Your label is {_DIRECTION_WORD[label_direction]}, but every analyzer "
                    f"with usable data reads {_DIRECTION_WORD[direction]}. Either choose a "
                    "label consistent with that evidence, or - if you have a specific "
                    "reason to go against it - choose a neutral label and set out that "
                    "reason explicitly in the reasoning."
                ),
            )
        )


def _check_label_strength(
    output: RecommendationOutput, calibration: CalibrationResult, report: RuleReport
) -> None:
    if output.label.is_strong and calibration.confidence < STRONG_LABEL_MIN_CONFIDENCE:
        report.violations.append(
            RuleViolation(
                rule="strong_label_needs_confidence",
                detail=(
                    f"label {output.label.value!r} requires calibrated confidence "
                    f">= {STRONG_LABEL_MIN_CONFIDENCE:.0f}, but the evidence supports "
                    f"{calibration.confidence:.1f}"
                ),
                correction=(
                    f"The evidence available supports a calibrated confidence of only "
                    f"{calibration.confidence:.1f} out of 100 "
                    f"({calibration.explanation}). That is below the "
                    f"{STRONG_LABEL_MIN_CONFIDENCE:.0f} required for "
                    f"{output.label.value!r}. Choose a label proportionate to the "
                    "evidence: "
                    + (
                        "'buy' or 'watchlist' instead of 'strong_buy'."
                        if output.label is RecommendationLabel.STRONG_BUY
                        else "'reduce' or 'hold' instead of 'sell'."
                    )
                ),
            )
        )
