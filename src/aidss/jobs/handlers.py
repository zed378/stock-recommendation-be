"""Job handlers and the registry that dispatches to them (Section 4).

A handler receives a session and the job's payload, and returns whatever should
be stored as the result. Raising ``PermanentJobError`` dead-letters the job
immediately; any other exception is retried with backoff.

That distinction is the important one. A malformed payload will be malformed on
the fourth attempt too, and retrying it three times only delays the alert while
producing three identical errors in the log.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from aidss.agents.engine import AnalysisEngine
from aidss.collectors.issuers import sync_directory
from aidss.collectors.market_data import FundamentalCollector, MarketDataCollector, load_candles
from aidss.collectors.trading_summary import BACKFILL_SESSIONS, sync_summaries
from aidss.config import get_settings
from aidss.db.base import get_sessionmaker
from aidss.db.models import (
    AnalysisResult,
    Asset,
    DailyTradingSummary,
    FundamentalMetric,
    SchedulerJob,
    TickerNewsSchedule,
)
from aidss.domain.types import Timeframe
from aidss.indicators.engine import IndicatorEngine
from aidss.indicators.features import persist_features
from aidss.jobs import queue, quota
from aidss.llm.provisioning import build_gateway
from aidss.monitoring.poller import poll_watched_assets
from aidss.monitoring.scan import SCAN_CHUNK, scan_tickers, scannable_tickers
from aidss.news.collector import NewsCollector, NewsScheduler
from aidss.news.schedules import next_run_at
from aidss.news.sweep import sweep_all_sources, tag_untagged
from aidss.platform.settings import (
    MARKET_SCAN_CRON,
    MARKET_SCAN_JITTER,
    NEWS_SWEEP_CRON,
    get_setting,
)
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.registry import get_market_data_provider, get_news_provider
from aidss.rag.provisioning import build_rag
from aidss.reporting.notifications import NotificationEvent, NotificationService

logger = logging.getLogger("aidss.jobs")

#: Seconds between queued backfill imports. The endpoint publishes no rate
#: limit, so the pacing is a guess made deliberately on the slow side: a
#: backfill is a one-off that can take an hour, and being throttled costs more
#: than waiting.
SUMMARY_BACKFILL_SPACING = 8.0

Handler = Callable[[Session, dict[str, Any]], dict[str, Any]]


class PermanentJobError(Exception):
    """The job cannot succeed however many times it is retried."""


class JobDeferred(Exception):
    """Not now, but not a failure either - try again after ``until``.

    Distinct from a retryable error on purpose. A retry costs the job one of
    its attempts, which is right when something went wrong and wrong when
    nothing did: a job waiting for tomorrow's provider allowance would spend
    its whole retry budget waiting and dead-letter without ever having been
    attempted.
    """

    def __init__(self, until: datetime, reason: str) -> None:
        super().__init__(f"deferred until {until.isoformat()}: {reason}")
        self.until = until
        self.reason = reason


_HANDLERS: dict[str, Handler] = {}


def register(job_type: str) -> Callable[[Handler], Handler]:
    def decorator(handler: Handler) -> Handler:
        if job_type in _HANDLERS:
            raise ValueError(f"a handler for {job_type!r} is already registered")
        _HANDLERS[job_type] = handler
        return handler

    return decorator


def get_handler(job_type: str) -> Handler:
    handler = _HANDLERS.get(job_type)
    if handler is None:
        # Permanent by nature: an unknown type will still be unknown next time,
        # usually because a worker is running older code than the enqueuer.
        raise PermanentJobError(
            f"no handler registered for job type {job_type!r}. "
            f"Known types: {sorted(_HANDLERS)}"
        )
    return handler


def registered_types() -> list[str]:
    return sorted(_HANDLERS)


def _asset(session: Session, payload: dict[str, Any]) -> Asset:
    asset_id = payload.get("asset_id")
    if not asset_id:
        raise PermanentJobError("payload is missing asset_id")
    asset = session.get(Asset, uuid.UUID(str(asset_id)))
    if asset is None:
        raise PermanentJobError(f"asset {asset_id} no longer exists")
    return asset


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------


@register("market_data.backfill")
def backfill_market_data(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Fetch price history and recompute indicators.

    This is the work Section 2.6 puts on the queue rather than a request
    thread: a multi-year backfill across several timeframes is minutes of
    provider calls, not milliseconds.
    """
    asset = _asset(session, payload)
    timeframe = Timeframe(payload.get("timeframe", Timeframe.D1.value))
    days = int(payload.get("days", 400))

    collector = MarketDataCollector(get_market_data_provider())
    end = datetime.now(UTC)
    report = collector.collect(session, asset, timeframe, end - timedelta(days=days), end)

    candles = load_candles(session, asset.id, timeframe)
    indicators = IndicatorEngine().persist(session, asset.id, timeframe, candles)
    persist_features(session, asset.id, timeframe, candles)

    return {
        "ticker": asset.ticker,
        "fetched": report.fetched,
        "inserted": report.inserted,
        "updated": report.updated,
        "rejected": report.rejected,
        "indicators_inserted": indicators.inserted,
    }


