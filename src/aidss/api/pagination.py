"""One window onto a list, and the count behind it.

Shared rather than written per route, because the interesting part is the same
everywhere and easy to get subtly wrong: the count has to run against the
*filtered* statement, and it has to drop the ordering before counting.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session


def paginate(
    session: Session, stmt: Any, order_by: Any, limit: int, offset: int
) -> tuple[list[Any], int]:
    """The rows for this window, and how many there are in total.

    `total` is counted before the window rather than after, which is the only
    way a reader learns there is more than they can see.

    The ordering is stripped for the count: counting an ordered subquery makes
    PostgreSQL sort rows it is only going to tally, and the answer is identical
    either way.
    """
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = list(session.scalars(stmt.order_by(order_by).limit(limit).offset(offset)).all())
    return rows, int(total or 0)
