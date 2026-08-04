"""Leader election by database lease.

Turns "run exactly one scheduler" from a deployment instruction into something
the system enforces. Every scheduler instance tries to hold the lease; only the
holder ticks, and the others idle until the holder stops renewing.

A lease rather than a PostgreSQL advisory lock, for two reasons. It is portable
- the same code runs on SQLite in tests, so the mechanism under test is the one
that runs in production. And it self-heals: an advisory lock is bound to a
session, and a pooled connection makes that identity slippery, whereas an
expiry releases the lease without anyone having to notice the holder died.

The trade is that leadership is only guaranteed within the expiry window, not
instantaneously. That is fine here: the worst case is one duplicate tick during
a handover, and the enqueue dedup key absorbs it. Belt and braces, deliberately
- the lease is the design, the dedup key is the safety net.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aidss.db.models import LeaderLease

#: How long a lease is valid without renewal. Several tick intervals, so a slow
#: tick or a brief GC pause does not hand leadership away needlessly.
DEFAULT_LEASE_SECONDS = 180

SCHEDULER_ROLE = "scheduler"


def identity() -> str:
    """Host and process, so the operations view names the actual leader."""
    return f"{socket.gethostname()}:{os.getpid()}"


@dataclass
class LeaseHolder:
    """Acquires and renews one lease."""

    name: str = SCHEDULER_ROLE
    holder: str | None = None
    ttl_seconds: int = DEFAULT_LEASE_SECONDS

    def __post_init__(self) -> None:
        self.holder = self.holder or identity()

    def acquire(self, session: Session, *, now: datetime | None = None) -> bool:
        """Take or renew the lease. Returns whether this process now holds it.

        One conditional UPDATE does the work: it succeeds when the lease is
        already ours (a renewal) or has expired (a takeover), and matches
        nothing when someone else holds it live. Reading first and then writing
        would leave a window where two processes both saw it free.
        """
        now = now or datetime.now(UTC)
        expires = now + timedelta(seconds=self.ttl_seconds)

        taken = session.execute(
            update(LeaderLease)
            .where(
                LeaderLease.name == self.name,
                (LeaderLease.holder == self.holder) | (LeaderLease.expires_at <= now),
            )
            .values(holder=self.holder, acquired_at=now, expires_at=expires)
        )
        if taken.rowcount:
            session.flush()
            return True

        # No row updated: either nobody has ever claimed this role, or someone
        # else holds it live. Distinguish by trying to insert.
        existing = session.scalar(select(LeaderLease).where(LeaderLease.name == self.name))
        if existing is not None:
            return False

        session.add(
            LeaderLease(
                name=self.name, holder=self.holder, acquired_at=now, expires_at=expires
            )
        )
        try:
            session.flush()
        except IntegrityError:
            # Another instance inserted between the check and the flush. It
            # won; this one waits for the expiry.
            session.rollback()
            return False
        return True

    def release(self, session: Session) -> bool:
        """Give up the lease so a peer can take over immediately.

        Called on clean shutdown. Without it a restart would idle for the whole
        expiry window before anything scheduled ran again - correct, but a
        needless gap.
        """
        removed = session.execute(
            delete(LeaderLease).where(
                LeaderLease.name == self.name, LeaderLease.holder == self.holder
            )
        )
        session.flush()
        return bool(removed.rowcount)


def current_leader(session: Session, name: str = SCHEDULER_ROLE) -> dict[str, str] | None:
    """Who holds the lease, for the operations overview.

    An expired lease reports as `expired` rather than as a holder: a stale name
    would read as "the scheduler is running" when nothing is.
    """
    lease = session.scalar(select(LeaderLease).where(LeaderLease.name == name))
    if lease is None:
        return None
    return {
        "holder": lease.holder,
        "acquired_at": lease.acquired_at.isoformat(),
        "expires_at": lease.expires_at.isoformat(),
        "state": "held" if lease.expires_at > datetime.now(UTC) else "expired",
    }