@register("fundamentals.refresh")
def refresh_fundamentals(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Refresh one asset's reported metrics, within the provider's daily budget.

    The budget is checked before the call, not discovered by being refused.
    Alpha Vantage's free tier is 25 requests a day and answers HTTP 200 when
    it is exhausted, so a refusal looks like an outage to everything
    downstream - and the retries it triggers spend tomorrow's allowance too.
    """
    asset = _asset(session, payload)
    provider = get_market_data_provider()
    settings = get_settings()

    # Attributed to the adapter that actually answers, because the allowance
    # belongs to that account rather than to a composite wrapper.
    source = provider.fundamentals_source_name()
    limit = settings.fundamentals_daily_quota

    # Committed on its own session, so a job that fails afterwards cannot roll
    # back a spend that already happened at the provider.
    if not quota.reserve_durably(get_sessionmaker(), source, limit=limit):
        current = quota.state(session, source, limit=limit)
        raise JobDeferred(
            quota.next_reset(),
            f"{source} daily allowance spent ({current.used}/{limit})",
        )

    report = FundamentalCollector(provider).collect(session, asset)
    return {
        "ticker": report.ticker,
        "fetched": report.fetched,
        "inserted": report.inserted,
        "updated": report.updated,
        "unsupported": report.unsupported,
        "quota": quota.state(session, source, limit=limit).as_dict(),
    }


@register("monitoring.poll")
def poll_monitored_assets(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Observe every followed asset once and evaluate the alert rules.

    One provider call per asset serves everyone following it, which is why this
    is a single system-wide job rather than one per user. Alert deduplication is
    per user, so two people watching the same asset are each told once.
    """
    report = poll_watched_assets(session, get_market_data_provider())
    return report.as_dict()


# ---------------------------------------------------------------------------
# News (Section 12.2)
# ---------------------------------------------------------------------------


@register("news.ingest_schedule")
def run_news_schedule(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Run one due news schedule.

    Delegates to the same `NewsScheduler` the manual endpoint uses, so the
    automated path exercises exactly what a manual run does rather than a
    convenient approximation of it.
    """
    schedule_id = payload.get("schedule_id")
    if not schedule_id:
        raise PermanentJobError("payload is missing schedule_id")

    schedule = session.get(TickerNewsSchedule, uuid.UUID(str(schedule_id)))
    if schedule is None:
        raise PermanentJobError(f"schedule {schedule_id} no longer exists")

    collector = NewsCollector(
        session,
        get_news_provider(session=session),
        runner=_runner(session),
        rag=build_rag(session),
    )
    report = NewsScheduler(session, collector).run_schedule(schedule)

    if not report.ok:
        # Raised so the queue retries with backoff. The schedule's own failure
        # counter has already been incremented, so a persistent outage flags it
        # for attention independently of what the queue does.
        raise ProviderUnavailableError("news", report.error or "ingestion failed")

    return report.as_dict()


@register("news.sweep")
def sweep_news(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Read every active feed once and attribute what it carries.

    Queued rather than run on the request, because reading twenty feeds over
    the open internet is not work that fits inside a request timeout - the
    same reason the analysis moved off it.
    """
    provider = get_news_provider(session=session)
    if not hasattr(provider, "fetch"):
        # The fixture provider manufactures articles per ticker and has no feed
        # to sweep. Saying so beats sweeping nothing and reporting success -
        # which is how this subsystem sat broken for weeks.
        raise PermanentJobError(
            f"the configured news provider ({type(provider).__name__}) reads no feeds; "
            "set AIDSS_NEWS_PROVIDER=rss"
        )

    try:
        report = sweep_all_sources(session, provider)
    except ValueError as exc:
        raise PermanentJobError(str(exc)) from exc

    result = report.as_payload()
    user_id = payload.get("user_id")
    if user_id:
        NotificationService(session).notify(
            uuid.UUID(str(user_id)),
            NotificationEvent.NEWS_SWEEP_COMPLETE,
            (
                f"Read {report.sources_read} feeds: {report.inserted} new articles, "
                f"{report.tagged} matched to an issuer."
            ),
            context=result,
        )
    return result


@register("news.tag_backfill")
def backfill_news_tags(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Attribute stories already in the database that carry no tags.

    Exists because tagging arrived after the news did, and because correcting
    an alias should be able to reach the archive rather than only future
    articles.
    """
    limit = int(payload.get("limit") or 500)
    return tag_untagged(session, limit=max(1, min(limit, 5000)))


# ---------------------------------------------------------------------------
# The listed-company directory
# ---------------------------------------------------------------------------


@register("market.trading_summary")
def sync_trading_summary(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Store one session's exchange record for every issuer.

    One request covers all 963, so this is a single job rather than one per
    watched ticker - and it means the foreign-flow history exists for a name
    before anybody starts watching it, which is when that history is worth
    having.

    A date with no rows is a weekend or a holiday, not a failure. Reported as
    such rather than retried: the queue would otherwise spend its attempts on
    a day the market was shut.
    """
    from aidss.plugins.adapters.market_idx import IDXMarketDataProvider

    raw = payload.get("date")
    on_date = date.fromisoformat(str(raw)) if raw else datetime.now(UTC).date()

    provider = IDXMarketDataProvider.from_settings(get_settings())
    rows = provider.daily_trading_summary(on_date)
    if not rows:
        return {"session_date": on_date.isoformat(), "added": 0, "updated": 0, "closed": True}

    report = sync_summaries(session, rows)
    return {**report.as_payload(), "closed": False}



@register("market.summary_backfill")
def plan_summary_backfill(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Queue one import job per session date, rather than fetching a year at once.

    Pulling a trading year in one job is three hundred sequential requests to
    an endpoint that publishes no rate limit and sits behind bot management.
    Held in a single job that is: one unit of work that runs for many minutes,
    retries from the beginning when it fails at request two hundred, and looks
    identical to a hang while it does.

    Split, each date is its own job with its own retry, the queue's existing
    concurrency limit paces the whole thing, and a failure costs one session
    rather than the run. The dates are spread out through `available_at` so the
    backfill does not become a burst the moment it is planned.

    Idempotent per date: re-planning a range that is already stored queues
    nothing, because the import jobs dedupe on their own date.
    """
    sessions = int(payload.get("sessions") or BACKFILL_SESSIONS)
    sessions = max(1, min(sessions, 1000))
    # `is None` rather than `or`: zero is a meaningful value here - "queue
    # them all now" - and `or` silently turns it into the default.
    raw_spacing = payload.get("spacing_seconds")
    spacing = float(SUMMARY_BACKFILL_SPACING if raw_spacing is None else raw_spacing)

    end = (
        date.fromisoformat(str(payload["until"]))
        if payload.get("until")
        else datetime.now(UTC).date()
    )
    # Which dates already have rows, so a re-plan after a partial run queues
    # only the gaps.
    stored = {
        row
        for row in session.scalars(
            select(DailyTradingSummary.session_date)
            .where(DailyTradingSummary.session_date > end - timedelta(days=sessions))
            .distinct()
        ).all()
    }

    queued = 0
    now = datetime.now(UTC)
    for offset in range(sessions):
        on_date = end - timedelta(days=offset)
        # Weekends are skipped here rather than discovered by the handler: the
        # exchange answers with an empty list, which costs a request to learn
        # something a calendar already knows.
        if on_date.weekday() >= 5 or on_date in stored:
            continue
        result = queue.enqueue(
            session,
            "market.trading_summary",
            {"date": on_date.isoformat()},
            dedup_key=f"trading-summary:{on_date.isoformat()}",
            available_at=now + timedelta(seconds=spacing * queued),
        )
        if result.created:
            queued += 1

    return {
        "queued": queued,
        "already_stored": len(stored),
        "until": end.isoformat(),
        "spacing_seconds": spacing,
    }



@register("market.scan")
def plan_market_scan(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Split the whole-market scan into chunks and queue them.

    A thousand issuers in one job is one unit of work that runs for minutes,
    holds a transaction open the whole time, and restarts from the first ticker
    when it fails at the nine hundredth. Chunked, a failure costs a hundred
    names and the queue's own concurrency limit paces the rest.

    Planning is separate from scanning so this job stays fast: it reads which
    tickers have enough history and queues the work, which is milliseconds.
    """
    tickers = scannable_tickers(session)
    if not tickers:
        return {"chunks": 0, "tickers": 0, "reason": "no issuer has enough stored sessions yet"}

    size = int(payload.get("chunk_size") or SCAN_CHUNK)
    size = max(10, min(size, 500))
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M")

    chunks = 0
    for start in range(0, len(tickers), size):
        batch = tickers[start : start + size]
        result = queue.enqueue(
            session,
            "market.scan_chunk",
            {"tickers": batch},
            # Keyed by the chunk's first ticker and the minute: a scheduler
            # ticking twice queues one set of chunks, not two.
            dedup_key=f"market-scan:{stamp}:{batch[0]}",
        )
        if result.created:
            chunks += 1

    return {"chunks": chunks, "tickers": len(tickers), "chunk_size": size}


@register("market.scan_chunk")
def scan_market_chunk(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate every criterion for one chunk of issuers."""
    tickers = [str(t).upper() for t in (payload.get("tickers") or [])]
    if not tickers:
        raise PermanentJobError("payload carried no tickers")
    return scan_tickers(session, tickers).as_payload()


@register("issuers.sync")
def sync_issuer_directory(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Refresh the IDX company directory that tagging matches against.

    Its completeness is what tagging's recall rests on: an issuer missing here
    produces no wrong tag, it produces silence, and silence is indistinguishable
    from a story that named nobody.
    """
    from aidss.plugins.adapters.market_idx import IDXMarketDataProvider

    provider = IDXMarketDataProvider.from_settings(get_settings())
    rows = provider.list_companies()
    if not rows:
        raise ProviderUnavailableError("idx", "the company directory came back empty")
    return sync_directory(session, rows).as_payload()


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


@register("analysis.run")
def run_analysis(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Run the multi-agent analysis off the request thread.

    Translation is *not* done here. It used to be, and it made a slow job far
    slower for no benefit to the person waiting: the analysis was finished and
    readable while five more model calls rendered a language they might never
    switch to. Worse, a gateway that gives up part-way through took the whole
    run with it - including the analysis that had already succeeded.

    So this stores the analysis and queues the rendering behind it. The reader
    gets the result as soon as it exists, and the other language arrives when
    it arrives.
    """
    asset = _asset(session, payload)
    timeframe = Timeframe(payload.get("timeframe", Timeframe.D1.value))
    user_id = payload.get("user_id")

    engine = AnalysisEngine(session, build_gateway(session))
    run = engine.analyze(
        asset,
        timeframe,
        user_id=uuid.UUID(str(user_id)) if user_id else None,
        include_recommendation=bool(payload.get("include_recommendation", True)),
        translate_output=False,
    )

    if not run.runs:
        # Not an error to retry: no agent had anything to work with, and that
        # will still be true in thirty seconds.
        raise PermanentJobError(
            "no agent produced output; "
            + "; ".join(f"{s.agent}: {s.reason}" for s in run.skipped)
        )

    translation_job: str | None = None
    if run.analysis_result_id is not None:
        # Enqueued in the same transaction as the analysis it renders. There is
        # no window where the analysis is stored and its rendering was never
        # asked for.
        queued = queue.enqueue(
            session,
            "analysis.translate",
            {
                "analysis_result_id": str(run.analysis_result_id),
                "user_id": str(user_id) if user_id else None,
                "ticker": run.asset_ticker,
            },
            dedup_key=f"translate:{run.analysis_result_id}",
        )
        translation_job = str(queued.job_id)

    return {
        "ticker": run.asset_ticker,
        "analysis_result_id": str(run.analysis_result_id) if run.analysis_result_id else None,
        "agents": sorted(r.agent for r in run.runs),
        "recommendation": (
            run.recommendation.as_payload()["label"] if run.recommendation else None
        ),
        "failed": [{"agent": f.agent, "reason": f.reason} for f in run.failed],
        "translation_job_id": translation_job,
    }


@register("analysis.translate")
def translate_analysis(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Render a stored analysis in the other language.

    A separate job because it is separate work: the analysis is the product and
    this is a convenience over it. Failing here leaves a complete analysis in
    one language, which is a smaller loss than the alternative and is what the
    interface already knows how to show.
    """
    raw_id = payload.get("analysis_result_id")
    if not raw_id:
        raise PermanentJobError("payload is missing analysis_result_id")

    result = session.get(AnalysisResult, uuid.UUID(str(raw_id)))
    if result is None:
        raise PermanentJobError(f"analysis {raw_id} no longer exists")

    engine = AnalysisEngine(session, build_gateway(session))
    report = engine.translate_stored(result)

    user_id = payload.get("user_id")
    if user_id and (report["agents"] or report["recommendation"]):
        # Announced only when something was actually rendered. Telling somebody
        # a translation is ready and then offering them nothing to switch to is
        # worse than staying quiet.
        NotificationService(session).notify(
            uuid.UUID(str(user_id)),
            NotificationEvent.TRANSLATION_READY,
            f"The other language is ready for {payload.get('ticker', 'this analysis')}.",
            context={
                "ticker": payload.get("ticker"),
                "analysis_result_id": str(result.id),
                "language": report["language"],
                "agents": report["agents"],
            },
        )

    return report


def _runner(session: Session):
    from aidss.agents.base import AgentRunner

    return AgentRunner(build_gateway(session))


# ---------------------------------------------------------------------------
# Enqueue helpers
# ---------------------------------------------------------------------------


def assets_needing_fundamentals(
    session: Session, *, now: datetime | None = None, limit: int | None = None
) -> list[Asset]:
    """Assets whose fundamentals are stalest, oldest first.

    An asset with no metrics at all sorts ahead of every asset that has some,
    because "we know nothing about this company" is a worse gap than "our
    figures are five weeks old". Without that ordering a large watchlist would
    top up the assets it already covers and never reach the ones it does not.

    Ordering is by the most recent ingestion per asset, so an asset half of
    whose metrics arrived last quarter is judged on the fresh half - a partial
    payload should not put it permanently at the front of the queue.
    """
    now = now or datetime.now(UTC)
    settings = get_settings()
    cutoff = now - timedelta(days=settings.fundamentals_refresh_interval_days)

    freshest = (
        select(
            FundamentalMetric.asset_id.label("asset_id"),
            func.max(FundamentalMetric.ingested_at).label("last_ingested"),
        )
        .group_by(FundamentalMetric.asset_id)
        .subquery()
    )

    stmt = (
        select(Asset)
        .outerjoin(freshest, freshest.c.asset_id == Asset.id)
        .where(
            (freshest.c.last_ingested.is_(None)) | (freshest.c.last_ingested < cutoff)
        )
        # NULLs first without relying on the dialect's default: PostgreSQL sorts
        # NULLs last ascending and SQLite sorts them first, so the two would
        # disagree about which assets get the day's allowance.
        .order_by(
            case((freshest.c.last_ingested.is_(None), 0), else_=1),
            freshest.c.last_ingested.asc(),
            Asset.ticker.asc(),
        )
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())


def enqueue_due_fundamentals(
    session: Session, *, now: datetime | None = None
) -> dict[str, Any]:
    """Queue fundamentals refreshes, within what today's allowance can pay for.

    The point is to spread a watchlist across days rather than to queue all of
    it and let the provider refuse most of it. Queueing beyond the budget is
    not harmful - the handler defers what it cannot afford - but it is noise,
    and a queue full of jobs waiting on tomorrow makes a real backlog harder
    to see.

    Enqueueing is *not* the same as spending: the reservation happens in the
    handler, right before the call. Reserving here would charge the allowance
    for work that has not happened yet, and any job that never ran would leak
    its slot permanently.
    """
    now = now or datetime.now(UTC)
    settings = get_settings()
    source = get_market_data_provider().fundamentals_source_name()
    limit = settings.fundamentals_daily_quota

    # `now=now` matters: without it the budget is read for the wall-clock day
    # while the dedup key below is built from `now`, so the two disagree about
    # which day it is. Harmless most of the time and wrong exactly at midnight,
    # which is when a scheduler is least likely to be watched.
    budget = quota.state(session, source, limit=limit, now=now)
    room = settings.fundamentals_max_enqueued_per_tick
    if not budget.unlimited:
        room = min(room, budget.remaining)
    if room <= 0:
        return {"enqueued": 0, "already_queued": 0, "quota": budget.as_dict()}

    enqueued = 0
    already = 0
    for asset in assets_needing_fundamentals(session, now=now, limit=room):
        # Keyed by day: one refresh per asset per day however often the
        # scheduler ticks, and a new key tomorrow if it is still stale.
        result = queue.enqueue(
            session,
            "fundamentals.refresh",
            {"asset_id": str(asset.id)},
            dedup_key=f"fundamentals:{asset.id}:{now.date().isoformat()}",
        )
        if result.created:
            enqueued += 1
        else:
            already += 1

    return {"enqueued": enqueued, "already_queued": already, "quota": budget.as_dict()}


def enqueue_monitoring_pass(
    session: Session, *, now: datetime | None = None
) -> dict[str, Any]:
    """Queue one monitoring pass per interval, however often the scheduler ticks.

    The dedup key is the interval *bucket* rather than the timestamp: a
    scheduler running every minute would otherwise queue sixty passes an hour
    against a source that updates every fifteen minutes.
    """
    now = now or datetime.now(UTC)
    interval = get_settings().monitoring_interval_seconds
    if interval <= 0:
        return {"enqueued": 0, "already_queued": 0, "disabled": True}

    bucket = int(now.timestamp()) // interval
    result = queue.enqueue(
        session, "monitoring.poll", {}, dedup_key=f"monitoring:{bucket}"
    )
    return {
        "enqueued": 1 if result.created else 0,
        "already_queued": 0 if result.created else 1,
        "disabled": False,
    }


def due_news_schedules(
    session: Session, *, now: datetime | None = None
) -> list[TickerNewsSchedule]:
    now = now or datetime.now(UTC)
    return list(
        session.scalars(
            select(TickerNewsSchedule).where(
                TickerNewsSchedule.is_active.is_(True),
                TickerNewsSchedule.next_run_at <= now,
            )
        ).all()
    )


def enqueue_daily_trading_summary(
    session: Session, *, now: datetime | None = None
) -> dict[str, Any]:
    """Queue the exchange session record on the operator's schedule.

    Cron-driven rather than fired on every scheduler tick, so the operator
    decides when the platform touches the exchange. It ships with a default -
    weekdays at 18:00 exchange time - because this is the exchange publishing
    about its own market, and a screener that sits idle until somebody finds a
    setting is a screener that looks broken.

    **The firing is jittered.** The endpoint publishes no rate limit, so the
    risk is not a documented quota but looking like a bot: a request landing at
    18:00:00.000 every weekday is a schedule, and a schedule is what rate
    limiting is for. The offset is derived from the due time rather than drawn
    randomly, so a scheduler that ticks twice inside the window computes the
    same delay both times and enqueues one job - a fresh random number each
    tick would queue a new one every minute.

    The scan is chained by the import handler once the rows are in, so nothing
    here needs to schedule it separately.
    """
    now = now or datetime.now(UTC)
    expression = str(get_setting(session, MARKET_SCAN_CRON) or "").strip()

    row = session.scalar(
        select(SchedulerJob).where(SchedulerJob.job_type == "market.trading_summary")
    )
    if not expression:
        # Turned off. Deactivated rather than deleted, so switching it back on
        # does not lose the schedule's history.
        if row is not None and row.is_active:
            row.is_active = False
        return {"enqueued": 0, "disabled": True}

    if row is None:
        row = SchedulerJob(
            job_type="market.trading_summary", cron_expr=expression, is_active=True
        )
        session.add(row)
        session.flush()
    if row.cron_expr != expression or not row.is_active:
        # Re-anchored on change: a new expression must not inherit a due time
        # computed from the old one.
        row.cron_expr = expression
        row.is_active = True
        row.next_run_at = None

    try:
        if row.next_run_at is None:
            row.next_run_at = next_run_at(expression, after=now)
            return {"enqueued": 0, "scheduled_for": row.next_run_at.isoformat()}
        if row.next_run_at > now:
            return {"enqueued": 0, "scheduled_for": row.next_run_at.isoformat()}
    except Exception as exc:  # noqa: BLE001 - the parser raises its own types
        logger.warning(
            "market scan schedule is not usable",
            extra={"cron": expression, "error": f"{type(exc).__name__}: {exc}"},
        )
        row.is_active = False
        return {"enqueued": 0, "disabled": True, "error": str(exc)}

    due = row.next_run_at
    on_date = now.date().isoformat()
    result = queue.enqueue(
        session,
        "market.trading_summary",
        {"date": on_date},
        # Deduplicated on the date rather than the due time: the record is
        # published once per session, and re-importing it is only useful when
        # the exchange revises it.
        dedup_key=f"trading-summary:{on_date}",
        available_at=due + timedelta(seconds=_jitter(session, due)),
    )
    if result.created:
        row.next_run_at = next_run_at(expression, after=now)
    return {
        "enqueued": 1 if result.created else 0,
        "already_queued": 0 if result.created else 1,
        "date": on_date,
        "scheduled_for": row.next_run_at.isoformat() if row.next_run_at else None,
    }


def _jitter(session: Session, due: datetime) -> int:
    """A stable offset inside the configured window.

    Derived from the due time by hashing rather than drawn from `random`, and
    that is load-bearing: a scheduler ticking every minute would otherwise
    compute a different `available_at` on each pass. The dedup key stops a
    second job being created, but the delay would still wander, and a job whose
    start time moves every minute is one nobody can predict or debug.
    """
    window = int(get_setting(session, MARKET_SCAN_JITTER) or 0)
    if window <= 0:
        return 0
    digest = hashlib.sha256(due.isoformat().encode()).digest()
    return int.from_bytes(digest[:4], "big") % window


def enqueue_due_news_sweep(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """Queue a sweep of every configured feed, if the operator scheduled one.

    Driven by a platform setting rather than an environment variable, because
    "read the news every two hours" is a decision the person running the
    platform makes and revises - not one that should require a redeploy.

    Empty means off, and off is the default. Reading somebody else's feeds on a
    timer nobody asked for is not a sensible thing to do by default.

    The due time is stored on a `scheduler_jobs` row rather than recomputed, so
    changing the cron takes effect from the change rather than from whenever
    the previous expression happened to point at. Advanced when the job is
    created, for the same reason the news schedules advance there: a job
    sitting in the queue would otherwise be re-enqueued on every tick.
    """
    now = now or datetime.now(UTC)
    expression = str(get_setting(session, NEWS_SWEEP_CRON) or "").strip()

    row = session.scalar(select(SchedulerJob).where(SchedulerJob.job_type == "news.sweep"))
    if not expression:
        # The operator turned it off. The row is deactivated rather than
        # deleted, so turning it back on does not lose the schedule's history.
        if row is not None and row.is_active:
            row.is_active = False
        return {"enqueued": 0, "disabled": True}

    if row is None:
        row = SchedulerJob(job_type="news.sweep", cron_expr=expression, is_active=True)
        session.add(row)
        session.flush()
    if row.cron_expr != expression or not row.is_active:
        # Re-anchored on change: a new expression must not inherit a due time
        # computed from the old one.
        row.cron_expr = expression
        row.is_active = True
        row.next_run_at = None

    try:
        if row.next_run_at is None:
            row.next_run_at = next_run_at(expression, after=now)
            return {"enqueued": 0, "scheduled_for": row.next_run_at.isoformat()}
        if row.next_run_at > now:
            return {"enqueued": 0, "scheduled_for": row.next_run_at.isoformat()}
    except Exception as exc:  # noqa: BLE001 - the parser raises its own types
        # A cron expression that stopped parsing disables the sweep loudly
        # rather than raising on every scheduler tick forever.
        logger.warning(
            "news sweep schedule is not usable",
            extra={"cron": expression, "error": f"{type(exc).__name__}: {exc}"},
        )
        row.is_active = False
        return {"enqueued": 0, "disabled": True, "error": str(exc)}

    due = row.next_run_at
    result = queue.enqueue(
        session, "news.sweep", {}, dedup_key=f"news-sweep:{due.isoformat()}"
    )
    if result.created:
        row.next_run_at = next_run_at(expression, after=now)
    return {
        "enqueued": 1 if result.created else 0,
        "already_queued": 0 if result.created else 1,
        "scheduled_for": row.next_run_at.isoformat() if row.next_run_at else None,
    }


@register("agenda.extract")
def extract_agenda(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Read dated corporate events out of coverage already stored and tagged.

    Chained after the news sweep rather than scheduled separately: the only
    thing that can produce a new calendar entry is a new article, so running
    this on its own timer would mostly re-read the same rows.
    """
    from aidss.news.agenda_extract import extract

    limit = int(payload.get("limit") or 500)
    return extract(session, limit=max(50, min(limit, 5000)))


@register("agenda.notices")
def raise_agenda_notices(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Raise one alert per watching user for each event inside its notice window."""
    from aidss.monitoring.agenda import raise_notices

    return raise_notices(session)
