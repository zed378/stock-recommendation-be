"""Output Validator (Sections 5.4, 11.2, 12.5).

Two checks run on every model response before it is stored or shown:

  1. **Structure** - does it parse as JSON and satisfy the agent's schema?
  2. **Language** - is it free of execution instructions?

The second is why this module exists as a separate stage rather than a
`model_validate` call at the call site. Provider JSON mode is uneven across the
servers this platform supports (Section 12.5), and a prompt instruction is a
request the model may ignore. Validation is the layer that does not depend on
the model cooperating.

A failure here is recoverable: `ValidationFailure` carries corrective feedback
the caller can append to a retry, which is the "retry with corrective
instruction" arrow in the Section 11.2 flow.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from aidss.prompts.language import LanguageViolation, find_execution_language

M = TypeVar("M", bound=BaseModel)

#: Models often wrap JSON in a markdown fence despite being told not to. That
#: is a formatting habit rather than a content failure, so it is stripped
#: rather than rejected - a retry would cost a call and usually reproduce it.
_FENCE = re.compile(r"^\s*```(?:json)?\s*(?P<body>.*?)\s*```\s*$", re.DOTALL)


class ValidationFailure(Exception):
    """The response did not pass structure or language validation."""

    def __init__(self, reasons: list[str], *, corrective_instruction: str) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons
        self.corrective_instruction = corrective_instruction


@dataclass(slots=True)
class ValidationReport:
    """What validation found, whether or not it passed."""

    ok: bool
    reasons: list[str] = field(default_factory=list)
    language_violations: list[LanguageViolation] = field(default_factory=list)


def strip_code_fence(raw: str) -> str:
    match = _FENCE.match(raw)
    return match.group("body") if match else raw.strip()


def _collect_text(payload: object) -> list[str]:
    """Every string inside a parsed payload, for the language check.

    Checking the raw response would also scan JSON keys; checking only the
    summary field would miss a violation hiding in a list entry.
    """
    if isinstance(payload, str):
        return [payload]
    if isinstance(payload, dict):
        return [t for value in payload.values() for t in _collect_text(value)]
    if isinstance(payload, list):
        return [t for item in payload for t in _collect_text(item)]
    return []


def check_language(payload: object) -> list[LanguageViolation]:
    violations: list[LanguageViolation] = []
    for text in _collect_text(payload):
        violations.extend(find_execution_language(text))
    return violations


def validate(raw: str, model: type[M]) -> tuple[M, ValidationReport]:
    """Parse, validate against ``model``, and check the language rule.

    Raises ``ValidationFailure`` with corrective feedback when either check
    fails.
    """
    body = strip_code_fence(raw)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValidationFailure(
            [f"response is not valid JSON: {exc}"],
            corrective_instruction=(
                "Your previous reply was not valid JSON. Reply with a single JSON "
                "object and nothing else - no prose, no markdown fences."
            ),
        ) from exc

    if not isinstance(payload, dict):
        raise ValidationFailure(
            [f"expected a JSON object, got {type(payload).__name__}"],
            corrective_instruction=(
                "Your previous reply was not a JSON object. Reply with a single "
                "JSON object matching the required shape."
            ),
        )

    # Language is checked before schema validation so a violation is reported
    # as a violation, rather than being masked by an unrelated schema error.
    violations = check_language(payload)
    if violations:
        quoted = ", ".join(f"{v.matched_text!r} ({v.reason})" for v in violations)
        raise ValidationFailure(
            [f"execution-instruction language found: {quoted}"],
            corrective_instruction=(
                "Your previous reply contained execution instructions: "
                f"{quoted}. Rewrite it as informational, conditional analysis. "
                "Describe what the evidence suggests and under what conditions; "
                "never tell the reader to transact."
            ),
        )

    try:
        validated = model.model_validate(payload)
    except ValidationError as exc:
        reasons = [
            f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors()
        ]
        raise ValidationFailure(
            reasons,
            corrective_instruction=(
                "Your previous reply did not match the required shape. Problems: "
                + "; ".join(reasons)
                + ". Reply again with a corrected JSON object."
            ),
        ) from exc

    return validated, ValidationReport(ok=True)
