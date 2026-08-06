"""Context Builder (Section 5.2).

Assembles everything the agents will reason over into one structured object
before a single prompt is composed. Two reasons it is a separate stage rather
than each agent fetching what it needs:

  * every agent then sees the *same* evidence, so a disagreement between two
    analyzers is a genuine difference of interpretation rather than an artefact
    of one having fresher data;
  * the whole context is snapshotted onto ``analysis_results``, which is what
    makes an output reproducible months later (Section 1, full traceability).

Every number here arrives already computed by the Indicator Engine. Nothing in
this module asks a model to derive a figure.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.agents.memory import InvestorMemory, MemoryManager
from aidss.collectors.market_data import load_candles
from aidss.db.models import (
    Asset,
    FundamentalMetric,
    NewsItem,
    NewsItemIssuer,
    SentimentScore,
)
from aidss.domain.types import Candle, Timeframe
from aidss.indicators.engine import IndicatorEngine
from aidss.indicators.features import compute_features

#: How far back news is considered relevant to an analysis run. News decays;
#: a six-month-old headline is history, not sentiment.
NEWS_WINDOW_DAYS = 30

#: Bars fed to the Indicator Engine. Enough for SMA(200) plus warm-up, so the
#: long-term averages are actually populated rather than silently null.
DEFAULT_LOOKBACK_BARS = 400


@dataclass(slots=True)
class AnalysisContext:
    """The complete, agent-agnostic evidence bundle for one analysis run."""

    asset: Asset
    timeframe: Timeframe
    memory: InvestorMemory
    candles: list[Candle] = field(default_factory=list)
    indicator_snapshot: dict[str, Any] = field(default_factory=dict)
    features: dict[str, Any] = field(default_factory=dict)
    fundamentals: list[dict[str, Any]] = field(default_factory=list)
    news: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_price_data(self) -> bool:
        return bool(self.candles)

    @property
    def has_fundamentals(self) -> bool:
        return bool(self.fundamentals)

    @property
    def has_news(self) -> bool:
        return bool(self.news)

    def snapshot(self) -> dict[str, Any]:
        """The serialisable record stored on ``analysis_results``.

        Raw candles are excluded deliberately - hundreds of bars per run would
        bloat every row, and the indicator snapshot plus features is what the
        agents actually saw.
        """
        return {
            "asset": {
                "ticker": self.asset.ticker,
                "exchange": self.asset.exchange,
                "sector": self.asset.sector,
                "industry": self.asset.industry,
            },
            "timeframe": self.timeframe.value,
            "bars": len(self.candles),
            "indicators": self.indicator_snapshot,
            "features": self.features,
            "fundamental_count": len(self.fundamentals),
            "news_count": len(self.news),
            "investor": self.memory.as_prompt_context(),
        }


class ContextBuilder:
    def __init__(
        self,
        session: Session,
        *,
        indicator_engine: IndicatorEngine | None = None,
        memory_manager: MemoryManager | None = None,
        now: datetime | None = None,
    ) -> None:
        self._session = session
        self._engine = indicator_engine or IndicatorEngine()
        self._memory = memory_manager or MemoryManager(session)
        # Injectable so a test can pin the news window instead of depending on
        # when the suite happens to run.
        self._now = now

    def _clock(self) -> datetime:
        return self._now or datetime.now(UTC)

    def build(
        self,
        asset: Asset,
        timeframe: Timeframe,
        *,
        user_id: uuid.UUID | None = None,
        lookback_bars: int = DEFAULT_LOOKBACK_BARS,
    ) -> AnalysisContext:
        candles = load_candles(self._session, asset.id, timeframe, limit=lookback_bars)

        context = AnalysisContext(
            asset=asset,
            timeframe=timeframe,
            memory=self._memory.load(user_id),
            candles=candles,
        )
        if candles:
            context.indicator_snapshot = self._engine.snapshot(candles)
            context.features = compute_features(candles)

        context.fundamentals = self._load_fundamentals(asset.id)
        context.news = self._load_news(asset.id, asset.ticker)
        return context

    def _load_fundamentals(self, asset_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = self._session.scalars(
            select(FundamentalMetric)
            .where(FundamentalMetric.asset_id == asset_id)
            .order_by(FundamentalMetric.period.desc())
            .limit(60)
        ).all()
        return [
            {
                "period": row.period.isoformat(),
                "period_type": row.period_type,
                "metric": row.metric_name,
                "value": float(row.value) if row.value is not None else None,
                "source": row.source,
            }
            for row in rows
        ]

    def _load_news(self, asset_id: uuid.UUID, ticker: str) -> list[dict[str, Any]]:
        """Coverage of this issuer in the recent past.

        Two ways an article gets here, unioned rather than one replacing the
        other:

          * ``asset_id`` - this asset's scheduled fetch retrieved it;
          * a tag - a sweep of every feed found this issuer named in it.

        The second is what makes a sector story about six banks reach all six
        rather than only whichever one's schedule happened to pull it. Both are
        needed: the schedules still cover tickers whose news arrives through a
        templated search URL the sweep cannot use.
        """
        since = self._clock() - timedelta(days=NEWS_WINDOW_DAYS)
        tagged = select(NewsItemIssuer.news_item_id).where(NewsItemIssuer.ticker == ticker)
        rows = self._session.scalars(
            select(NewsItem)
            .where(
                (NewsItem.asset_id == asset_id) | NewsItem.id.in_(tagged),
                NewsItem.published_at >= since,
            )
            .order_by(NewsItem.published_at.desc())
            .limit(40)
        ).all()

        articles: list[dict[str, Any]] = []
        for row in rows:
            score = self._session.scalar(
                select(SentimentScore)
                .where(SentimentScore.news_item_id == row.id)
                .order_by(SentimentScore.created_at.desc())
            )
            articles.append(
                {
                    "published_at": row.published_at.isoformat(),
                    "source": row.source,
                    "headline": row.headline,
                    "summary": row.body_summary,
                    "prior_sentiment": score.score if score else None,
                }
            )
        return articles
