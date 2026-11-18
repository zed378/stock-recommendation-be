"""The backtest figure the promotion gate reads (ADR-059).

A promotion gate that accepts a number the owner types is not a gate: the figure could be edited
until it passes. So the gate reads stored BACKTEST runs and nothing else.

What is read: for the strategy version in force, the **latest run of each pair**, and of those only
the runs that started from the same equity as the newest one (so the sum is of like quantities).
The figure is the plain sum of those runs' total returns, in percent of that start equity. It is
stated for what it is: each pair was run on its own, with the full start equity and without the
portfolio's open-position and exposure limits, so it approximates trading all of them side by side
and ignores the limits that would have restrained that. It is a coarse, short-sample figure, and
the gate shows how many pairs and trades stand behind it.

A different strategy version (changed parameters) has no evidence until it is backtested again.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss_trader.db.models import BacktestRunRow

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class BacktestEvidence:
    return_pct: Decimal
    pairs: int
    trades: int

    def describe(self) -> str:
        return f"{self.return_pct:.3f} (sum over {self.pairs} pairs, {self.trades} trades)"


def backtest_evidence(
    session: Session, strategy_id: str, strategy_version: str
) -> BacktestEvidence | None:
    rows = session.scalars(
        select(BacktestRunRow)
        .where(
            BacktestRunRow.strategy_id == strategy_id,
            BacktestRunRow.strategy_version == strategy_version,
            BacktestRunRow.origin == "BACKTEST",
        )
        .order_by(BacktestRunRow.ran_at.desc())
    ).all()
    if not rows:
        return None
    start = rows[0].start_equity_idr
    latest: dict[str, BacktestRunRow] = {}
    for row in rows:
        if row.start_equity_idr == start and row.pair not in latest:
            latest[row.pair] = row
    total = sum((Decimal(str(r.total_return_pct)) for r in latest.values()), ZERO)
    return BacktestEvidence(
        return_pct=total,
        pairs=len(latest),
        trades=sum(r.trades for r in latest.values()),
    )
