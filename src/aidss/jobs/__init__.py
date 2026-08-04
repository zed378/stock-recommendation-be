"""Background job queue, handlers, worker, and scheduler (Sections 2.6, 4)."""

from aidss.jobs.handlers import (
    Handler,
    PermanentJobError,
    due_news_schedules,
    get_handler,
    register,
    registered_types,
)
from aidss.jobs.leader import (
    DEFAULT_LEASE_SECONDS,
    SCHEDULER_ROLE,
    LeaseHolder,
    current_leader,
)
from aidss.jobs.queue import (
    LOCK_TIMEOUT_SECONDS,
    EnqueueResult,
    claim,
    complete,
    enqueue,
    fail,
    reclaim_abandoned,
    retry_delay,
    stats,
    worker_identity,
)
from aidss.jobs.worker import Scheduler, Worker, WorkerStats, install_signal_handlers

__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "LOCK_TIMEOUT_SECONDS",
    "SCHEDULER_ROLE",
    "EnqueueResult",
    "Handler",
    "LeaseHolder",
    "PermanentJobError",
    "Scheduler",
    "Worker",
    "WorkerStats",
    "claim",
    "complete",
    "current_leader",
    "due_news_schedules",
    "enqueue",
    "fail",
    "get_handler",
    "install_signal_handlers",
    "reclaim_abandoned",
    "register",
    "registered_types",
    "retry_delay",
    "stats",
    "worker_identity",
]
