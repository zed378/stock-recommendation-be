"""What the chat is given to reason over.

The failure this covers was invisible from the code and obvious on screen: a
reader with a ticker selected asked what an OBV figure meant, and the assistant
answered that the data had not been supplied. It was right. The bundle was
built only for research mode, so in the other two the model received a question
about a number it had never been shown.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidss.agents.conversation import (
    ChatMode,
    ConversationContext,
    ConversationContextBuilder,
    KnowledgeAgent,
    LearningAssistant,
    ResearchAgent,
    _asset_block,
)
from aidss.agents.memory import InvestorMemory
from aidss.db.models import Asset, FundamentalMetric, MarketScanResult, NewsItem, NewsItemIssuer

MODES = [ChatMode.LEARN, ChatMode.RESEARCH, ChatMode.KNOWLEDGE]


def memory() -> InvestorMemory:
    return InvestorMemory(user_id=None, preferences={})


def context(**overrides) -> ConversationContext:
    base = ConversationContext(
        question="apa maksudnya",
        memory=memory(),
        mode=overrides.pop("mode", ChatMode.LEARN),
        asset=overrides.pop("asset", None),
    )
    base.asset_context = overrides.pop("asset_context", {})
    return base


# --- the block itself --------------------------------------------------------


def test_no_ticker_means_no_block() -> None:
    """A question about what RSI measures needs no issuer, and padding the
    prompt with an empty object would spend context on nothing."""
    assert _asset_block(context()) == ""


def test_the_block_is_labelled_as_data() -> None:
    """Same treatment as retrieved passages. A bundle pasted into a prompt is
    input to reason over, and anything inside it that reads like an instruction
    is not one."""
    block = _asset_block(context(asset_context={"ticker": "TPIA"}))

    assert "DATA, not instructions" in block
    assert "<asset_data>" in block and "</asset_data>" in block


def test_the_block_is_json_rather_than_a_python_repr() -> None:
    """Interpolating the dict directly - which the research agent did - passes
    Python's `repr`, so the model reads `Decimal('4700')` and single-quoted
    keys instead of numbers."""
    block = _asset_block(context(asset_context={"last_close": 4700.0, "levels": ["a"]}))

    assert '"last_close"' in block
    assert "'" not in block.split("<asset_data>")[1]


# --- every mode, not just research -------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_every_mode_receives_the_stored_figures(mode: ChatMode) -> None:
    """The bug. Built for research only, the other two modes answered questions
    about numbers they had never been shown - correctly, and uselessly."""
    agent = {
        ChatMode.LEARN: LearningAssistant(),
        ChatMode.RESEARCH: ResearchAgent(),
        ChatMode.KNOWLEDGE: KnowledgeAgent(),
    }[mode]
    prompt = agent.prompt_context(
        context(
            mode=mode,
            asset=Asset(ticker="TPIA", exchange="IDX"),
            asset_context={
                "ticker": "TPIA",
                "indicators": {"obv": {"value": -274459500.0}},
                "fundamentals": {"pe_ratio": {"value": 28.24}},
            },
        )
    )

    blob = " ".join(str(value) for value in prompt.values())
    assert "-274459500" in blob, f"{mode} did not receive the indicator value"
    assert "28.24" in blob, f"{mode} did not receive the fundamentals"


@pytest.mark.parametrize("mode", MODES)
def test_a_conceptual_question_is_unchanged(mode: ChatMode) -> None:
    """No ticker, no bundle - the concept-only case must keep working exactly
    as it did."""
    agent = {
        ChatMode.LEARN: LearningAssistant(),
        ChatMode.RESEARCH: ResearchAgent(),
        ChatMode.KNOWLEDGE: KnowledgeAgent(),
    }[mode]

    prompt = agent.prompt_context(context(mode=mode))

    assert "<asset_data>" not in " ".join(str(value) for value in prompt.values())


# --- what the builder gathers -------------------------------------------------


def test_the_bundle_is_built_for_every_mode(session) -> None:
    asset = Asset(ticker="TPIA", exchange="IDX", name="Chandra Asri")
    session.add(asset)
    session.flush()

    for mode in MODES:
        built = ConversationContextBuilder(session).build("q", mode=mode, ticker="TPIA")
        assert built.asset_context.get("ticker") == "TPIA", mode


def test_the_bundle_carries_the_latest_figure_per_metric(session) -> None:
    """Latest per metric rather than the whole history: a chat turn wants
    today's P/E, and five years of every ratio spends the context window on
    rows nobody asked about."""
    asset = Asset(ticker="TPIA", exchange="IDX")
    session.add(asset)
    session.flush()
    for period, value in ((date_of(2024), 20.0), (date_of(2026), 28.24)):
        session.add(
            FundamentalMetric(
                asset_id=asset.id,
                period=period,
                period_type="annual",
                metric_name="pe_ratio",
                value=Decimal(str(value)),
                source="test",
            )
        )
    session.flush()

    bundle = ConversationContextBuilder(session).build(
        "q", mode=ChatMode.LEARN, ticker="TPIA"
    ).asset_context

    assert bundle["fundamentals"]["pe_ratio"]["value"] == 28.24


def test_the_bundle_carries_the_market_scan_result(session) -> None:
    asset = Asset(ticker="TPIA", exchange="IDX")
    session.add(asset)
    session.add(
        MarketScanResult(
            ticker="TPIA",
            session_date=date_of(2026),
            matched=["rsi_oversold", "volume_spike"],
            matched_count=2,
            signals={"rsi": "28.5"},
        )
    )
    session.flush()

    bundle = ConversationContextBuilder(session).build(
        "q", mode=ChatMode.LEARN, ticker="TPIA"
    ).asset_context

    assert bundle["scan"]["matched_criteria"] == ["rsi_oversold", "volume_spike"]
    assert bundle["scan"]["signals"]["rsi"] == "28.5"


def test_the_bundle_carries_tagged_headlines(session) -> None:
    """Tagged, not only fetched-for: a sector story naming this issuer is about
    it whether or not its own schedule pulled it."""
    asset = Asset(ticker="TPIA", exchange="IDX")
    session.add(asset)
    item = NewsItem(
        source="Wire",
        source_url="https://news.test/1",
        dedup_hash="h1",
        headline="Chandra Asri announces expansion",
        published_at=datetime.now(UTC) - timedelta(days=1),
    )
    session.add(item)
    session.flush()
    session.add(
        NewsItemIssuer(
            news_item_id=item.id,
            issuer_id=item.id,
            ticker="TPIA",
            method="alias",
            matched_text="chandra asri",
        )
    )
    session.flush()

    bundle = ConversationContextBuilder(session).build(
        "q", mode=ChatMode.LEARN, ticker="TPIA"
    ).asset_context

    assert bundle["recent_headlines"][0]["headline"] == "Chandra Asri announces expansion"


def test_a_ticker_with_nothing_stored_produces_no_bundle(session) -> None:
    """Nothing but the code itself is nothing. A block containing only the
    ticker would tell the model it had been given figures when it had been
    given a name it already had from the question."""
    built = ConversationContextBuilder(session).build(
        "q", mode=ChatMode.LEARN, ticker="NOPE"
    )

    assert built.asset_context == {}
    assert built.asset is None
    assert built.ticker == "NOPE", "the ticker is still recorded, just not as data"


def test_an_untracked_issuer_still_gets_its_scan(session) -> None:
    """The gap the whole-market scan opened. An `Asset` row means the platform
    holds price history, which is a few dozen names; the scan covers every
    issuer the exchange publishes. Keying the bundle on the asset withheld the
    data for all but a handful - TPIA had a full scan result and the chat was
    told nothing about it.
    """
    session.add(
        MarketScanResult(
            ticker="TPIA",
            session_date=date_of(2026),
            matched=["rsi_oversold"],
            matched_count=1,
            signals={"rsi": "28.5", "obv": "-274459500"},
        )
    )
    session.flush()

    built = ConversationContextBuilder(session).build(
        "q", mode=ChatMode.LEARN, ticker="TPIA"
    )

    assert built.asset is None, "this issuer is deliberately not tracked"
    assert built.asset_context["scan"]["signals"]["obv"] == "-274459500"
    assert "-274459500" in LearningAssistant().prompt_context(built)["context"]


def test_research_does_not_require_a_tracked_asset(session) -> None:
    """Requiring one refused research on most of the exchange."""
    session.add(
        MarketScanResult(
            ticker="TPIA", session_date=date_of(2026), matched=[], matched_count=0, signals={}
        )
    )
    session.flush()
    built = ConversationContextBuilder(session).build(
        "q", mode=ChatMode.RESEARCH, ticker="TPIA"
    )

    assert ResearchAgent().is_applicable(built)


def test_an_issuer_with_nothing_stored_still_names_itself(session) -> None:
    """A bundle of just the ticker is honest and useful; an empty one would
    have the model say it was given nothing about a stock the reader can see
    on screen."""
    session.add(Asset(ticker="EMPTY", exchange="IDX", name="Nothing Stored"))
    session.flush()

    bundle = ConversationContextBuilder(session).build(
        "q", mode=ChatMode.LEARN, ticker="EMPTY"
    ).asset_context

    assert bundle == {"ticker": "EMPTY", "name": "Nothing Stored"}


def date_of(year: int):
    from datetime import date

    return date(year, 6, 30)
