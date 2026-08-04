"""Deterministic portfolio and risk metrics (Phase 6).

Same principle as the indicator suite: the arithmetic is checked against
analytic cases whose answer follows from the definition, so agreement means
agreement on the right number.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from aidss.domain.types import Candle
from aidss.portfolio.metrics import (
    Position,
    compute_portfolio_metrics,
    correlation_matrix,
    diversification_score,
    herfindahl,
)
from aidss.portfolio.risk import (
    MIN_OBSERVATIONS_FOR_VAR,
    asset_risk,
    compute_risk_metrics,
    portfolio_risk,
)
from aidss.portfolio.simulation import AllocationChange, SimulationError, simulate


def position(
    ticker: str,
    quantity: str,
    average_price: str,
    last_price: str | None = None,
    sector: str | None = "Financials",
) -> Position:
    return Position(
        ticker=ticker,
        sector=sector,
        quantity=Decimal(quantity),
        average_price=Decimal(average_price),
        last_price=None if last_price is None else Decimal(last_price),
    )


def series(prices: list[float], start: datetime | None = None) -> list[Candle]:
    start = start or datetime(2025, 1, 1, tzinfo=UTC)
    return [
        Candle(
            timestamp=start + timedelta(days=i),
            open=Decimal(str(p)),
            high=Decimal(str(p)),
            low=Decimal(str(p)),
            close=Decimal(str(p)),
            volume=Decimal("1000"),
        )
        for i, p in enumerate(prices)
    ]


# --- Concentration ---------------------------------------------------------


def test_herfindahl_of_a_single_holding_is_one() -> None:
    assert herfindahl([1.0]) == pytest.approx(1.0)


def test_herfindahl_of_n_equal_weights_is_one_over_n() -> None:
    assert herfindahl([0.25] * 4) == pytest.approx(0.25)


def test_diversification_rewards_spread_over_count() -> None:
    """Five names where one holds 90% is not five names' worth of spread."""
    even = diversification_score([0.2] * 5)
    lopsided = diversification_score([0.9, 0.025, 0.025, 0.025, 0.025])
    assert even > lopsided * 2


def test_a_single_holding_scores_zero_diversification() -> None:
    assert diversification_score([1.0]) == pytest.approx(0.0)


def test_diversification_is_capped_at_one_hundred() -> None:
    assert diversification_score([0.01] * 100) == pytest.approx(100.0)


# --- Portfolio metrics -----------------------------------------------------


def test_an_empty_portfolio_is_handled() -> None:
    metrics = compute_portfolio_metrics([])
    assert metrics.position_count == 0
    assert metrics.total_value == Decimal("0")
    assert metrics.concentration_reading == "empty"


def test_weights_sum_to_one() -> None:
    metrics = compute_portfolio_metrics(
        [
            position("BBCA", "100", "9000", "9500"),
            position("TLKM", "500", "3000", "3100"),
        ]
    )
    assert sum(metrics.weights.values()) == pytest.approx(1.0)


def test_market_value_uses_the_last_price_when_available() -> None:
    metrics = compute_portfolio_metrics([position("BBCA", "100", "9000", "9500")])
    assert metrics.total_value == Decimal("950000")
    assert metrics.total_cost == Decimal("900000")


def test_an_unpriced_position_falls_back_to_cost_and_is_reported() -> None:
    """A silent substitution would make a stale portfolio look current."""
    metrics = compute_portfolio_metrics(
        [position("BBCA", "100", "9000", "9500"), position("TLKM", "500", "3000", None)]
    )
    assert metrics.priced_positions == 1
    assert metrics.position_count == 2
    # P&L is withheld entirely rather than computed from a mix of prices and costs.
    assert metrics.unrealised_pnl is None


def test_unrealised_pnl_is_computed_when_every_position_is_priced() -> None:
    metrics = compute_portfolio_metrics([position("BBCA", "100", "9000", "9500")])
    assert metrics.unrealised_pnl == Decimal("50000")
    assert metrics.unrealised_pnl_pct == pytest.approx(50000 / 900000)


def test_sector_weights_aggregate_positions() -> None:
    metrics = compute_portfolio_metrics(
        [
            position("BBCA", "100", "9000", "9000", sector="Financials"),
            position("BBRI", "100", "9000", "9000", sector="Financials"),
            position("TLKM", "200", "9000", "9000", sector="Telecom"),
        ]
    )
    assert metrics.sector_weights["Financials"] == pytest.approx(0.5)
    assert metrics.sector_weights["Telecom"] == pytest.approx(0.5)


