"""Deterministic screening over stored indicators.

A screen is not a forecast, and the difference is the whole design. Everything
here reads settled numbers and reports which stated conditions are currently
true. Nothing predicts a price, nothing attaches a probability, and no score
means "chance of rising".
"""

from aidss.screener.criteria import CRITERIA_BY_HORIZON, Horizon
from aidss.screener.engine import (
    ScreenedAsset,
    ScreenResult,
    horizon_scores,
    limit_proximity,
    screen,
    screen_stored,
)

__all__ = [
    "CRITERIA_BY_HORIZON",
    "Horizon",
    "ScreenResult",
    "ScreenedAsset",
    "horizon_scores",
    "limit_proximity",
    "screen",
    "screen_stored",
]
