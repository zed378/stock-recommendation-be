"""Prompt layer tests (Sections 5.4, 11, 12.5).

The execution-language guard gets the most attention here. Section 17 rates an
accidental slip into instruction language as the product's highest-impact
compliance risk, and a guard that has never been tested against real phrasing
is a guard nobody should trust.
"""

from __future__ import annotations

import json

import pytest

from aidss.prompts import catalog
from aidss.prompts.language import LANGUAGE_RULE, find_execution_language, is_compliant
from aidss.prompts.manager import PromptComposer, PromptManager, PromptNotFoundError, schema_hint
from aidss.prompts.schemas import Bias, DataSufficiency, SynthesisOutput, TechnicalOutput
from aidss.prompts.validator import ValidationFailure, strip_code_fence, validate

# --- Language guard: phrasing that must be rejected -------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Beli sekarang sebelum harga naik lebih jauh.",
        "Segera jual posisi Anda.",
        "Jual semua saham ini.",
        "Anda harus beli saham ini hari ini.",
        "Belilah saat pembukaan besok.",
        "Buy now before the breakout completes.",
        "Sell immediately.",
        "You should sell this position.",
        "Sell everything and move to cash.",
        "Place a buy order at the open.",
        "Exit the position now.",
    ],
)
def test_execution_instructions_are_detected(text: str) -> None:
    assert not is_compliant(text), f"should have been flagged: {text!r}"


# --- Language guard: analytical phrasing that must pass ---------------------


@pytest.mark.parametrize(
    "text",
    [
        # The vocabulary of trading is not an instruction to trade. Flagging
        # these would make the guard useless: analysts would route around it.
        "Buying pressure increased through the session.",
        "A bullish crossover formed on the daily chart.",
        "Sellers dominated the final hour.",
        "The indicators produce what is conventionally called a buy signal.",
        "Tekanan beli meningkat menjelang penutupan.",
        "Volume jual terlihat mendominasi sesi kedua.",
        "Rasio beli terhadap jual bergeser ke sisi pembeli.",
        "If the level holds, the setup would favour an upward continuation, "
        "though the weak trend reading argues against relying on it.",
        "A stop below the recent swing low is one level a reader might consider.",
        "Historically this pattern preceded a move higher about half the time.",
    ],
)
def test_analytical_language_is_not_flagged(text: str) -> None:
    violations = find_execution_language(text)
    assert not violations, f"false positive on {text!r}: {violations}"


def test_violation_reports_what_and_where() -> None:
    violations = find_execution_language("The trend is up. Buy now. Risks remain.")
    assert len(violations) == 1
    assert violations[0].matched_text.lower() == "buy now"
    assert violations[0].position > 0


def test_multiple_violations_are_returned_in_order() -> None:
    violations = find_execution_language("Buy now. Later: sell everything.")
    assert len(violations) == 2
    assert violations[0].position < violations[1].position


# --- Catalog ---------------------------------------------------------------


def test_every_template_carries_the_language_rule() -> None:
    """The rule is stated in the prompt as well as enforced on the output."""
    for template in catalog.ALL_TEMPLATES:
        rendered = template.render_system("{}")
        assert LANGUAGE_RULE in rendered, f"{template.name} is missing the language rule"


def test_every_template_forbids_recomputing_numbers() -> None:
    """Section 2.7: models interpret figures, they do not derive them."""
    for template in catalog.ALL_TEMPLATES:
        rendered = template.render_system("{}").lower()
        assert "do not recalculate" in rendered, f"{template.name} is missing the numeric rule"


def test_all_ten_section_11_1_categories_exist() -> None:
    categories = {t.category for t in catalog.ALL_TEMPLATES}
    assert {
        "technical",
        "fundamental",
        "sentiment",
        "research",
        "portfolio",
        "risk",
        "education",
        "reflection",
        "market",
        "synthesis",
    } <= categories


