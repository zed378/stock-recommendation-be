"""The job queue (Sections 2.6, 4 - Job Queue).

Backed by the database rather than a broker. At this scale that is the better
trade in both directions: a job is enqueued in the same transaction as the rows
it concerns, so there is no window where the data was written and the job was
not; and there is no second system to deploy, monitor, and lose messages in.

Claiming uses ``SELECT ... FOR UPDATE SKIP LOCKED`` on PostgreSQL, which lets
several workers pull from one queue without any of them blocking on a row
another already holds. SQLite has no such clause, so the fallback claims
optimistically and re-checks - correct for the single-worker case tests run in,
and honest about which is which rather than pretending one implementation
covers both.
"""

from __future__ import annotations

import os
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aidss.db.models import JobQueueEntry, JobStatus

#: Base of the exponential retry backoff.
RETRY_BASE_SECONDS = 30

#: Ceiling on the backoff. Beyond roughly an hour, a job that keeps failing
#: needs a human rather than another attempt.
RETRY_MAX_SECONDS = 3600

#: A RUNNING job whose lock is older than this is treated as abandoned. Set
#: well above the slowest expected job: reclaiming one that is merely slow
#: would run it twice.
LOCK_TIMEOUT_SECONDS = 900


def worker_identity() -> str:
    """Host and process, so a stuck job names the worker that had it."""
    return f"{socket.gethostname()}:{os.getpid()}"


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    job_id: uuid.UUID
    created: bool

    @property
    def deduplicated(self) -> bool:
        return not self.created


def enqueue(
    session: Session,
    job_type: str,
    payload: dict[str, Any] | None = None,
    *,
    dedup_key: str | None = None,
    available_at: datetime | None = None,
    max_retries: int = 3,
    scheduler_job_id: uuid.UUID | None = None,
) -> EnqueueResult:
    """Add a job, or return the existing one when ``dedup_key`` matches.

    Deduplication is checked *and* enforced by a unique index. The check alone
    would race between two schedulers; the index alone would raise where the
    caller wants a quiet no-op.
    """
    if dedup_key:
        existing = session.scalar(
            select(JobQueueEntry).where(JobQueueEntry.dedup_key == dedup_key)
        )
        if existing is not None:
            return EnqueueResult(job_id=existing.id, created=False)

    entry = JobQueueEntry(
        job_type=job_type,
        payload=payload or {},
        dedup_key=dedup_key,
        available_at=available_at or datetime.now(UTC),
        max_retries=max_retries,
        scheduler_job_id=scheduler_job_id,
    )
    session.add(entry)
    try:
        session.flush()
    except IntegrityError:
        # Another worker inserted the same key between the check and the flush.
        session.rollback()
        existing = session.scalar(
            select(JobQueueEntry).where(JobQueueEntry.dedup_key == dedup_key)
        )
        if existing is None:
            raise
        return EnqueueResult(job_id=existing.id, created=False)

    return EnqueueResult(job_id=entry.id, created=True)


def claim(
    session: Session, *, worker: str | None = None, now: datetime | None = None
) -> JobQueueEntry | None:
    """Take the next due job, or return None.

    The whole claim happens in one statement where the dialect allows it, so
    two workers cannot both believe they hold the same row.
    """
    now = now or datetime.now(UTC)
    worker = worker or worker_identity()

    stmt = (
        select(JobQueueEntry)
        .where(
            JobQueueEntry.status == JobStatus.PENDING,
            JobQueueEntry.available_at <= now,
        )
        .order_by(JobQueueEntry.available_at)
        .limit(1)
    )

    if session.bind is not None and session.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)

    entry = session.scalar(stmt)
    if entry is None:
        return None

    # Guarded by status as well as id: on a dialect without SKIP LOCKED, this
    # is what stops a second worker that read the same row from also taking it.
    claimed = session.execute(
        update(JobQueueEntry)
        .where(JobQueueEntry.id == entry.id, JobQueueEntry.status == JobStatus.PENDING)
        .values(
            status=JobStatus.RUNNING,
            locked_at=now,
            locked_by=worker,
            started_at=now,
        )
    )
    if claimed.rowcount == 0:
        return None

    session.flush()
    session.refresh(entry)
    return entry


def complete(session: Session, entry: JobQueueEntry, result: dict[str, Any] | None = None) -> None:
    entry.status = JobStatus.SUCCEEDED
    entry.result = result or {}
    entry.finished_at = datetime.now(UTC)
    entry.locked_at = None
    entry.locked_by = None
    entry.last_error = None
    session.flush()


def retry_delay(attempt: int) -> int:
    """Exponential backoff, capped."""
    return min(RETRY_BASE_SECONDS * (2 ** max(0, attempt - 1)), RETRY_MAX_SECONDS)


def fail(session: Session, entry: JobQueueEntry, error: str, *, retryable: bool = True) -> None:
    """Record a failure, scheduling a retry or dead-lettering.

    A non-retryable failure goes straight to dead. Retrying a malformed payload
    three times just produces the same error three times and delays the alert.
    """
    entry.retry_count += 1
    entry.last_error = error[:4000]
    entry.locked_at = None
    entry.locked_by = None

    if not retryable or entry.retry_count > entry.max_retries:
        entry.status = JobStatus.DEAD
        entry.finished_at = datetime.now(UTC)
    else:
        entry.status = JobStatus.PENDING
        entry.available_at = datetime.now(UTC) + timedelta(seconds=retry_delay(entry.retry_count))

    session.flush()


def defer(session: Session, entry: JobQueueEntry, until: datetime, reason: str) -> None:
    """Put a job back without charging it a retry.

    "The daily provider allowance is spent, come back after midnight" is not a
    failure and must not be counted as one. Routing it through ``fail`` would
    burn the retry budget on waiting - three deferrals and a perfectly healthy
    job is dead-lettered, having never once been attempted against a provider
    that was up.

    The reason is recorded in ``last_error`` because that is where an operator
    looks, but ``retry_count`` is left alone: the job has not been tried yet.
    """
    entry.status = JobStatus.PENDING
    entry.available_at = until
    entry.locked_at = None
    entry.locked_by = None
    entry.started_at = None
    entry.last_error = f"deferred: {reason}"[:4000]
    session.flush()


def reclaim_abandoned(
    session: Session, *, now: datetime | None = None, timeout: int = LOCK_TIMEOUT_SECONDS
) -> int:
    """Return jobs whose worker died to the pending pool.

    Without this a worker killed mid-job leaves the row RUNNING forever, and
    the work silently never happens - the worst failure mode a queue has,
    because nothing reports an error.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(seconds=timeout)

    result = session.execute(
        update(JobQueueEntry)
        .where(JobQueueEntry.status == JobStatus.RUNNING, JobQueueEntry.locked_at < cutoff)
        .values(
            status=JobStatus.PENDING,
            locked_at=None,
            locked_by=None,
            available_at=now,
            last_error="reclaimed after the worker holding it stopped responding",
        )
    )
    session.flush()
    return int(result.rowcount or 0)


def stats(session: Session) -> dict[str, int]:
    """Queue depth by status, for the operations overview."""
    counts = {status.value: 0 for status in JobStatus}
    for entry in session.scalars(select(JobQueueEntry)).all():
        counts[entry.status.value] += 1
    return counts
