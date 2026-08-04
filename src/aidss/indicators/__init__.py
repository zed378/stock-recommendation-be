"""Indicator Engine and Feature Engineering (Phase 3).

Every calculation in this package is deterministic and LLM-free
(Sections 2.7 and 5.3).
"""

from aidss.indicators.engine import (
    DEFAULT_SPECS,
    IndicatorEngine,
    IndicatorRunReport,
    IndicatorSpec,
    candles_to_frame,
    compute,
)
from aidss.indicators.features import compute_features, persist_features

__all__ = [
    "DEFAULT_SPECS",
    "IndicatorEngine",
    "IndicatorRunReport",
    "IndicatorSpec",
    "candles_to_frame",
    "compute",
    "compute_features",
    "persist_features",
]
