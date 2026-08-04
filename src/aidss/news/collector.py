"""Scheduled news ingestion (Phase 7, Section 6.3).

The nine steps of Section 6.3.1, from a due schedule through to chunks a RAG
query can reach: fetch incrementally, deduplicate, store, score sentiment,
chunk, embed, index.

The idempotency rules of Section 6.3.3 are the spine of it:

  * ``last_fetched_at`` advances **only** on success, so a job that dies
    halfway re-fetches the same window instead of skipping over it.
  * Articles deduplicate on a content hash, so re-fetching that window inserts
    nothing new.
  * ``is_indexed`` gates embedding, so a retry does not pay for the same
    vectors twice.

Repeated failure flags the schedule rather than disabling it. A schedule that
silently stopped would look identical to one finding no news.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.agents.base import Agent, AgentRunner
from aidss.agents.memory import InvestorMemory
from aidss.db.models import (
    Asset,
    NewsItem,
    ScheduleStatus,
    SentimentScore,
    TickerNewsSchedule,
)
from aidss.domain.types import NewsArticle
from aidss.llm.errors import GatewayError
from aidss.llm.router import TaskComplexity
from aidss.news.schedules import next_run_at
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.interfaces import NewsProvider
from aidss.prompts.schemas import BatchSentimentOutput
from aidss.prompts.validator import ValidationFailure
from aidss.rag.engine import RAGEngine

#: How far back a schedule reaches on its very first run. Without a bound, a
#: new schedule would try to ingest an issuer's entire news history.
FIRST_RUN_LOOKBACK_DAYS = 7

#: Consecutive failures before the schedule is flagged for attention
#: (Section 6.3.3).
FAILURE_THRESHOLD = 5

#: Articles scored per model call.
SENTIMENT_BATCH_SIZE = 20


def content_hash(article: NewsArticle) -> str:
    """Deduplication key.

    Hashes URL *and* headline: the same story is often syndicated under
    different URLs, and some providers append tracking parameters that make one
    article look like several.
    """
    material = f"{article.source_url.split('?')[0]}|{article.headline.strip().lower()}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class IngestionReport:
    ticker: str
    fetched: int = 0
    inserted: int = 0
    duplicates: int = 0
    scored: int = 0
    chunks_indexed: int = 0
    error: str | None = None
    #: Non-fatal problems: the articles were stored, but something downstream
    #: did not complete. Kept separate from `error` so a sentiment outage does
    #: not read as an ingestion failure.
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "fetched": self.fetched,
            "inserted": self.inserted,
            "duplicates": self.duplicates,
            "scored": self.scored,
            "chunks_indexed": self.chunks_indexed,
            "error": self.error,
            "warnings": list(self.warnings),
        }


class SentimentScorer(Agent):
    """Scores a batch of articles in one call."""

    name = "sentiment_scorer"
    template_name = "sentiment_scoring"
    output_model = BatchSentimentOutput
    complexity = TaskComplexity.LIGHT

    def __init__(self, ticker: str, articles: list[NewsItem]) -> None:
        self._ticker = ticker
        self._articles = articles

    def prompt_context(self, context: Any) -> dict[str, Any]:
        return {
            "ticker": self._ticker,
            "articles": [
                {
                    "index": i,
                    "published_at": item.published_at.isoformat(),
                    "source": item.source,
                    "headline": item.headline,
                    "summary": item.body_summary,
                }
                for i, item in enumerate(self._articles)
            ],
        }


@dataclass(slots=True)
class _ScoringContext:
    """Minimal context - the scorer needs no market evidence, only the articles."""

    memory: InvestorMemory


class NewsCollector:
    def __init__(
        self,
        session: Session,
        provider: NewsProvider,
        *,
        runner: AgentRunner | None = None,
        rag: RAGEngine | None = None,
    ) -> None:
        self._session = session
        self._provider = provider
        #: Both optional: ingestion is useful on its own, and a sentiment or
        #: embedding outage should not stop articles being stored.
        self._runner = runner
        self._rag = rag

    # --- steps 5-7: fetch, deduplicate, store ---------------------------

    def fetch_and_store(
        self,
        asset: Asset,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        schedule_id: uuid.UUID | None = None,
    ) -> tuple[IngestionReport, list[NewsItem]]:
        report = IngestionReport(ticker=asset.ticker)
        until = until or datetime.now(UTC)
        since = since or (until - timedelta(days=FIRST_RUN_LOOKBACK_DAYS))

        try:
            articles = self._provider.get_news(asset.ticker, since, until)
        except ProviderUnavailableError as exc:
            report.error = str(exc)
            return report, []

        report.fetched = len(articles)
        if not articles:
            return report, []

        hashes = [content_hash(a) for a in articles]
        already = set(
            self._session.scalars(
                select(NewsItem.dedup_hash).where(NewsItem.dedup_hash.in_(hashes))
            ).all()
        )

        stored: list[NewsItem] = []
        seen_in_batch: set[str] = set()
        for article, digest in zip(articles, hashes, strict=True):
            # Checked against the batch as well as the database: providers do
            # return the same story twice within one response.
            if digest in already or digest in seen_in_batch:
                report.duplicates += 1
                continue
            seen_in_batch.add(digest)

            item = NewsItem(
                asset_id=asset.id,
                schedule_id=schedule_id,
                source=article.source,
                source_url=article.source_url[:1000],
                dedup_hash=digest,
                headline=article.headline[:500],
                body_summary=article.summary,
                published_at=article.published_at,
            )
            self._session.add(item)
            stored.append(item)
            report.inserted += 1

        self._session.flush()
        return report, stored

    # --- step 6: sentiment ----------------------------------------------

    def score_sentiment(
        self, asset: Asset, items: list[NewsItem], report: IngestionReport
    ) -> None:
        if not items or self._runner is None:
            return

        context = _ScoringContext(memory=InvestorMemory(user_id=None, preferences={}))

        for start in range(0, len(items), SENTIMENT_BATCH_SIZE):
            batch = items[start : start + SENTIMENT_BATCH_SIZE]
            try:
                run = self._runner.run(SentimentScorer(asset.ticker, batch), context)
            except (ValidationFailure, GatewayError) as exc:
                # Articles are already stored; scoring can be retried later.
                report.warnings.append(f"sentiment scoring failed: {exc}")
                return

            output: BatchSentimentOutput = run.output  # type: ignore[assignment]
            for entry in output.scores:
                if entry.index >= len(batch):
                    # A hallucinated index would otherwise attach a score to
                    # the wrong article, which is worse than no score.
                    report.warnings.append(
                        f"sentiment score referenced article {entry.index}, "
                        f"which was not in the batch of {len(batch)}"
                    )
                    continue
                self._session.add(
                    SentimentScore(
                        news_item_id=batch[entry.index].id,
                        score=entry.score,
                        model_used=run.usage.model,
                        rationale=entry.rationale,
                    )
                )
                report.scored += 1

        self._session.flush()

    # --- steps 8-9: chunk, embed, index ---------------------------------

    def index(self, items: list[NewsItem], report: IngestionReport) -> None:
        if not items or self._rag is None:
            return
        try:
            index_report = self._rag.index_news(items)
        except ProviderUnavailableError as exc:
            report.warnings.append(f"embedding failed: {exc}")
            return
        report.chunks_indexed = index_report.chunks_created

    # --- the whole flow --------------------------------------------------

    def ingest(
        self,
        asset: Asset,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        schedule_id: uuid.UUID | None = None,
    ) -> IngestionReport:
        report, stored = self.fetch_and_store(
            asset, since=since, until=until, schedule_id=schedule_id
        )
        if not report.ok:
            return report
        self.score_sentiment(asset, stored, report)
        self.index(stored, report)
        return report


class NewsScheduler:
    """Finds due schedules and runs them (Section 6.3.2)."""

    def __init__(self, session: Session, collector: NewsCollector) -> None:
        self._session = session
        self._collector = collector

    def due(self, *, now: datetime | None = None) -> list[TickerNewsSchedule]:
        now = now or datetime.now(UTC)
        return list(
            self._session.scalars(
                select(TickerNewsSchedule).where(
                    TickerNewsSchedule.is_active.is_(True),
                    TickerNewsSchedule.next_run_at <= now,
                )
            ).all()
        )

    def run_schedule(
        self, schedule: TickerNewsSchedule, *, now: datetime | None = None
    ) -> IngestionReport:
        now = now or datetime.now(UTC)
        asset = self._session.get(Asset, schedule.asset_id)
        if asset is None:
            report = IngestionReport(ticker="unknown", error="asset no longer exists")
            schedule.is_active = False
            self._session.flush()
            return report

        report = self._collector.ingest(
            asset,
            since=schedule.last_fetched_at,
            until=now,
            schedule_id=schedule.id,
        )

        if report.ok:
            # Advanced only on success: on failure the same window is retried,
            # so nothing published during the outage is skipped.
            schedule.last_fetched_at = now
            schedule.consecutive_failures = 0
            schedule.status = ScheduleStatus.ACTIVE
        else:
            schedule.consecutive_failures += 1
            if schedule.consecutive_failures >= FAILURE_THRESHOLD:
                # Flagged, not disabled. A schedule that silently stopped would
                # look exactly like one finding no news (Section 6.3.3).
                schedule.status = ScheduleStatus.NEEDS_ATTENTION

        schedule.next_run_at = next_run_at(schedule.cron_expression, after=now)
        self._session.flush()
        return report

    def run_due(self, *, now: datetime | None = None, limit: int = 50) -> list[IngestionReport]:
        return [self.run_schedule(s, now=now) for s in self.due(now=now)[:limit]]
