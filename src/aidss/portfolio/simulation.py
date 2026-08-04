"""What-if allocation simulation (Phase 6, Section 10 `/portfolio/simulate`).

Answers "what would this portfolio look like if I held X instead of Y" without
touching anything. Nothing here writes a holding, and nothing here could place
an order even if asked - the module takes a list of positions and returns a
comparison.

The distinction matters more than it might sound. A simulation that quietly
mutated the stored portfolio would turn a question into a decision, and the
whole product rests on the user making decisions themselves, outside the
system.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aidss.domain.types import Candle
from aidss.portfolio.metrics import (
    PortfolioMetrics,
    Position,
    compute_portfolio_metrics,
    correlation_matrix,
)
from aidss.portfolio.risk import RiskMetrics, portfolio_risk


class SimulationError(ValueError):
    """The requested change cannot be expressed as a portfolio."""


@dataclass(frozen=True, slots=True)
class AllocationChange:
    """One hypothetical change. Quantity is absolute, not a delta.

    Absolute rather than relative because "hold 150 shares" has one meaning,
    while "add 50" depends on a starting point the caller may have wrong. A
    quantity of zero removes the position.
    """

    ticker: str
    quantity: Decimal

    def __post_init__(self) -> None:
        if self.quantity < 0:
            raise SimulationError(
                f"{self.ticker}: quantity cannot be negative. This platform models "
                "long positions entered by the investor; it has no short or margin "
                "representation."
            )


@dataclass(slots=True)
class SimulationResult:
    before: PortfolioMetrics
    after: PortfolioMetrics
    before_risk: RiskMetrics
    after_risk: RiskMetrics
    changes: list[dict[str, Any]]
    correlation: dict[str, Any]

    def deltas(self) -> dict[str, Any]:
        """What actually moved, so a reader does not have to diff two blobs."""
        return {
            "diversification_score": _delta(
                self.before.diversification_score, self.after.diversification_score
            ),
            "concentration_hhi": _delta(
                self.before.concentration_hhi, self.after.concentration_hhi
            ),
            "sector_concentration_hhi": _delta(
                self.before.sector_concentration_hhi, self.after.sector_concentration_hhi
            ),
            "position_count": self.after.position_count - self.before.position_count,
            "total_value": str(self.after.total_value - self.before.total_value),
            "annualised_volatility": _delta(
                self.before_risk.annualised_volatility, self.after_risk.annualised_volatility
            ),
            "max_drawdown": _delta(
                self.before_risk.max_drawdown, self.after_risk.max_drawdown
            ),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "changes": self.changes,
            "before": {"portfolio": self.before.as_dict(), "risk": self.before_risk.as_dict()},
            "after": {"portfolio": self.after.as_dict(), "risk": self.after_risk.as_dict()},
            "deltas": self.deltas(),
            "correlation_after": self.correlation,
            "note": (
                "A hypothetical comparison only. Nothing was changed, and this "
                "platform cannot place an order."
            ),
        }


def _delta(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return round(after - before, 6)


def apply_changes(
    positions: list[Position], changes: list[AllocationChange]
) -> tuple[list[Position], list[dict[str, Any]]]:
    """Produce the hypothetical position list, leaving the input untouched.

    A new position needs a price to be valued at. When the caller supplies no
    reference price the change is rejected rather than valued at zero, which
    would silently understate the position to nothing.
    """
    by_ticker = {p.ticker: p for p in positions}
    applied: list[dict[str, Any]] = []
    result: dict[str, Position] = dict(by_ticker)

    for change in changes:
        existing = by_ticker.get(change.ticker)
        if change.quantity == 0:
            if existing is None:
                raise SimulationError(
                    f"{change.ticker} is not held, so it cannot be removed"
                )
            result.pop(change.ticker, None)
            applied.append(
                {"ticker": change.ticker, "action": "remove", "from": str(existing.quantity),
                 "to": "0"}
            )
            continue

        if existing is None:
            raise SimulationError(
                f"{change.ticker} is not currently held. Simulating a new position "
                "requires a reference price; add it to the portfolio first, or "
                "simulate a change to something already held."
            )

        result[change.ticker] = Position(
            ticker=existing.ticker,
            sector=existing.sector,
            quantity=change.quantity,
            average_price=existing.average_price,
            last_price=existing.last_price,
        )
        applied.append(
            {
                "ticker": change.ticker,
                "action": "resize",
                "from": str(existing.quantity),
                "to": str(change.quantity),
            }
        )

    if not result:
        raise SimulationError("the simulated portfolio would be empty")

    return list(result.values()), applied


def simulate(
    positions: list[Position],
    changes: list[AllocationChange],
    series_by_ticker: dict[str, list[Candle]],
) -> SimulationResult:
    if not positions:
        raise SimulationError("there is no portfolio to simulate against")
    if not changes:
        raise SimulationError("no changes were supplied")

    after_positions, applied = apply_changes(positions, changes)
    after_series = {
        ticker: candles
        for ticker, candles in series_by_ticker.items()
        if ticker in {p.ticker for p in after_positions}
    }

    return SimulationResult(
        before=compute_portfolio_metrics(positions),
        after=compute_portfolio_metrics(after_positions),
        before_risk=portfolio_risk(positions, series_by_ticker),
        after_risk=portfolio_risk(after_positions, after_series),
        changes=applied,
        correlation=correlation_matrix(after_series),
    )
