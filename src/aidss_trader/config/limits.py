"""Risk limits: the mechanism, with no values.

Every number here is the owner's (docs/01-PRODUCT-REQUIREMENTS/08). **No
loss-limiting field has a default.** A required field that is `None` disables
trading for the affected strategy (FR-T11), so a forgotten setting can never
become a permissive one.

The single exception is `daily_loss_day_boundary`: the owner decided it
(ADR-034, local midnight WIB), so it is a recorded decision, not a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class RiskLimits:
    risk_per_trade_pct: Decimal | None = None
    max_daily_loss_idr: Decimal | None = None
    daily_loss_day_boundary: str | None = "LOCAL"  # ADR-034
    max_drawdown_pct: Decimal | None = None
    max_consecutive_losses: int | None = None
    max_open_positions: int | None = None
    max_exposure_per_pair_pct: Decimal | None = None
    max_total_exposure_pct: Decimal | None = None
    max_order_idr: Decimal | None = None
    price_deviation_pct: Decimal | None = None
    freshness_limit_s: int | None = None
    cooldown_s: int | None = None
    order_rate_limit: int | None = None
    # `trading_window` is optional by design (None means always open), so it is
    # not part of REQUIRED_RISK_FIELDS.
    trading_window: str | None = None


REQUIRED_RISK_FIELDS: tuple[str, ...] = tuple(
    f.name for f in fields(RiskLimits) if f.name != "trading_window"
)


def unset_risk_fields(limits: RiskLimits | None) -> list[str]:
    """Names of required limits that have no value. Empty means trading may be enabled."""
    if limits is None:
        return list(REQUIRED_RISK_FIELDS)
    return [name for name in REQUIRED_RISK_FIELDS if getattr(limits, name) is None]
