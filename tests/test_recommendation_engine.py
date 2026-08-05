"""Section 5.4 rules and the Recommendation Engine (Phase 5).

Section 15 sets the Phase 5 deliverable as "recommendations pass schema
validation 100%". The way to achieve that is to make storing an invalid one
impossible, which is what these tests hold the engine to.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from aidss.agents.base import AgentRunner
from aidss.agents.context import ContextBuilder
from aidss.agents.engine import AnalysisEngine
from aidss.collectors.market_data import MarketDataCollector
from aidss.config import Settings
from aidss.db.models import Recommendation, User
from aidss.domain.types import ChatCompletion, RecommendationLabel, Timeframe
from aidss.plugins.adapters.ai_fixture import FixtureAIProvider
from aidss.plugins.registry import get_market_data_provider
from aidss.prompts.schemas import Bias, RecommendationOutput
from aidss.recommendations.calibration import calibrate
from aidss.recommendations.engine import RecommendationEngine, RecommendationRejected
from aidss.recommendations.rules import check
from aidss.security.passwords import hash_password
from tests.test_agents import make_gateway
from tests.test_recommendation_calibration import fundamental, news, technical

# --- Fixtures --------------------------------------------------------------


@pytest.fixture
def user(session) -> User:
    row = User(email="rec-test@example.com", password_hash=hash_password("correct-horse-battery"))
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def asset(session):
    collector = MarketDataCollector(
        get_market_data_provider(Settings(market_data_provider="fixture"))
    )
    row = collector.get_or_create_asset(session, "BBCA", sector="Financials")
    end = datetime(2025, 6, 1, tzinfo=UTC)
    collector.collect(session, row, Timeframe.D1, end - timedelta(days=400), end)
    return row


def recommendation_payload(**overrides) -> dict:
    payload = {
        "summary": "A watchlist stance given thin coverage.",
        "data_sufficiency": "partial",
        "confidence": 75.0,
        "label": "watchlist",
        "reasoning": "Momentum is mid-range and no fundamental data exists.",
        "supporting_factors": ["price above the medium-term average"],
        "conflicting_factors": ["trend strength is weak"],
        "risk_factors": ["conclusions rest on price data alone"],
        "bullish_scenario": "A close above the nearest resistance would confirm continuation.",
        "bearish_scenario": "A loss of the nearest support would invalidate the reading.",
        "horizon": "medium",
    }
    payload.update(overrides)
    return payload


def output(**overrides) -> RecommendationOutput:
    return RecommendationOutput.model_validate(recommendation_payload(**overrides))


def scripted(*responses: dict) -> FixtureAIProvider:
    """A provider that answers the Recommendation Agent from a script."""
    queue = [json.dumps(r) for r in responses]

    class Scripted(FixtureAIProvider):
        def chat_completion(self, messages, **kwargs):
            self.calls.append(list(messages))
            joined = "\n".join(m.content for m in messages)
            if "Recommendation Agent" in joined and queue:
                content = queue.pop(0) if len(queue) > 1 else queue[0]
                return ChatCompletion(
                    content=content, model="fixture-model", prompt_tokens=10, completion_tokens=5
                )
            return super().chat_completion(messages, **kwargs)

    return Scripted()


# --- Rules -----------------------------------------------------------------


THIN = {"technical_analyzer": technical(Bias.NEUTRAL)}
BROAD_BULLISH = {
    "technical_analyzer": technical(Bias.BULLISH),
    "fundamental_analyzer": fundamental(Bias.BULLISH),
    "news_analyzer": news(0.7),
}


def calibration_for(outputs, supporting=2, conflicting=2):
    return calibrate(outputs, supporting_count=supporting, conflicting_count=conflicting)


def test_a_complete_recommendation_passes() -> None:
    assert check(output(), calibration_for(THIN)).ok


def test_empty_conflicting_factors_is_rejected() -> None:
    """The single most important rule in Section 5.4.

    A recommendation that can find nothing against itself has not been
    examined, and the requirement exists to make confirmation bias structurally
    difficult rather than merely discouraged.
    """
    report = check(output(conflicting_factors=[]), calibration_for(THIN))
    assert not report.ok
    assert any(v.rule == "conflicting_factors_required" for v in report.violations)


def test_whitespace_does_not_satisfy_the_conflicting_factors_requirement() -> None:
    report = check(output(conflicting_factors=["   "]), calibration_for(THIN))
    assert not report.ok


def test_empty_supporting_factors_is_rejected() -> None:
    assert not check(output(supporting_factors=[]), calibration_for(THIN)).ok


def test_empty_risk_factors_is_rejected() -> None:
    assert not check(output(risk_factors=[]), calibration_for(THIN)).ok


@pytest.mark.parametrize("field", ["reasoning", "bullish_scenario", "bearish_scenario"])
def test_a_blank_mandatory_narrative_is_rejected(field: str) -> None:
    """Pydantic proves a field exists; this proves someone filled it in."""
    report = check(output(**{field: "   "}), calibration_for(THIN))
    assert not report.ok
    assert any(field in v.detail for v in report.violations)


def test_a_label_contradicting_unanimous_evidence_is_rejected() -> None:
    bearish = {
        "technical_analyzer": technical(Bias.BEARISH),
        "fundamental_analyzer": fundamental(Bias.BEARISH),
    }
    report = check(output(label="buy"), calibration_for(bearish))
    assert not report.ok
    assert any(v.rule == "label_contradicts_evidence" for v in report.violations)


def test_split_evidence_does_not_trigger_the_contradiction_check() -> None:
    """The rule catches a genuine contradiction, not every judgement call."""
    split = {
        "technical_analyzer": technical(Bias.BULLISH),
        "fundamental_analyzer": fundamental(Bias.BEARISH),
    }
    report = check(output(label="buy"), calibration_for(split))
    assert not any(v.rule == "label_contradicts_evidence" for v in report.violations)


def test_a_neutral_label_never_contradicts_the_evidence() -> None:
    bearish = {"technical_analyzer": technical(Bias.BEARISH)}
    report = check(output(label="watchlist"), calibration_for(bearish))
    assert not any(v.rule == "label_contradicts_evidence" for v in report.violations)


def test_a_strong_label_on_thin_evidence_is_rejected() -> None:
    """"Strong Buy" on one lone signal is the misleading output of Section 17."""
    report = check(output(label="strong_buy"), calibration_for(THIN))
    assert not report.ok
    assert any(v.rule == "strong_label_needs_confidence" for v in report.violations)


def test_a_strong_label_on_broad_agreeing_evidence_passes() -> None:
    report = check(output(label="strong_buy"), calibration_for(BROAD_BULLISH, 4, 3))
    assert report.ok


def test_the_correction_tells_the_model_what_to_do_instead() -> None:
    """A retry that only says "wrong" reproduces the same answer."""
    report = check(output(label="strong_buy", conflicting_factors=[]), calibration_for(THIN))
    instruction = report.corrective_instruction()
    assert "conflicting_factors" in instruction
    assert "watchlist" in instruction or "weaker" in instruction


# --- Engine ----------------------------------------------------------------


def build(session, asset, provider=None):
    context = ContextBuilder(session).build(asset, Timeframe.D1)
    gateway = make_gateway(provider or FixtureAIProvider())
    return context, RecommendationEngine(session, AgentRunner(gateway))


def analyzer_runs(session, asset, provider=None):
    """Run the analyzers so the recommendation has real inputs."""
    run = AnalysisEngine(session, make_gateway(provider or FixtureAIProvider())).analyze(
        asset, Timeframe.D1, persist=False, include_recommendation=False
    )
    return run


def test_the_engine_produces_the_full_section_5_4_structure(session, asset) -> None:
    run = analyzer_runs(session, asset)
    context, engine = build(session, asset)
    result = engine.generate(context, run.analyzer_runs, run.synthesis, persist=False)

    payload = result.as_payload()
    for field in (
        "label",
        "confidence",
        "reasoning",
        "supporting_factors",
        "conflicting_factors",
        "risk_factors",
        "bullish_scenario",
        "bearish_scenario",
        "support_level",
        "resistance_level",
        "target_price",
        "suggested_stop",
        "horizon",
    ):
        assert field in payload, f"Section 5.4 field missing: {field}"


def test_the_published_confidence_is_the_calibrated_one(session, asset) -> None:
    """The fixture reports 75; the evidence supports considerably less."""
    run = analyzer_runs(session, asset)
    context, engine = build(session, asset)
    result = engine.generate(context, run.analyzer_runs, run.synthesis, persist=False)

    assert result.output.confidence == 75.0, "the model's self-report"
    assert result.calibration.confidence != 75.0
    assert result.as_payload()["confidence"] == result.calibration.confidence
    assert result.as_payload()["model_self_reported_confidence"] == 75.0


def test_prices_are_measured_not_generated(session, asset) -> None:
    """Every price traces back to the Indicator Engine, with its method named."""
    run = analyzer_runs(session, asset)
    context, engine = build(session, asset)
    result = engine.generate(context, run.analyzer_runs, run.synthesis, persist=False)

    snapshot_levels = context.indicator_snapshot["levels"]
    if snapshot_levels["support"]:
        assert float(result.levels.support) == pytest.approx(
            snapshot_levels["support"][0], abs=0.01
        )
    # The schema the model answers with has no price field at all.
    assert not hasattr(result.output, "target_price")


def test_conflicting_factors_are_never_empty_in_a_stored_result(session, asset) -> None:
    run = analyzer_runs(session, asset)
    context, engine = build(session, asset)
    result = engine.generate(context, run.analyzer_runs, run.synthesis, persist=False)
    assert result.output.conflicting_factors


def test_a_rule_violation_is_retried_with_a_correction(session, asset) -> None:
    """The first answer over-claims; the correction names the fix."""
    provider = scripted(
        recommendation_payload(label="strong_buy"),
        recommendation_payload(label="buy"),
    )
    run = analyzer_runs(session, asset)
    context, engine = build(session, asset, provider)
    result = engine.generate(context, run.analyzer_runs, run.synthesis, persist=False)

    assert result.output.label is RecommendationLabel.BUY

    # Two calls actually reached the Recommendation Agent: the rejected one
    # and the corrected one.
    recommendation_calls = [
        call for call in provider.calls if any("Recommendation Agent" in m.content for m in call)
    ]
    assert len(recommendation_calls) == 2

    # The second carried the specific reason, not a bare "try again".
    correction = recommendation_calls[-1][-1].content
    assert "strong_buy" in correction
    assert "calibrated confidence" in correction


def test_a_persistently_invalid_recommendation_is_rejected(session, asset) -> None:
    """Better no recommendation than one whose evidence was never weighed."""
    provider = scripted(recommendation_payload(conflicting_factors=[]))
    run = analyzer_runs(session, asset)
    context, engine = build(session, asset, provider)

    with pytest.raises(RecommendationRejected, match="conflicting_factors"):
        engine.generate(context, run.analyzer_runs, run.synthesis, persist=False)


def test_execution_language_in_a_recommendation_is_still_caught(session, asset) -> None:
    """The generic guard applies here too - this is where it matters most."""
    from aidss.prompts.validator import ValidationFailure

    provider = scripted(
        recommendation_payload(reasoning="Momentum is strong. Buy now before it runs.")
    )
    run = analyzer_runs(session, asset)
    context, engine = build(session, asset, provider)

    with pytest.raises(ValidationFailure, match="execution-instruction"):
        engine.generate(context, run.analyzer_runs, run.synthesis, persist=False)


# --- Persistence and orchestration ----------------------------------------


def test_the_analysis_run_stores_a_recommendation_row(session, asset, user) -> None:
    run = AnalysisEngine(session, make_gateway()).analyze(asset, Timeframe.D1, user_id=user.id)

    assert run.recommendation is not None
    row = session.scalar(select(Recommendation))
    assert row is not None
    assert row.analysis_result_id == run.analysis_result_id
    assert row.confidence == run.recommendation.calibration.confidence
    assert row.conflicting_factors
    assert row.label in set(RecommendationLabel)


def test_the_stored_confidence_is_within_the_declared_range(session, asset, user) -> None:
    AnalysisEngine(session, make_gateway()).analyze(asset, Timeframe.D1, user_id=user.id)
    row = session.scalar(select(Recommendation))
    assert 0 <= row.confidence <= 100


def test_the_recommendation_agent_is_not_counted_as_an_evidence_source(
    session, asset, user
) -> None:
    """Otherwise it would feed its own conclusion back into its confidence."""
    run = AnalysisEngine(session, make_gateway()).analyze(asset, Timeframe.D1, user_id=user.id)
    assert "recommendation_agent" not in {r.agent for r in run.analyzer_runs}
    assert "recommendation_agent" in {r.agent for r in run.runs}


def test_recommendation_can_be_skipped(session, asset, user) -> None:
    run = AnalysisEngine(session, make_gateway()).analyze(
        asset, Timeframe.D1, user_id=user.id, include_recommendation=False
    )
    assert run.recommendation is None
    assert session.scalar(select(Recommendation)) is None


def test_a_rejected_recommendation_is_reported_not_stored(session, asset, user) -> None:
    provider = scripted(recommendation_payload(conflicting_factors=[]))
    run = AnalysisEngine(session, make_gateway(provider)).analyze(
        asset, Timeframe.D1, user_id=user.id
    )

    assert run.recommendation is None
    assert any(f.agent == "recommendation_agent" for f in run.failed)
    assert session.scalar(select(Recommendation)) is None
    # The rest of the analysis survived.
    assert any(r.agent == "technical_analyzer" for r in run.runs)


def test_no_recommendation_without_analyzer_output(session, user) -> None:
    from aidss.db.models import Asset

    empty = Asset(ticker="EMPTY", exchange="IDX")
    session.add(empty)
    session.flush()

    run = AnalysisEngine(session, make_gateway()).analyze(empty, Timeframe.D1, user_id=user.id)
    assert run.recommendation is None


def test_the_stored_snapshot_includes_the_recommendation(session, asset, user) -> None:
    from aidss.db.models import AnalysisResult

    run = AnalysisEngine(session, make_gateway()).analyze(asset, Timeframe.D1, user_id=user.id)
    stored = session.get(AnalysisResult, run.analysis_result_id)
    assert stored.context_snapshot["result"]["recommendation"]["label"]


# --- Announcing a finished analysis ----------------------------------------
#
# An analysis is worth several seconds of model time and then sits in the
# database unread. These cover the notification that says it is there - and
# that producing it can never cost the analysis itself.


def _notes(session, user_id):
    from aidss.db.models import Notification

    return list(
        session.scalars(select(Notification).where(Notification.user_id == user_id)).all()
    )


def test_a_finished_analysis_notifies_the_person_who_asked(session, asset, user) -> None:
    run = AnalysisEngine(session, make_gateway()).analyze(asset, Timeframe.D1, user_id=user.id)

    [note] = _notes(session, user.id)
    assert note.event == "analysis_ready"
    assert "BBCA" in note.message
    assert note.context["ticker"] == "BBCA"
    assert note.context["timeframe"] == Timeframe.D1.value
    assert note.context["analysis_result_id"] == str(run.analysis_result_id)
    # Carried as a number, not only inside the sentence: the interface composes
    # the line in the reader's language, and a stored English string cannot
    # follow a language switch made after it was written.
    assert note.context["agents"] == len(run.runs)


def test_the_stance_travels_as_data_not_as_prose(session, asset, user) -> None:
    """Same rule as alerts. The message is read in two seconds, stripped of the
    confidence and the counter-evidence that surround it on the analysis screen,
    so nothing in it may read as a call to transact."""
    import re

    AnalysisEngine(session, make_gateway()).analyze(asset, Timeframe.D1, user_id=user.id)

    [note] = _notes(session, user.id)
    text = f"{note.subject} {note.message}".lower()
    for word in ("buy", "sell", "order", "execute", "trade", "beli", "jual"):
        assert not re.search(rf"\b{word}\b", text), f"{word!r} in {text!r}"

    # ...but it is still available to the interface, which renders it beside
    # the link back to where the reasoning is.
    assert note.context["stance"] in {label.value for label in RecommendationLabel}
    assert 0 <= note.context["confidence"] <= 100


def test_an_analysis_nobody_asked_for_notifies_nobody(session, asset) -> None:
    """A scheduled backfill has no user to tell, and inventing one would send a
    notification to somebody who never requested the analysis."""
    from aidss.db.models import Notification

    AnalysisEngine(session, make_gateway()).analyze(asset, Timeframe.D1)
    assert session.scalar(select(Notification)) is None


def test_a_broken_notifier_does_not_lose_the_analysis(session, asset, user, monkeypatch) -> None:
    """The analysis is already stored by the time this runs. Throwing here would
    report failure for work sitting in the database."""
    from aidss.agents import engine as engine_module

    def explode(*args, **kwargs):
        raise RuntimeError("notification backend is down")

    monkeypatch.setattr(engine_module.NotificationService, "notify", explode)

    run = AnalysisEngine(session, make_gateway()).analyze(
        asset, Timeframe.D1, user_id=user.id
    )

    assert run.analysis_result_id is not None
    assert session.scalar(select(Recommendation)) is not None
