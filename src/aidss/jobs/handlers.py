"""Job handlers and the registry that dispatches to them (Section 4).

A handler receives a session and the job's payload, and returns whatever should
be stored as the result. Raising ``PermanentJobError`` dead-letters the job
immediately; any other exception is retried with backoff.

That distinction is the important one. A malformed payload will be malformed on
the fourth attempt too, and retrying it three times only delays the alert while
producing three identical errors in the log.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from aidss.agents.engine import AnalysisEngine
from aidss.collectors.issuers import sync_directory
from aidss.collectors.market_data import FundamentalCollector, MarketDataCollector, load_candles
from aidss.config import get_settings
from aidss.db.base import get_sessionmaker
from aidss.db.models import AnalysisResult, Asset, FundamentalMetric, TickerNewsSchedule
from aidss.domain.types import Timeframe
from aidss.indicators.engine import IndicatorEngine
from aidss.indicators.features import persist_features
from aidss.jobs import queue, quota
from aidss.llm.provisioning import build_gateway
from aidss.monitoring.poller import poll_watched_assets
from aidss.news.collector import NewsCollector, NewsScheduler
from aidss.news.sweep import sweep_all_sources, tag_untagged
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.registry import get_market_data_provider, get_news_provider
from aidss.rag.provisioning import build_rag
from aidss.reporting.notifications import NotificationEvent, NotificationService

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
# News (Section 6.3.2)
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
