"""Risk limits in the database: immutable versions, every save audited.

Loading never invents a value: a column that is NULL comes back as `None`, which
means "unset", which disables trading for the strategy (FR-T11).
"""

from __future__ import annotations

from dataclasses import asdict, fields
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aidss_trader.audit import AuditLogger
from aidss_trader.config.limits import RiskLimits
from aidss_trader.db.models import RiskLimitVersion

_NAMES = [f.name for f in fields(RiskLimits)]


def load_risk_limits(session: Session) -> RiskLimits | None:
    """The latest version, or None if the owner has never saved any."""
    row = session.scalar(
        select(RiskLimitVersion).order_by(RiskLimitVersion.version.desc()).limit(1)
    )
    if row is None:
        return None
    return RiskLimits(**{name: getattr(row, name) for name in _NAMES})


def save_risk_limits(
    session: Session, limits: RiskLimits, *, set_by: str, now: datetime | None = None
) -> int:
    """Write a new version (never an update) and audit the change. Returns the version."""
    now = now or datetime.now(UTC)
    before = load_risk_limits(session)
    version = (session.scalar(select(func.max(RiskLimitVersion.version))) or 0) + 1
    session.add(
        RiskLimitVersion(version=version, effective_from=now, set_by=set_by, **asdict(limits))
    )
    session.flush()
    AuditLogger(session).record(
        actor=set_by,
        action="limit.change",
        subject_type="risk_limit",
        subject_id=str(version),
        before=_plain(before),
        after=_plain(limits),
        at=now,
    )
    return version


def _plain(limits: RiskLimits | None) -> dict[str, str | None] | None:
    if limits is None:
        return None

    # Decimals come back from the database padded to the column scale; normalise so
    # the same value reads the same in "before" and "after".
    def text(v: object) -> str | None:
        if v is None:
            return None
        return format(v.normalize(), "f") if isinstance(v, Decimal) else str(v)

    return {k: text(v) for k, v in asdict(limits).items()}
