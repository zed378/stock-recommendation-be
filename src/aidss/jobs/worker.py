"""The worker loop and the scheduler tick (Sections 2.6, 4, 6.3.2).

Two responsibilities, kept apart on purpose:

  * the **worker** claims jobs and runs them;
  * the **scheduler** notices due schedules and enqueues jobs for them.

Separating them means a slow job cannot delay the scheduler, and several
workers can share one queue while exactly one scheduler decides what goes into
it. They can run in the same process for convenience, or as separate services.

Each job runs in its own session and transaction. A handler that fails rolls
back only its own work - the alternative, one long-lived session, means one bad
job poisons every job that followed it.
"""

from __future__ import annotations

import logging
import signal
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from aidss.db.base import get_sessionmaker
from aidss.db.models import JobQueueEntry
from aidss.jobs import queue
from aidss.jobs.handlers import (
    JobDeferred,
    PermanentJobError,
    due_news_schedules,
    enqueue_due_fundamentals,
    enqueue_due_news_sweep,
    enqueue_monitoring_pass,
    get_handler,
)
from aidss.jobs.leader import LeaseHolder
from aidss.news.schedules import next_run_at
from aidss.observability.logging import bind_request, clear_request, new_request_id
from aidss.observability.metrics import MetricsRegistry, registry
from aidss.plugins.errors import ProviderUnavailableError

logger = logging.getLogger("aidss.worker")

#: How long to wait when the queue is empty. Short enough that a newly enqueued
#: job starts promptly, long enough that an idle worker is not a busy loop.
IDLE_SLEEP_SECONDS = 2.0

#: How often the scheduler looks for due schedules. Section 6.3.3 suggests
#: about a minute, and the minimum schedule interval is five.
SCHEDULER_INTERVAL_SECONDS = 60.0


@dataclass
class WorkerStats:
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    dead: int = 0
    #: Counted apart from failures on purpose. A worker deferring steadily is
    #: healthy and rate-limited; a worker failing steadily is broken, and one
    #: number covering both would hide which.
    deferred: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "processed": self.processed,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "dead": self.dead,
            "deferred": self.deferred,
        }


