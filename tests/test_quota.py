"""Daily provider allowances, and the deferral that is not a failure.

The behaviour under test is mostly about which direction to be wrong in.
Over-counting collects a little less than it could. Under-counting ends in the
provider refusing requests, which arrives downstream looking like an outage and
triggers retries that spend tomorrow's allowance too. So every ambiguous case
here resolves towards spending less.

The other theme is that waiting is not failing. A job deferred until midnight
must not be charged a retry, or three quiet days would dead-letter a job that
was never once attempted against a provider that was down.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aidss.db.models import JobQueueEntry, JobStatus, ProviderQuotaUsage
from aidss.jobs import queue, quota

NOON = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


# --- reserving -------------------------------------------------------------


def test_a_reservation_is_granted_and_recorded(session) -> None:
    assert quota.reserve(session, "alphavantage", limit=3, now=NOON) is True
    assert quota.state(session, "alphavantage", limit=3, now=NOON).used == 1


def test_reservations_accumulate_until_the_limit(session) -> None:
    for _ in range(3):
        assert quota.reserve(session, "av", limit=3, now=NOON) is True
    assert quota.reserve(session, "av", limit=3, now=NOON) is False


def test_a_refused_reservation_changes_nothing(session) -> None:
    """A refusal that still incremented would ratchet the counter past the
    limit and never recover."""
    for _ in range(3):
        quota.reserve(session, "av", limit=3, now=NOON)
    quota.reserve(session, "av", limit=3, now=NOON)
    quota.reserve(session, "av", limit=3, now=NOON)
    assert quota.state(session, "av", limit=3, now=NOON).used == 3


def test_a_new_day_starts_fresh(session) -> None:
    """The day is part of the key, so nothing has to reset anything at
    midnight - a write nobody is awake to perform."""
    for _ in range(3):
        quota.reserve(session, "av", limit=3, now=NOON)
    tomorrow = NOON + timedelta(days=1)
    assert quota.reserve(session, "av", limit=3, now=tomorrow) is True
    assert quota.state(session, "av", limit=3, now=tomorrow).used == 1
    # Yesterday is still on record.
    assert quota.state(session, "av", limit=3, now=NOON).used == 3


def test_providers_do_not_share_an_allowance(session) -> None:
    quota.reserve(session, "alphavantage", limit=1, now=NOON)
    assert quota.reserve(session, "finnhub", limit=1, now=NOON) is True


def test_a_multi_call_reservation_is_all_or_nothing(session) -> None:
    """Granting part of a batch would authorise calls the caller never made
    and leave it believing it had none."""
    quota.reserve(session, "av", limit=5, count=4, now=NOON)
    assert quota.reserve(session, "av", limit=5, count=2, now=NOON) is False
    assert quota.state(session, "av", limit=5, now=NOON).used == 4


def test_a_request_larger_than_the_whole_allowance_is_refused(session) -> None:
    """Otherwise it would create a row that can never be filled and block the
    day for the callers that would have fitted."""
    assert quota.reserve(session, "av", limit=5, count=6, now=NOON) is False
    assert quota.state(session, "av", limit=5, now=NOON).used == 0


def test_a_limit_of_zero_means_unlimited_not_forbidden(session) -> None:
    """Most providers have no daily cap. A default read as "spend nothing"
    would look exactly like a total outage."""
    state = quota.state(session, "yahoo", limit=0, now=NOON)
    assert state.unlimited
    assert quota.reserve(session, "yahoo", limit=0, now=NOON) is True


def test_usage_is_recorded_even_when_unlimited(session) -> None:
    """"How many calls did we make yesterday?" is worth answering before a
    limit starts biting, not after."""
    quota.reserve(session, "yahoo", limit=0, now=NOON)
    quota.reserve(session, "yahoo", limit=0, now=NOON)
    assert session.get(ProviderQuotaUsage, ("yahoo", NOON.date())).used == 2


def test_remaining_and_exhausted_report_usefully(session) -> None:
    quota.reserve(session, "av", limit=2, now=NOON)
    state = quota.state(session, "av", limit=2, now=NOON)
    assert state.remaining == 1
    assert not state.exhausted

    quota.reserve(session, "av", limit=2, now=NOON)
    assert quota.state(session, "av", limit=2, now=NOON).exhausted


def test_unlimited_remaining_is_not_a_number_to_loop_over(session) -> None:
    assert quota.state(session, "yahoo", limit=0, now=NOON).remaining == -1
    assert quota.state(session, "yahoo", limit=0, now=NOON).as_dict()["remaining"] is None


def test_the_next_reset_is_the_coming_utc_midnight() -> None:
    assert quota.next_reset(NOON) == datetime(2026, 8, 5, tzinfo=UTC)


def test_the_day_boundary_is_utc_whatever_the_caller_passes() -> None:
    """A local-time boundary would move the reset by the offset and hand out a
    second allowance early."""
    jakarta = datetime(2026, 8, 5, 3, 0, tzinfo=UTC).astimezone(
        __import__("zoneinfo").ZoneInfo("Asia/Jakarta")
    )
    assert quota.next_reset(jakarta) == datetime(2026, 8, 6, tzinfo=UTC)


def test_recent_usage_is_reported_newest_first(session) -> None:
    for offset in range(3):
        quota.reserve(session, "av", limit=10, now=NOON + timedelta(days=offset))
    days = [row.day for row in quota.recent(session, "av")]
    assert days == sorted(days, reverse=True)


# --- deferral --------------------------------------------------------------


def enqueued(session) -> JobQueueEntry:
    result = queue.enqueue(session, "fundamentals.refresh", {"asset_id": "x"})
    return session.get(JobQueueEntry, result.job_id)


def test_a_deferral_does_not_spend_a_retry(session) -> None:
    """The whole reason `defer` exists rather than reusing `fail`.

    Three deferrals through the failure path would dead-letter a job that had
    never been attempted against a provider that was up.
    """
    entry = enqueued(session)
    for _ in range(5):
        queue.defer(session, entry, quota.next_reset(NOON), "allowance spent")

    assert entry.retry_count == 0
    assert entry.status == JobStatus.PENDING


def test_a_deferred_job_comes_back_when_the_budget_does(session) -> None:
    entry = enqueued(session)
    queue.defer(session, entry, quota.next_reset(NOON), "allowance spent")
    assert entry.available_at == datetime(2026, 8, 5, tzinfo=UTC)


def test_a_deferral_releases_the_lock(session) -> None:
    """A deferred job left locked would only return via the reclaim timeout,
    fifteen minutes later, for no reason."""
    entry = enqueued(session)
    entry.locked_by = "worker-1"
    entry.locked_at = NOON
    entry.started_at = NOON

    queue.defer(session, entry, quota.next_reset(NOON), "allowance spent")

    assert entry.locked_by is None
    assert entry.locked_at is None
    assert entry.started_at is None


def test_the_reason_is_recorded_where_an_operator_looks(session) -> None:
    entry = enqueued(session)
    queue.defer(session, entry, quota.next_reset(NOON), "alphavantage allowance spent (25/25)")
    assert "alphavantage allowance spent" in (entry.last_error or "")
    assert entry.last_error.startswith("deferred:")


def test_failing_still_spends_a_retry(session) -> None:
    """The contrast that makes the distinction meaningful."""
    entry = enqueued(session)
    queue.fail(session, entry, "provider down")
    assert entry.retry_count == 1


# --- durability ------------------------------------------------------------


def test_a_durable_reservation_survives_the_callers_rollback(session_factory) -> None:
    """The point of committing on a separate session.

    A reservation on the job's own session is rolled back when the job fails -
    and the HTTP request it authorised cannot be rolled back with it. The
    allowance would be spent at the provider and unspent in our records, which
    is how a caller ends up refused.
    """
    assert quota.reserve_durably(session_factory, "av", limit=5, now=NOON) is True

    # A different session, standing in for the job's transaction failing.
    other = session_factory()
    other.rollback()
    assert quota.state(other, "av", limit=5, now=NOON).used == 1
    other.close()


def test_durable_reservations_still_respect_the_limit(session_factory) -> None:
    granted = [quota.reserve_durably(session_factory, "av", limit=2, now=NOON) for _ in range(4)]
    assert granted == [True, True, False, False]


# --- the handler's contract ------------------------------------------------


def test_the_handler_defers_rather_than_fails_when_the_budget_is_gone(
    session, session_factory, monkeypatch
) -> None:
    """End to end: an exhausted allowance must reach the queue as a deferral."""
    from aidss.db.models import Asset
    from aidss.jobs import handlers

    asset = Asset(ticker="BBCA", exchange="IDX")
    session.add(asset)
    session.flush()
    session.commit()

    class Provider:
        name = "alphavantage"

        def fundamentals_source_name(self) -> str:
            return "alphavantage"

        def get_fundamentals(self, ticker: str):  # pragma: no cover - must not run
            raise AssertionError("the provider was called with no allowance left")

    monkeypatch.setattr(handlers, "get_market_data_provider", lambda: Provider())
    monkeypatch.setattr(handlers, "get_sessionmaker", lambda: session_factory)

    # Spend the whole allowance first.
    for _ in range(handlers.get_settings().fundamentals_daily_quota):
        quota.reserve_durably(session_factory, "alphavantage", limit=10_000)

    with pytest.raises(handlers.JobDeferred) as exc:
        handlers.refresh_fundamentals(session, {"asset_id": str(asset.id)})

    assert "allowance spent" in exc.value.reason
    assert exc.value.until == quota.next_reset()


# --- spreading the work across days ----------------------------------------


def make_assets(session, *tickers: str):
    from aidss.db.models import Asset

    assets = [Asset(ticker=t, exchange="IDX") for t in tickers]
    session.add_all(assets)
    session.flush()
    return assets


def age_fundamentals(session, asset, *, days_ago: int) -> None:
    from aidss.db.models import FundamentalMetric

    session.add(
        FundamentalMetric(
            asset_id=asset.id,
            period=(NOON - timedelta(days=days_ago)).date(),
            period_type="ttm",
            metric_name="pe_ratio",
            value=None,
            source="alphavantage",
            ingested_at=NOON - timedelta(days=days_ago),
        )
    )
    session.flush()


def test_an_asset_with_no_fundamentals_at_all_goes_first(session) -> None:
    """"We know nothing about this company" is a worse gap than "our figures
    are five weeks old", and a large watchlist would otherwise keep topping up
    what it already covers and never reach what it does not."""
    from aidss.jobs.handlers import assets_needing_fundamentals

    covered, uncovered = make_assets(session, "AAAA", "ZZZZ")
    age_fundamentals(session, covered, days_ago=200)

    ordered = assets_needing_fundamentals(session, now=NOON)
    assert [a.ticker for a in ordered] == ["ZZZZ", "AAAA"]


def test_stalest_first_among_assets_that_have_some(session) -> None:
    from aidss.jobs.handlers import assets_needing_fundamentals

    fresh, stale = make_assets(session, "FRSH", "STAL")
    age_fundamentals(session, fresh, days_ago=40)
    age_fundamentals(session, stale, days_ago=400)

    assert [a.ticker for a in assets_needing_fundamentals(session, now=NOON)] == ["STAL", "FRSH"]


def test_recently_refreshed_assets_are_left_alone(session) -> None:
    """Reported financials change quarterly. Refetching weekly spends an
    allowance to rewrite identical numbers."""
    from aidss.jobs.handlers import assets_needing_fundamentals

    (asset,) = make_assets(session, "BBCA")
    age_fundamentals(session, asset, days_ago=2)

    assert assets_needing_fundamentals(session, now=NOON) == []


def test_a_partial_payload_is_judged_on_its_freshest_metric(session) -> None:
    """Otherwise one old row would keep an otherwise-current asset permanently
    at the front of the queue."""
    from aidss.jobs.handlers import assets_needing_fundamentals

    (asset,) = make_assets(session, "BBCA")
    age_fundamentals(session, asset, days_ago=400)
    age_fundamentals(session, asset, days_ago=1)

    assert assets_needing_fundamentals(session, now=NOON) == []


def test_enqueueing_stops_at_what_the_days_allowance_can_pay_for(session, monkeypatch) -> None:
    from aidss.jobs import handlers

    make_assets(session, "AAAA", "BBBB", "CCCC", "DDDD", "EEEE")
    settings = handlers.get_settings()
    monkeypatch.setattr(settings, "fundamentals_daily_quota", 2)
    monkeypatch.setattr(settings, "fundamentals_max_enqueued_per_tick", 10)

    summary = handlers.enqueue_due_fundamentals(session, now=NOON)
    assert summary["enqueued"] == 2


def test_the_per_tick_cap_applies_even_with_budget_to_spare(session, monkeypatch) -> None:
    """A first run against a large watchlist should not fill the queue with
    jobs that spend the next fortnight being deferred."""
    from aidss.jobs import handlers

    make_assets(session, "AAAA", "BBBB", "CCCC", "DDDD", "EEEE")
    settings = handlers.get_settings()
    monkeypatch.setattr(settings, "fundamentals_daily_quota", 25)
    monkeypatch.setattr(settings, "fundamentals_max_enqueued_per_tick", 3)

    assert handlers.enqueue_due_fundamentals(session, now=NOON)["enqueued"] == 3


def test_nothing_is_enqueued_once_the_allowance_is_gone(session, monkeypatch) -> None:
    from aidss.jobs import handlers

    make_assets(session, "AAAA", "BBBB")
    settings = handlers.get_settings()
    monkeypatch.setattr(settings, "fundamentals_daily_quota", 2)
    for _ in range(2):
        quota.reserve(session, "fixture", limit=2, now=NOON)

    assert handlers.enqueue_due_fundamentals(session, now=NOON)["enqueued"] == 0


def test_ticking_twice_in_a_day_enqueues_once_per_asset(session, monkeypatch) -> None:
    from aidss.jobs import handlers

    make_assets(session, "AAAA", "BBBB")
    monkeypatch.setattr(handlers.get_settings(), "fundamentals_daily_quota", 25)

    first = handlers.enqueue_due_fundamentals(session, now=NOON)
    second = handlers.enqueue_due_fundamentals(session, now=NOON + timedelta(hours=1))

    assert first["enqueued"] == 2
    assert second["enqueued"] == 0
    assert second["already_queued"] == 2


def test_a_still_stale_asset_is_queued_again_tomorrow(session, monkeypatch) -> None:
    """The dedup key is per day, so yesterday's job does not block today's."""
    from aidss.jobs import handlers

    make_assets(session, "AAAA")
    monkeypatch.setattr(handlers.get_settings(), "fundamentals_daily_quota", 25)

    handlers.enqueue_due_fundamentals(session, now=NOON)
    tomorrow = handlers.enqueue_due_fundamentals(session, now=NOON + timedelta(days=1))
    assert tomorrow["enqueued"] == 1


def test_enqueueing_does_not_spend_the_allowance(session, monkeypatch) -> None:
    """The reservation belongs next to the call, not next to the plan to make
    one - a job that never runs would otherwise leak its slot for good."""
    from aidss.jobs import handlers

    make_assets(session, "AAAA", "BBBB")
    monkeypatch.setattr(handlers.get_settings(), "fundamentals_daily_quota", 25)

    handlers.enqueue_due_fundamentals(session, now=NOON)
    assert quota.state(session, "fixture", limit=25, now=NOON).used == 0


# --- the worker's side -----------------------------------------------------


def test_the_worker_records_a_deferral_apart_from_a_failure(session_factory) -> None:
    """A worker deferring steadily is healthy and rate-limited; a worker
    failing steadily is broken. One counter covering both hides which."""
    from aidss.jobs import handlers
    from aidss.jobs.worker import Worker

    @handlers.register("test.deferring")
    def _handler(session, payload):  # pragma: no cover - registered for one test
        raise handlers.JobDeferred(datetime(2026, 8, 5, tzinfo=UTC), "allowance spent")

    session = session_factory()
    queue.enqueue(session, "test.deferring", {})
    session.commit()
    session.close()

    worker = Worker(session_factory=session_factory)
    assert worker.run_once() is True
    assert worker.stats.deferred == 1
    assert worker.stats.failed == 0

    check = session_factory()
    entry = check.query(JobQueueEntry).one()
    assert entry.status == JobStatus.PENDING
    assert entry.retry_count == 0
    assert entry.available_at == datetime(2026, 8, 5, tzinfo=UTC)
    check.close()

    handlers._HANDLERS.pop("test.deferring", None)
