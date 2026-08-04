"""Job queue, worker, and scheduler (Sections 2.6, 4, 6.3.2).

The failure paths get most of the attention. A queue's happy path is easy; what
decides whether background work can be trusted is what happens when a handler
raises, a worker dies mid-job, or the same work is enqueued twice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from aidss.db.base import get_sessionmaker
from aidss.db.models import (
    Asset,
    JobQueueEntry,
    JobStatus,
    LeaderLease,
    TickerNewsSchedule,
    User,
)
from aidss.jobs import queue
from aidss.jobs.handlers import PermanentJobError, get_handler, register, registered_types
from aidss.jobs.leader import LeaseHolder, current_leader
from aidss.jobs.worker import Scheduler, Worker
from aidss.plugins.errors import ProviderUnavailableError
from aidss.security.passwords import hash_password

NOW = datetime(2025, 6, 2, 9, 0, tzinfo=UTC)


def enqueue_due(session, job_type: str = "test.noop", payload: dict | None = None, **kwargs):
    """Enqueue a job that is already due at ``NOW``.

    ``enqueue`` defaults ``available_at`` to the wall clock, which sits in the
    future relative to this fixed ``NOW`` - so a test claiming at ``NOW`` would
    find nothing and look like a broken queue rather than a stale fixture.
    """
    kwargs.setdefault("available_at", NOW - timedelta(minutes=5))
    return queue.enqueue(session, job_type, payload, **kwargs)


# --- Enqueue ---------------------------------------------------------------


def test_a_job_is_queued_as_pending(session) -> None:
    result = enqueue_due(session, "test.noop", {"x": 1})
    entry = session.get(JobQueueEntry, result.job_id)

    assert result.created
    assert entry.status is JobStatus.PENDING
    assert entry.payload == {"x": 1}


def test_the_same_dedup_key_returns_the_existing_job(session) -> None:
    """A double-click must not buy the same expensive work twice."""
    first = enqueue_due(session, "test.noop", dedup_key="same")
    second = enqueue_due(session, "test.noop", dedup_key="same")

    assert first.created
    assert second.deduplicated
    assert second.job_id == first.job_id
    assert session.scalar(select(func.count()).select_from(JobQueueEntry)) == 1


def test_jobs_without_a_dedup_key_are_independent(session) -> None:
    enqueue_due(session, "test.noop")
    enqueue_due(session, "test.noop")
    assert session.scalar(select(func.count()).select_from(JobQueueEntry)) == 2


def test_a_job_can_be_scheduled_for_later(session) -> None:
    enqueue_due(session, "test.noop", available_at=NOW + timedelta(hours=1))
    assert queue.claim(session, now=NOW) is None


# --- Claiming --------------------------------------------------------------


def test_claiming_marks_the_job_running(session) -> None:
    enqueue_due(session, "test.noop")
    entry = queue.claim(session, worker="w1", now=NOW)

    assert entry is not None
    assert entry.status is JobStatus.RUNNING
    assert entry.locked_by == "w1"
    assert entry.started_at == NOW


def test_a_claimed_job_is_not_claimed_again(session) -> None:
    enqueue_due(session, "test.noop")
    assert queue.claim(session, now=NOW) is not None
    assert queue.claim(session, now=NOW) is None


def test_the_oldest_due_job_goes_first(session) -> None:
    late = enqueue_due(session, "test.noop", available_at=NOW - timedelta(minutes=1))
    early = enqueue_due(session, "test.noop", available_at=NOW - timedelta(hours=1))

    claimed = queue.claim(session, now=NOW)
    assert claimed.id == early.job_id
    assert claimed.id != late.job_id


def test_an_empty_queue_yields_nothing(session) -> None:
    assert queue.claim(session, now=NOW) is None


# --- Completion, retry, dead-lettering -------------------------------------


def test_completion_stores_the_result(session) -> None:
    enqueue_due(session, "test.noop")
    entry = queue.claim(session, now=NOW)
    queue.complete(session, entry, {"ok": True})

    assert entry.status is JobStatus.SUCCEEDED
    assert entry.result == {"ok": True}
    assert entry.locked_by is None


def test_a_retryable_failure_goes_back_to_pending_with_backoff(session) -> None:
    enqueue_due(session, "test.noop")
    entry = queue.claim(session, now=NOW)
    queue.fail(session, entry, "provider timeout")

    assert entry.status is JobStatus.PENDING
    assert entry.retry_count == 1
    assert entry.available_at > datetime.now(UTC)
    assert "timeout" in entry.last_error


def test_backoff_grows_and_is_capped() -> None:
    delays = [queue.retry_delay(n) for n in (1, 2, 3, 10)]
    assert delays[0] < delays[1] < delays[2]
    assert delays[-1] == queue.RETRY_MAX_SECONDS


def test_exhausting_the_retries_dead_letters(session) -> None:
    enqueue_due(session, "test.noop", max_retries=2)
    for _ in range(3):
        entry = session.scalar(select(JobQueueEntry))
        entry.status = JobStatus.RUNNING
        queue.fail(session, entry, "still failing")

    assert entry.status is JobStatus.DEAD
    assert entry.finished_at is not None


def test_a_non_retryable_failure_dead_letters_immediately(session) -> None:
    """Retrying a malformed payload three times just delays the alert."""
    enqueue_due(session, "test.noop")
    entry = queue.claim(session, now=NOW)
    queue.fail(session, entry, "payload is missing asset_id", retryable=False)

    assert entry.status is JobStatus.DEAD
    assert entry.retry_count == 1


def test_a_dead_job_is_kept_not_deleted(session) -> None:
    """The job that failed permanently is the one most worth inspecting."""
    enqueue_due(session, "test.noop")
    entry = queue.claim(session, now=NOW)
    queue.fail(session, entry, "bad payload", retryable=False)

    assert session.scalar(select(func.count()).select_from(JobQueueEntry)) == 1
    assert session.scalar(select(JobQueueEntry)).last_error


# --- Reclaiming ------------------------------------------------------------


def test_a_job_whose_worker_died_is_reclaimed(session) -> None:
    """Otherwise the work silently never happens - the worst queue failure."""
    enqueue_due(session, "test.noop")
    entry = queue.claim(session, worker="dead-worker", now=NOW)
    entry.locked_at = NOW - timedelta(hours=2)
    session.flush()

    assert queue.reclaim_abandoned(session, now=NOW) == 1
    assert entry.status is JobStatus.PENDING
    assert entry.locked_by is None
    assert "stopped responding" in entry.last_error


def test_a_job_that_is_merely_slow_is_not_reclaimed(session) -> None:
    """Reclaiming a running job would run it twice."""
    enqueue_due(session, "test.noop")
    queue.claim(session, now=NOW)
    assert queue.reclaim_abandoned(session, now=NOW + timedelta(seconds=30)) == 0


# --- Handler registry ------------------------------------------------------


def test_an_unknown_job_type_is_permanent(session) -> None:
    """It will still be unknown next time - usually a stale worker build."""
    with pytest.raises(PermanentJobError, match="no handler registered"):
        get_handler("does.not.exist")


def test_registering_a_duplicate_type_is_refused() -> None:
    with pytest.raises(ValueError, match="already registered"):
        register("analysis.run")(lambda session, payload: {})


def test_the_expected_job_types_are_registered() -> None:
    types = set(registered_types())
    assert {
        "analysis.run",
        "news.ingest_schedule",
        "market_data.backfill",
        "fundamentals.refresh",
    } <= types


# --- Worker ----------------------------------------------------------------


@pytest.fixture
def worker() -> Worker:
    return Worker(session_factory=get_sessionmaker())


def register_probe(name: str, fn):
    """Register a handler for one test, then remove it again."""
    from aidss.jobs import handlers

    handlers._HANDLERS[name] = fn
    return name


def test_the_worker_runs_a_job_and_stores_its_result(session, worker: Worker) -> None:
    register_probe("probe.ok", lambda s, p: {"doubled": p["n"] * 2})
    job = queue.enqueue(session, "probe.ok", {"n": 21})
    session.commit()

    assert worker.run_once() is True

    session.expire_all()
    entry = session.get(JobQueueEntry, job.job_id)
    assert entry.status is JobStatus.SUCCEEDED
    assert entry.result == {"doubled": 42}


def test_an_empty_queue_reports_no_work(worker: Worker) -> None:
    assert worker.run_once() is False


def test_a_raising_handler_is_recorded_not_lost(session, worker: Worker) -> None:
    def boom(s, p):
        raise RuntimeError("something broke")

    register_probe("probe.boom", boom)
    job = queue.enqueue(session, "probe.boom")
    session.commit()

    worker.run_once()

    session.expire_all()
    entry = session.get(JobQueueEntry, job.job_id)
    assert entry.status is JobStatus.PENDING, "a retryable failure goes back to the queue"
    assert "RuntimeError" in entry.last_error
    assert worker.stats.failed == 1


def test_a_handler_that_corrupts_its_session_still_records_the_failure(
    session, worker: Worker
) -> None:
    """A failed flush leaves the session unusable; the failure must still land."""

    def corrupt(s, p):
        s.add(Asset(ticker=None, exchange="IDX"))  # violates NOT NULL
        s.flush()

    register_probe("probe.corrupt", corrupt)
    job = queue.enqueue(session, "probe.corrupt")
    session.commit()

    worker.run_once()

    session.expire_all()
    entry = session.get(JobQueueEntry, job.job_id)
    assert entry.last_error, "the failure was recorded on a fresh session"


def test_a_permanent_error_dead_letters(session, worker: Worker) -> None:
    def permanent(s, p):
        raise PermanentJobError("payload is missing asset_id")

    register_probe("probe.permanent", permanent)
    job = queue.enqueue(session, "probe.permanent")
    session.commit()

    worker.run_once()

    session.expire_all()
    assert session.get(JobQueueEntry, job.job_id).status is JobStatus.DEAD
    assert worker.stats.dead == 1


def test_a_provider_outage_is_retried(session, worker: Worker) -> None:
    def unavailable(s, p):
        raise ProviderUnavailableError("yahoo", "rate limited", retryable=True)

    register_probe("probe.unavailable", unavailable)
    job = queue.enqueue(session, "probe.unavailable")
    session.commit()

    worker.run_once()

    session.expire_all()
    entry = session.get(JobQueueEntry, job.job_id)
    assert entry.status is JobStatus.PENDING
    assert entry.retry_count == 1


def test_one_failing_job_does_not_stop_the_next(session, worker: Worker) -> None:
    """One bad job must not poison the ones behind it."""

    def boom(s, p):
        raise RuntimeError("nope")

    register_probe("probe.boom2", boom)
    register_probe("probe.fine", lambda s, p: {"ok": True})

    queue.enqueue(session, "probe.boom2", available_at=datetime.now(UTC) - timedelta(minutes=5))
    good = queue.enqueue(session, "probe.fine")
    session.commit()

    worker.run_once()
    worker.run_once()

    session.expire_all()
    assert session.get(JobQueueEntry, good.job_id).status is JobStatus.SUCCEEDED


def test_the_worker_records_metrics(session, worker: Worker) -> None:
    from aidss.observability.metrics import registry

    register_probe("probe.metrics", lambda s, p: {})
    queue.enqueue(session, "probe.metrics")
    session.commit()
    worker.run_once()

    rendered = registry().render()
    assert "aidss_jobs_total" in rendered
    assert "aidss_job_duration_seconds" in rendered


# --- Scheduler -------------------------------------------------------------


@pytest.fixture
def due_schedule(session) -> TickerNewsSchedule:
    user = User(email="sched-job@example.com", password_hash=hash_password("correct-horse-b"))
    asset = Asset(ticker="BBCA", exchange="IDX")
    session.add_all([user, asset])
    session.flush()

    row = TickerNewsSchedule(
        user_id=user.id,
        asset_id=asset.id,
        cron_expression="0 7 * * 1-5",
        next_run_at=NOW - timedelta(minutes=1),
    )
    session.add(row)
    session.commit()
    return row


def test_the_scheduler_enqueues_a_due_schedule(session, due_schedule) -> None:
    summary = Scheduler(session_factory=get_sessionmaker()).tick(now=NOW)

    assert summary["enqueued"] == 1
    entry = session.scalar(select(JobQueueEntry))
    assert entry.job_type == "news.ingest_schedule"
    assert entry.payload["schedule_id"] == str(due_schedule.id)


def news_jobs(session) -> int:
    """Count news jobs specifically.

    A bare count of the queue used to say the same thing, back when news was
    the only work the scheduler produced. It now also paces fundamentals, so
    the bare count answers a different question than these tests are asking.
    """
    return session.scalar(
        select(func.count())
        .select_from(JobQueueEntry)
        .where(JobQueueEntry.job_type == "news.ingest_schedule")
    )


def test_ticking_twice_does_not_enqueue_twice(session, due_schedule) -> None:
    """Two schedulers, or one that ticks fast, must not double the work."""
    scheduler = Scheduler(session_factory=get_sessionmaker())
    scheduler.tick(now=NOW)
    second = scheduler.tick(now=NOW)

    assert second["enqueued"] == 0
    assert news_jobs(session) == 1


def test_the_schedule_is_advanced_when_the_job_is_queued(session, due_schedule) -> None:
    """Advanced at enqueue, not in the handler.

    Otherwise a job sitting in the queue would be re-enqueued on every tick
    until it finally ran.
    """
    Scheduler(session_factory=get_sessionmaker()).tick(now=NOW)

    session.expire_all()
    refreshed = session.get(TickerNewsSchedule, due_schedule.id)
    assert refreshed.next_run_at > NOW


def test_a_schedule_that_is_not_due_is_left_alone(session, due_schedule) -> None:
    due_schedule.next_run_at = NOW + timedelta(days=1)
    session.commit()

    assert Scheduler(session_factory=get_sessionmaker()).tick(now=NOW)["enqueued"] == 0


def test_an_inactive_schedule_is_never_enqueued(session, due_schedule) -> None:
    due_schedule.is_active = False
    session.commit()

    assert Scheduler(session_factory=get_sessionmaker()).tick(now=NOW)["enqueued"] == 0


def test_the_scheduler_reclaims_abandoned_jobs(session) -> None:
    enqueue_due(session, "test.noop")
    entry = queue.claim(session, now=NOW)
    entry.locked_at = NOW - timedelta(hours=2)
    session.commit()

    assert Scheduler(session_factory=get_sessionmaker()).tick(now=NOW)["reclaimed"] == 1


# --- Leader election -------------------------------------------------------


def test_the_first_scheduler_takes_the_lease(session) -> None:
    assert LeaseHolder(holder="a").acquire(session, now=NOW) is True

    lease = session.scalar(select(LeaderLease))
    assert lease.holder == "a"
    assert lease.expires_at > NOW


def test_a_second_scheduler_is_refused_while_the_lease_is_live(session) -> None:
    """The point of the whole mechanism: two schedulers, one leader."""
    assert LeaseHolder(holder="a").acquire(session, now=NOW) is True
    assert LeaseHolder(holder="b").acquire(session, now=NOW) is False


def test_the_holder_can_renew_its_own_lease(session) -> None:
    holder = LeaseHolder(holder="a", ttl_seconds=60)
    holder.acquire(session, now=NOW)
    assert holder.acquire(session, now=NOW + timedelta(seconds=30)) is True

    lease = session.scalar(select(LeaderLease))
    assert lease.expires_at == NOW + timedelta(seconds=90)


def test_an_expired_lease_is_taken_over(session) -> None:
    """A leader that dies must not block scheduling until someone notices."""
    LeaseHolder(holder="dead", ttl_seconds=60).acquire(session, now=NOW)

    later = NOW + timedelta(seconds=61)
    assert LeaseHolder(holder="successor").acquire(session, now=later) is True
    assert session.scalar(select(LeaderLease)).holder == "successor"


def test_releasing_hands_over_immediately(session) -> None:
    """Otherwise a restart idles for the whole expiry window."""
    holder = LeaseHolder(holder="a")
    holder.acquire(session, now=NOW)

    assert holder.release(session) is True
    assert LeaseHolder(holder="b").acquire(session, now=NOW) is True


def test_releasing_someone_elses_lease_does_nothing(session) -> None:
    LeaseHolder(holder="a").acquire(session, now=NOW)
    assert LeaseHolder(holder="b").release(session) is False
    assert session.scalar(select(LeaderLease)).holder == "a"


def test_only_the_leader_ticks(session, due_schedule) -> None:
    leader = Scheduler(session_factory=get_sessionmaker(), lease=LeaseHolder(holder="leader"))
    follower = Scheduler(session_factory=get_sessionmaker(), lease=LeaseHolder(holder="follower"))

    first = leader.tick(now=NOW)
    second = follower.tick(now=NOW)

    assert first["leader"] is True
    assert first["enqueued"] == 1
    assert second["leader"] is False
    assert second["enqueued"] == 0
    # And crucially, only one news job exists.
    assert news_jobs(session) == 1


def test_a_follower_takes_over_when_the_leader_stops_renewing(session, due_schedule) -> None:
    leader = Scheduler(
        session_factory=get_sessionmaker(),
        lease=LeaseHolder(holder="leader", ttl_seconds=60),
    )
    follower = Scheduler(session_factory=get_sessionmaker(), lease=LeaseHolder(holder="follower"))

    leader.tick(now=NOW)
    assert follower.tick(now=NOW)["leader"] is False

    # The leader goes away; nothing renews the lease.
    assert follower.tick(now=NOW + timedelta(seconds=61))["leader"] is True


def test_losing_leadership_is_noticed(session, due_schedule) -> None:
    scheduler = Scheduler(
        session_factory=get_sessionmaker(),
        lease=LeaseHolder(holder="a", ttl_seconds=60),
    )
    scheduler.tick(now=NOW)
    assert scheduler.is_leader

    LeaseHolder(holder="usurper").acquire(session, now=NOW + timedelta(seconds=61))
    session.commit()

    scheduler.tick(now=NOW + timedelta(seconds=62))
    assert not scheduler.is_leader


def test_the_current_leader_is_reportable(session) -> None:
    assert current_leader(session) is None

    LeaseHolder(holder="a").acquire(session, now=datetime.now(UTC))
    reported = current_leader(session)
    assert reported["holder"] == "a"
    assert reported["state"] == "held"


def test_an_expired_lease_reports_as_expired_not_as_a_holder(session) -> None:
    """A stale name would read as "the scheduler is running" when nothing is."""
    LeaseHolder(holder="a", ttl_seconds=1).acquire(
        session, now=datetime.now(UTC) - timedelta(minutes=5)
    )
    assert current_leader(session)["state"] == "expired"


# --- Queue statistics ------------------------------------------------------


def test_stats_count_every_status(session) -> None:
    enqueue_due(session, "test.noop")
    claimed = enqueue_due(session, "test.noop")
    entry = session.get(JobQueueEntry, claimed.job_id)
    entry.status = JobStatus.DEAD
    session.flush()

    counts = queue.stats(session)
    assert counts["pending"] == 1
    assert counts["dead"] == 1
    assert set(counts) == {s.value for s in JobStatus}
