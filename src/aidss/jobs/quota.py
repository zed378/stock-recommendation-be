"""Daily provider allowances, enforced before the call rather than after it.

Alpha Vantage's free tier allows 25 requests a day. Discovering that by being
refused is the expensive way: the refusal arrives as an ordinary provider
failure, the job retries with backoff, burns more of tomorrow's allowance on
the retries, and the logs read like an outage rather than a budget.

So the budget is checked first. A caller **reserves** a slot, does the work if
it got one, and is told to come back after the reset if it did not.

Two properties this has to have, both learned from the queue:

  * **Atomic under concurrency.** Two workers must not both see the last slot.
    The reservation is a single conditional ``UPDATE ... WHERE used < limit``,
    so the database decides the winner - the same shape as the leader lease,
    and for the same reason.
  * **Durable across restarts.** An in-process counter resets on deploy and
    counts separately in each worker, so a Tuesday afternoon restart spends the
    allowance twice.

The day boundary is UTC, matching the rest of the system's timestamps. Alpha
Vantage's own reset is US market time, so the two do not line up exactly; the
practical effect is that the allowance is treated as slightly more
conservative than it is, which is the right direction to be wrong in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from aidss.db.models import ProviderQuotaUsage

#: A limit of zero or less means "no ceiling configured", not "spend nothing".
#: Distinguishing them matters: most providers have no daily cap, and a
#: misread default that blocked every call would look exactly like an outage.
UNLIMITED = 0


@dataclass(frozen=True, slots=True)
class QuotaState:
    provider: str
    day: date
    used: int
    limit: int

    @property
    def unlimited(self) -> bool:
        return self.limit <= UNLIMITED

    @property
    def remaining(self) -> int:
        """How many calls are left today. Unlimited reports as -1, not as a
        large number that a caller might loop over."""
        return -1 if self.unlimited else max(0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        return not self.unlimited and self.used >= self.limit

    def as_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "day": self.day.isoformat(),
            "used": self.used,
            "limit": None if self.unlimited else self.limit,
            "remaining": None if self.unlimited else self.remaining,
        }


def _today(now: datetime | None) -> date:
    return (now or datetime.now(UTC)).astimezone(UTC).date()


def next_reset(now: datetime | None = None) -> datetime:
    """The next UTC midnight - when a deferred job should be retried.

    Returned rather than assumed by the caller so that "when does the budget
    come back?" has exactly one answer in the codebase.
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    return datetime.combine(moment.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)


def state(
    session: Session, provider: str, *, limit: int, now: datetime | None = None
) -> QuotaState:
    """What has been spent today. Reads only; reserves nothing."""
    day = _today(now)
    row = session.get(ProviderQuotaUsage, (provider, day))
    return QuotaState(provider=provider, day=day, used=row.used if row else 0, limit=limit)


def reserve(
    session: Session,
    provider: str,
    *,
    limit: int,
    count: int = 1,
    now: datetime | None = None,
) -> bool:
    """Claim ``count`` calls against today's allowance.

    Returns False when the allowance would be exceeded, having changed nothing.
    The caller must not make the call in that case - the point is to not spend
    what is not there.

    The increment and the check are one statement. Reading the counter and then
    writing it back would let two workers both pass the check on the last slot,
    which is precisely the case a daily cap exists to prevent.
    """
    if limit <= UNLIMITED:
        # No ceiling configured. Still recorded, because "how many calls did we
        # make yesterday?" is worth answering before a limit bites.
        _record(session, provider, count, now=now)
        return True
    if count <= 0:
        return True

    day = _today(now)
    taken = session.execute(
        update(ProviderQuotaUsage)
        .where(
            ProviderQuotaUsage.provider == provider,
            ProviderQuotaUsage.usage_date == day,
            ProviderQuotaUsage.used <= limit - count,
        )
        .values(used=ProviderQuotaUsage.used + count, updated_at=datetime.now(UTC))
    )
    if taken.rowcount:
        session.flush()
        return True

    # No row was updated. Either today has no row yet, or the allowance is
    # spent - and those need different answers, so ask.
    existing = session.get(ProviderQuotaUsage, (provider, day))
    if existing is not None:
        return False
    if count > limit:
        # A single request larger than the whole day's allowance would never
        # succeed. Refusing now beats inserting a row that can never be filled.
        return False

    return _insert_first_use(session, provider, day, count, limit)


def _insert_first_use(
    session: Session, provider: str, day: date, count: int, limit: int
) -> bool:
    """Create today's row, losing gracefully to whoever creates it first."""
    session.add(ProviderQuotaUsage(provider=provider, usage_date=day, used=count))
    try:
        session.flush()
    except IntegrityError:
        # Another worker inserted today's row between the update and this
        # insert. Roll back and retry through the conditional update, which is
        # now the correct path because the row exists.
        session.rollback()
        retried = session.execute(
            update(ProviderQuotaUsage)
            .where(
                ProviderQuotaUsage.provider == provider,
                ProviderQuotaUsage.usage_date == day,
                ProviderQuotaUsage.used <= limit - count,
            )
            .values(used=ProviderQuotaUsage.used + count, updated_at=datetime.now(UTC))
        )
        if not retried.rowcount:
            return False
        session.flush()
    return True


def _record(session: Session, provider: str, count: int, *, now: datetime | None) -> None:
    """Increment without enforcing - used when no limit is configured."""
    day = _today(now)
    updated = session.execute(
        update(ProviderQuotaUsage)
        .where(
            ProviderQuotaUsage.provider == provider,
            ProviderQuotaUsage.usage_date == day,
        )
        .values(used=ProviderQuotaUsage.used + count, updated_at=datetime.now(UTC))
    )
    if updated.rowcount:
        session.flush()
        return

    session.add(ProviderQuotaUsage(provider=provider, usage_date=day, used=count))
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        session.execute(
            update(ProviderQuotaUsage)
            .where(
                ProviderQuotaUsage.provider == provider,
                ProviderQuotaUsage.usage_date == day,
            )
            .values(used=ProviderQuotaUsage.used + count, updated_at=datetime.now(UTC))
        )
        session.flush()


def reserve_durably(
    session_factory: sessionmaker,
    provider: str,
    *,
    limit: int,
    count: int = 1,
    now: datetime | None = None,
) -> bool:
    """Reserve on a session of its own, and commit it before returning.

    This is the form callers should use before an outbound call, and the second
    session is the whole point rather than an oversight. A reservation taken on
    the job's session is rolled back when the job fails - and the HTTP request
    it authorised cannot be rolled back with it. The allowance would then be
    spent at the provider and unspent in our records, which is the one
    direction of error that ends in being refused.

    So the two are deliberately decoupled: the spend is recorded whatever
    happens to the work it was for.

    The corollary is that a call which failed before reaching the provider -
    a connection reset, say - still costs a slot. That is the safe direction:
    over-counting collects a little less than it could, while under-counting
    ends in the provider refusing requests, which reads downstream as an
    outage rather than as a budget.
    """
    session = session_factory()
    try:
        granted = reserve(session, provider, limit=limit, count=count, now=now)
        session.commit()
        return granted
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def recent(session: Session, provider: str, *, days: int = 7) -> list[QuotaState]:
    """Recent daily usage, newest first - for the operations overview."""
    rows = session.scalars(
        select(ProviderQuotaUsage)
        .where(ProviderQuotaUsage.provider == provider)
        .order_by(ProviderQuotaUsage.usage_date.desc())
        .limit(days)
    ).all()
    return [
        QuotaState(provider=row.provider, day=row.usage_date, used=row.used, limit=UNLIMITED)
        for row in rows
    ]
