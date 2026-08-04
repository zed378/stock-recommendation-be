"""Deterministic risk metrics (Phase 6, Section 5.2).

Historical drawdown, volatility, and value-at-risk for a single asset or a
whole portfolio. All of it computed, none of it generated.

One honest limitation stated up front: every figure here is backward-looking.
Historical VaR says what the worst 5% of *observed* days looked like, not what
tomorrow holds. The metrics carry their observation counts so a reader can see
how much history is actually behind a number, and the Risk Analyzer's prompt
is told to say so rather than present these as forecasts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from aidss.domain.types import Candle
from aidss.portfolio.metrics import Position, returns_frame

TRADING_DAYS_PER_YEAR = 252

#: Below this many observations a distribution-based figure is not reported.
#: VaR at 95% from 40 days rests on the two worst days in the sample.
MIN_OBSERVATIONS_FOR_VAR = 120


@dataclass(slots=True)
class RiskMetrics:
    observations: int
    annualised_volatility: float | None = None
    max_drawdown: float | None = None
    current_drawdown: float | None = None
    #: Historical VaR at 95% - the daily loss the worst 5% of observed days
    #: exceeded. Negative by convention.
    var_95: float | None = None
    #: Mean loss on the days beyond VaR. Answers "when it goes wrong, how
    #: wrong?", which VaR alone does not.
    expected_shortfall_95: float | None = None
    downside_deviation: float | None = None
    best_day: float | None = None
    worst_day: float | None = None
    #: Reasons a metric is absent, so a null reads as "not enough data" rather
    #: than "no risk".
    unavailable: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "observations": self.observations,
            "annualised_volatility": _round(self.annualised_volatility),
            "max_drawdown": _round(self.max_drawdown),
            "current_drawdown": _round(self.current_drawdown),
            "var_95": _round(self.var_95),
            "expected_shortfall_95": _round(self.expected_shortfall_95),
            "downside_deviation": _round(self.downside_deviation),
            "best_day": _round(self.best_day),
            "worst_day": _round(self.worst_day),
            "unavailable": dict(self.unavailable),
            "basis": (
                "All figures are historical: they describe observed behaviour over "
                f"{self.observations} periods, not a forecast."
            ),
        }


def _round(value: float | None) -> float | None:
    if value is None or math.isnan(value) or math.isinf(value):
        return None
    return round(value, 6)


def _returns_from_candles(candles: list[Candle]) -> pd.Series:
    if len(candles) < 2:
        return pd.Series(dtype=float)
    closes = pd.Series([float(c.close) for c in candles])
    return np.log(closes / closes.shift(1)).dropna()


def compute_risk_metrics(returns: pd.Series, *, prices: pd.Series | None = None) -> RiskMetrics:
    """Risk figures from a log-return series.

    ``prices`` drives drawdown, which is a property of the equity curve rather
    than of returns; when absent it is reconstructed from the returns.
    """
    metrics = RiskMetrics(observations=int(len(returns)))
    if returns.empty:
        metrics.unavailable["all"] = "no return observations"
        return metrics

    metrics.annualised_volatility = float(
        returns.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR)
    )
    metrics.best_day = float(returns.max())
    metrics.worst_day = float(returns.min())

    downside = returns[returns < 0]
    metrics.downside_deviation = (
        float(downside.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR))
        if len(downside) > 1
        else None
    )

    if len(returns) >= MIN_OBSERVATIONS_FOR_VAR:
        metrics.var_95 = float(np.percentile(returns, 5))
        tail = returns[returns <= metrics.var_95]
        metrics.expected_shortfall_95 = float(tail.mean()) if len(tail) else None
    else:
        metrics.unavailable["var_95"] = (
            f"{len(returns)} observations; at least {MIN_OBSERVATIONS_FOR_VAR} are needed "
            "before a 5% tail contains enough days to mean anything"
        )

    curve = prices if prices is not None else (1.0 + returns).cumprod()
    if len(curve) > 1:
        running_max = curve.cummax()
        drawdown = curve / running_max - 1.0
        metrics.max_drawdown = float(drawdown.min())
        metrics.current_drawdown = float(drawdown.iloc[-1])

    return metrics


def asset_risk(candles: list[Candle]) -> RiskMetrics:
    returns = _returns_from_candles(candles)
    prices = (
        pd.Series([float(c.close) for c in candles]) if len(candles) > 1 else None
    )
    return compute_risk_metrics(returns, prices=prices)


def portfolio_risk(
    positions: list[Position], series_by_ticker: dict[str, list[Candle]]
) -> RiskMetrics:
    """Risk of the weighted portfolio, not the average of its parts.

    The weighted return series is built first and measured second. Averaging
    per-asset volatilities would ignore diversification entirely and overstate
    the portfolio's risk - the whole point of holding more than one thing.
    """
    frame = returns_frame({t: c for t, c in series_by_ticker.items() if c})
    if frame.empty:
        metrics = RiskMetrics(observations=0)
        metrics.unavailable["all"] = "no overlapping price history across the holdings"
        return metrics

    total_value = sum((p.market_value for p in positions), start=Decimal("0"))
    if total_value <= 0:
        metrics = RiskMetrics(observations=0)
        metrics.unavailable["all"] = "portfolio has no value to measure"
        return metrics

    weights = {
        p.ticker: float(p.market_value / total_value)
        for p in positions
        if p.ticker in frame.columns
    }
    if not weights:
        metrics = RiskMetrics(observations=0)
        metrics.unavailable["all"] = "no holding has stored price history"
        return metrics

    # Renormalise across the holdings that actually have history, so the result
    # describes the measurable part of the portfolio rather than silently
    # treating missing holdings as zero-risk.
    scale = sum(weights.values())
    weighted = sum(frame[ticker] * (weight / scale) for ticker, weight in weights.items())

    metrics = compute_risk_metrics(pd.Series(weighted))
    if len(weights) < len(positions):
        missing = len(positions) - len(weights)
        metrics.unavailable["coverage"] = (
            f"{missing} of {len(positions)} holdings had no usable price history and are "
            "excluded; the figures describe the remainder"
        )
    return metrics
