"""Job status endpoints (Sections 2.6, 4).

A client that queued work needs to find out what happened to it. Without this
the queue is a place work goes to disappear.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.api.deps import CommitBeforeResponse, get_db, require_permission
from aidss.api.pagination import paginate
from aidss.api.schemas import JobResponse, Page, QueueStatsResponse
from aidss.db.models import JobQueueEntry, JobStatus, User
from aidss.jobs.handlers import registered_types
from aidss.jobs.leader import current_leader
from aidss.jobs.queue import stats
from aidss.security.rbac import Permission

router = APIRouter(tags=["jobs"], route_class=CommitBeforeResponse)


def _to_response(entry: JobQueueEntry) -> JobResponse:
    return JobResponse(
        id=entry.id,
        job_type=entry.job_type,
        status=entry.status,
        retry_count=entry.retry_count,
        max_retries=entry.max_retries,
        last_error=entry.last_error,
        result=entry.result,
        available_at=entry.available_at,
        started_at=entry.started_at,
        finished_at=entry.finished_at,
        created_at=entry.created_at,
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: uuid.UUID,
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> JobResponse:
    """The state of one job.

    A `dead` status carries `last_error`, so a client that queued work and
    never saw a result can find out why rather than waiting indefinitely.
    """
    entry = session.get(JobQueueEntry, job_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _to_response(entry)


@router.get("/jobs", response_model=Page[JobResponse])
def list_jobs(
    job_status: JobStatus | None = Query(default=None, alias="status"),
    job_type: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> Page[JobResponse]:
    stmt = select(JobQueueEntry)
    if job_status is not None:
        stmt = stmt.where(JobQueueEntry.status == job_status)
    if job_type:
        stmt = stmt.where(JobQueueEntry.job_type == job_type)
    rows, total = paginate(session, stmt, JobQueueEntry.created_at.desc(), limit, offset)
    return Page(
        items=[_to_response(entry) for entry in rows], total=total, limit=limit, offset=offset
    )


@router.get("/admin/queue", response_model=QueueStatsResponse)
def queue_stats(
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> QueueStatsResponse:
    """Queue depth by status, plus what this worker build knows how to run.

    The registered-types list matters operationally: a job whose type no worker
    recognises dead-letters, and the usual cause is a worker running older code
    than whatever enqueued it.
    """
    counts = stats(session)
    leader = current_leader(session)
    return QueueStatsResponse(
        by_status=counts,
        registered_job_types=registered_types(),
        # Absent or expired means nothing is scheduling work - the failure that
        # looks exactly like "no schedules are due" unless it is surfaced.
        scheduler_leader=leader,
        note=(
            "A job type that no worker recognises will dead-letter. If `dead` is "
            "rising, check that the workers are running the same build as the API. "
            "If `scheduler_leader` is absent or expired, no process is enqueueing "
            "scheduled work."
        ),
    )
