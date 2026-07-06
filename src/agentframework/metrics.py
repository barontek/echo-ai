"""Simple metrics collection for observability.

This module provides basic metrics primitives for tracking:
- Counters: Increment-only metrics
- Histograms: Value distributions
- Gauges: Point-in-time values
- Timers: Context managers for duration tracking

Supports Prometheus export format.
"""

import time
import threading
from dataclasses import dataclass, field
from contextlib import contextmanager


@dataclass
class Counter:
    """A counter metric."""

    name: str
    value: int = 0
    labels: dict[str, str] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    def inc(self, amount: int = 1):
        """Increment the counter."""
        with self._lock:
            self.value += amount

    def reset(self):
        """Reset the counter."""
        with self._lock:
            self.value = 0


@dataclass
class Histogram:
    """A histogram metric for tracking distributions."""

    name: str
    values: list[float] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    def observe(self, value: float):
        """Record an observation."""
        with self._lock:
            self.values.append(value)

    @property
    def count(self) -> int:
        """Number of observations."""
        with self._lock:
            return len(self.values)

    @property
    def sum(self) -> float:
        """Sum of all observations."""
        with self._lock:
            return sum(self.values)

    @property
    def avg(self) -> float:
        """Average of observations."""
        return self.sum / self.count if self.count > 0 else 0.0

    def reset(self):
        """Reset the histogram."""
        with self._lock:
            self.values.clear()


class Metrics:
    """Simple metrics collector for the agent framework."""

    def __init__(self):
        self._lock = threading.RLock()
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}
        self._gauges: dict[str, float] = {}

    def counter(self, name: str, labels: dict[str, str] | None = None) -> Counter:
        """Get or create a counter."""
        key = self._make_key(name, labels)
        with self._lock:
            if key not in self._counters:
                self._counters[key] = Counter(name=name, labels=labels or {})
            return self._counters[key]

    def histogram(self, name: str, labels: dict[str, str] | None = None) -> Histogram:
        """Get or create a histogram."""
        key = self._make_key(name, labels)
        with self._lock:
            if key not in self._histograms:
                self._histograms[key] = Histogram(name=name, labels=labels or {})
            return self._histograms[key]

    def gauge(self, name: str, value: float, labels: dict[str, str] | None = None):
        """Set a gauge value."""
        key = self._make_key(name, labels)
        with self._lock:
            self._gauges[key] = value

    def inc_counter(
        self, name: str, amount: int = 1, labels: dict[str, str] | None = None
    ):
        """Increment a counter."""
        self.counter(name, labels).inc(amount)

    def observe_histogram(
        self, name: str, value: float, labels: dict[str, str] | None = None
    ):
        """Record a histogram observation."""
        self.histogram(name, labels).observe(value)

    @contextmanager
    def timer(self, name: str, labels: dict[str, str] | None = None):
        """Context manager for timing operations."""
        start = time.perf_counter()
        try:
            yield
        finally:
            duration = time.perf_counter() - start
            self.observe_histogram(name, duration, labels)

    def _make_key(self, name: str, labels: dict[str, str] | None) -> str:
        """Create a unique key for a metric."""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def get_all(self) -> dict[str, dict]:
        """Get all metrics as a dictionary."""
        with self._lock:
            counters_snapshot = dict(self._counters)
            histograms_snapshot = dict(self._histograms)
            gauges_snapshot = dict(self._gauges)

        result = {}
        for key, counter in counters_snapshot.items():
            result[f"counter:{key}"] = {
                "name": counter.name,
                "value": counter.value,
                "labels": counter.labels,
            }

        for key, histogram in histograms_snapshot.items():
            result[f"histogram:{key}"] = {
                "name": histogram.name,
                "count": histogram.count,
                "sum": histogram.sum,
                "avg": histogram.avg,
                "labels": histogram.labels,
            }

        for key, value in gauges_snapshot.items():
            result[f"gauge:{key}"] = {"value": value}

        return result

    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        with self._lock:
            counters_snapshot = dict(self._counters)
            histograms_snapshot = dict(self._histograms)
            gauges_snapshot = dict(self._gauges)

        lines = []
        for key, counter in counters_snapshot.items():
            labels_str = (
                ",".join(f'{k}="{v}"' for k, v in counter.labels.items())
                if counter.labels
                else ""
            )
            name = counter.name.replace("-", "_").replace(".", "_")
            if labels_str:
                lines.append(f"{name}{{{labels_str}}} {counter.value}")
            else:
                lines.append(f"{name} {counter.value}")

        for key, histogram in histograms_snapshot.items():
            labels_str = (
                ",".join(f'{k}="{v}"' for k, v in histogram.labels.items())
                if histogram.labels
                else ""
            )
            name = histogram.name.replace("-", "_").replace(".", "_")

            if labels_str:
                lines.append(f"{name}_count{{{labels_str}}} {histogram.count}")
                lines.append(f"{name}_sum{{{labels_str}}} {histogram.sum}")
            else:
                lines.append(f"{name}_count {histogram.count}")
                lines.append(f"{name}_sum {histogram.sum}")

        for key, value in gauges_snapshot.items():
            labels_start = key.find("{")
            if labels_start != -1:
                name = key[:labels_start].replace("-", "_").replace(".", "_")
                labels_str = key[labels_start:]
                lines.append(f"{name}{labels_str} {value}")
            else:
                name = key.replace("-", "_").replace(".", "_")
                lines.append(f"{name} {value}")

        return "\n".join(lines) + "\n"


_metrics = Metrics()


def get_metrics() -> Metrics:
    """Get the global metrics instance."""
    return _metrics


def record_agent_request(provider: str, duration: float):
    """Record an agent request."""
    _metrics.inc_counter(
        "agent_requests_total", labels={"provider": provider, "status": "success"}
    )
    _metrics.observe_histogram(
        "agent_request_duration_seconds", duration, labels={"provider": provider}
    )


def record_tool_execution(tool_name: str, duration: float, success: bool):
    """Record a tool execution."""
    _metrics.inc_counter(
        "tool_executions_total",
        labels={"tool": tool_name, "status": "success" if success else "error"},
    )
    _metrics.observe_histogram(
        "tool_execution_duration_seconds", duration, labels={"tool": tool_name}
    )
