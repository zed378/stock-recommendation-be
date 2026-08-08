"""Recommendation Engine (Phase 5, Section 14.4)."""

from aidss.recommendations.agent import RecommendationAgent
from aidss.recommendations.calibration import (
    MAX_CONFIDENCE,
    SOURCE_WEIGHTS,
    STRONG_LABEL_MIN_CONFIDENCE,
    CalibrationResult,
    DerivedLevels,
    EvidenceSignal,
    calibrate,
    derive_levels,
    evidence_direction,
)
from aidss.recommendations.engine import (
    RecommendationEngine,
    RecommendationRejected,
    RecommendationResult,
)
from aidss.recommendations.rules import RuleReport, RuleViolation, check

__all__ = [
    "MAX_CONFIDENCE",
    "SOURCE_WEIGHTS",
    "STRONG_LABEL_MIN_CONFIDENCE",
    "CalibrationResult",
    "DerivedLevels",
    "EvidenceSignal",
    "RecommendationAgent",
    "RecommendationEngine",
    "RecommendationRejected",
    "RecommendationResult",
    "RuleReport",
    "RuleViolation",
    "calibrate",
    "check",
    "derive_levels",
    "evidence_direction",
]
