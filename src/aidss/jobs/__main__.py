"""Worker entrypoint: ``python -m aidss.jobs``.

Runs the worker, the scheduler, or both. Both-in-one-process is the sensible
default for a small deployment; splitting them lets workers scale horizontally
while exactly one scheduler decides what enters the queue.

    python -m aidss.jobs              # worker and scheduler together
    python -m aidss.jobs --worker     # workers only (scale this one)
    python -m aidss.jobs --scheduler  # exactly one of these
"""

from __future__ import annotations

import argparse
import logging
import threading

from aidss.config import get_settings
from aidss.jobs.worker import (
    SCHEDULER_INTERVAL_SECONDS,
    Scheduler,
    Worker,
    install_signal_handlers,
)
from aidss.observability.logging import configure_logging

logger = logging.getLogger("aidss.jobs")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AIDSS background worker")
    parser.add_argument("--worker", action="store_true", help="run the job worker")
    parser.add_argument("--scheduler", action="store_true", help="run the schedule enqueuer")
    parser.add_argument(
        "--scheduler-interval",
        type=float,
        default=SCHEDULER_INTERVAL_SECONDS,
        help="seconds between scheduler passes",
    )
    args = parser.parse_args(argv)

    # Neither flag means both, which is what a single-process deployment wants.
    run_worker = args.worker or not args.scheduler
    run_scheduler = args.scheduler or not args.worker

    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.json_logs)

    # Importing the handler module is what registers the job types; without it
    # the worker would claim jobs and dead-letter every one as unknown.
    import aidss.jobs.handlers  # noqa: F401
    import aidss.plugins  # noqa: F401  (registers provider adapters)

    logger.info(
        "starting background processes",
        extra={"worker": run_worker, "scheduler": run_scheduler},
    )

    worker = Worker() if run_worker else None
    scheduler = Scheduler() if run_scheduler else None
    install_signal_handlers(worker, scheduler)

    if scheduler is not None:
        logger.info(
            "scheduler will run only while it holds the leader lease; "
            "extra instances idle safely"
        )
        if worker is None:
            scheduler.run_forever(interval=args.scheduler_interval)
            return 0
        # Daemon thread: the worker's shutdown decides when the process ends,
        # and a scheduler mid-sleep should not delay that. Its `finally` still
        # releases the lease because `stop()` breaks the loop first.
        thread = threading.Thread(
            target=scheduler.run_forever,
            kwargs={"interval": args.scheduler_interval},
            daemon=True,
            name="aidss-scheduler",
        )
        thread.start()

    if worker is not None:
        worker.run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())
