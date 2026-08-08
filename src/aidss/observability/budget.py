"""Daily AI spend governance (Phase 9, Section 16.9).

Section 28 lists AI cost growing with scale as a real operational risk. The
mitigation has two halves and both matter:

  * a **warning** at a configurable fraction of the ceiling, so someone hears
    about it while there is still time to act;
  * a **stop** at the ceiling itself, because a budget that only reports
    overspending is a report.

Spend is read from `ai_messages`, the same rows the audit trail uses. A second
counter would eventually disagree with the first, and then nobody would know
which to believe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aidss.db.models import AIMessage


class BudgetState:
    OK = "ok"
    WARNING = "warning"
    EXCEEDED = "exceeded"


@dataclass(slots=True)
class BudgetStatus:
    spent: Decimal
    ceiling: Decimal | None
    state: str
    #: Fraction of the ceiling used; None when no ceiling is configured.
    utilisation: float | None
    window_start: datetime
    message: str

    @property
    def should_block(self) -> bool:
        return self.state == BudgetState.EXCEEDED

    def as_dict(self) -> dict[str, Any]:
        return {
            "spent": str(self.spent),
            "ceiling": None if self.ceiling is None else str(self.ceiling),
            "state": self.state,
            "utilisation": None if self.utilisation is None else round(self.utilisation, 4),
            "window_start": self.window_start.isoformat(),
            "message": self.message,
        }


def spend_since(session: Session, since: datetime) -> Decimal:
    total = session.scalar(
        select(func.coalesce(func.sum(AIMessage.cost_estimate), 0)).where(
            AIMessage.created_at >= since
        )
    )
    return Decimal(str(total or 0))


def daily_status(
    session: Session,
    *,
    ceiling: float | None,
    warning_threshold: float = 0.8,
    now: datetime | None = None,
) -> BudgetStatus:
    """Where today's spend stands against the configured ceiling.

    The window is the last 24 hours rather than the calendar day, so a run
    started before midnight is not split across two budgets and neither half
    trips a limit the whole would have.
    """
    now = now or datetime.now(UTC)
    window_start = now - timedelta(days=1)
    spent = spend_since(session, window_start)

    if ceiling is None:
        return BudgetStatus(
            spent=spent,
            ceiling=None,
            state=BudgetState.OK,
            utilisation=None,
            window_start=window_start,
            message=(
                f"No daily ceiling is configured. Estimated spend in the last 24 hours: "
                f"{spent}."
            ),
        )

    limit = Decimal(str(ceiling))
    utilisation = float(spent / limit) if limit > 0 else 0.0

    if spent >= limit:
        state = BudgetState.EXCEEDED
        message = (
            f"Estimated spend {spent} has reached the daily ceiling {limit}. "
            "Further AI calls are blocked until the window rolls forward."
        )
    elif utilisation >= warning_threshold:
        state = BudgetState.WARNING
        message = (
            f"Estimated spend {spent} is {utilisation:.0%} of the daily ceiling {limit}."
        )
    else:
        state = BudgetState.OK
        message = f"Estimated spend {spent} of a {limit} daily ceiling ({utilisation:.0%})."

    return BudgetStatus(
        spent=spent,
        ceiling=limit,
        state=state,
        utilisation=utilisation,
        window_start=window_start,
        message=message,
    )
