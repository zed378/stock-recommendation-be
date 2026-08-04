"""Group F - Notification, Audit, Config, Scheduler (Section 8.2)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from aidss.db.base import Base, enum_column, new_uuid, utcnow


class ActorType(StrEnum):
    USER = "user"
    AI = "ai"
    SYSTEM = "system"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    #: Exhausted its retries. Kept rather than deleted: a job that failed
    #: permanently is the one most worth being able to inspect.
    DEAD = "dead"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(40))
    subject: Mapped[str | None] = mapped_column(String(200), default=None)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditLog(Base):
    """Append-only (Section 13). The absence of an updated_at column is deliberate."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    actor_type: Mapped[ActorType] = mapped_column(enum_column(ActorType, length=10))
    actor_id: Mapped[str | None] = mapped_column(String(80), default=None)
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(80), default=None)
    before: Mapped[dict[str, Any] | None] = mapped_column(default=None)
    after: Mapped[dict[str, Any] | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (Index("ix_audit_entity_created", "entity", "created_at"),)


class SystemConfiguration(Base):
    __tablename__ = "system_configuration"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    scope: Mapped[str] = mapped_column(String(60), default="global")
    key: Mapped[str] = mapped_column(String(120))
    value: Mapped[dict[str, Any]] = mapped_column(default=dict)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("scope", "key", name="uq_config_scope_key"),)


class SchedulerJob(Base):
    __tablename__ = "scheduler_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    job_type: Mapped[str] = mapped_column(String(80))
    cron_expr: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    next_run_at: Mapped[datetime | None] = mapped_column(default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class JobQueueEntry(Base):
    """One unit of background work.

    The queue lives in the database rather than in a broker. For this scale
    that is the better trade: a job is enqueued in the same transaction as the
    rows it concerns, so there is no window where the data was written and the
    job was not, and no second system to operate. `FOR UPDATE SKIP LOCKED`
    makes multi-worker claiming safe on PostgreSQL.
    """

    __tablename__ = "job_queue"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    scheduler_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scheduler_jobs.id", ondelete="SET NULL"), default=None
    )
    job_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[JobStatus] = mapped_column(
        enum_column(JobStatus), default=JobStatus.PENDING, index=True
    )
    retry_count: Mapped[int] = mapped_column(default=0)
    max_retries: Mapped[int] = mapped_column(default=3)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    #: What the handler returned, for a caller polling the job.
    result: Mapped[dict[str, Any] | None] = mapped_column(default=None)

    #: Not claimable before this. Carries the retry backoff, and lets a job be
    #: scheduled for later without a separate mechanism.
    available_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    #: Set while a worker holds the job. A row that is RUNNING with a stale
    #: `locked_at` is a worker that died, and can be reclaimed.
    locked_at: Mapped[datetime | None] = mapped_column(default=None)
    locked_by: Mapped[str | None] = mapped_column(String(80), default=None)

    #: Idempotency key. A unique index means enqueueing the same logical work
    #: twice is a no-op rather than two runs.
    dedup_key: Mapped[str | None] = mapped_column(String(200), default=None, unique=True)

    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (Index("ix_job_claimable", "status", "available_at"),)


class LeaderLease(Base):
    """A time-bounded claim on a role only one process may hold.

    The scheduler is the case that needs it: two of them would each enqueue for
    the same due schedule, and only the dedup key would stop the duplicates -
    which works, but leaves "run exactly one scheduler" as a deployment
    instruction rather than something the system enforces.

    A lease rather than an advisory lock, because a lease is portable across
    dialects and survives its holder dying: the expiry releases it without
    anyone having to notice.
    """

    __tablename__ = "leader_leases"

    #: The role being claimed, e.g. "scheduler". Primary key, so the table can
    #: hold at most one row per role by construction.
    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    holder: Mapped[str] = mapped_column(String(120))
    acquired_at: Mapped[datetime] = mapped_column(default=utcnow)
    #: Renewed on every tick. Set to a few multiples of the tick interval, so a
    #: brief pause does not hand leadership to another process needlessly.
    expires_at: Mapped[datetime] = mapped_column(index=True)


class ProviderQuotaUsage(Base):
    """Calls spent against one provider's daily allowance, one row per UTC day.

    Alpha Vantage's free tier allows 25 requests a day. Tracking that in memory
    would reset on every deploy and count separately in every worker, so the
    first restart after lunch would spend the allowance twice and the provider
    would start refusing - which reads, downstream, as an outage.

    A row per day rather than a running counter that gets reset: resetting is a
    write someone has to perform on time, and nobody does it at midnight. The
    day is part of the key instead, so a new day simply has no row yet.

    Old rows are left in place. They are a few dozen bytes each and they answer
    "were we throttled last Tuesday?", which is exactly the question asked when
    a week-old figure turns out to be missing.
    """

    __tablename__ = "provider_quota_usage"

    #: The adapter name, e.g. "alphavantage" - the concrete source, never a
    #: composite wrapper, because the allowance belongs to the account behind it.
    provider: Mapped[str] = mapped_column(String(80), primary_key=True)
    usage_date: Mapped[date] = mapped_column(primary_key=True)
    used: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ProviderIngestionRun(Base):
    """A record of every Market Data Collector run (Phase 2).

    Exists for observability and diagnosis: how many bars arrived, how many
    validation rejected, and from which provider.
    """

    __tablename__ = "provider_ingestion_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    provider_name: Mapped[str] = mapped_column(String(80))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), default=None
    )
    timeframe: Mapped[str | None] = mapped_column(String(8), default=None)
    range_start: Mapped[datetime | None] = mapped_column(default=None)
    range_end: Mapped[datetime | None] = mapped_column(default=None)
    fetched_count: Mapped[int] = mapped_column(default=0)
    inserted_count: Mapped[int] = mapped_column(default=0)
    updated_count: Mapped[int] = mapped_column(default=0)
    rejected_count: Mapped[int] = mapped_column(default=0)
    status: Mapped[JobStatus] = mapped_column(
        enum_column(JobStatus), default=JobStatus.SUCCEEDED
    )
    error: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