@dataclass
class Worker:
    """Claims and runs jobs."""

    session_factory: sessionmaker | None = None
    metrics: MetricsRegistry | None = None
    stats: WorkerStats = field(default_factory=WorkerStats)
    _stopping: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self._sessions = self.session_factory or get_sessionmaker()
        self._metrics = self.metrics or registry()

    def stop(self) -> None:
        """Ask the loop to finish the current job and exit."""
        self._stopping = True

    def run_once(self) -> bool:
        """Claim and run at most one job. Returns whether one was found.

        The claim commits before the handler runs. If the process dies
        mid-handler the row is left RUNNING and `reclaim_abandoned` returns it
        later; if the claim were part of the handler's transaction, a crash
        would roll the claim back too and two workers could take the same job.
        """
        session = self._sessions()
        try:
            entry = queue.claim(session)
            if entry is None:
                session.commit()
                return False

            job_id = entry.id
            job_type = entry.job_type
            payload = dict(entry.payload or {})
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        self._execute(job_id, job_type, payload)
        return True

    def _execute(self, job_id: uuid.UUID, job_type: str, payload: dict[str, Any]) -> None:
        # Correlated like a request, so a job's log lines can be pulled back
        # together the same way.
        bind_request(new_request_id())
        duration = self._metrics.histogram(
            "aidss_job_duration_seconds", "Background job duration in seconds"
        )
        started = time.perf_counter()

        try:
            outcome = self._run_handler(job_id, job_type, payload)
        finally:
            self.stats.processed += 1
            duration.observe(time.perf_counter() - started, type=job_type)
            clear_request()

        self._metrics.counter(
            "aidss_jobs_total", "Background jobs processed, by type and outcome"
        ).inc(type=job_type, outcome=outcome)

    def _run_handler(self, job_id: uuid.UUID, job_type: str, payload: dict[str, Any]) -> str:
        session = self._sessions()
        try:
            entry = session.get(JobQueueEntry, job_id)
            if entry is None:
                return "missing"

            try:
                result = get_handler(job_type)(session, payload)
            except JobDeferred as exc:
                # Not a failure: the job has not been attempted yet, so it must
                # not be charged a retry for waiting.
                queue.defer(session, entry, exc.until, exc.reason)
                session.commit()
                self.stats.deferred += 1
                logger.info(
                    "job deferred",
                    extra={
                        "job_type": job_type,
                        "job_id": str(job_id),
                        "until": exc.until.isoformat(),
                        "reason": exc.reason,
                    },
                )
                return "deferred"
            except PermanentJobError as exc:
                queue.fail(session, entry, str(exc), retryable=False)
                session.commit()
                self.stats.dead += 1
                logger.error(
                    "job dead-lettered", extra={"job_type": job_type, "job_id": str(job_id)}
                )
                return "dead"
            except ProviderUnavailableError as exc:
                queue.fail(session, entry, str(exc), retryable=exc.retryable)
                session.commit()
                self.stats.failed += 1
                logger.warning("job failed", extra={"job_type": job_type, "job_id": str(job_id)})
                return "failed"
            except Exception as exc:  # noqa: BLE001 - the queue records every failure
                self._record_unexpected_failure(session, job_id, exc)
                self.stats.failed += 1
                logger.exception("job raised", extra={"job_type": job_type, "job_id": str(job_id)})
                return "failed"

            queue.complete(session, entry, result)
            session.commit()
            self.stats.succeeded += 1
            logger.info("job completed", extra={"job_type": job_type, "job_id": str(job_id)})
            return "succeeded"
        finally:
            session.close()

    def _record_unexpected_failure(
        self, session: Session, job_id: uuid.UUID, exc: Exception
    ) -> None:
        """Record the failure on a fresh session.

        A handler that raised mid-flush leaves its session unusable, and the
        failure still has to be written - otherwise the row stays RUNNING and
        only the reclaim timeout eventually notices.
        """
        session.rollback()
        recovery = self._sessions()
        try:
            entry = recovery.get(JobQueueEntry, job_id)
            if entry is not None:
                queue.fail(recovery, entry, f"{type(exc).__name__}: {exc}")
                recovery.commit()
        except Exception:
            recovery.rollback()
            logger.exception("could not record job failure", extra={"job_id": str(job_id)})
        finally:
            recovery.close()

    def run_forever(self, *, idle_sleep: float = IDLE_SLEEP_SECONDS) -> None:
        logger.info("worker started", extra={"worker": queue.worker_identity()})
        while not self._stopping:
            try:
                if not self.run_once():
                    time.sleep(idle_sleep)
            except Exception:
                # The loop must outlive any single failure; a worker that exits
                # on an unexpected error stops all background work silently.
                logger.exception("worker loop error")
                time.sleep(idle_sleep)
        logger.info("worker stopped", extra=self.stats.as_dict())


