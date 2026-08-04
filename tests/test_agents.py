"""Context Builder, Memory Manager, agents, and Analysis Engine (Section 5)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from aidss.agents.analyzers import (
    FundamentalAnalyzer,
    MarketAnalyzer,
    NewsAnalyzer,
    SummaryAgent,
    TechnicalAnalyzer,
)
from aidss.agents.base import AgentRunner
from aidss.agents.context import ContextBuilder
from aidss.agents.engine import AnalysisEngine
from aidss.agents.memory import MemoryManager, PreferenceKey
from aidss.collectors.market_data import MarketDataCollector
from aidss.config import Settings
from aidss.db.models import (
    AIMessage,
    AnalysisResult,
    FundamentalMetric,
    NewsItem,
    User,
    UserPreference,
)
from aidss.domain.types import ChatCompletion, Timeframe
from aidss.llm.gateway import LLMGateway
from aidss.llm.router import ModelRouter, ProviderBinding, TaskComplexity
from aidss.plugins.adapters.ai_fixture import FixtureAIProvider
from aidss.plugins.registry import get_market_data_provider
from aidss.prompts.validator import ValidationFailure
from aidss.security.passwords import hash_password
from tests.test_llm_gateway import FakeClock

# --- Fixtures --------------------------------------------------------------


@pytest.fixture
def user(session) -> User:
    row = User(email="agent-test@example.com", password_hash=hash_password("correct-horse-battery"))
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def asset(session):
    collector = MarketDataCollector(
        get_market_data_provider(Settings(market_data_provider="fixture"))
    )
    row = collector.get_or_create_asset(session, "BBCA", sector="Financials", industry="Banks")
    end = datetime(2025, 6, 1, tzinfo=UTC)
    collector.collect(session, row, Timeframe.D1, end - timedelta(days=400), end)
    return row


def make_gateway(provider: FixtureAIProvider | None = None) -> LLMGateway:
    provider = provider or FixtureAIProvider()
    return LLMGateway(
        ModelRouter(
            [
                ProviderBinding(
                    name="fixture",
                    provider=provider,
                    model="fixture-model",
                    handles=frozenset(TaskComplexity),
                    self_hosted=True,
                )
            ]
        ),
        clock=FakeClock(),
    )


# --- Memory Manager --------------------------------------------------------


def test_memory_returns_neutral_defaults_for_an_unknown_user(session) -> None:
    """Assuming an aggressive short-horizon investor would colour every analysis."""
    memory = MemoryManager(session).load(uuid.uuid4())
    assert memory.horizon == "medium"
    assert memory.risk_appetite == "moderate"
    assert not memory.high_privacy


def test_stated_preferences_are_loaded(session, user) -> None:
    manager = MemoryManager(session)
    manager.remember(user.id, PreferenceKey.HORIZON, "long")
    manager.remember(user.id, PreferenceKey.RISK_APPETITE, "conservative")

    memory = manager.load(user.id)
    assert memory.horizon == "long"
    assert memory.risk_appetite == "conservative"


def test_an_inferred_preference_never_overwrites_a_stated_one(session, user) -> None:
    """Reflecting a guess back as 'you told us' is how a product gets people wrong."""
    manager = MemoryManager(session)
    manager.remember(user.id, PreferenceKey.HORIZON, "long", source="stated")
    manager.remember(user.id, PreferenceKey.HORIZON, "short", source="inferred")
    assert manager.load(user.id).horizon == "long"


def test_a_stated_preference_may_be_updated(session, user) -> None:
    manager = MemoryManager(session)
    manager.remember(user.id, PreferenceKey.HORIZON, "short")
    manager.remember(user.id, PreferenceKey.HORIZON, "long")
    assert manager.load(user.id).horizon == "long"


def test_preferences_do_not_leak_between_users(session, user) -> None:
    other = User(
        email="other-agent@example.com", password_hash=hash_password("correct-horse-battery")
    )
    session.add(other)
    session.flush()

    manager = MemoryManager(session)
    manager.remember(user.id, PreferenceKey.RISK_APPETITE, "aggressive")
    assert manager.load(other.id).risk_appetite == "moderate"


def test_high_privacy_mode_is_detected(session, user) -> None:
    manager = MemoryManager(session)
    manager.remember(user.id, PreferenceKey.PRIVACY_MODE, "high")
    assert manager.load(user.id).high_privacy


def test_one_preference_per_user_and_key(session, user) -> None:
    from sqlalchemy import func, select

    manager = MemoryManager(session)
    manager.remember(user.id, PreferenceKey.HORIZON, "short")
    manager.remember(user.id, PreferenceKey.HORIZON, "long")
    count = session.scalar(
        select(func.count()).select_from(UserPreference).where(UserPreference.user_id == user.id)
    )
    assert count == 1


# --- Context Builder -------------------------------------------------------


def test_context_carries_indicators_and_features(session, asset, user) -> None:
    context = ContextBuilder(session).build(asset, Timeframe.D1, user_id=user.id)
    assert context.has_price_data
    assert context.indicator_snapshot["bars"] > 0
    assert "rsi(period=14)" in context.indicator_snapshot["indicators"]
    assert context.features["return_1b"] is not None


def test_context_reports_absent_sources_rather_than_faking_them(session, asset) -> None:
    context = ContextBuilder(session).build(asset, Timeframe.D1)
    assert not context.has_fundamentals
    assert not context.has_news


def test_context_picks_up_fundamentals_when_present(session, asset) -> None:
    from datetime import date

    session.add(
        FundamentalMetric(
            asset_id=asset.id,
            period=date(2025, 3, 31),
            metric_name="pe_ratio",
            value=18.4,
            source="test",
        )
    )
    session.flush()
    context = ContextBuilder(session).build(asset, Timeframe.D1)
    assert context.has_fundamentals
    assert context.fundamentals[0]["metric"] == "pe_ratio"


def test_news_outside_the_window_is_excluded(session, asset) -> None:
    """Sentiment decays; a six-month-old headline is history, not signal."""
    now = datetime(2025, 6, 1, tzinfo=UTC)
    session.add(
        NewsItem(
            asset_id=asset.id,
            source="test",
            source_url="https://example.invalid/recent",
            dedup_hash="hash-recent",
            headline="Recent coverage",
            published_at=now - timedelta(days=3),
        )
    )
    session.add(
        NewsItem(
            asset_id=asset.id,
            source="test",
            source_url="https://example.invalid/ancient",
            dedup_hash="hash-ancient",
            headline="Ancient coverage",
            published_at=now - timedelta(days=200),
        )
    )
    session.flush()

    context = ContextBuilder(session, now=now).build(asset, Timeframe.D1)
    assert [n["headline"] for n in context.news] == ["Recent coverage"]


def test_snapshot_excludes_raw_candles(session, asset) -> None:
    """Hundreds of bars per row would bloat every stored analysis."""
    snapshot = ContextBuilder(session).build(asset, Timeframe.D1).snapshot()
    assert "candles" not in snapshot
    assert snapshot["bars"] > 0
    assert snapshot["indicators"]


# --- Agent applicability ---------------------------------------------------


def test_analyzers_requiring_missing_data_decline_to_run(session, asset) -> None:
    """Narrating an empty table is the failure mode, not a missing narration."""
    context = ContextBuilder(session).build(asset, Timeframe.D1)
    assert TechnicalAnalyzer().is_applicable(context)
    assert MarketAnalyzer().is_applicable(context)
    assert not FundamentalAnalyzer().is_applicable(context)
    assert not NewsAnalyzer().is_applicable(context)


def test_summary_needs_at_least_two_analyzer_outputs(session, asset) -> None:
    context = ContextBuilder(session).build(asset, Timeframe.D1)
    assert not SummaryAgent([]).is_applicable(context)


def test_technical_prompt_context_contains_only_computed_numbers(session, asset) -> None:
    context = ContextBuilder(session).build(asset, Timeframe.D1)
    variables = TechnicalAnalyzer().prompt_context(context)
    assert variables["ticker"] == "BBCA"
    assert variables["indicators"]
    assert "support" in variables and "resistance" in variables


# --- Agent runner ----------------------------------------------------------


def test_runner_validates_and_returns_typed_output(session, asset) -> None:
    context = ContextBuilder(session).build(asset, Timeframe.D1)
    run = AgentRunner(make_gateway()).run(TechnicalAnalyzer(), context)
    assert run.agent == "technical_analyzer"
    assert 0 <= run.output.confidence <= 100
    assert run.attempts == 1


def test_runner_retries_with_corrective_feedback_after_bad_json(session, asset) -> None:
    """A blind retry usually reproduces the same mistake; feedback does not."""
    calls = {"n": 0}
    good = json.dumps(
        {
            "summary": "Momentum is mid-range.",
            "data_sufficiency": "sufficient",
            "confidence": 55.0,
            "bias": "neutral",
            "supporting_signals": [],
            "conflicting_signals": [],
            "level_commentary": "",
        }
    )

    class FlakyProvider(FixtureAIProvider):
        def chat_completion(self, messages, **kwargs):
            calls["n"] += 1
            self.calls.append(list(messages))
            content = "not json at all" if calls["n"] == 1 else good
            return ChatCompletion(
                content=content, model="fixture-model", prompt_tokens=10, completion_tokens=5
            )

    provider = FlakyProvider()
    context = ContextBuilder(session).build(asset, Timeframe.D1)
    run = AgentRunner(make_gateway(provider)).run(TechnicalAnalyzer(), context)

    assert run.attempts == 2
    # The retry told the model what was wrong.
    assert any("not valid JSON" in m.content for m in provider.calls[-1])


def test_runner_gives_up_after_the_retry_budget(session, asset) -> None:
    provider = FixtureAIProvider(scripted={"technical_analyzer": "still not json"})
    context = ContextBuilder(session).build(asset, Timeframe.D1)
    with pytest.raises(ValidationFailure):
        AgentRunner(make_gateway(provider)).run(TechnicalAnalyzer(), context)


def test_output_containing_an_execution_instruction_is_rejected(session, asset) -> None:
    """The product-defining rule, exercised through the real agent path."""
    offending = json.dumps(
        {
            "summary": "Momentum is strong. Buy now before the breakout completes.",
            "data_sufficiency": "sufficient",
            "confidence": 80.0,
            "bias": "bullish",
            "supporting_signals": [],
            "conflicting_signals": [],
            "level_commentary": "",
        }
    )
    provider = FixtureAIProvider(scripted={"technical_analyzer": offending})
    context = ContextBuilder(session).build(asset, Timeframe.D1)

    with pytest.raises(ValidationFailure, match="execution-instruction"):
        AgentRunner(make_gateway(provider)).run(TechnicalAnalyzer(), context)


def test_runner_records_the_exchange_for_traceability(session, asset, user) -> None:
    from sqlalchemy import select

    from aidss.agents.base import ConversationRecorder
    from aidss.db.models import AIConversation

    conversation = AIConversation(user_id=user.id, context_type="test")
    session.add(conversation)
    session.flush()

    context = ContextBuilder(session).build(asset, Timeframe.D1)
    AgentRunner(
        make_gateway(), recorder=ConversationRecorder(session, conversation.id)
    ).run(TechnicalAnalyzer(), context)

    messages = session.scalars(
        select(AIMessage).where(AIMessage.conversation_id == conversation.id)
    ).all()
    assert {m.role for m in messages} == {"user", "assistant"}
    assert all(m.agent_name == "technical_analyzer" for m in messages)
    # The audit trail records what actually answered, not what was requested:
    # a fixture must never be filed under a real model's name.
    assert all(m.model_used == "fixture-model" for m in messages)


# --- Analysis Engine -------------------------------------------------------


def test_engine_runs_the_applicable_agents_and_synthesises(session, asset, user) -> None:
    run = AnalysisEngine(session, make_gateway()).analyze(asset, Timeframe.D1, user_id=user.id)

    produced = {r.agent for r in run.runs}
    assert {"market_analyzer", "technical_analyzer", "summary_agent"} <= produced
    assert run.synthesis is not None
    assert run.failed == []


def test_engine_records_skips_with_their_reasons(session, asset, user) -> None:
    run = AnalysisEngine(session, make_gateway()).analyze(asset, Timeframe.D1, user_id=user.id)
    skipped = {s.agent: s.reason for s in run.skipped}
    assert "fundamental_analyzer" in skipped
    assert "news_analyzer" in skipped
    assert "no fundamental metrics" in skipped["fundamental_analyzer"]


def test_one_broken_agent_does_not_fail_the_whole_run(session, asset, user) -> None:
    """A partial analysis that says what is missing beats no analysis."""
    provider = FixtureAIProvider(scripted={"technical_analyzer": "garbage"})
    run = AnalysisEngine(session, make_gateway(provider)).analyze(
        asset, Timeframe.D1, user_id=user.id
    )

    assert [f.agent for f in run.failed] == ["technical_analyzer"]
    assert any(r.agent == "market_analyzer" for r in run.runs)


def test_skipped_and_failed_are_reported_separately(session, asset, user) -> None:
    """'No data exists' and 'the component is broken' are different problems."""
    provider = FixtureAIProvider(scripted={"technical_analyzer": "garbage"})
    run = AnalysisEngine(session, make_gateway(provider)).analyze(
        asset, Timeframe.D1, user_id=user.id
    )
    assert {s.agent for s in run.skipped}.isdisjoint({f.agent for f in run.failed})


def test_engine_persists_a_reproducible_result(session, asset, user) -> None:
    from sqlalchemy import select

    run = AnalysisEngine(session, make_gateway()).analyze(asset, Timeframe.D1, user_id=user.id)

    stored = session.get(AnalysisResult, run.analysis_result_id)
    assert stored is not None
    assert stored.analysis_type == "multi_agent"
    assert stored.prompt_version, "the prompt version must be recorded"
    assert stored.model_used

    snapshot = stored.context_snapshot
    # Both halves are needed to reproduce: what the agents saw, and what they said.
    assert snapshot["context"]["indicators"]
    assert snapshot["result"]["agents"]

    assert session.scalars(select(AIMessage)).all(), "the exchange must be recorded"


def test_usage_is_aggregated_across_agents(session, asset, user) -> None:
    run = AnalysisEngine(session, make_gateway()).analyze(asset, Timeframe.D1, user_id=user.id)
    assert run.total_tokens > 0
    assert run.as_payload()["usage"]["total_tokens"] == run.total_tokens


def test_analysis_without_a_user_skips_conversation_recording(session, asset) -> None:
    run = AnalysisEngine(session, make_gateway()).analyze(asset, Timeframe.D1)
    assert run.conversation_id is None
    assert run.runs


def test_an_asset_without_price_data_produces_no_agent_output(session, user) -> None:
    from aidss.db.models import Asset

    empty = Asset(ticker="EMPTY", exchange="IDX")
    session.add(empty)
    session.flush()

    run = AnalysisEngine(session, make_gateway()).analyze(empty, Timeframe.D1, user_id=user.id)
    assert run.runs == []
    assert {s.agent for s in run.skipped} >= {"market_analyzer", "technical_analyzer"}
