"""Position and PnL by weighted average cost (ADR-022). Pure: no database.

Costs on a buy raise the cost basis; costs on a sell reduce proceeds; both stay
visible as separate amounts. The position is long-only: a sell larger than what
is held is an integrity error and halts, never a short.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal(0)


class LedgerIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Position:
    quantity: Decimal = ZERO
    avg_cost: Decimal = ZERO


def apply_fill(
    position: Position, side: str, quantity: Decimal, price: Decimal, costs: Decimal
) -> tuple[Position, Decimal]:
    """Return the new position and the realised PnL (zero for a buy), net of costs."""
    if quantity <= 0 or price <= 0 or costs < 0:
        raise LedgerIntegrityError(
            "a fill needs positive quantity and price and non-negative costs"
        )
    if side == "BUY":
        new_qty = position.quantity + quantity
        cost_basis = position.quantity * position.avg_cost + quantity * price + costs
        return Position(new_qty, cost_basis / new_qty), ZERO
    if side == "SELL":
        if quantity > position.quantity:
            raise LedgerIntegrityError("a sell larger than the position")
        realised = (price - position.avg_cost) * quantity - costs
        remaining = position.quantity - quantity
        return Position(remaining, position.avg_cost if remaining else ZERO), realised
    raise LedgerIntegrityError(f"unknown side {side!r}")


def replay(
    fills: Iterable[tuple[str, Decimal, Decimal, Decimal]],
) -> tuple[Position, Decimal]:
    """Replay (side, quantity, price, costs) in order: the position and total realised PnL."""
    position, total = Position(), ZERO
    for side, qty, price, costs in fills:
        position, realised = apply_fill(position, side, qty, price, costs)
        total += realised
    return position, total


def unrealised(position: Position, last_price: Decimal) -> Decimal:
    return (last_price - position.avg_cost) * position.quantity
