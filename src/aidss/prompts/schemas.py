"""Structured output contracts for each agent (Sections 5.2, 12.5).

Every agent returns JSON validated against one of these models. Free-form text
would leave the Summary Agent parsing prose and the UI guessing, and it would
make the Section 5.4 completeness checks impossible to run programmatically.

Note what these models deliberately do not contain: any numeric field the
Indicator Engine already computes. Agents interpret figures; they never
restate them as their own output, because a restated number is a number that
can drift from the one that was actually measured (Section 2.7).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from aidss.domain.types import InvestmentHorizon, RecommendationLabel


class Bias(StrEnum):
    """A directional stance. Not an instruction - see `language.py`."""

    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"


class DataSufficiency(StrEnum):
    """How much the agent had to work with.

    An agent that says 'insufficient' is doing its job. The alternative -
    producing confident narrative from nothing - is exactly the failure mode
    the plan's AI-quality risk describes (Section 17).
    """

    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


class AgentOutput(BaseModel):
    """Fields every agent must supply."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=4000)
    data_sufficiency: DataSufficiency = DataSufficiency.SUFFICIENT
    #: 0-100, calibrated against how much evidence supported the reading -
    #: not a general feeling of certainty.
    confidence: float = Field(ge=0, le=100)


class MarketContextOutput(AgentOutput):
    """Market Analyzer - macro and sector backdrop (Section 5.2)."""

    regime: str = Field(min_length=1, max_length=200)
    sector_note: str = Field(default="", max_length=2000)
    key_drivers: list[str] = Field(default_factory=list, max_length=10)


class TechnicalOutput(AgentOutput):
    """Technical Analyzer - reading of the computed indicators."""

    bias: Bias
    supporting_signals: list[str] = Field(default_factory=list, max_length=15)
    conflicting_signals: list[str] = Field(default_factory=list, max_length=15)
    #: Free-text because methods vary; the numeric levels themselves come from
    #: the Indicator Engine and are attached by the engine, not by the model.
    level_commentary: str = Field(default="", max_length=2000)


class FundamentalOutput(AgentOutput):
    """Fundamental Analyzer - valuation, growth, balance sheet."""

    bias: Bias
    valuation_note: str = Field(default="", max_length=2000)
    growth_note: str = Field(default="", max_length=2000)
    balance_sheet_note: str = Field(default="", max_length=2000)
    concerns: list[str] = Field(default_factory=list, max_length=10)


class NewsSentimentOutput(AgentOutput):
    """News Analyzer - sentiment score plus the reasoning behind it."""

    #: -1 (strongly negative) to +1 (strongly positive).
    sentiment_score: float = Field(ge=-1, le=1)
    key_themes: list[str] = Field(default_factory=list, max_length=10)
    notable_events: list[str] = Field(default_factory=list, max_length=10)


class SynthesisOutput(AgentOutput):
    """Summary Agent - the combined reading across every analyzer.

    Phase 4 stops here. The graded Strong Buy - Sell label with its mandatory
    Section 5.4 structure is the Recommendation Engine's job in Phase 5, and
    inventing a partial version of it now would mean two places to keep
    correct.
    """

    overall_bias: Bias
    agreements: list[str] = Field(default_factory=list, max_length=15)
    #: Mandatory in spirit and in the prompt: where the analyzers disagree is
    #: usually the most informative part, and hiding it invites confirmation
    #: bias (Section 5.4).
    disagreements: list[str] = Field(default_factory=list, max_length=15)
    risk_factors: list[str] = Field(default_factory=list, max_length=15)
    watch_items: list[str] = Field(default_factory=list, max_length=15)


