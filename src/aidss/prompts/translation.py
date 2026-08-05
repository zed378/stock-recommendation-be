"""Rendering a stored analysis in another language.

The obvious design - generate the analysis twice, once per language - is the
wrong one, and the reason is worth stating because it looks harmless. Two
independent runs over the same evidence can reach different stances. A reader
seeing "beli" in one column and "tahan" in the other has no way to resolve it,
and the platform would have published two contradictory analyses of the same
asset with equal authority.

So there is one analysis, and translations are renderings of it. The original
stays authoritative, every translation says which analysis it came from, and a
translation that fails leaves the original untouched rather than producing a
half-rendered mixture.

Cached because a translation of a stored analysis cannot change: the source
text is immutable, so paying for it twice buys nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from aidss.domain.types import ChatMessage
from aidss.llm.gateway import LLMGateway, LLMRequest
from aidss.llm.router import Sensitivity, TaskComplexity
from aidss.prompts.language import OutputLanguage, find_execution_language

#: Fields that are prose and should be rendered. Anything not listed here -
#: labels, numbers, model names, prompt versions - is carried through
#: unchanged. Translating a stance label would produce a value the enum does
#: not contain, and translating a price would be nonsense.
#: This list was written when only the recommendation was rendered, and it
#: covered that payload exactly. Once every agent's own write-up started being
#: translated it covered barely a third of what a reader sees: the summary
#: agent's `watch_items` and `disagreements`, the technical analyzer's signals,
#: every analyzer's notes - all of them stayed in the source language while the
#: paragraph above them changed, producing a card half in each.
#:
#: `test_translation_covers_every_prose_field` holds this to the schemas, so a
#: field added later is a failing test rather than a silently untranslated
#: section.
TRANSLATABLE_KEYS: frozenset[str] = frozenset(
    {
        # --- the recommendation ------------------------------------------
        "reasoning",
        "summary",
        "bullish_scenario",
        "bearish_scenario",
        "supporting_factors",
        "conflicting_factors",
        "risk_factors",
        "rationale",
        "conditions",
        "invalidated_if",
        # --- market analyzer ----------------------------------------------
        "regime",
        "key_drivers",
        "sector_note",
        # --- technical analyzer ---------------------------------------------
        "level_commentary",
        "supporting_signals",
        "conflicting_signals",
        # --- fundamental analyzer -------------------------------------------
        "valuation_note",
        "growth_note",
        "balance_sheet_note",
        "concerns",
        # --- news analyzer ----------------------------------------------------
        "key_themes",
        "notable_events",
        # --- summary agent ------------------------------------------------------
        "agreements",
        "disagreements",
        "watch_items",
        # --- portfolio and risk ---------------------------------------------------
        "observations",
        "considerations",
        "concentration_reading",
        "diversification_note",
        "correlation_note",
        "risk_reading",
        "volatility_note",
        "drawdown_note",
        "concentration_risks",
        "limitations",
        # --- journal, chat, knowledge -------------------------------------------------
        "patterns",
        "insufficient_evidence_for",
        "questions_to_consider",
        "answer",
        "follow_up_questions",
    }
)

#: Prose-shaped fields that must survive untouched, and why.
#:
#: Kept as an explicit set rather than simply omitted from the list above: the
#: test pairs the two, so leaving a field out of both fails rather than passing
#: quietly as an oversight.
NOT_TRANSLATED: frozenset[str] = frozenset(
    {
        # References back to the retrieved passages an answer drew on.
        # Translating a citation breaks the link to the thing being cited.
        "sources_used",
    }
)

SYSTEM_PROMPT = """You translate financial analysis text between Indonesian and English.

Rules, all of them absolute:
- Translate meaning, never add, remove, soften, or strengthen a claim.
- A hedge stays a hedge. "may", "appears to", "mungkin" carry the writer's
  uncertainty and dropping one changes what was said.
- Keep ticker symbols, numbers, percentages, dates, and level names exactly as
  they are.
- Never introduce an instruction. If the source describes a stance, the
  translation describes a stance.
- Return JSON with exactly the same keys and structure you were given.
"""


@dataclass(frozen=True, slots=True)
class Translation:
    language: OutputLanguage
    fields: dict[str, Any]
    model: str | None
    #: Always true. Present so the interface cannot render a translation
    #: without knowing it is one.
    is_machine_translation: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "language": self.language.value,
            "fields": self.fields,
            "model": self.model,
            "is_machine_translation": self.is_machine_translation,
        }


def translatable_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """The prose worth rendering, and nothing else."""
    return {
        key: value
        for key, value in payload.items()
        if key in TRANSLATABLE_KEYS and value not in (None, "", [], {})
    }


def translate(
    gateway: LLMGateway,
    payload: dict[str, Any],
    target: OutputLanguage,
    *,
    agent: str = "translator",
    sensitivity: Sensitivity = Sensitivity.PUBLIC,
) -> Translation:
    """Render the prose fields of one stored payload in ``target``.

    Raises rather than returning a partial result: a response that translated
    three fields and dropped two would be displayed as a complete analysis
    missing its counter-evidence, which is worse than showing the original.
    """
    fields = translatable_fields(payload)
    if not fields:
        return Translation(language=target, fields={}, model=None)

    language_name = "Indonesian" if target is OutputLanguage.ID else "English"
    response = gateway.complete(
        LLMRequest(
            agent=agent,
            messages=[
                ChatMessage(role="system", content=SYSTEM_PROMPT),
                ChatMessage(
                    role="user",
                    content=(
                        f"Translate every string value in this JSON into "
                        f"{language_name}. Return only JSON with identical keys.\n\n"
                        f"{json.dumps(fields, ensure_ascii=False, indent=2)}"
                    ),
                ),
            ],
            # Translation is mechanical next to analysis, and routing it as
            # complex would spend a reasoning model on a rendering task.
            complexity=TaskComplexity.STANDARD,
            sensitivity=sensitivity,
            expects_json=True,
            temperature=0.0,
        )
    )

    translated = _parse(response.content)
    missing = set(fields) - set(translated)
    if missing:
        raise ValueError(
            f"The translation dropped {sorted(missing)}; showing a partial rendering "
            "would present an analysis without the parts that went missing."
        )

    # The execution-language guard applies to the translation too. A source
    # that passed in Indonesian could come back as "buy now" in English, and a
    # rule enforced only on the original would have a hole exactly the width of
    # this feature.
    violations = find_execution_language(json.dumps(translated, ensure_ascii=False))
    if violations:
        raise ValueError(
            "The translation introduced execution language: "
            + "; ".join(v.reason for v in violations)
        )

    return Translation(language=target, fields=translated, model=response.usage.model)


def _parse(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        # Some models fence JSON even when asked not to.
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"The translation was not JSON: {text[:120]!r}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("The translation was not a JSON object")
    return parsed
