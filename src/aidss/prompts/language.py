"""The execution-language guard (Section 5.4, hard rule).

The product's whole positioning rests on one distinction: analysis may say
"this area shows potential, though risk Z applies"; it may not say "buy now".
Section 17 rates an accidental slip into instruction language as a
medium-likelihood, high-impact compliance risk, and notes it needs an explicit
guardrail rather than good intentions.

That guardrail is applied twice, as the plan requires: the prompt tells the
model the rule (`prompts/catalog.py`), and this module checks the output
regardless of what the model was told. The second check is the one that
matters - a prompt is a request, not a constraint.

Both languages are covered because the platform serves an Indonesian market
while models frequently answer in English.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

#: Imperative execution phrasing. Each pattern targets a *command to transact*,
#: not the vocabulary of trading: "buying pressure", "sellers are active", and
#: "a buy signal" are legitimate analytical description and must pass.
_EXECUTION_PATTERNS: tuple[tuple[str, str], ...] = (
    # --- Indonesian ---
    (r"\b(beli|jual)\s+(sekarang|segera|hari\s+ini)\b", "imperative buy/sell with timing"),
    (r"\bsegera\s+(beli|jual)\b", "imperative buy/sell with urgency"),
    (r"\b(jual|beli)\s+(semua|seluruh)\b", "instruction to transact an entire position"),
    (r"\banda\s+harus\s+(beli|jual|membeli|menjual)\b", "direct obligation to transact"),
    (r"\b(belilah|juallah)\b", "imperative verb form"),
    (r"\bmasuk\s+posisi\s+sekarang\b", "instruction to open a position now"),
    (r"\b(borong|cut\s+loss)\s+sekarang\b", "instruction to transact now"),
    # --- English ---
    (r"\b(buy|sell)\s+(now|immediately|today)\b", "imperative buy/sell with timing"),
    (
        r"\b(sell|buy)\s+(everything|all\s+your|your\s+entire)\b",
        "instruction to transact a position",
    ),
    (r"\byou\s+(should|must)\s+(buy|sell)\b", "direct obligation to transact"),
    (r"\bplace\s+(a|your)?\s*(buy|sell)?\s*order\b", "instruction to place an order"),
    (r"\bexit\s+(the\s+)?position\s+now\b", "instruction to close a position now"),
    (r"\bdump\s+(this|the)\s+stock\b", "instruction to liquidate"),
)

_COMPILED = tuple((re.compile(p, re.IGNORECASE), reason) for p, reason in _EXECUTION_PATTERNS)


@dataclass(frozen=True, slots=True)
class LanguageViolation:
    matched_text: str
    reason: str
    position: int


def find_execution_language(text: str) -> list[LanguageViolation]:
    """Return every execution-instruction phrase found in ``text``."""
    violations: list[LanguageViolation] = []
    for pattern, reason in _COMPILED:
        for match in pattern.finditer(text):
            violations.append(
                LanguageViolation(
                    matched_text=match.group(0), reason=reason, position=match.start()
                )
            )
    return sorted(violations, key=lambda v: v.position)


def is_compliant(text: str) -> bool:
    return not find_execution_language(text)


#: Injected into every prompt that produces investor-facing narrative. Stated
#: as a rule with a worked contrast, because models follow demonstrated
#: patterns more reliably than prohibitions alone.
class OutputLanguage(StrEnum):
    """The languages this platform renders analysis in.

    Closed rather than a free string: a translation target the validator has no
    execution-language patterns for would be published unchecked, and the
    guard in this module only covers Indonesian and English.
    """

    ID = "id"
    EN = "en"

    @property
    def english_name(self) -> str:
        return "Indonesian" if self is OutputLanguage.ID else "English"


def output_language_rule(language: OutputLanguage) -> str:
    """Tell the model which language to answer in.

    Nothing used to. The model answered in whatever language it felt like -
    English, usually - while the stored `language` column said Indonesian
    because that was the default nobody had checked. Asking for two languages
    is what exposed it: the "translation" came back identical to the
    "original", because both were English.

    Field names stay English on purpose. They are schema keys, and translating
    one produces a document that fails validation.
    """
    return f"""\
OUTPUT LANGUAGE (mandatory):
Write every piece of prose - reasoning, factors, scenarios, summaries - in
{language.english_name}. Use {language.english_name} even when the input data,
the indicator names, or the news headlines are in another language.

JSON field names, enum values, ticker symbols, and indicator names stay exactly
as the schema defines them. Only the prose you write is in {language.english_name}."""


LANGUAGE_RULE = """\
LANGUAGE RULE (mandatory, applies to every sentence you write):
Write informational and conditional analysis. Never write an execution
instruction. You are not placing trades and you are not telling anyone to.

  Not allowed: "Buy now." / "Sell everything." / "You should buy this."
  Allowed:     "The indicators point to X, which historically preceded Y,
                though Z would argue against it."

Describing market activity is fine - "buying pressure", "a bullish crossover",
"sellers dominated the session" are all normal analytical language. What is
forbidden is instructing the reader to transact.

Any stop level you mention is a suggestion for the reader to consider, never
an order to place."""
