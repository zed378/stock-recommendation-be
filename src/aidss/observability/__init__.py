"""Observability: metrics and structured logging (Phase 9)."""

from aidss.observability.logging import (
    REDACTED,
    SENSITIVE_KEYS,
    JSONFormatter,
    bind_request,
    clear_request,
    configure_logging,
    new_request_id,
    redact,
    request_id_var,
)
from aidss.observability.metrics import (
    DEFAULT_BUCKETS,
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    Timer,
    registry,
    reset_registry,
)

__all__ = [
    "DEFAULT_BUCKETS",
    "REDACTED",
    "SENSITIVE_KEYS",
    "Counter",
    "Gauge",
    "Histogram",
    "JSONFormatter",
    "MetricsRegistry",
    "Timer",
    "bind_request",
    "clear_request",
    "configure_logging",
    "new_request_id",
    "redact",
    "registry",
    "request_id_var",
    "reset_registry",
]
