"""In-process metrics with Prometheus exposition (Phase 9, Section 2.6).

A small registry rather than the `prometheus_client` library, for one reason
that matters here: that library keeps a process-global registry, which makes
test isolation awkward and encourages metrics to be declared as import-time
side effects scattered through the codebase. An explicit registry that can be
constructed per application is easier to reason about and to test, and the
exposition format itself is a few dozen lines.

Scope note, stated plainly: these counters live in one process. With several
replicas each exposes its own view, which is exactly what a Prometheus scrape
expects - it aggregates across instances. What this does *not* give you is a
single authoritative number readable from one process, and nothing here
pretends otherwise.
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

#: Latency buckets in seconds. Chosen around what actually matters here: the
#: plan's non-functional requirement is on-demand analysis under 10 seconds
#: (Section 2.6), so the buckets straddle that rather than stopping at 1s.
DEFAULT_BUCKETS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0,
)

Labels = tuple[tuple[str, str], ...]


def _normalise(labels: dict[str, str] | None) -> Labels:
    """Sort label pairs so the same labels always produce the same series."""
    if not labels:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def _render_labels(labels: Labels, extra: dict[str, str] | None = None) -> str:
    pairs = list(labels)
    if extra:
        pairs.extend(extra.items())
    if not pairs:
        return ""
    body = ",".join(f'{k}="{_escape(v)}"' for k, v in pairs)
    return "{" + body + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


@dataclass
class Counter:
    name: str
    help: str
    _values: dict[Labels, float] = field(default_factory=lambda: defaultdict(float))

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        if amount < 0:
            # A counter that can go down is a gauge that lies about its type,
            # and every rate() over it would be wrong.
            raise ValueError("a counter cannot decrease")
        self._values[_normalise(labels)] += amount

    def value(self, **labels: str) -> float:
        return self._values.get(_normalise(labels), 0.0)

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        for labels, value in sorted(self._values.items()):
            lines.append(f"{self.name}{_render_labels(labels)} {value}")
        return lines


@dataclass
class Gauge:
    name: str
    help: str
    _values: dict[Labels, float] = field(default_factory=lambda: defaultdict(float))

    def set(self, value: float, **labels: str) -> None:
        self._values[_normalise(labels)] = value

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        self._values[_normalise(labels)] += amount

    def value(self, **labels: str) -> float:
        return self._values.get(_normalise(labels), 0.0)

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} gauge"]
        for labels, value in sorted(self._values.items()):
            lines.append(f"{self.name}{_render_labels(labels)} {value}")
        return lines


@dataclass
class Histogram:
    name: str
    help: str
    buckets: tuple[float, ...] = DEFAULT_BUCKETS
    _counts: dict[Labels, list[int]] = field(default_factory=dict)
    _sums: dict[Labels, float] = field(default_factory=lambda: defaultdict(float))
    _totals: dict[Labels, int] = field(default_factory=lambda: defaultdict(int))

    def observe(self, value: float, **labels: str) -> None:
        if math.isnan(value):
            return
        key = _normalise(labels)
        if key not in self._counts:
            self._counts[key] = [0] * len(self.buckets)
        for i, bound in enumerate(self.buckets):
            if value <= bound:
                self._counts[key][i] += 1
        self._sums[key] += value
        self._totals[key] += 1

    def count(self, **labels: str) -> int:
        return self._totals.get(_normalise(labels), 0)

    def total(self, **labels: str) -> float:
        return self._sums.get(_normalise(labels), 0.0)

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        for key in sorted(self._counts):
            cumulative = self._counts[key]
            for bound, count in zip(self.buckets, cumulative, strict=True):
                le = "+Inf" if math.isinf(bound) else repr(bound)
                lines.append(f"{self.name}_bucket{_render_labels(key, {'le': le})} {count}")
            # The +Inf bucket is mandatory and must equal the total count.
            lines.append(
                f"{self.name}_bucket{_render_labels(key, {'le': '+Inf'})} {self._totals[key]}"
            )
            lines.append(f"{self.name}_sum{_render_labels(key)} {self._sums[key]}")
            lines.append(f"{self.name}_count{_render_labels(key)} {self._totals[key]}")
        return lines


class MetricsRegistry:
    """A collection of metrics that can be rendered for a scrape."""

    def __init__(self) -> None:
        self._metrics: dict[str, Counter | Gauge | Histogram] = {}
        self._lock = threading.Lock()

    def counter(self, name: str, help: str) -> Counter:
        return self._get_or_create(name, lambda: Counter(name, help), Counter)

    def gauge(self, name: str, help: str) -> Gauge:
        return self._get_or_create(name, lambda: Gauge(name, help), Gauge)

    def histogram(
        self, name: str, help: str, buckets: tuple[float, ...] = DEFAULT_BUCKETS
    ) -> Histogram:
        return self._get_or_create(name, lambda: Histogram(name, help, buckets), Histogram)

    def _get_or_create(self, name: str, factory, expected_type):
        with self._lock:
            existing = self._metrics.get(name)
            if existing is not None:
                if not isinstance(existing, expected_type):
                    # Two metrics sharing a name with different types produce
                    # an exposition Prometheus rejects outright.
                    raise TypeError(
                        f"{name!r} is already registered as {type(existing).__name__}"
                    )
                return existing
            metric = factory()
            self._metrics[name] = metric
            return metric

    def render(self) -> str:
        lines: list[str] = []
        for _, metric in sorted(self._metrics.items()):
            lines.extend(metric.render())
        return "\n".join(lines) + "\n"

    def snapshot(self) -> dict[str, Any]:
        """A JSON view, for the admin dashboard rather than a scraper."""
        out: dict[str, Any] = {}
        for name, metric in sorted(self._metrics.items()):
            if isinstance(metric, Histogram):
                out[name] = {
                    "count": sum(metric._totals.values()),
                    "sum": sum(metric._sums.values()),
                }
            else:
                out[name] = sum(metric._values.values())
        return out


#: The application registry. Module-level so instrumentation points can reach
#: it without threading it through every call, but replaceable in tests.
_registry = MetricsRegistry()


def registry() -> MetricsRegistry:
    return _registry


def reset_registry() -> MetricsRegistry:
    """Replace the registry - used by tests so counts do not leak between them."""
    global _registry
    _registry = MetricsRegistry()
    return _registry


class Timer:
    """Context manager that records elapsed seconds into a histogram."""

    def __init__(self, histogram: Histogram, **labels: str) -> None:
        self._histogram = histogram
        self._labels = labels
        self._start = 0.0

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._histogram.observe(time.perf_counter() - self._start, **self._labels)
