"""A deterministic AIProvider for development, CI, and demos.

The counterpart to the fixture market-data provider: it lets the whole
multi-agent pipeline run end to end with no API key, no network, no cost, and
identical output on every run. Without it, testing the Analysis Engine would
mean either paying per test run or mocking so deeply that the test stops
exercising the real path.

It answers by recognising which agent is asking - agents identify themselves
in their system prompt - and returning a canned response that satisfies that
agent's schema. Responses are intentionally bland and language-rule compliant;
tests that need a violation or a malformed answer inject one explicitly
through ``scripted``.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import ClassVar

from aidss.config import Settings, get_settings
from aidss.domain.types import ChatCompletion, ChatMessage
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.interfaces import AIProvider
from aidss.plugins.registry import register

#: Recognised by the phrase each agent uses to introduce itself.
_AGENT_MARKERS: tuple[tuple[str, str], ...] = (
    ("Market Analyzer agent", "market_analyzer"),
    ("Technical Analyzer agent", "technical_analyzer"),
    ("Fundamental Analyzer agent", "fundamental_analyzer"),
    ("News Analyzer agent", "news_analyzer"),
    ("Summary Agent", "summary_agent"),
    ("Recommendation Agent", "recommendation_agent"),
    ("Portfolio Analyzer agent", "portfolio_analyzer"),
    ("Risk Analyzer agent", "risk_analyzer"),
    # Listed before "News Analyzer agent" would not help - the two phrases are
    # distinct - but it must be listed at all, or the scorer silently falls
    # through to the generic fallback and reports zero scores.
    ("News Sentiment Scorer agent", "sentiment_scorer"),
    ("Knowledge Agent", "knowledge_agent"),
    ("Learning Assistant", "learning_assistant"),
    ("Research Agent", "research_agent"),
    ("Reflection Agent", "reflection_agent"),
)

_CANNED: dict[str, dict] = {
    "market_analyzer": {
        "summary": (
            "Conditions look range-bound with moderate participation. Breadth is "
            "neither broadly expanding nor deteriorating, which historically "
            "leaves single names driven more by their own catalysts than by the "
            "index."
        ),
        "data_sufficiency": "partial",
        "confidence": 55.0,
        "regime": "range-bound with moderate volatility",
        "sector_note": "No pronounced sector rotation is visible in the supplied window.",
        "key_drivers": ["index-level volatility", "trading volume trend"],
    },
    "technical_analyzer": {
        "summary": (
            "Momentum sits near the middle of its range and the moving averages "
            "are only mildly separated, which points to continuation rather than "
            "reversal, though the weak trend strength reading argues against "
            "reading much into direction here."
        ),
        "data_sufficiency": "sufficient",
        "confidence": 62.0,
        "bias": "neutral",
        "supporting_signals": [
            "price holding above the medium-term moving average",
            "MACD histogram marginally positive",
        ],
        "conflicting_signals": [
            "trend strength reading is low, so directional signals carry less weight",
            "volume has not confirmed the move",
        ],
        "level_commentary": (
            "The nearest levels above and below sit close together, so the "
            "current area offers little room before one of them is tested."
        ),
    },
    "fundamental_analyzer": {
        "summary": (
            "The supplied metrics are too sparse to support a valuation view. "
            "Reporting that plainly is more useful than extrapolating from what "
            "little is present."
        ),
        "data_sufficiency": "insufficient",
        "confidence": 15.0,
        "bias": "neutral",
        "valuation_note": "No valuation multiples were provided.",
        "growth_note": "No revenue or earnings history was provided.",
        "balance_sheet_note": "No leverage or liquidity figures were provided.",
        "concerns": ["fundamental coverage is not yet ingested for this issuer"],
    },
    "news_analyzer": {
        "summary": (
            "Coverage is routine: results reporting and management commentary, "
            "with nothing that changes the operating picture materially."
        ),
        "data_sufficiency": "partial",
        "confidence": 48.0,
        "sentiment_score": 0.1,
        "key_themes": ["quarterly reporting", "management guidance"],
        "notable_events": [],
    },
    "summary_agent": {
        "summary": (
            "The analyzers do not converge. The technical reading is neutral with "
            "low conviction, fundamentals could not be assessed at all, and news "
            "flow is routine. Taken together the evidence supports observation "
            "rather than a firm directional conclusion."
        ),
        "data_sufficiency": "partial",
        "confidence": 40.0,
        "overall_bias": "neutral",
        "agreements": ["no analyzer reports a strong directional signal"],
        "disagreements": [
            "the technical view carries moderate confidence while the fundamental "
            "view has no data behind it at all"
        ],
        "risk_factors": [
            "conclusions rest largely on price data alone",
            "fundamental coverage is absent",
        ],
        "watch_items": ["fundamental data becoming available", "a decisive break of nearby levels"],
    },
    "portfolio_analyzer": {
        "summary": (
            "The portfolio is concentrated in a small number of names, so its "
            "behaviour will track those holdings closely rather than the market."
        ),
        "data_sufficiency": "sufficient",
        "confidence": 60.0,
        "concentration_reading": "concentrated in a handful of positions",
        "diversification_note": (
            "The effective number of positions is well below the nominal count, "
            "because weight is unevenly distributed."
        ),
        "correlation_note": "Correlation could not be measured across all holdings.",
        "observations": [
            "the largest position dominates the portfolio's weight",
            "sector exposure is narrow",
        ],
        "considerations": [
            "whether the concentration matches the stated risk appetite",
            "whether the holdings respond to the same underlying drivers",
        ],
    },
    "risk_analyzer": {
        "summary": (
            "Historical volatility is moderate and the observed drawdown is "
            "substantial, though both describe the past rather than the future."
        ),
        "data_sufficiency": "partial",
        "confidence": 50.0,
        "risk_reading": "moderate historical volatility with a deep observed drawdown",
        "drawdown_note": (
            "The worst peak-to-trough decline in the observed window was material, "
            "and the portfolio has not fully recovered from it."
        ),
        "volatility_note": "Annualised volatility sits in the middle of the usual equity range.",
        "concentration_risks": ["a single position drives most of the variance"],
        "limitations": [
            "every figure is backward-looking and says nothing about future losses",
            "the observation window may not contain a comparable market regime",
        ],
    },
    "knowledge_agent": {
        "summary": "Answered from the retrieved passages.",
        "data_sufficiency": "sufficient",
        "confidence": 60.0,
        "answer": (
            "The retrieved material covers this directly: the indicator measures "
            "the speed of recent price changes rather than value, which is why a "
            "high reading describes momentum and not expensiveness."
        ),
        "sources_used": ["retrieved passage 1"],
        "follow_up_questions": ["How is this reading affected by a low-volume market?"],
    },
    "learning_assistant": {
        "summary": "Explained the concept in plain language.",
        "data_sufficiency": "sufficient",
        "confidence": 65.0,
        "answer": (
            "Think of it as a speedometer rather than a price tag. It tells you how "
            "quickly price has been moving recently, which is a different question "
            "from whether the price is reasonable. It misleads most often in quiet, "
            "thinly traded markets, where small moves produce large readings."
        ),
        "sources_used": [],
        "follow_up_questions": ["What does it look like when a trend is ending?"],
    },
    "research_agent": {
        "summary": "Profiled the issuer from the available context.",
        "data_sufficiency": "partial",
        "confidence": 45.0,
        "answer": (
            "The available context covers recent price behaviour and routine "
            "coverage. There is no fundamental data ingested for this issuer, so "
            "anything about its business quality would be outside what has been "
            "measured here."
        ),
        "sources_used": ["retrieved coverage"],
        "follow_up_questions": ["What would fundamental coverage add to this picture?"],
    },
    "reflection_agent": {
        "summary": "Reviewed the journal for patterns in how these decisions were made.",
        "data_sufficiency": "partial",
        "confidence": 40.0,
        "patterns": [
            "decisions are more often recorded after a move than before one",
            "entries that reference a platform recommendation carry longer notes",
        ],
        "insufficient_evidence_for": [
            "whether losing positions are held longer than the stated plan - too few "
            "entries record an exit"
        ],
        "questions_to_consider": [
            "What did you expect to happen when you wrote each entry?",
            "Which of these decisions would you make the same way again?",
        ],
    },
    "recommendation_agent": {
        "summary": (
            "A watchlist stance: the technical picture is readable but not "
            "decisive, and with no fundamental coverage there is not enough "
            "behind a directional call."
        ),
        "data_sufficiency": "partial",
        # Deliberately different from what the platform will calibrate, so the
        # tests can prove the published figure is the calibrated one.
        "confidence": 75.0,
        "label": "watchlist",
        "reasoning": (
            "Price is holding above its medium-term average and momentum sits "
            "mid-range, which is consistent with continuation. But trend "
            "strength is weak, volume has not confirmed the move, and no "
            "fundamental data is available at all. That combination supports "
            "watching the name rather than forming a directional view."
        ),
        "supporting_factors": [
            "price holding above the medium-term moving average",
            "momentum mid-range rather than stretched",
        ],
        "conflicting_factors": [
            "trend strength is weak, so directional signals carry little weight",
            "volume has not confirmed the recent move",
            "no fundamental coverage exists for this issuer",
        ],
        "risk_factors": [
            "conclusions rest on price data alone",
            "nearby support and resistance sit close together, leaving little room",
        ],
        "bullish_scenario": (
            "A close above the nearest resistance on expanding volume would "
            "confirm the continuation the moving averages hint at, and would "
            "make the weak trend-strength reading a lagging artefact."
        ),
        "bearish_scenario": (
            "A loss of the nearest support would leave price below both the "
            "medium-term average and the recent range, turning the current "
            "reading into a failed continuation."
        ),
        "horizon": "medium",
    },
}

#: The scorer's prompt renders each article with its index; counting them is
#: how the fixture knows how many entries its answer needs.
_ARTICLE_INDEX = re.compile(r'"index"\s*:\s*(\d+)')


def _sentiment_for(messages: list[ChatMessage]) -> dict:
    """One score per article in the prompt, derived from the headline text."""
    joined = "\n".join(m.content for m in messages)
    indexes = sorted({int(m) for m in _ARTICLE_INDEX.findall(joined)})

    scores = []
    for index in indexes:
        # Deterministic but not uniform, so a batch does not collapse to one
        # value and hide an aggregation bug.
        digest = hashlib.sha256(f"sentiment|{index}".encode()).digest()
        score = round((digest[0] / 255.0) * 1.6 - 0.8, 3)
        scores.append(
            {
                "index": index,
                "score": score,
                "rationale": "Routine coverage with no material change to the operating picture.",
            }
        )

    return {
        "summary": f"Scored {len(scores)} article(s).",
        "data_sufficiency": "sufficient" if scores else "insufficient",
        "confidence": 55.0,
        "scores": scores,
    }


def _pseudo_vector(text: str, width: int) -> list[float]:
    """A deterministic vector of the requested width.

    Extended by re-hashing with a counter rather than by repeating or padding:
    a repeated block would make every vector's second half identical to its
    first, and padding with zeros would push every similarity toward the same
    value.
    """
    values: list[float] = []
    counter = 0
    while len(values) < width:
        digest = hashlib.sha256(f"{counter}|{text}".encode()).digest()
        values.extend(b / 255.0 for b in digest)
        counter += 1
    return values[:width]


_FALLBACK = {
    "summary": "Insufficient context was supplied to produce an analysis.",
    "data_sufficiency": "insufficient",
    "confidence": 5.0,
}


@register
class FixtureAIProvider(AIProvider):
    name: ClassVar[str] = "fixture"

    def __init__(
        self,
        *,
        scripted: dict[str, str] | None = None,
        fail_times: int = 0,
        retryable: bool = True,
        dimensions: int | None = None,
    ) -> None:
        #: Overrides the configured embedding width; used by tests that need a
        #: deliberate mismatch.
        self._dimensions = dimensions
        #: Overrides keyed by agent name; tests use this to inject a malformed
        #: or non-compliant answer without touching the rest of the pipeline.
        self._scripted = scripted or {}
        self._fail_times = fail_times
        self._retryable = retryable
        self.calls: list[list[ChatMessage]] = []

    @classmethod
    def from_settings(cls, settings: Settings) -> FixtureAIProvider:  # noqa: ARG003
        return cls()

    @staticmethod
    def _detect_agent(messages: list[ChatMessage]) -> str | None:
        joined = "\n".join(m.content for m in messages)
        for marker, agent in _AGENT_MARKERS:
            if marker in joined:
                return agent
        return None

    def chat_completion(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> ChatCompletion:
        self.calls.append(list(messages))

        if self._fail_times > 0:
            self._fail_times -= 1
            raise ProviderUnavailableError(
                self.name, "scripted failure", retryable=self._retryable
            )

        agent = self._detect_agent(messages)
        if agent and agent in self._scripted:
            content = self._scripted[agent]
        elif agent == "sentiment_scorer":
            # Built from the prompt rather than canned, because this agent's
            # answer must have exactly one entry per article supplied. A fixed
            # list would either under-score every batch or reference articles
            # that were not in it.
            content = json.dumps(
                _sentiment_for(messages), ensure_ascii=False
            )
        else:
            content = json.dumps(_CANNED.get(agent or "", _FALLBACK), ensure_ascii=False)

        prompt_tokens = sum(len(m.content) for m in messages) // 4
        return ChatCompletion(
            content=content,
            # Always reports itself, never the model name it was asked for.
            # Echoing the request would write "gpt-4o-mini" into an audit trail
            # for text no such model produced - and the audit trail is the one
            # place a convenient fiction does real damage.
            model="fixture-model",
            prompt_tokens=prompt_tokens,
            completion_tokens=len(content) // 4,
            raw={"fixture": True, "agent": agent, "requested_model": model},
        )

    def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        """Stable pseudo-embeddings: the same text always yields the same vector.

        Produced at the *configured* width rather than a convenient small one.
        An earlier version returned 8 dimensions, which SQLite accepted happily
        and PostgreSQL rejected - so the whole RAG suite passed while the
        production path was broken. A fixture whose shape differs from the real
        thing tests the wrong thing.
        """
        width = self._dimensions or get_settings().embedding_dimensions
        return [_pseudo_vector(text, width) for text in texts]

    def supports_tool_calling(self) -> bool:
        return False

    def supports_structured_output(self) -> bool:
        return True
