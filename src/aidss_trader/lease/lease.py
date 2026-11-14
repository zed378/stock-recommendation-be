"""Exactly one active Trader (ADR-027).

Same self-healing pattern the analysis platform uses for its scheduler: a row
with an expiry, taken by one conditional UPDATE. A database advisory lock was
rejected because it ties correctness to a connection's lifetime and is not
portable to the SQLite path the hermetic tests use.

The renewal and the takeover are the same statement, so a holder that stops
renewing simply loses the row once it expires; nobody has to notice it died.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aidss_trader.db.models import Lease

LEASE_NAME = "trader"


@dataclass(frozen=True, slots=True)
class LeaseHolder:
    holder: str
    ttl_s: int
    name: str = LEASE_NAME

    def acquire(self, session: Session, *, now: datetime | None = None) -> bool:
        """Take or renew the lease. True means this instance may trade."""
        now = now or datetime.now(UTC)
        expires = now + timedelta(seconds=self.ttl_s)

        if session.get(Lease, self.name) is None:
            try:
                with session.begin_nested():
                    session.add(
                        Lease(
                            name=self.name,
                            holder=self.holder,
                            expires_at=expires,
                            heartbeat_at=now,
                        )
                    )
                return True
            except IntegrityError:
                pass  # another instance created it first; fall through to the conditional UPDATE

        result = session.execute(
            update(Lease)
            .where(
                Lease.name == self.name,
                (Lease.holder == self.holder) | (Lease.expires_at < now),
            )
            .values(holder=self.holder, expires_at=expires, heartbeat_at=now)
        )
        session.flush()
        return result.rowcount == 1

    def release(self, session: Session) -> bool:
        result = session.execute(
            delete(Lease).where(Lease.name == self.name, Lease.holder == self.holder)
        )
        session.flush()
        return result.rowcount == 1

    def current(self, session: Session) -> Lease | None:
        return session.scalar(select(Lease).where(Lease.name == self.name))
