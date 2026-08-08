"""Deterministic portfolio metrics (Phase 6, Section 14.2).

The same division of labour as everywhere else in this codebase: the numbers
are computed here, and the AI layer only interprets them. Concentration,
diversification, and correlation are arithmetic - asking a language model to
produce them would introduce error into figures a user may act on.

Everything here operates on holdings the investor entered themselves. There is
no brokerage connection anywhere in the path, and `input_method` records that
on every position.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from aidss.domain.types import Candle

#: Below this, a portfolio is concentrated enough that single-name risk
#: dominates. The thresholds follow the usual Herfindahl reading: above 0.25 is
#: highly concentrated, 0.15-0.25 moderately so.
HHI_HIGH_CONCENTRATION = 0.25
HHI_MODERATE_CONCENTRATION = 0.15


@dataclass(frozen=True, slots=True)
class Position:
    """One holding, reduced to what the metrics need."""

    ticker: str
    sector: str | None
    quantity: Decimal
    average_price: Decimal
    last_price: Decimal | None = None

    @property
    def cost_basis(self) -> Decimal:
        return self.quantity * self.average_price

    @property
    def market_value(self) -> Decimal:
        """Current value, falling back to cost when no price is stored.

        The fallback is stated rather than hidden: a portfolio whose prices
        have never been fetched is valued at what the investor paid, and
        `priced_positions` reports how many positions that applies to.
        """
        price = self.last_price if self.last_price is not None else self.average_price
        return self.quantity * price

    @property
    def unrealised_pnl(self) -> Decimal | None:
        if self.last_price is None:
            return None
        return (self.last_price - self.average_price) * self.quantity


@dataclass(slots=True)
class PortfolioMetrics:
    total_value: Decimal
    total_cost: Decimal
    position_count: int
    #: How many positions had a stored price. Anything less than
    #: `position_count` means part of the valuation is cost-based.
    priced_positions: int
    weights: dict[str, float] = field(default_factory=dict)
    sector_weights: dict[str, float] = field(default_factory=dict)
    #: Herfindahl-Hirschman index of position weights: 1/n when perfectly even,
    #: 1.0 when everything sits in one name.
    concentration_hhi: float = 0.0
    sector_concentration_hhi: float = 0.0
    #: 0-100, where 100 would be an evenly weighted portfolio across many names.
    diversification_score: float = 0.0
    largest_position: tuple[str, float] | None = None
    unrealised_pnl: Decimal | None = None
    unrealised_pnl_pct: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_value": str(self.total_value),
            "total_cost": str(self.total_cost),
            "position_count": self.position_count,
            "priced_positions": self.priced_positions,
            "weights": {k: round(v, 6) for k, v in self.weights.items()},
            "sector_weights": {k: round(v, 6) for k, v in self.sector_weights.items()},
            "concentration_hhi": round(self.concentration_hhi, 6),
            "sector_concentration_hhi": round(self.sector_concentration_hhi, 6),
            "diversification_score": round(self.diversification_score, 2),
            "largest_position": (
                {"ticker": self.largest_position[0], "weight": round(self.largest_position[1], 6)}
                if self.largest_position
                else None
            ),
            "unrealised_pnl": None if self.unrealised_pnl is None else str(self.unrealised_pnl),
            "unrealised_pnl_pct": (
                None if self.unrealised_pnl_pct is None else round(self.unrealised_pnl_pct, 6)
            ),
            "concentration_reading": self.concentration_reading,
        }

    @property
    def concentration_reading(self) -> str:
        if self.position_count == 0:
            return "empty"
        if self.concentration_hhi >= HHI_HIGH_CONCENTRATION:
            return "highly concentrated"
        if self.concentration_hhi >= HHI_MODERATE_CONCENTRATION:
            return "moderately concentrated"
        return "reasonably spread"


def herfindahl(weights: list[float]) -> float:
    """Sum of squared weights. 1/n for n equal weights, 1.0 for a single name."""
    return float(sum(w * w for w in weights))


def diversification_score(weights: list[float]) -> float:
    """0-100, from the effective number of positions.

    The effective count is 1/HHI: five equally weighted names score 5, but five
    names where one holds 90% score close to 1. Mapped onto 0-100 with a
    logarithmic curve, because going from one holding to five matters far more
    than going from twenty to twenty-five.
    """
    if not weights:
        return 0.0
    hhi = herfindahl(weights)
    if hhi <= 0:
        return 0.0
    effective = 1.0 / hhi
    # log10(20) ~ 1.3, so twenty effective positions reaches 100.
    return float(min(100.0, 100.0 * math.log10(effective) / math.log10(20)))


def compute_portfolio_metrics(positions: list[Position]) -> PortfolioMetrics:
    if not positions:
        return PortfolioMetrics(
            total_value=Decimal("0"), total_cost=Decimal("0"),
            position_count=0, priced_positions=0,
        )

    total_value = sum((p.market_value for p in positions), start=Decimal("0"))
    total_cost = sum((p.cost_basis for p in positions), start=Decimal("0"))

    weights: dict[str, float] = {}
    if total_value > 0:
        for position in positions:
            weights[position.ticker] = float(position.market_value / total_value)

    sector_weights: dict[str, float] = {}
    for position in positions:
        # An asset whose sector was never populated is grouped under
        # "unclassified" rather than dropped: hiding it would overstate how
        # diversified the classified part is.
        sector = position.sector or "unclassified"
        sector_weights[sector] = sector_weights.get(sector, 0.0) + weights.get(position.ticker, 0.0)

    priced = [p for p in positions if p.last_price is not None]
    pnl: Decimal | None = None
    pnl_pct: float | None = None
    if len(priced) == len(positions) and total_cost > 0:
        pnl = total_value - total_cost
        pnl_pct = float(pnl / total_cost)

    weight_values = list(weights.values())
    largest = max(weights.items(), key=lambda kv: kv[1]) if weights else None

    return PortfolioMetrics(
        total_value=total_value,
        total_cost=total_cost,
        position_count=len(positions),
        priced_positions=len(priced),
        weights=weights,
        sector_weights=sector_weights,
        concentration_hhi=herfindahl(weight_values),
        sector_concentration_hhi=herfindahl(list(sector_weights.values())),
        diversification_score=diversification_score(weight_values),
        largest_position=largest,
        unrealised_pnl=pnl,
        unrealised_pnl_pct=pnl_pct,
    )


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------


def returns_frame(series_by_ticker: dict[str, list[Candle]]) -> pd.DataFrame:
    """Aligned daily log returns, one column per ticker.

    Aligned on shared timestamps: correlating two series that trade on
    different days would measure the calendar rather than the relationship.
    """
    columns: dict[str, pd.Series] = {}
    for ticker, candles in series_by_ticker.items():
        if len(candles) < 2:
            continue
        closes = pd.Series(
            [float(c.close) for c in candles],
            index=pd.DatetimeIndex([c.timestamp for c in candles]),
        ).sort_index()
        columns[ticker] = np.log(closes / closes.shift(1))

    if not columns:
        return pd.DataFrame()
    return pd.DataFrame(columns).dropna(how="any")


def correlation_matrix(
    series_by_ticker: dict[str, list[Candle]], *, min_observations: int = 30
) -> dict[str, Any]:
    """Pairwise correlation of daily returns.

    Returns an explicit "insufficient data" marker rather than a matrix built
    on a handful of overlapping days. A correlation computed from eight
    observations looks exactly like one computed from eight hundred, and only
    one of them means anything.
    """
    frame = returns_frame(series_by_ticker)
    if frame.empty or len(frame.columns) < 2:
        return {
            "available": False,
            "reason": "at least two assets with overlapping price history are required",
            "matrix": {},
        }
    if len(frame) < min_observations:
        return {
            "available": False,
            "reason": (
                f"only {len(frame)} overlapping observations; "
                f"at least {min_observations} are needed for a meaningful correlation"
            ),
            "matrix": {},
        }

    matrix = frame.corr()
    return {
        "available": True,
        "observations": int(len(frame)),
        "matrix": {
            row: {col: _clean(matrix.loc[row, col]) for col in matrix.columns}
            for row in matrix.index
        },
        "average_pairwise": _average_pairwise(matrix),
    }


def _average_pairwise(matrix: pd.DataFrame) -> float | None:
    """Mean of the off-diagonal entries - a single read on how much the
    portfolio's holdings move together."""
    values = [
        matrix.iloc[i, j]
        for i in range(len(matrix))
        for j in range(i + 1, len(matrix))
        if not math.isnan(matrix.iloc[i, j])
    ]
    return float(sum(values) / len(values)) if values else None


def _clean(value: Any) -> float | None:
    number = float(value)
    return None if math.isnan(number) else round(number, 6)
