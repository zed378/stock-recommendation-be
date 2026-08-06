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
from datetime import UTC, datetime, timedelta

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


def test_the_default_is_english() -> None:
    """English is the authoritative one: the models available here reason more
    reliably in it, and every rule the output is checked against - the
    execution-language guard above all - was written and tested against English
    text. Indonesian is rendered from it during the same run and stored beside
    it, so an Indonesian reader waits for nothing."""
    from aidss.config import Settings

    settings = Settings(jwt_secret="test-secret-not-for-production-0123456789abcdef")
    assert settings.analysis_language == "en"


def test_the_runner_reports_the_language_it_asks_for() -> None:
    """Read off the composer rather than from settings again: the two could
    drift, and a stored analysis needs the language it was actually asked for."""
    from aidss.agents.base import AgentRunner

    runner = AgentRunner(gateway=None, composer=PromptComposer(language=OutputLanguage.EN))  # type: ignore[arg-type]
    assert runner.language is OutputLanguage.EN


def test_every_agent_stores_its_own_rendering(session, monkeypatch) -> None:
    """The analysis tab shows what each agent found, not only the conclusion. A
    switch that translated the recommendation and left the evidence beneath it
    in the other language would be half a feature - and fetching six
    translations on demand is the cost this was moved into the run to avoid.
    """
    from aidss.agents.engine import AnalysisEngine
    from aidss.collectors.market_data import MarketDataCollector
    from aidss.config import Settings
    from aidss.domain.types import Timeframe
    from aidss.plugins.registry import get_market_data_provider
    from aidss.prompts import translation as translation_module
    from aidss.prompts.language import OutputLanguage
    from tests.test_agents import make_gateway

    collector = MarketDataCollector(
        get_market_data_provider(Settings(market_data_provider="fixture"))
    )
    asset = collector.get_or_create_asset(session, "BBCA", sector="Financials")
    end = datetime(2025, 6, 1, tzinfo=UTC)
    collector.collect(session, asset, Timeframe.D1, end - timedelta(days=400), end)

    def fake_translate(gateway, payload, target, **kwargs):  # noqa: ANN001, ANN202, ARG001
        fields = translation_module.translatable_fields(payload)
        return translation_module.Translation(
            language=target,
            fields={key: f"[{target.value}] {value}" for key, value in fields.items()},
            model="stub-translator",
        )

    monkeypatch.setattr("aidss.agents.engine.translate", fake_translate)

    run = AnalysisEngine(session, make_gateway()).analyze(asset, Timeframe.D1)
    target = OutputLanguage.EN if run.language == "id" else OutputLanguage.ID

    stored = run.as_payload()["agents"]
    assert stored, "the run produced no agents to translate"

    # Every agent, not merely one of them. Asserting that *some* agent carried
    # a rendering passed for weeks while the summary agent's lists and every
    # analyzer's notes went untranslated - the paragraph changed language and
    # the lists under it did not.
    from aidss.prompts.translation import translatable_fields

    missing = []
    for name, payload in stored.items():
        if not translatable_fields(payload):
            # Nothing but labels and numbers; a call here would spend tokens to
            # return what it was given.
            continue
        rendered = payload["translations"].get(target.value, {}).get("fields")
        if not rendered:
            missing.append(name)
            continue

        assert stored[name]["language"] == run.language
        assert stored[name]["translations"][target.value]["is_machine_translation"] is True
        # And the rendering covers the same fields the original had prose in,
        # not a subset - a card showing three of five translated sections is
        # the failure this is here to prevent.
        assert set(rendered) == set(translatable_fields(payload)), name

    assert not missing, f"these agents carried no rendering at all: {sorted(missing)}"


