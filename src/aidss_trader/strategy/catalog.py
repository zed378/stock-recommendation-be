"""The parameter sets the comparison backtest runs (ADR-061).

**Proposed starting points, not the owner's numbers (OQ-11).** They are the usual textbook values
for each rule, written down before any result was seen and never adjusted afterwards: a set that
was tuned until the backtest looked good would measure the tuning, not the rule. Every rule gets
the same stop shape (2.5 x ATR of 14, the reference strategy's own multiple) and the same cooldown
(one 4H candle), so position sizes differ only because the rules' prices differ.
"""

from __future__ import annotations

from decimal import Decimal

from aidss_trader.strategy.base import Strategy
from aidss_trader.strategy.ema_adx import EmaAdxParams, EmaAdxStrategy
from aidss_trader.strategy.library import (
    BollingerParams,
    BollingerReversion,
    DonchianBreakout,
    DonchianParams,
    MacdTrend,
    MacdTrendParams,
    RsiParams,
    RsiReversion,
)

D = Decimal
STOP_MULTIPLE = D("2.5")
COOLDOWN_S = 14_400  # one 4H candle


def proposed_strategies() -> dict[str, Strategy]:
    return {
        s.name: s
        for s in (
            DonchianBreakout(DonchianParams(20, 10, 14, STOP_MULTIPLE, COOLDOWN_S)),
            RsiReversion(RsiParams(14, D(30), D(55), 14, STOP_MULTIPLE, COOLDOWN_S)),
            BollingerReversion(BollingerParams(20, D(2), 14, STOP_MULTIPLE, COOLDOWN_S)),
            MacdTrend(MacdTrendParams(12, 26, 9, 100, 14, STOP_MULTIPLE, COOLDOWN_S)),
        )
    }


def reference_ema_adx(params: EmaAdxParams) -> EmaAdxStrategy:
    """The reference rule with the owner's stored parameters, passed in by the caller."""
    return EmaAdxStrategy(params)