def test_template_names_are_unique() -> None:
    names = [t.name for t in catalog.ALL_TEMPLATES]
    assert len(names) == len(set(names))


# --- Schema hint -----------------------------------------------------------


def test_schema_hint_lists_enum_values() -> None:
    """Without the vocabulary, a model invents its own labels."""
    hint = schema_hint(TechnicalOutput)
    assert '"bias"' in hint
    for member in Bias:
        assert f'"{member.value}"' in hint


def test_schema_hint_covers_every_field() -> None:
    hint = schema_hint(SynthesisOutput)
    for name in SynthesisOutput.model_fields:
        assert f'"{name}"' in hint


# --- Validator -------------------------------------------------------------


def valid_technical(**overrides) -> str:
    payload = {
        "summary": "Momentum is mid-range and the averages are only mildly separated.",
        "data_sufficiency": "sufficient",
        "confidence": 60.0,
        "bias": "neutral",
        "supporting_signals": ["price above the medium-term average"],
        "conflicting_signals": ["trend strength is weak"],
        "level_commentary": "Nearby levels sit close together.",
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_valid_output_parses_into_the_model() -> None:
    output, report = validate(valid_technical(), TechnicalOutput)
    assert report.ok
    assert output.bias is Bias.NEUTRAL
    assert output.data_sufficiency is DataSufficiency.SUFFICIENT


def test_markdown_fences_are_stripped_rather_than_rejected() -> None:
    """A fence is a formatting habit; rejecting it would cost a retry per call."""
    fenced = f"```json\n{valid_technical()}\n```"
    output, _ = validate(fenced, TechnicalOutput)
    assert output.confidence == 60.0


def test_strip_code_fence_leaves_plain_json_alone() -> None:
    assert strip_code_fence('{"a": 1}') == '{"a": 1}'


def test_non_json_is_rejected_with_corrective_feedback() -> None:
    with pytest.raises(ValidationFailure) as excinfo:
        validate("Here is my analysis: the trend is up.", TechnicalOutput)
    assert "not valid JSON" in str(excinfo.value)
    assert "JSON object" in excinfo.value.corrective_instruction


def test_missing_required_field_is_rejected() -> None:
    payload = json.loads(valid_technical())
    del payload["bias"]
    with pytest.raises(ValidationFailure) as excinfo:
        validate(json.dumps(payload), TechnicalOutput)
    assert any("bias" in reason for reason in excinfo.value.reasons)


def test_confidence_outside_its_range_is_rejected() -> None:
    with pytest.raises(ValidationFailure):
        validate(valid_technical(confidence=140.0), TechnicalOutput)


def test_unknown_enum_value_is_rejected() -> None:
    with pytest.raises(ValidationFailure):
        validate(valid_technical(bias="strong_buy"), TechnicalOutput)


def test_extra_fields_are_rejected() -> None:
    """Silent extras hide a drifting prompt; a loud failure surfaces it."""
    with pytest.raises(ValidationFailure):
        validate(valid_technical(target_price=9999), TechnicalOutput)


def test_execution_language_anywhere_in_the_payload_is_rejected() -> None:
    """Including inside a list - checking only `summary` would miss this."""
    with pytest.raises(ValidationFailure) as excinfo:
        validate(
            valid_technical(supporting_signals=["strong momentum", "buy now while it lasts"]),
            TechnicalOutput,
        )
    assert "execution-instruction language" in str(excinfo.value)


def test_language_failure_explains_how_to_rewrite() -> None:
    with pytest.raises(ValidationFailure) as excinfo:
        validate(valid_technical(summary="Buy now."), TechnicalOutput)
    instruction = excinfo.value.corrective_instruction.lower()
    assert "informational" in instruction
    assert "never tell the reader to transact" in instruction


def test_a_json_array_is_rejected() -> None:
    with pytest.raises(ValidationFailure, match="JSON object"):
        validate("[1, 2, 3]", TechnicalOutput)


# --- Manager & composer ----------------------------------------------------


def test_builtin_catalog_resolves_without_a_database() -> None:
    template = PromptManager().get("technical_analysis")
    assert template.category == "technical"


def test_unknown_template_lists_what_is_available() -> None:
    with pytest.raises(PromptNotFoundError, match="technical_analysis"):
        PromptManager().get("does_not_exist")


def test_composer_produces_a_system_and_user_message() -> None:
    prompt = PromptComposer().compose(
        "technical_analysis",
        {
            "ticker": "BBCA",
            "exchange": "IDX",
            "timeframe": "1d",
            "as_of": "2026-01-01",
            "indicators": {"rsi": 55},
            "features": {},
            "structure": "uptrend",
            "breakout": {},
            "support": [],
            "resistance": [],
        },
        TechnicalOutput,
    )
    assert [m.role for m in prompt.messages] == ["system", "user"]
    assert "BBCA" in prompt.messages[1].content
    assert prompt.template_version == catalog.CATALOG_VERSION


def test_corrective_instruction_is_appended_as_a_separate_turn() -> None:
    """A retry should read as a correction to a specific answer."""
    prompt = PromptComposer().compose(
        "market_context",
        {
            "ticker": "BBCA",
            "exchange": "IDX",
            "sector": "banking",
            "as_of": "x",
            "price_context": {},
        },
        TechnicalOutput,
        corrective_instruction="Your previous reply was not valid JSON.",
    )
    assert len(prompt.messages) == 3
    assert prompt.messages[-1].role == "user"
    assert "not valid JSON" in prompt.messages[-1].content


def test_database_template_takes_precedence_over_the_catalog(session) -> None:
    from aidss.db.models import PromptTemplate as Row

    session.add(
        Row(
            name="technical_analysis",
            category="technical",
            template_text="OVERRIDDEN SYSTEM PROMPT",
            version="9.9.9",
            is_active=True,
        )
    )
    session.flush()

    template = PromptManager(session).get("technical_analysis")
    assert template.version == "9.9.9"
    assert "OVERRIDDEN" in template.system


def test_seeding_the_catalog_is_idempotent(session) -> None:
    manager = PromptManager(session)
    first = manager.seed_catalog()
    second = manager.seed_catalog()
    assert first == len(catalog.ALL_TEMPLATES)
    assert second == 0


def test_seeding_does_not_overwrite_an_operator_edit(session) -> None:
    from sqlalchemy import select

    from aidss.db.models import PromptTemplate as Row

    manager = PromptManager(session)
    manager.seed_catalog()

    row = session.scalar(select(Row).where(Row.name == "synthesis"))
    row.template_text = "Operator's tuned prompt"
    session.flush()

    manager.seed_catalog()
    reread = session.scalar(select(Row).where(Row.name == "synthesis"))
    assert reread.template_text == "Operator's tuned prompt"


def test_the_sentiment_prompt_names_the_fields_its_schema_requires() -> None:
    """A prompt that asks for one word while the schema demands another is a
    silent, total failure: every response is rejected, the retry corrects
    nothing because the wording is unchanged, and the caller records a warning
    rather than an error.

    That happened here - the prompt said "a short reason", the schema required
    `rationale` and forbade extras, and sentiment scoring produced no rows at
    all for as long as it had existed.
    """
    from aidss.prompts.catalog import SENTIMENT_SCORING
    from aidss.prompts.schemas import ArticleSentiment

    text = f"{SENTIMENT_SCORING.system}\n{SENTIMENT_SCORING.user}"
    required = [
        name
        for name, field in ArticleSentiment.model_fields.items()
        if field.is_required()
    ]
    assert required, "the schema must have required fields for this to mean anything"

    missing = [name for name in required if name not in text]
    assert not missing, (
        f"the sentiment prompt never names {missing}, so the model has to guess "
        f"what to call them"
    )