def test_an_unclassified_asset_is_grouped_not_dropped() -> None:
    """Dropping it would overstate how diversified the classified part is."""
    metrics = compute_portfolio_metrics(
        [
            position("BBCA", "100", "9000", "9000", sector="Financials"),
            position("XXXX", "100", "9000", "9000", sector=None),
        ]
    )
    assert "unclassified" in metrics.sector_weights
    assert sum(metrics.sector_weights.values()) == pytest.approx(1.0)


def test_concentration_reading_matches_the_index() -> None:
    concentrated = compute_portfolio_metrics([position("BBCA", "100", "9000", "9000")])
    spread = compute_portfolio_metrics(
        [position(f"T{i}", "100", "9000", "9000") for i in range(10)]
    )
    assert concentrated.concentration_reading == "highly concentrated"
    assert spread.concentration_reading == "reasonably spread"


# --- Correlation -----------------------------------------------------------


def test_correlation_needs_at_least_two_assets() -> None:
    result = correlation_matrix({"BBCA": series([100.0] * 50)})
    assert not result["available"]
    assert "two assets" in result["reason"]


def test_correlation_needs_enough_overlapping_observations() -> None:
    """Eight observations look exactly like eight hundred, and mean far less."""
    result = correlation_matrix(
        {"A": series([100.0 + i for i in range(8)]), "B": series([50.0 + i for i in range(8)])}
    )
    assert not result["available"]
    assert "overlapping observations" in result["reason"]


def test_identical_series_correlate_perfectly() -> None:
    prices = [100.0 * (1.01**i) if i % 2 else 100.0 * (0.99**i) for i in range(60)]
    result = correlation_matrix({"A": series(prices), "B": series(prices)})
    assert result["available"]
    assert result["matrix"]["A"]["B"] == pytest.approx(1.0, abs=1e-6)


def test_inverse_series_correlate_negatively() -> None:
    rng = np.random.default_rng(7)
    steps = rng.normal(0, 0.01, 80)
    up = list(100 * np.exp(np.cumsum(steps)))
    down = list(100 * np.exp(np.cumsum(-steps)))
    result = correlation_matrix({"A": series(up), "B": series(down)})
    assert result["matrix"]["A"]["B"] < -0.9


def test_average_pairwise_is_reported() -> None:
    prices = [100.0 + i for i in range(60)]
    result = correlation_matrix({"A": series(prices), "B": series(prices)})
    assert result["average_pairwise"] == pytest.approx(1.0, abs=1e-6)


# --- Risk ------------------------------------------------------------------


def test_a_flat_series_has_no_volatility() -> None:
    metrics = asset_risk(series([100.0] * 200))
    assert metrics.annualised_volatility == pytest.approx(0.0)
    assert metrics.max_drawdown == pytest.approx(0.0)


def test_a_monotonic_rise_has_no_drawdown() -> None:
    metrics = asset_risk(series([100.0 + i for i in range(200)]))
    assert metrics.max_drawdown == pytest.approx(0.0)
    assert metrics.current_drawdown == pytest.approx(0.0)


def test_drawdown_measures_peak_to_trough() -> None:
    prices = [100.0] * 10 + [50.0] + [75.0] * 10
    metrics = asset_risk(series(prices))
    assert metrics.max_drawdown == pytest.approx(-0.5)
    assert metrics.current_drawdown == pytest.approx(-0.25)


def test_var_is_withheld_below_the_observation_floor() -> None:
    """A 5% tail of 40 days is two days; that is not a distribution."""
    metrics = asset_risk(series([100.0 + i % 7 for i in range(40)]))
    assert metrics.var_95 is None
    assert "var_95" in metrics.unavailable
    assert str(MIN_OBSERVATIONS_FOR_VAR) in metrics.unavailable["var_95"]


def test_var_and_shortfall_are_reported_with_enough_history() -> None:
    rng = np.random.default_rng(11)
    returns = pd.Series(rng.normal(0, 0.02, 500))
    metrics = compute_risk_metrics(returns)

    assert metrics.var_95 is not None
    assert metrics.var_95 < 0
    # Expected shortfall is the mean beyond VaR, so it is always at least as bad.
    assert metrics.expected_shortfall_95 <= metrics.var_95


def test_risk_metrics_state_that_they_are_historical() -> None:
    """A risk figure read as a forecast is a risk figure misused."""
    payload = asset_risk(series([100.0 + i for i in range(200)])).as_dict()
    assert "not a forecast" in payload["basis"]


def test_annualisation_uses_the_trading_year() -> None:
    rng = np.random.default_rng(3)
    daily = pd.Series(rng.normal(0, 0.01, 400))
    metrics = compute_risk_metrics(daily)
    assert metrics.annualised_volatility == pytest.approx(
        float(daily.std(ddof=1)) * math.sqrt(252), rel=1e-9
    )


