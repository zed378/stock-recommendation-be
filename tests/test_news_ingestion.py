"""Scheduled news ingestion (Phase 7, Section 12).

The idempotency rules get the most attention, because they are what make a
retried job safe: a failed run must not skip a window, a repeated fetch must
not duplicate an article, and a retry must not pay for the same embeddings
twice.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from aidss.agents.base import AgentRunner
from aidss.db.models import Asset, NewsItem, ScheduleStatus, SentimentScore, TickerNewsSchedule
from aidss.domain.types import ChatCompletion, NewsArticle
from aidss.news.collector import (
    FAILURE_THRESHOLD,
    NewsCollector,
    NewsScheduler,
    content_hash,
)
from aidss.news.schedules import (
    EXCHANGE_TIMEZONE,
    MIN_INTERVAL_SECONDS,
    PRESETS,
    InvalidScheduleError,
    next_run_at,
    resolve,
    validate_expression,
)
from aidss.plugins.adapters.ai_fixture import FixtureAIProvider
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.interfaces import NewsProvider
from aidss.rag.engine import RAGEngine
from tests.test_agents import make_gateway

NOW = datetime(2025, 6, 2, 9, 0, tzinfo=UTC)


# --- Cron presets and validation -------------------------------------------


def test_every_preset_is_a_valid_expression() -> None:
    for preset in PRESETS:
        assert validate_expression(preset.expression) == preset.expression


def test_a_malformed_expression_is_rejected() -> None:
    with pytest.raises(InvalidScheduleError, match="invalid cron"):
        validate_expression("not a cron expression")


def test_an_empty_expression_is_rejected() -> None:
    with pytest.raises(InvalidScheduleError, match="required"):
        validate_expression("   ")


def test_a_schedule_that_fires_too_often_is_rejected() -> None:
    """Below the floor, extra requests buy rate-limiting, not information."""
    with pytest.raises(InvalidScheduleError, match=str(MIN_INTERVAL_SECONDS)):
        validate_expression("* * * * *")


def test_cadence_is_measured_not_parsed() -> None:
    """`*/1` and `0-59` fire identically and look nothing alike."""
    with pytest.raises(InvalidScheduleError):
        validate_expression("0-59 * * * *")


def test_the_floor_is_exactly_five_minutes() -> None:
    assert validate_expression("*/5 * * * *") == "*/5 * * * *"
    with pytest.raises(InvalidScheduleError):
        validate_expression("*/4 * * * *")


def test_resolving_a_preset_returns_its_label() -> None:
    expression, label = resolve("daily_premarket", None)
    assert expression == "0 7 * * 1-5"
    assert "before the market opens" in label


def test_an_unknown_preset_lists_the_available_ones() -> None:
    with pytest.raises(InvalidScheduleError, match="daily_premarket"):
        resolve("does_not_exist", None)


def test_either_a_preset_or_an_expression_is_required() -> None:
    with pytest.raises(InvalidScheduleError, match="required"):
        resolve(None, None)


def test_schedules_fire_in_exchange_time_not_utc() -> None:
    """"Before the market opens" must not mean mid-afternoon in Jakarta."""
    fires = next_run_at("0 7 * * 1-5", after=NOW)
    assert fires.astimezone(EXCHANGE_TIMEZONE).hour == 7


def test_a_weekday_schedule_skips_the_weekend() -> None:
    saturday = datetime(2025, 6, 7, 12, 0, tzinfo=UTC)
    fires = next_run_at("0 7 * * 1-5", after=saturday).astimezone(EXCHANGE_TIMEZONE)
    assert fires.weekday() < 5


# --- Deduplication ---------------------------------------------------------


def article(headline: str, url: str, published: datetime | None = None) -> NewsArticle:
    return NewsArticle(
        source="test-wire",
        source_url=url,
        headline=headline,
        summary=f"Body text for {headline}.",
        published_at=published or (NOW - timedelta(hours=1)),
    )


def test_tracking_parameters_do_not_create_a_duplicate() -> None:
    """Some providers append them; the same story must hash the same."""
    a = article("BBCA reports growth", "https://wire.invalid/a")
    b = article("BBCA reports growth", "https://wire.invalid/a?utm_source=feed")
    assert content_hash(a) == content_hash(b)


def test_a_different_headline_at_the_same_url_is_a_different_article() -> None:
    a = article("BBCA reports growth", "https://wire.invalid/a")
    b = article("BBCA reports a decline", "https://wire.invalid/a")
    assert content_hash(a) != content_hash(b)


# --- Collector -------------------------------------------------------------


class StubNewsProvider(NewsProvider):
    name = "stub-news"

    def __init__(self, articles: list[NewsArticle], *, fail: bool = False) -> None:
        self._articles = articles
        self._fail = fail
        self.calls: list[tuple[datetime, datetime]] = []

    def get_news(self, ticker, start, end):
        self.calls.append((start, end))
        if self._fail:
            raise ProviderUnavailableError(self.name, "upstream down", retryable=True)
        return list(self._articles)


@pytest.fixture
def asset(session) -> Asset:
    row = Asset(ticker="BBCA", exchange="IDX")
    session.add(row)
    session.flush()
    return row


def sentiment_runner(scores: list[dict] | None = None) -> AgentRunner:
    """A runner whose sentiment scorer answers from a script."""
    payload = json.dumps(
        {
            "summary": "Scored the supplied articles.",
            "data_sufficiency": "sufficient",
            "confidence": 60.0,
            "scores": scores if scores is not None else [],
        }
    )

    class Scorer(FixtureAIProvider):
        def chat_completion(self, messages, **kwargs):
            self.calls.append(list(messages))
            return ChatCompletion(
                content=payload, model="fixture-model", prompt_tokens=10, completion_tokens=5
            )

    return AgentRunner(make_gateway(Scorer()))


def test_articles_are_fetched_and_stored(session, asset) -> None:
    provider = StubNewsProvider([article("BBCA up", "https://wire.invalid/1")])
    collector = NewsCollector(session, provider)
    report = collector.ingest(asset, since=NOW - timedelta(days=1), until=NOW)

    assert report.fetched == 1
    assert report.inserted == 1
    assert session.scalar(select(func.count()).select_from(NewsItem)) == 1


def test_refetching_the_same_window_inserts_nothing(session, asset) -> None:
    provider = StubNewsProvider([article("BBCA up", "https://wire.invalid/1")])
    collector = NewsCollector(session, provider)

    collector.ingest(asset, since=NOW - timedelta(days=1), until=NOW)
    second = collector.ingest(asset, since=NOW - timedelta(days=1), until=NOW)

    assert second.inserted == 0
    assert second.duplicates == 1


def test_duplicates_within_one_response_are_collapsed(session, asset) -> None:
    """Providers do return the same story twice in a single payload."""
    duplicate = article("BBCA up", "https://wire.invalid/1")
    provider = StubNewsProvider([duplicate, duplicate])
    report = NewsCollector(session, provider).ingest(
        asset, since=NOW - timedelta(days=1), until=NOW
    )

    assert report.inserted == 1
    assert report.duplicates == 1


def test_a_provider_failure_is_reported_not_swallowed(session, asset) -> None:
    provider = StubNewsProvider([], fail=True)
    report = NewsCollector(session, provider).ingest(
        asset, since=NOW - timedelta(days=1), until=NOW
    )

    assert not report.ok
    assert "upstream down" in report.error


def test_sentiment_is_stored_per_article(session, asset) -> None:
    provider = StubNewsProvider(
        [
            article("BBCA up", "https://wire.invalid/1"),
            article("BBCA down", "https://wire.invalid/2"),
        ]
    )
    runner = sentiment_runner(
        [
            {"index": 0, "score": 0.6, "rationale": "Profit growth reported."},
            {"index": 1, "score": -0.4, "rationale": "Guidance was cut."},
        ]
    )
    report = NewsCollector(session, provider, runner=runner).ingest(
        asset, since=NOW - timedelta(days=1), until=NOW
    )

    assert report.scored == 2
    scores = session.scalars(select(SentimentScore)).all()
    assert sorted(s.score for s in scores) == [-0.4, 0.6]
    assert all(s.rationale for s in scores)


def test_a_hallucinated_index_is_dropped_with_a_warning(session, asset) -> None:
    """Attaching a score to the wrong article is worse than no score."""
    provider = StubNewsProvider([article("BBCA up", "https://wire.invalid/1")])
    runner = sentiment_runner(
        [
            {"index": 0, "score": 0.5, "rationale": "Fine."},
            {"index": 9, "score": -0.9, "rationale": "Refers to nothing."},
        ]
    )
    report = NewsCollector(session, provider, runner=runner).ingest(
        asset, since=NOW - timedelta(days=1), until=NOW
    )

    assert report.scored == 1
    assert any("article 9" in w for w in report.warnings)


def test_a_sentiment_outage_does_not_lose_the_articles(session, asset) -> None:
    """Ingestion is useful on its own; scoring can be retried later."""
    provider = StubNewsProvider([article("BBCA up", "https://wire.invalid/1")])

    class Broken(FixtureAIProvider):
        def chat_completion(self, messages, **kwargs):
            return ChatCompletion(
                content="not json", model="fixture-model", prompt_tokens=1, completion_tokens=1
            )

    report = NewsCollector(session, provider, runner=AgentRunner(make_gateway(Broken()))).ingest(
        asset, since=NOW - timedelta(days=1), until=NOW
    )

    assert report.inserted == 1
    assert report.ok, "a scoring failure is not an ingestion failure"
    assert report.warnings


def test_articles_are_chunked_and_indexed(session, asset) -> None:
    provider = StubNewsProvider([article("BBCA up", "https://wire.invalid/1")])
    rag = RAGEngine(session, FixtureAIProvider(), embedding_model="fixture-embed")
    report = NewsCollector(session, provider, rag=rag).ingest(
        asset, since=NOW - timedelta(days=1), until=NOW
    )

    assert report.chunks_indexed > 0
    assert session.scalar(select(NewsItem)).is_indexed is True


# --- Scheduler -------------------------------------------------------------


def schedule_for(session, asset, expression: str = "0 7 * * 1-5") -> TickerNewsSchedule:
    from aidss.db.models import User
    from aidss.security.passwords import hash_password

    # Reused rather than recreated: a test that sets up two schedules would
    # otherwise trip the unique-email constraint.
    user = session.scalar(select(User).where(User.email == "sched@example.com"))
    if user is None:
        user = User(
            email="sched@example.com", password_hash=hash_password("correct-horse-battery")
        )
        session.add(user)
        session.flush()

    row = TickerNewsSchedule(
        user_id=user.id,
        asset_id=asset.id,
        cron_expression=expression,
        next_run_at=NOW - timedelta(minutes=1),
    )
    session.add(row)
    session.flush()
    return row


def test_only_due_and_active_schedules_are_selected(session, asset) -> None:
    due = schedule_for(session, asset)
    future = schedule_for(session, asset, "0 8 * * 1-5")
    future.next_run_at = NOW + timedelta(days=1)
    session.flush()

    scheduler = NewsScheduler(session, NewsCollector(session, StubNewsProvider([])))
    assert [s.id for s in scheduler.due(now=NOW)] == [due.id]


def test_an_inactive_schedule_is_never_due(session, asset) -> None:
    row = schedule_for(session, asset)
    row.is_active = False
    session.flush()

    scheduler = NewsScheduler(session, NewsCollector(session, StubNewsProvider([])))
    assert scheduler.due(now=NOW) == []


def test_a_successful_run_advances_the_window(session, asset) -> None:
    row = schedule_for(session, asset)
    provider = StubNewsProvider([article("BBCA up", "https://wire.invalid/1")])
    scheduler = NewsScheduler(session, NewsCollector(session, provider))

    scheduler.run_schedule(row, now=NOW)
    assert row.last_fetched_at == NOW
    assert row.next_run_at > NOW
    assert row.consecutive_failures == 0


def test_a_failed_run_does_not_advance_the_window(session, asset) -> None:
    """Otherwise everything published during the outage is skipped forever."""
    row = schedule_for(session, asset)
    row.last_fetched_at = NOW - timedelta(hours=6)
    session.flush()

    scheduler = NewsScheduler(session, NewsCollector(session, StubNewsProvider([], fail=True)))
    scheduler.run_schedule(row, now=NOW)

    assert row.last_fetched_at == NOW - timedelta(hours=6)
    assert row.consecutive_failures == 1
    # It is still rescheduled, so a transient outage recovers on its own.
    assert row.next_run_at > NOW


def test_repeated_failure_flags_rather_than_disables(session, asset) -> None:
    """A silently stopped schedule looks identical to one finding no news."""
    row = schedule_for(session, asset)
    scheduler = NewsScheduler(session, NewsCollector(session, StubNewsProvider([], fail=True)))

    for _ in range(FAILURE_THRESHOLD):
        scheduler.run_schedule(row, now=NOW)

    assert row.status is ScheduleStatus.NEEDS_ATTENTION
    assert row.is_active is True, "flagged for attention, not switched off"


def test_recovery_clears_the_flag(session, asset) -> None:
    row = schedule_for(session, asset)
    failing = NewsScheduler(session, NewsCollector(session, StubNewsProvider([], fail=True)))
    for _ in range(FAILURE_THRESHOLD):
        failing.run_schedule(row, now=NOW)
    assert row.status is ScheduleStatus.NEEDS_ATTENTION

    healthy = NewsScheduler(
        session, NewsCollector(session, StubNewsProvider([article("BBCA", "https://w.invalid/x")]))
    )
    healthy.run_schedule(row, now=NOW)

    assert row.status is ScheduleStatus.ACTIVE
    assert row.consecutive_failures == 0


def test_the_fetch_window_starts_where_the_last_one_ended(session, asset) -> None:
    row = schedule_for(session, asset)
    row.last_fetched_at = NOW - timedelta(hours=3)
    session.flush()

    provider = StubNewsProvider([])
    NewsScheduler(session, NewsCollector(session, provider)).run_schedule(row, now=NOW)

    start, end = provider.calls[0]
    assert start == NOW - timedelta(hours=3)
    assert end == NOW


def test_a_schedule_whose_asset_vanished_is_deactivated(session, asset) -> None:
    row = schedule_for(session, asset)
    row.asset_id = asset.id
    session.delete(asset)
    session.flush()

    scheduler = NewsScheduler(session, NewsCollector(session, StubNewsProvider([])))
    report = scheduler.run_schedule(row, now=NOW)
    assert not report.ok
    assert row.is_active is False


def test_a_score_labelled_reason_is_still_accepted(session, asset) -> None:
    """The bug this exists to prevent recurring.

    The prompt asked for "a short reason" and never named the field; the schema
    required `rationale` and forbade extras. The model did exactly as it was
    told, so every batch failed validation on every article and sentiment
    scoring never once produced a row - reported only as a warning inside an
    otherwise successful ingestion.

    The existing test could not have caught it: it scripted the model's answer
    using our own field name, so it exercised the schema against itself rather
    than against anything a model would say.
    """
    provider = StubNewsProvider([article("BBCA up", "https://wire.invalid/1")])
    runner = sentiment_runner([{"index": 0, "score": 0.5, "reason": "Profit growth."}])

    report = NewsCollector(session, provider, runner=runner).ingest(
        asset, since=NOW - timedelta(days=1), until=NOW
    )

    assert report.scored == 1
    assert report.warnings == []
    [score] = session.scalars(select(SentimentScore)).all()
    assert score.rationale == "Profit growth."
