"""The Trader's service loop: lease, heartbeat, and (when assembled) the trading runtime.

Without a `Runtime` it only proves the safety scaffolding: the master key is
readable, the lease is held by exactly one instance, and a heartbeat is written for
the health check. With one, each iteration that holds the lease also runs a
`Runtime` cycle (docs/02-ARCHITECTURE). The runtime starts HALTED on a fresh
install, so assembling it does not by itself allow anything to trade.

`evaluate` reports why the service is not ready; it never reports permission to trade.
That belongs to the kill-switch state and the Risk Engine.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from aidss_trader.config import TraderSettings, unset_risk_fields
from aidss_trader.credentials import MasterKeyUnavailable, load_master_key
from aidss_trader.lease import LeaseHolder
from aidss_trader.logsafe import safe_log
from aidss_trader.runtime.loop import Runtime

logger = logging.getLogger("aidss_trader")


class TradingState(StrEnum):
    RUNNING = "RUNNING"
    HALTED = "HALTED"
    DISABLED = "DISABLED"


@dataclass(slots=True)
class Status:
    state: TradingState = TradingState.DISABLED
    reasons: list[str] = field(default_factory=list)
    holds_lease: bool = False


def evaluate(settings: TraderSettings, session: Session, holder: LeaseHolder) -> Status:
    """One cycle: check preconditions and renew the lease. Never raises for a failed check."""
    status = Status()

    try:
        load_master_key(settings.master_key_file)
    except MasterKeyUnavailable as exc:
        status.reasons.append(f"master key unavailable: {exc}")

    status.holds_lease = holder.acquire(session)
    if not status.holds_lease:
        status.reasons.append("another Trader instance holds the lease")

    # No limits are stored yet in T1, so this always lists every required field.
    # The point is that the answer is "disabled", never a permissive default.
    unset = unset_risk_fields(None)
    status.reasons.append(f"{len(unset)} required risk limits are unset")
    return status


def write_heartbeat(path: Path, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    path.write_text(now.isoformat())


def heartbeat_age_s(path: Path, now: datetime | None = None) -> float | None:
    try:
        written = datetime.fromisoformat(path.read_text().strip())
    except (OSError, ValueError):
        return None
    return ((now or datetime.now(UTC)) - written).total_seconds()


def run(
    settings: TraderSettings,
    factory: sessionmaker[Session],
    *,
    sleep: Callable[[float], None] = time.sleep,
    stop: Callable[[], bool] = lambda: False,
    runtime: Runtime | None = None,
) -> None:
    holder = LeaseHolder(holder=settings.instance_name, ttl_s=settings.lease_ttl_s)
    while not stop():
        with factory() as session:
            status = evaluate(settings, session, holder)
            session.commit()
        if runtime is not None and status.holds_lease:
            # Only the lease holder trades (ADR-027). A cycle error never ends the loop: the
            # heartbeat below must keep telling the truth about whether the process is alive.
            try:
                runtime.run_if_due()
            except Exception:
                safe_log(logger, logging.ERROR, "runtime cycle failed", exc_info=True)
        write_heartbeat(settings.heartbeat_file)
        safe_log(
            logger,
            logging.INFO,
            "cycle",
            extra={
                "state": status.state.value,
                "lease": status.holds_lease,
                "reasons": status.reasons,
            },
        )
        sleep(settings.lease_heartbeat_s)
