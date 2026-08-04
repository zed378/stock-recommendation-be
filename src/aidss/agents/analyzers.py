"""The core analyzer agents of Phase 4 (Section 5.2).

Market, Technical, Fundamental, and News Analyzers, plus the Summary Agent
that combines them. Research, Portfolio, Risk, Knowledge, and Reflection
agents arrive with Phases 6 and 7 and slot into the same base class.
"""

from __future__ import annotations

from typing import Any

from aidss.agents.base import Agent, AgentRun
from aidss.agents.context import AnalysisContext
from aidss.llm.router import TaskComplexity
from aidss.prompts.schemas import (
    FundamentalOutput,
    MarketContextOutput,
    NewsSentimentOutput,
    SynthesisOutput,
    TechnicalOutput,
)


class MarketAnalyzer(Agent):
    """Sets the macro and sector backdrop before per-asset analysis."""

    name = "market_analyzer"
    template_name = "market_context"
    output_model = MarketContextOutput
    complexity = TaskComplexity.LIGHT

    def is_applicable(self, context: AnalysisContext) -> bool:
        return context.has_price_data

    def skip_reason(self, context: AnalysisContext) -> str:
        return "no price history stored for this asset"

    def prompt_context(self, context: AnalysisContext) -> dict[str, Any]:
        snapshot = context.indicator_snapshot
        return {
            "ticker": context.asset.ticker,
            "exchange": context.asset.exchange,
            "sector": context.asset.sector or "unknown",
            "as_of": snapshot.get("as_of", "unknown"),
            "price_context": {
                "last_close": snapshot.get("last_close"),
                "market_structure": snapshot.get("structure"),
                "breakout": snapshot.get("breakout"),
                "return_20_bars": context.features.get("return_20b"),
                "return_60_bars": context.features.get("return_60b"),
                "volatility_20_bars": context.features.get("volatility_20b"),
                "range_position": context.features.get("range_position_52b"),
            },
        }


class TechnicalAnalyzer(Agent):
    """Interprets the deterministically computed indicators."""

    name = "technical_analyzer"
    template_name = "technical_analysis"
    output_model = TechnicalOutput
    complexity = TaskComplexity.STANDARD

    def is_applicable(self, context: AnalysisContext) -> bool:
        return context.has_price_data

    def skip_reason(self, context: AnalysisContext) -> str:
        return "no price history stored for this asset"

    def prompt_context(self, context: AnalysisContext) -> dict[str, Any]:
        snapshot = context.indicator_snapshot
        levels = snapshot.get("levels", {})
        return {
            "ticker": context.asset.ticker,
            "exchange": context.asset.exchange,
            "timeframe": context.timeframe.value,
            "as_of": snapshot.get("as_of", "unknown"),
            "indicators": snapshot.get("indicators", {}),
            "features": context.features,
            "structure": snapshot.get("structure", "undetermined"),
            "breakout": snapshot.get("breakout", {}),
            "support": levels.get("support", []),
            "resistance": levels.get("resistance", []),
        }


class FundamentalAnalyzer(Agent):
    """Interprets reported financial metrics."""

    name = "fundamental_analyzer"
    template_name = "fundamental_analysis"
    output_model = FundamentalOutput
    complexity = TaskComplexity.STANDARD

    def is_applicable(self, context: AnalysisContext) -> bool:
        # Fundamental ingestion is not part of Phases 1-3, so for most assets
        # this agent will correctly decline to run rather than narrate an empty
        # table.
        return context.has_fundamentals

    def skip_reason(self, context: AnalysisContext) -> str:
        return "no fundamental metrics ingested for this asset"

    def prompt_context(self, context: AnalysisContext) -> dict[str, Any]:
        return {
            "ticker": context.asset.ticker,
            "exchange": context.asset.exchange,
            "sector": context.asset.sector or "unknown",
            "industry": context.asset.industry or "unknown",
            "fundamentals": context.fundamentals,
        }


class NewsAnalyzer(Agent):
    """Summarises recent coverage and scores its sentiment."""

    name = "news_analyzer"
    template_name = "news_summary"
    output_model = NewsSentimentOutput
    complexity = TaskComplexity.LIGHT

    def is_applicable(self, context: AnalysisContext) -> bool:
        return context.has_news

    def skip_reason(self, context: AnalysisContext) -> str:
        return "no news stored for this asset in the recent window"

    def prompt_context(self, context: AnalysisContext) -> dict[str, Any]:
        return {
            "ticker": context.asset.ticker,
            "exchange": context.asset.exchange,
            "window": f"last {len(context.news)} articles",
            # Article text reaches the model inside <articles> delimiters, as
            # data rather than instruction. Combined with a read-only tool
            # surface, a successful injection has nothing to act on
            # (Section 13).
            "articles": context.news,
        }


class SummaryAgent(Agent):
    """Combines the analyzer outputs into one coherent reading."""

    name = "summary_agent"
    template_name = "synthesis"
    output_model = SynthesisOutput
    #: The only agent that reasons across sources, so it gets the strongest
    #: routing tier (Section 12.10).
    complexity = TaskComplexity.COMPLEX

    def __init__(self, runs: list[AgentRun]) -> None:
        self._runs = runs

    def is_applicable(self, context: AnalysisContext) -> bool:
        # Nothing to synthesise from a single input; the analyzer's own output
        # is already the answer, and re-summarising it only adds a paraphrase.
        return len(self._runs) >= 2

    def skip_reason(self, context: AnalysisContext) -> str:
        return "fewer than two analyzers produced output, so there is nothing to synthesise"

    def prompt_context(self, context: AnalysisContext) -> dict[str, Any]:
        return {
            "ticker": context.asset.ticker,
            "exchange": context.asset.exchange,
            "timeframe": context.timeframe.value,
            "analyses": [
                {
                    "agent": run.agent,
                    "confidence": run.output.confidence,
                    "data_sufficiency": run.output.data_sufficiency.value,
                    **run.output.model_dump(
                        mode="json", exclude={"confidence", "data_sufficiency"}
                    ),
                }
                for run in self._runs
            ],
        }
