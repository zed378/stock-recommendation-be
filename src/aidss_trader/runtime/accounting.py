"""Positions, realised loss, and drawdown, derived from stored LIVE fills and snapshots.

Everything here is computed from the exchange's own trades as the Trader stored them
(ADR-022), never from what the Trader intended. PAPER and BACKTEST rows are excluded
by origin, so a simulated trade can never move a live limit.

Day boundary: the owner decided local midnight WIB (ADR-034); WIB is UTC+7 with no
daylight saving, so a fixed offset is exact.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss_trader.db.models import EquitySnapshot, Fill
from aidss_trader.ledger.position import Position, apply_fill

WIB = timedelta(hours=7)
ZERO = Decimal(0)


def _aware(v: datetime) -> datetime:
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class Realised:
    at: datetime
    pair: str
    pnl: Decimal


def replay_live(session: Session) -> tuple[dict[str, Position], list[Realised]]:
    """Replay every LIVE fill in time order. Raises LedgerIntegrityError on an impossible sell."""
    fills = list(
        session.scalars(
            select(Fill).where(Fill.origin == "LIVE").order_by(Fill.executed_at, Fill.id)
        )
    )
    positions: dict[str, Position] = {}
    events: list[Realised] = []
    for f in fills:
        current = positions.get(f.pair, Position())
        updated, realised = apply_fill(current, f.side, f.quantity, f.price, f.commission)
        positions[f.pair] = updated
        if f.side == "SELL":
            events.append(Realised(_aware(f.executed_at), f.pair, realised))
    return {p: pos for p, pos in positions.items() if pos.quantity > 0}, events


def wib_day_start(now: datetime) -> datetime:
    local = _aware(now) + WIB
    return local.replace(hour=0, minute=0, second=0, microsecond=0) - WIB


def daily_loss(events: list[Realised], now: datetime) -> Decimal:
    """Net loss since local midnight as a positive number; a profitable day is zero."""
    start = wib_day_start(now)
    total = sum((e.pnl for e in events if e.at >= start), ZERO)
    return -total if total < 0 else ZERO


def consecutive_losses(events: list[Realised]) -> int:
    count = 0
    for e in reversed(events):
        if e.pnl < 0:
            count += 1
        else:
            break
    return count


def record_equity(session: Session, equity: Decimal, now: datetime) -> None:
    session.add(EquitySnapshot(at=now, equity_idr=equity))
    session.flush()


def drawdown_pct(session: Session, equity: Decimal) -> Decimal:
    """Percent below the highest stored equity. The current value counts toward the peak."""
    peak = max((e for (e,) in session.execute(select(EquitySnapshot.equity_idr))), default=equity)
    peak = max(peak, equity)
    return ZERO if peak <= 0 else (peak - equity) / peak * 100
