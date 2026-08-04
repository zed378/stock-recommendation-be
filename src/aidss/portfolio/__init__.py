"""Portfolio Intelligence (Phase 6, Section 5.2).

Deterministic metrics, risk figures, and what-if simulation over holdings the
investor entered manually. Nothing in this package writes to a holding, and
nothing in it could reach a brokerage account.
"""

from aidss.portfolio.agents import PortfolioAnalyzer, PortfolioContext, RiskAnalyzer
from aidss.portfolio.engine import PortfolioAnalysisRun, PortfolioIntelligenceEngine
from aidss.portfolio.loader import load_positions, load_price_series
from aidss.portfolio.metrics import (
    PortfolioMetrics,
    Position,
    compute_portfolio_metrics,
    correlation_matrix,
    diversification_score,
    herfindahl,
)
from aidss.portfolio.risk import RiskMetrics, asset_risk, compute_risk_metrics, portfolio_risk
from aidss.portfolio.simulation import (
    AllocationChange,
    SimulationError,
    SimulationResult,
    simulate,
)

__all__ = [
    "AllocationChange",
    "PortfolioAnalysisRun",
    "PortfolioAnalyzer",
    "PortfolioContext",
    "PortfolioIntelligenceEngine",
    "PortfolioMetrics",
    "Position",
    "RiskAnalyzer",
    "RiskMetrics",
    "SimulationError",
    "SimulationResult",
    "asset_risk",
    "compute_portfolio_metrics",
    "compute_risk_metrics",
    "correlation_matrix",
    "diversification_score",
    "herfindahl",
    "load_positions",
    "load_price_series",
    "portfolio_risk",
    "simulate",
]
