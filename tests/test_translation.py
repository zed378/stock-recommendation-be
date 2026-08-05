"""Translation as a rendering, not as a second analysis.

The design decision under test: one analysis is authoritative and translations
are renderings of it. Generating the analysis twice - once per language - could
produce two different stances for one asset with equal authority, and a reader
seeing "beli" beside "hold" would have no way to resolve it.

Everything else follows from that. Only prose is translated, because a
translated stance label would be a value the enum does not contain and a
translated price would be nonsense. A partial result is refused, because half
an analysis reads as a whole one that happens to be missing its
counter-evidence. And the execution-language guard runs on the output, because
a rule enforced only on the original would have a hole exactly the width of
this feature.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from aidss.domain.types import ChatMessage
from aidss.llm.cost import Usage
from aidss.llm.gateway import LLMResponse
from aidss.prompts.language import OutputLanguage
from aidss.prompts.translation import (
    TRANSLATABLE_KEYS,
    translatable_fields,
    translate,
)

ANALYSIS = {
    "label": "buy",
    "confidence": 78.5,
    "target_price": "11000",
    "model": "Qwen/Bodha",
    "prompt_version": "1.0.0",
    "reasoning": "Tren jangka menengah masih naik.",
    "supporting_factors": ["Harga di atas SMA 50"],
    "conflicting_factors": ["Volume menurun"],
}


class FakeGateway:
    """Returns a prepared payload and records what it was asked."""

    def __init__(self, payload: object) -> None:
        self._payload = payload
        self.requests: list[object] = []

    def complete(self, request):  # noqa: ANN001
        self.requests.append(request)
        content = (
            self._payload if isinstance(self._payload, str)
            else json.dumps(self._payload, ensure_ascii=False)
        )
        return LLMResponse(
            content=content,
            usage=Usage(
                provider="fake",
                model="translator-model",
                prompt_tokens=10,
                completion_tokens=10,
                cost_estimate=Decimal("0"),
            ),
        )


# --- what gets translated --------------------------------------------------


def test_only_prose_is_sent_for_translation() -> None:
    """A translated stance label would be a value the enum does not contain."""
    selected = translatable_fields(ANALYSIS)
    assert set(selected) == {"reasoning", "supporting_factors", "conflicting_factors"}


def test_labels_prices_and_provenance_are_never_translated() -> None:
    selected = translatable_fields(ANALYSIS)
    for key in ("label", "confidence", "target_price", "model", "prompt_version"):
        assert key not in selected


def test_empty_and_absent_fields_are_not_sent() -> None:
    """Paying for the translation of an empty string buys nothing."""
    selected = translatable_fields({"reasoning": "", "supporting_factors": [], "summary": None})
    assert selected == {}


def test_nothing_to_translate_makes_no_call() -> None:
    gateway = FakeGateway({})
    result = translate(gateway, {"label": "buy"}, OutputLanguage.EN)
    assert result.fields == {}
    assert gateway.requests == []


def test_the_translatable_set_covers_the_fields_that_carry_meaning() -> None:
    """Counter-evidence in particular: a translation that dropped
    `conflicting_factors` would render an analysis without the part that
    argues against it."""
    for key in ("reasoning", "conflicting_factors", "risk_factors", "summary"):
        assert key in TRANSLATABLE_KEYS


# --- the result ------------------------------------------------------------


def test_a_complete_translation_is_returned_and_marked_as_one() -> None:
    """The interface must not be able to render a translation without knowing
    it is one."""
    gateway = FakeGateway(
        {
            "reasoning": "The medium-term trend is still up.",
            "supporting_factors": ["Price above the 50-day average"],
            "conflicting_factors": ["Volume is declining"],
        }
    )
    result = translate(gateway, ANALYSIS, OutputLanguage.EN)

    assert result.is_machine_translation is True
    assert result.language is OutputLanguage.EN
    assert result.model == "translator-model"
    assert "medium-term" in result.fields["reasoning"]


def test_a_partial_translation_is_refused() -> None:
    """Half an analysis reads as a whole one missing its counter-evidence."""
    gateway = FakeGateway({"reasoning": "The trend is up."})
    with pytest.raises(ValueError, match="dropped"):
        translate(gateway, ANALYSIS, OutputLanguage.EN)


def test_a_non_json_response_is_refused() -> None:
    gateway = FakeGateway("not json at all")
    with pytest.raises(ValueError, match="not JSON"):
        translate(gateway, ANALYSIS, OutputLanguage.EN)


def test_a_fenced_json_response_is_accepted() -> None:
    """Some models fence JSON even when asked not to, and refusing a correct
    answer over its wrapper would fail for a reason nobody can act on."""
    body = json.dumps(
        {
            "reasoning": "The trend is up.",
            "supporting_factors": ["Above average"],
            "conflicting_factors": ["Volume declining"],
        }
    )
    result = translate(FakeGateway(f"```json\n{body}\n```"), ANALYSIS, OutputLanguage.EN)
    assert result.fields["reasoning"] == "The trend is up."


# --- the guard applies to the translation too ------------------------------


def test_a_translation_that_introduces_an_instruction_is_refused() -> None:
    """A source that passed in Indonesian could come back as "buy now" in
    English. A rule enforced only on the original would have a hole exactly the
    width of this feature.
    """
    gateway = FakeGateway(
        {
            "reasoning": "Buy now while the trend is up.",
            "supporting_factors": ["Above average"],
            "conflicting_factors": ["Volume declining"],
        }
    )
    with pytest.raises(ValueError, match="execution language"):
        translate(gateway, ANALYSIS, OutputLanguage.EN)


def test_ordinary_analytical_vocabulary_still_passes() -> None:
    """A guard with false positives is one that pushes wording towards evasive
    circumlocution rather than towards clarity."""
    gateway = FakeGateway(
        {
            "reasoning": "Buying pressure increased and a bullish crossover formed.",
            "supporting_factors": ["Sellers were absent"],
            "conflicting_factors": ["A buy signal here has failed before"],
        }
    )
    assert translate(gateway, ANALYSIS, OutputLanguage.EN).fields


# --- routing ---------------------------------------------------------------


def test_translation_is_routed_as_standard_not_complex() -> None:
    """Rendering is mechanical next to analysis; routing it as complex would
    spend a reasoning model on it."""
    from aidss.llm.router import TaskComplexity

    gateway = FakeGateway(
        {
            "reasoning": "x",
            "supporting_factors": ["y"],
            "conflicting_factors": ["z"],
        }
    )
    translate(gateway, ANALYSIS, OutputLanguage.EN)
    assert gateway.requests[0].complexity is TaskComplexity.STANDARD


def test_personal_text_can_be_routed_through_the_sensitive_path() -> None:
    """A journal reflection is personal financial data, and translating it
    must not send it somewhere the analysis itself would not have gone."""
    from aidss.llm.router import Sensitivity

    gateway = FakeGateway({"summary": "x"})
    translate(
        gateway,
        {"summary": "ringkasan"},
        OutputLanguage.EN,
        sensitivity=Sensitivity.SENSITIVE,
    )
    assert gateway.requests[0].sensitivity is Sensitivity.SENSITIVE


def test_json_is_requested_so_the_output_can_be_validated() -> None:
    gateway = FakeGateway({"summary": "x"})
    translate(gateway, {"summary": "ringkasan"}, OutputLanguage.EN)
    assert gateway.requests[0].expects_json is True


def test_the_prompt_forbids_adding_or_removing_claims() -> None:
    """The failure mode that matters: a hedge dropped in translation changes
    what was said."""
    from aidss.prompts.translation import SYSTEM_PROMPT

    lowered = SYSTEM_PROMPT.lower()
    assert "never add, remove, soften, or strengthen a claim" in lowered
    assert "hedge stays a hedge" in lowered
    assert "never introduce an instruction" in lowered


def test_the_system_message_is_sent_as_a_system_role() -> None:
    gateway = FakeGateway({"summary": "x"})
    translate(gateway, {"summary": "ringkasan"}, OutputLanguage.EN)
    messages: list[ChatMessage] = gateway.requests[0].messages
    assert messages[0].role == "system"