def test_a_failed_agent_translation_does_not_lose_the_analysis(session, monkeypatch) -> None:
    """The analysis is the product; a rendering is a convenience."""
    from aidss.agents.engine import AnalysisEngine
    from aidss.collectors.market_data import MarketDataCollector
    from aidss.config import Settings
    from aidss.domain.types import Timeframe
    from aidss.plugins.registry import get_market_data_provider
    from tests.test_agents import make_gateway

    collector = MarketDataCollector(
        get_market_data_provider(Settings(market_data_provider="fixture"))
    )
    asset = collector.get_or_create_asset(session, "BBRI", sector="Financials")
    end = datetime(2025, 6, 1, tzinfo=UTC)
    collector.collect(session, asset, Timeframe.D1, end - timedelta(days=400), end)

    def explode(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise ValueError("the translation dropped a key")

    monkeypatch.setattr("aidss.agents.engine.translate", explode)

    run = AnalysisEngine(session, make_gateway()).analyze(asset, Timeframe.D1)

    assert run.runs, "the analysis itself must survive"
    assert all(
        not payload["translations"] for payload in run.as_payload()["agents"].values()
    )


def test_the_stored_row_records_the_language_the_prompt_asked_for(session) -> None:
    """The column was never written, so it took the model's default of "id"
    whatever the prompt had said. English analyses were stored claiming to be
    Indonesian - and the switch then offered to translate them into the
    language they were already in, which no stored rendering could satisfy.

    `RecommendationResult.language` was set correctly all along, which is why
    the API response looked right and only the database was wrong.
    """
    from sqlalchemy import select

    from aidss.agents.engine import AnalysisEngine
    from aidss.collectors.market_data import MarketDataCollector
    from aidss.config import Settings
    from aidss.db.models import Recommendation
    from aidss.domain.types import Timeframe
    from aidss.plugins.registry import get_market_data_provider
    from tests.test_agents import make_gateway

    collector = MarketDataCollector(
        get_market_data_provider(Settings(market_data_provider="fixture"))
    )
    asset = collector.get_or_create_asset(session, "TLKM", sector="Infrastructure")
    end = datetime(2025, 6, 1, tzinfo=UTC)
    collector.collect(session, asset, Timeframe.D1, end - timedelta(days=400), end)

    run = AnalysisEngine(session, make_gateway()).analyze(
        asset, Timeframe.D1, translate_output=False
    )
    assert run.recommendation is not None

    row = session.scalar(select(Recommendation))
    assert row is not None
    assert row.language == run.language


def test_translation_covers_every_prose_field() -> None:
    """The list of translatable keys was written when only the recommendation
    was rendered, and it covered that payload exactly. Once every agent's own
    write-up started being translated it covered barely a third of what a
    reader sees - the summary agent's `watch_items` and `disagreements`, every
    analyzer's notes - so a card came back with its paragraph in one language
    and its lists in the other.

    Holding the list to the schemas is what turns the next added field into a
    failing test rather than another half-translated section.
    """
    from aidss.prompts.schemas import OUTPUT_MODELS
    from aidss.prompts.translation import NOT_TRANSLATED, TRANSLATABLE_KEYS

    known = TRANSLATABLE_KEYS | NOT_TRANSLATED
    unclassified: dict[str, set[str]] = {}

    for agent, model in OUTPUT_MODELS.items():
        for name, field in model.model_fields.items():
            # Only free text. Numbers, enums, and booleans are carried through
            # unchanged - a translated stance label is a value the enum does
            # not contain, and a translated price is nonsense.
            if field.annotation not in (str, list[str], str | None):
                continue
            if name not in known:
                unclassified.setdefault(name, set()).add(agent)

    assert not unclassified, (
        "these prose fields are neither translated nor explicitly excluded, so "
        "they would stay in the source language while the text around them "
        f"changed: { {k: sorted(v) for k, v in sorted(unclassified.items())} }"
    )


def test_nothing_is_both_translated_and_excluded() -> None:
    """Two lists that disagree would make the behaviour depend on which one a
    reader happened to check."""
    from aidss.prompts.translation import NOT_TRANSLATED, TRANSLATABLE_KEYS

    assert not (TRANSLATABLE_KEYS & NOT_TRANSLATED)


def test_the_summary_agents_lists_are_translated() -> None:
    """Named explicitly because this is the card the gap was noticed on: its
    paragraph changed language and its three lists did not."""
    from aidss.prompts.translation import TRANSLATABLE_KEYS

    for field in ("summary", "agreements", "disagreements", "watch_items", "risk_factors"):
        assert field in TRANSLATABLE_KEYS, field


# --- translation as its own job ---------------------------------------------


def _stored_analysis(session):
    """One persisted analysis, English only, exactly as `analysis.run` leaves it."""
    from aidss.agents.engine import AnalysisEngine
    from aidss.collectors.market_data import MarketDataCollector
    from aidss.config import Settings
    from aidss.db.models import AnalysisResult
    from aidss.domain.types import Timeframe
    from aidss.plugins.registry import get_market_data_provider
    from tests.test_agents import make_gateway

    collector = MarketDataCollector(
        get_market_data_provider(Settings(market_data_provider="fixture"))
    )
    asset = collector.get_or_create_asset(session, "ANTM", sector="Mining")
    end = datetime(2025, 6, 1, tzinfo=UTC)
    collector.collect(session, asset, Timeframe.D1, end - timedelta(days=400), end)

    run = AnalysisEngine(session, make_gateway()).analyze(
        asset, Timeframe.D1, translate_output=False
    )
    return run, session.get(AnalysisResult, run.analysis_result_id)


def _stub_translate(monkeypatch, calls=None):
    from aidss.prompts import translation as translation_module

    def fake(gateway, payload, target, **kwargs):  # noqa: ANN001, ANN202, ARG001
        fields = translation_module.translatable_fields(payload)
        if calls is not None:
            calls.append(kwargs.get("agent", "?"))
        return translation_module.Translation(
            language=target,
            fields={k: f"[{target.value}] {v}" for k, v in fields.items()},
            model="stub-translator",
        )

    monkeypatch.setattr("aidss.agents.engine.translate", fake)
    monkeypatch.setattr("aidss.recommendations.rendering.translate", fake)


def test_the_analysis_job_stores_one_language(session) -> None:
    """Translating inline made a slow run far slower for no benefit to the
    person waiting - and a gateway that gave up part-way took the finished
    analysis with it."""
    run, result = _stored_analysis(session)

    agents = result.context_snapshot["result"]["agents"]
    assert agents, "the analysis produced nothing to check"
    assert all(not a.get("translations") for a in agents.values())


def test_the_translation_job_fills_in_the_other_language(session, monkeypatch) -> None:
    from aidss.agents.engine import AnalysisEngine
    from aidss.prompts.translation import translatable_fields
    from tests.test_agents import make_gateway

    run, result = _stored_analysis(session)
    _stub_translate(monkeypatch)

    report = AnalysisEngine(session, make_gateway()).translate_stored(result)
    target = report["language"]

    assert report["agents"], "no agent was rendered"
    session.refresh(result)
    agents = result.context_snapshot["result"]["agents"]
    for name in report["agents"]:
        rendered = agents[name]["translations"][target]["fields"]
        assert set(rendered) == set(translatable_fields(agents[name])), name


def test_re_running_the_translation_pays_for_nothing_twice(session, monkeypatch) -> None:
    """A retry after a partial failure must not re-render what already
    succeeded; those tokens are spent."""
    from aidss.agents.engine import AnalysisEngine
    from tests.test_agents import make_gateway

    run, result = _stored_analysis(session)

    first: list[str] = []
    _stub_translate(monkeypatch, first)
    AnalysisEngine(session, make_gateway()).translate_stored(result)
    assert first, "the first pass rendered nothing"

    session.refresh(result)
    second: list[str] = []
    _stub_translate(monkeypatch, second)
    report = AnalysisEngine(session, make_gateway()).translate_stored(result)

    assert report["agents"] == [], "an already-rendered agent was translated again"


def test_a_failed_translation_leaves_the_analysis_readable(session, monkeypatch) -> None:
    """The analysis is the product; this is a convenience over it."""
    from aidss.agents.engine import AnalysisEngine
    from tests.test_agents import make_gateway

    run, result = _stored_analysis(session)

    def explode(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise ValueError("the gateway gave up")

    monkeypatch.setattr("aidss.agents.engine.translate", explode)
    monkeypatch.setattr("aidss.recommendations.rendering.translate", explode)

    report = AnalysisEngine(session, make_gateway()).translate_stored(result)

    assert report["agents"] == []
    session.refresh(result)
    assert result.context_snapshot["result"]["agents"], "the analysis itself must survive"