@dataclass
class Scheduler:
    """Enqueues jobs for schedules that have come due (Section 6.3.2).

    Several instances may run; only the one holding the leader lease ticks. The
    rest idle and take over automatically if the leader stops renewing, which
    makes "exactly one scheduler" a property of the system rather than an
    instruction in a runbook.
    """

    session_factory: sessionmaker | None = None
    lease: LeaseHolder | None = None
    #: Off only for tests that exercise tick() directly without the election.
    require_leadership: bool = True
    _stopping: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self._sessions = self.session_factory or get_sessionmaker()
        self._lease = self.lease or LeaseHolder()
        self._was_leader = False

    @property
    def is_leader(self) -> bool:
        return self._was_leader

    def tick(self, *, now: datetime | None = None) -> dict[str, Any]:
        """One pass: take the lease, reclaim abandoned jobs, enqueue what is due."""
        now = now or datetime.now(UTC)
        session = self._sessions()
        try:
            if self.require_leadership and not self._lease.acquire(session, now=now):
                session.commit()
                if self._was_leader:
                    # Losing the lease means this process paused long enough for
                    # a peer to take over. Worth a log line: it usually points at
                    # something worse than a scheduler hiccup.
                    logger.warning("lost scheduler leadership")
                    self._was_leader = False
                return {"leader": False, "reclaimed": 0, "enqueued": 0, "already_queued": 0}

            if self.require_leadership and not self._was_leader:
                logger.info("acquired scheduler leadership")
                self._was_leader = True

            reclaimed = queue.reclaim_abandoned(session, now=now)

            enqueued = 0
            skipped = 0
            for schedule in due_news_schedules(session, now=now):
                # The dedup key pins the job to this schedule and this due
                # time, so a scheduler that ticks twice - or two schedulers
                # running at once - enqueue one job, not two.
                due_stamp = schedule.next_run_at or now
                result = queue.enqueue(
                    session,
                    "news.ingest_schedule",
                    {"schedule_id": str(schedule.id)},
                    dedup_key=f"news:{schedule.id}:{due_stamp.isoformat()}",
                )
                if result.created:
                    enqueued += 1
                    # Advanced here, not in the handler: otherwise a job
                    # sitting in the queue would be re-enqueued on every tick
                    # until it ran.
                    schedule.next_run_at = next_run_at(schedule.cron_expression, after=now)
                else:
                    skipped += 1

            # Fundamentals are paced by the provider's daily allowance rather
            # than by a cron expression, so they are queued here instead of
            # carrying a schedule row each.
            fundamentals = enqueue_due_fundamentals(session, now=now)

            # Monitoring is paced by a fixed interval, and the dedup key is the
            # interval bucket - so a scheduler ticking every minute still
            # queues one pass per interval rather than one per tick.
            monitoring = enqueue_monitoring_pass(session, now=now)

            # The sweep over every configured feed, on whatever cron the
            # operator set from the admin screen. Off unless they set one.
            news_sweep = enqueue_due_news_sweep(session, now=now)

            session.commit()
            return {
                "leader": True,
                "reclaimed": reclaimed,
                # `enqueued` keeps meaning what it always did - news schedules.
                # Folding fundamentals into it made one number answer two
                # questions, and every existing caller was already reading it
                # as the answer to the first.
                "enqueued": enqueued,
                "already_queued": skipped,
                "fundamentals": fundamentals,
                "news_sweep": news_sweep,
                "monitoring": monitoring,
                "total_enqueued": (
                    enqueued + fundamentals["enqueued"] + monitoring["enqueued"]
                ),
            }
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def stop(self) -> None:
        """Ask the loop to exit and hand the lease back."""
        self._stopping = True

    def release(self) -> None:
        """Give up leadership so a peer can take over at once.

        Without this a restart idles for the whole expiry window before
        anything scheduled runs again - correct, but a needless gap.
        """
        if not self._was_leader:
            return
        session = self._sessions()
        try:
            self._lease.release(session)
            session.commit()
            self._was_leader = False
            logger.info("released scheduler leadership")
        except Exception:
            session.rollback()
            logger.exception("could not release the scheduler lease")
        finally:
            session.close()

    def run_forever(self, *, interval: float = SCHEDULER_INTERVAL_SECONDS) -> None:
        logger.info("scheduler started", extra={"holder": self._lease.holder})
        try:
            while not self._stopping:
                try:
                    summary = self.tick()
                    if summary.get("total_enqueued"):
                        logger.info("scheduler enqueued work", extra=summary)
                except Exception:
                    # The loop must outlive any single failure, or all scheduled
                    # work stops silently.
                    logger.exception("scheduler tick failed")
                time.sleep(interval)
        finally:
            self.release()


def install_signal_handlers(worker: Worker | None, scheduler: Scheduler | None = None) -> None:
    """Finish the current job on SIGTERM rather than dropping it.

    The scheduler is stopped too so it hands the lease back, letting a peer
    take over immediately instead of after the expiry.
    """

    def handle(signum: int, _frame: object) -> None:
        logger.info("shutdown signal received", extra={"signal": signum})
        if worker is not None:
            worker.stop()
        if scheduler is not None:
            scheduler.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handle)
        except (ValueError, OSError):
            # Not the main thread, or a platform without the signal - not fatal.
            pass