class ArticleSentiment(BaseModel):
    """Sentiment for one article inside a batch."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    #: Position in the supplied list. An index rather than a URL, because a
    #: model reproducing a long URL is a model with one more chance to alter it.
    index: int = Field(ge=0)
    score: float = Field(ge=-1, le=1)
    #: `reason` is accepted as well as `rationale`. The prompt used to ask for
    #: "a short reason" without naming the field, and the model did exactly as
    #: it was told - so every batch of twenty failed validation on twenty
    #: counts, sentiment scoring never once produced a row, and the ingestion
    #: report called it a warning. The prompt now names the field; the alias is
    #: here because "reason" is the word a model reaches for anyway, and
    #: spending a retry to correct a synonym buys nothing.
    rationale: str = Field(
        min_length=1,
        max_length=1000,
        validation_alias=AliasChoices("rationale", "reason"),
    )


class BatchSentimentOutput(AgentOutput):
    """News Sentiment Scorer - one score per article, in a single call.

    Batched deliberately: a per-article call turns twenty new headlines into
    twenty round trips, and the plan's cost risk (Section 17) is real. The
    schema keeps the results separable so each article still gets its own row.
    """

    scores: list[ArticleSentiment] = Field(default_factory=list, max_length=50)


class PortfolioOutput(AgentOutput):
    """Portfolio Analyzer - diversification, concentration, allocation shape.

    No numeric field: concentration indices, weights, and correlations are all
    computed in `aidss.portfolio.metrics` and attached by the engine. The agent
    explains what those figures mean for this particular portfolio.
    """

    concentration_reading: str = Field(min_length=1, max_length=500)
    diversification_note: str = Field(default="", max_length=2000)
    correlation_note: str = Field(default="", max_length=2000)
    observations: list[str] = Field(default_factory=list, max_length=15)
    #: What the investor may want to weigh - framed as considerations, never
    #: as transactions to perform (Section 5.4 language rule).
    considerations: list[str] = Field(default_factory=list, max_length=15)


class RiskOutput(AgentOutput):
    """Risk Analyzer - what the historical figures imply about downside."""

    risk_reading: str = Field(min_length=1, max_length=500)
    drawdown_note: str = Field(default="", max_length=2000)
    volatility_note: str = Field(default="", max_length=2000)
    concentration_risks: list[str] = Field(default_factory=list, max_length=15)
    #: The agent is asked to name what these backward-looking figures cannot
    #: tell you. A risk report that does not state its own blind spots invites
    #: being read as a forecast.
    limitations: list[str] = Field(default_factory=list, max_length=10)


class ReflectionOutput(AgentOutput):
    """Reflection Agent - patterns in how *this investor* decides (Section 5.2).

    Explicitly not an evaluation of a trading strategy's performance. The
    subject is the person's decision-making, and the aim is self-awareness
    rather than a verdict, which is why there is no score field here: a number
    would invite treating it as a grade.
    """

    #: What is visible in how they decide - "positions held past the stated
    #: plan", not "your returns were poor".
    patterns: list[str] = Field(default_factory=list, max_length=10)
    #: Where the journal is too thin to support a pattern. Naming this is what
    #: keeps the agent from inventing one.
    insufficient_evidence_for: list[str] = Field(default_factory=list, max_length=10)
    questions_to_consider: list[str] = Field(default_factory=list, max_length=10)


class ConversationOutput(AgentOutput):
    """Free-form chat: Learning Assistant, Research Agent, Knowledge Agent.

    Carries its sources so an answer built from retrieved context can be
    checked against that context rather than taken on trust.
    """

    answer: str = Field(min_length=1, max_length=8000)
    #: Retrieved passages the answer drew on. Empty means the model answered
    #: from its own training, which the caller should be able to see.
    sources_used: list[str] = Field(default_factory=list, max_length=10)
    follow_up_questions: list[str] = Field(default_factory=list, max_length=5)


class RecommendationOutput(AgentOutput):
    """What the model contributes to a recommendation (Section 5.4).

    Note what is **absent**: support, resistance, target price, and the
    suggested stop. Those are prices, and a price stated by a language model is
    a number nobody measured. The Recommendation Engine derives them from the
    Indicator Engine and attaches them afterwards, with the method recorded
    (Section 2.7).

    `confidence`, inherited from AgentOutput, is likewise not what gets stored.
    Section 5.4 requires a consistently calibrated score rather than an
    arbitrary number from the model; the engine computes one and keeps the
    model's self-report only for comparison.
    """

    label: RecommendationLabel
    #: The narrative answer to "why this label".
    reasoning: str = Field(min_length=1, max_length=4000)
    supporting_factors: list[str] = Field(default_factory=list, max_length=15)
    #: Mandatory and non-empty - enforced by the engine, not merely requested.
    #: Section 5.4 makes this the structural defence against confirmation bias:
    #: a recommendation that can find nothing against itself has not been
    #: examined.
    conflicting_factors: list[str] = Field(default_factory=list, max_length=15)
    risk_factors: list[str] = Field(default_factory=list, max_length=15)
    bullish_scenario: str = Field(min_length=1, max_length=2000)
    bearish_scenario: str = Field(min_length=1, max_length=2000)
    horizon: InvestmentHorizon


#: Maps an agent name to the model its output must satisfy.
OUTPUT_MODELS: dict[str, type[AgentOutput]] = {
    "market_analyzer": MarketContextOutput,
    "technical_analyzer": TechnicalOutput,
    "fundamental_analyzer": FundamentalOutput,
    "news_analyzer": NewsSentimentOutput,
    "summary_agent": SynthesisOutput,
    "recommendation_agent": RecommendationOutput,
    "portfolio_analyzer": PortfolioOutput,
    "risk_analyzer": RiskOutput,
    "sentiment_scorer": BatchSentimentOutput,
    "reflection_agent": ReflectionOutput,
    "knowledge_agent": ConversationOutput,
    "research_agent": ConversationOutput,
    "learning_assistant": ConversationOutput,
}
