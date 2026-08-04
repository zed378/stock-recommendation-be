"""Scheduled news ingestion (Phase 7, Section 6.3)."""

from aidss.news.collector import (
    FAILURE_THRESHOLD,
    IngestionReport,
    NewsCollector,
    NewsScheduler,
    SentimentScorer,
    content_hash,
)
from aidss.news.schedules import (
    EXCHANGE_TIMEZONE,
    MIN_INTERVAL_SECONDS,
    PRESETS,
    PRESETS_BY_KEY,
    CronPreset,
    InvalidScheduleError,
    next_run_at,
    resolve,
    validate_expression,
)

__all__ = [
    "EXCHANGE_TIMEZONE",
    "FAILURE_THRESHOLD",
    "MIN_INTERVAL_SECONDS",
    "PRESETS",
    "PRESETS_BY_KEY",
    "CronPreset",
    "IngestionReport",
    "InvalidScheduleError",
    "NewsCollector",
    "NewsScheduler",
    "SentimentScorer",
    "content_hash",
    "next_run_at",
    "resolve",
    "validate_expression",
]