def test_no_observations_reports_why_rather_than_zero() -> None:
    metrics = asset_risk([])
    assert metrics.observations == 0
    assert metrics.unavailable["all"]


# --- Portfolio-level risk --------------------------------------------------


def test_portfolio_risk_measures_the_weighted_series_not_the_average() -> None:
    """Averaging per-asset volatility would ignore diversification entirely."""
    rng = np.random.default_rng(5)
    a = list(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 300))))
    b = list(100 * np.exp(np.cumsum(-rng.normal(0, 0.02, 300))))

    positions = [position("A", "1", "100", "100"), position("B", "1", "100", "100")]
    combined = portfolio_risk(positions, {"A": series(a), "B": series(b)})

    solo_a = asset_risk(series(a))
    # Two partly offsetting holdings must be calmer than either alone.
    assert combined.annualised_volatility < solo_a.annualised_volatility


def test_holdings_without_history_are_excluded_and_reported() -> None:
    """Treating a missing holding as zero-risk would understate the portfolio."""
    positions = [position("A", "1", "100", "100"), position("B", "1", "100", "100")]
    metrics = portfolio_risk(positions, {"A": series([100.0 + i for i in range(200)])})
    assert metrics.observations > 0
    assert "coverage" in metrics.unavailable
    assert "1 of 2" in metrics.unavailable["coverage"]


def test_portfolio_risk_without_any_history_says_so() -> None:
    metrics = portfolio_risk([position("A", "1", "100", "100")], {})
    assert metrics.observations == 0
    assert metrics.unavailable["all"]


# --- Simulation ------------------------------------------------------------


BASE = [
    position("BBCA", "100", "9000", "9000", sector="Financials"),
    position("TLKM", "100", "3000", "3000", sector="Telecom"),
]
SERIES = {
    "BBCA": series([9000.0 + i for i in range(200)]),
    "TLKM": series([3000.0 + i for i in range(200)]),
}


def test_simulation_does_not_mutate_the_input() -> None:
    """A simulation that changed the portfolio would turn a question into a decision."""
    before = [(p.ticker, p.quantity) for p in BASE]
    simulate(BASE, [AllocationChange("BBCA", Decimal("200"))], SERIES)
    assert [(p.ticker, p.quantity) for p in BASE] == before


def test_resizing_a_position_changes_the_weights() -> None:
    result = simulate(BASE, [AllocationChange("BBCA", Decimal("300"))], SERIES)
    assert result.after.weights["BBCA"] > result.before.weights["BBCA"]
    assert result.deltas()["concentration_hhi"] > 0


def test_removing_a_position_reduces_the_count() -> None:
    result = simulate(BASE, [AllocationChange("TLKM", Decimal("0"))], SERIES)
    assert result.after.position_count == 1
    assert result.deltas()["position_count"] == -1


def test_concentrating_lowers_the_diversification_score() -> None:
    result = simulate(BASE, [AllocationChange("TLKM", Decimal("0"))], SERIES)
    assert result.deltas()["diversification_score"] < 0


def test_a_negative_quantity_is_rejected() -> None:
    """The platform models long positions entered by the investor, nothing else."""
    with pytest.raises(SimulationError, match="negative"):
        AllocationChange("BBCA", Decimal("-5"))


def test_simulating_an_unheld_asset_is_rejected_rather_than_valued_at_zero() -> None:
    with pytest.raises(SimulationError, match="reference price"):
        simulate(BASE, [AllocationChange("GOTO", Decimal("100"))], SERIES)


def test_removing_something_not_held_is_rejected() -> None:
    with pytest.raises(SimulationError, match="not held"):
        simulate(BASE, [AllocationChange("GOTO", Decimal("0"))], SERIES)


def test_emptying_the_portfolio_is_rejected() -> None:
    changes = [AllocationChange("BBCA", Decimal("0")), AllocationChange("TLKM", Decimal("0"))]
    with pytest.raises(SimulationError, match="empty"):
        simulate(BASE, changes, SERIES)


def test_simulation_requires_a_portfolio_and_a_change() -> None:
    with pytest.raises(SimulationError, match="no portfolio"):
        simulate([], [AllocationChange("BBCA", Decimal("1"))], SERIES)
    with pytest.raises(SimulationError, match="no changes"):
        simulate(BASE, [], SERIES)


def test_the_simulation_payload_says_nothing_was_changed() -> None:
    payload = simulate(BASE, [AllocationChange("BBCA", Decimal("50"))], SERIES).as_dict()
    assert "Nothing was changed" in payload["note"]
    assert "cannot place an order" in payload["note"]
