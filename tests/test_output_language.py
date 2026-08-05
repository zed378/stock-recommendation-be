"""The output language is asked for, not assumed.

Nothing in the prompts named a language. The model answered in whatever it
preferred - English, in practice - while the stored `language` column recorded
the default nobody had checked. Producing two languages is what exposed it: the
"translation" came back word for word identical to the "original", because both
were English.

A column that records an assumption is worse than one that records nothing: it
looks like a fact, and everything downstream treats it as one.
"""

from __future__ import annotations

import re

import pytest

from aidss.prompts import catalog
from aidss.prompts.language import LANGUAGE_RULE, OutputLanguage, output_language_rule
from aidss.prompts.manager import PromptComposer
from aidss.prompts.schemas import OUTPUT_MODELS


def test_the_rule_names_the_language_in_words_the_model_understands() -> None:
    assert "Indonesian" in output_language_rule(OutputLanguage.ID)
    assert "English" in output_language_rule(OutputLanguage.EN)


def test_the_rule_exempts_schema_keys() -> None:
    """Translating a field name produces a document that fails validation."""
    rule = output_language_rule(OutputLanguage.ID)
    assert "JSON field names" in rule
    assert "enum values" in rule


def test_the_rule_covers_input_in_another_language() -> None:
    """IDX filings and headlines arrive in Indonesian and the indicators are
    named in English; without this the model follows whichever it saw last."""
    assert "even when the input data" in output_language_rule(OutputLanguage.EN)


@pytest.mark.parametrize("template", catalog.ALL_TEMPLATES, ids=lambda t: t.name)
def test_every_template_can_state_an_output_language(template) -> None:
    rendered = template.render_system("{}", OutputLanguage.ID)
    assert "OUTPUT LANGUAGE" in rendered
    # And the execution-language guard is still there: the two rules are about
    # different things and neither replaces the other.
    assert LANGUAGE_RULE in rendered


@pytest.mark.parametrize("template", catalog.ALL_TEMPLATES, ids=lambda t: t.name)
def test_omitting_the_language_leaves_the_prompt_otherwise_unchanged(template) -> None:
    """Optional so existing callers keep working, rather than every call site
    having to be updated at once."""
    assert "OUTPUT LANGUAGE" not in template.render_system("{}")


def context_for(template) -> dict[str, str]:
    """Every placeholder the template interpolates, filled with a stub.

    Read off the template rather than listed by hand. A hand-written fixture
    goes stale the moment a placeholder is added, and the failure - a KeyError
    from `str.format` - reads like a bug in the composer rather than an
    incomplete test.
    """
    return {key: "-" for key in set(re.findall(r"\{(\w+)\}", template.user))}


def compose(name: str, agent: str, **kwargs):
    template = catalog.BY_NAME[name]
    composer = PromptComposer(language=kwargs.pop("composer_language", None))
    return composer.compose(
        name, context_for(template), OUTPUT_MODELS[agent], **kwargs
    )


def test_the_composer_asks_for_the_configured_language() -> None:
    prompt = compose(
        "technical_analysis", "technical_analyzer", composer_language=OutputLanguage.ID
    )
    assert "Indonesian" in prompt.messages[0].content


def test_the_composer_can_be_overridden_per_call() -> None:
    prompt = compose(
        "technical_analysis",
        "technical_analyzer",
        composer_language=OutputLanguage.ID,
        language=OutputLanguage.EN,
    )
    assert "English" in prompt.messages[0].content


@pytest.mark.parametrize(
    ("name", "agent"),
    [
        ("technical_analysis", "technical_analyzer"),
        ("fundamental_analysis", "fundamental_analyzer"),
        ("recommendation", "recommendation_agent"),
    ],
)
def test_the_language_reaches_every_agent_not_just_one(name: str, agent: str) -> None:
    """The recommendation is the one a reader acts on, so it is the one that
    must not quietly come back in a different language from the analysis."""
    prompt = compose(name, agent, composer_language=OutputLanguage.ID)
    assert "Indonesian" in prompt.messages[0].content


def test_the_default_is_indonesian() -> None:
    """This is an IDX product read by Indonesian investors; the other language
    is rendered from it during the same run."""
    from aidss.config import Settings

    settings = Settings(jwt_secret="test-secret-not-for-production-0123456789abcdef")
    assert settings.analysis_language == "id"


def test_the_runner_reports_the_language_it_asks_for() -> None:
    """Read off the composer rather than from settings again: the two could
    drift, and a stored analysis needs the language it was actually asked for."""
    from aidss.agents.base import AgentRunner

    runner = AgentRunner(gateway=None, composer=PromptComposer(language=OutputLanguage.EN))  # type: ignore[arg-type]
    assert runner.language is OutputLanguage.EN
