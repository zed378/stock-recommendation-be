"""Backtests started from the screen, run in the background and polled for the answer.

A backtest over a dozen pairs takes seconds to a minute, longer than a request should hold a
connection through the tunnel, so the route starts a job and the screen polls it. Jobs live in this
process only: they are a convenience for the person watching, not a record. What is kept is the
`backtest_run` rows a job writes when it finishes a pair, so a restart loses a running job's
progress but never a stored result.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session, sessionmaker

from aidss_trader.backtest.runner import (
    BacktestInputsMissing,
    StrategyResult,
    load_inputs,
    run_strategy,
)
from aidss_trader.strategy.base import Strategy

MAX_JOBS_KEPT = 20
KEEP_SECONDS = 3600


@dataclass(slots=True)
class Job:
    id: str
    strategy_ids: list[str]
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    state: str = "RUNNING"  # RUNNING | DONE | FAILED
    error: str | None = None
    current: str | None = None
    done_strategies: int = 0
    results: list[StrategyResult] = field(default_factory=list)


class BacktestJobs:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def active(self) -> Job | None:
        with self._lock:
            return next((j for j in self._jobs.values() if j.state == "RUNNING"), None)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def start(
        self,
        strategies: list[tuple[str, Callable[[], Strategy]]],
        *,
        by: str,
        sync: bool = False,
    ) -> Job:
        """One job at a time: a second backtest started while one runs is refused by the caller
        (`active`), because they would compete for the same database and the same few seconds."""
        job = Job(uuid.uuid4().hex, [sid for sid, _ in strategies])
        with self._lock:
            self._prune()
            self._jobs[job.id] = job
        if sync:
            self._run(job, strategies, by)
        else:
            threading.Thread(
                target=self._run,
                args=(job, strategies, by),
                daemon=True,
                name=f"backtest-{job.id[:6]}",
            ).start()
        return job

    def _prune(self) -> None:
        now = time.time()
        old = [
            j.id
            for j in self._jobs.values()
            if j.finished_at is not None and now - j.finished_at > KEEP_SECONDS
        ]
        for jid in old:
            del self._jobs[jid]
        while len(self._jobs) > MAX_JOBS_KEPT:
            oldest = min(self._jobs.values(), key=lambda j: j.started_at)
            del self._jobs[oldest.id]

    def _run(self, job: Job, strategies: list[tuple[str, Callable[[], Strategy]]], by: str) -> None:
        try:
            with self._factory() as session:
                inputs = load_inputs(session)
                for sid, build in strategies:
                    job.current = sid
                    result = run_strategy(
                        session,
                        build(),
                        inputs,
                        strategy_id=sid,
                        record=True,
                        by=by,
                        progress=lambda pair, sid=sid: setattr(job, "current", f"{sid} {pair}"),
                    )
                    job.results.append(result)
                    job.done_strategies += 1
            job.state = "DONE"
        except BacktestInputsMissing as exc:
            job.state, job.error = "FAILED", str(exc)
        except Exception as exc:  # noqa: BLE001 - the screen needs a reason, not a stack trace
            job.state, job.error = "FAILED", f"{type(exc).__name__}: backtest could not finish"
        finally:
            job.current = None
            job.finished_at = time.time()


def summarise(result: StrategyResult) -> dict[str, object]:
    return {
        "strategy_id": result.strategy_id,
        "version": result.version,
        "return_pct": format(result.return_pct.quantize(Decimal("0.001")), "f"),
        "pairs": len(result.pairs),
        "trades": result.trades,
        "skipped": result.skipped,
    }
