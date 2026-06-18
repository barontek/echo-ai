"""Tests for metrics collection."""

import time
import pytest
from src.agentframework.metrics import (
    Counter,
    Histogram,
    Metrics,
    get_metrics,
    record_agent_request,
    record_tool_execution,
)


class TestCounter:
    def test_default_value(self):
        c = Counter(name="test")
        assert c.value == 0

    def test_inc_default(self):
        c = Counter(name="test")
        c.inc()
        assert c.value == 1

    def test_inc_amount(self):
        c = Counter(name="test")
        c.inc(5)
        assert c.value == 5

    def test_reset(self):
        c = Counter(name="test")
        c.inc(10)
        c.reset()
        assert c.value == 0

    def test_labels(self):
        c = Counter(name="test", labels={"env": "prod"})
        assert c.labels == {"env": "prod"}


class TestHistogram:
    def test_default_state(self):
        h = Histogram(name="test")
        assert h.values == []
        assert h.count == 0
        assert h.sum == 0.0
        assert h.avg == 0.0

    def test_observe(self):
        h = Histogram(name="test")
        h.observe(1.0)
        h.observe(2.0)
        h.observe(3.0)
        assert h.values == [1.0, 2.0, 3.0]
        assert h.count == 3
        assert h.sum == 6.0
        assert h.avg == 2.0

    def test_reset(self):
        h = Histogram(name="test")
        h.observe(1.0)
        h.observe(2.0)
        h.reset()
        assert h.values == []
        assert h.count == 0


class TestMetrics:
    @pytest.fixture
    def metrics(self):
        return Metrics()

    def test_counter_create(self, metrics):
        counter = metrics.counter("requests")
        assert counter.name == "requests"
        assert counter.value == 0

    def test_counter_reuses_instance(self, metrics):
        c1 = metrics.counter("requests")
        c2 = metrics.counter("requests")
        assert c1 is c2

    def test_counter_with_labels_is_separate(self, metrics):
        c1 = metrics.counter("requests", labels={"env": "prod"})
        c2 = metrics.counter("requests", labels={"env": "staging"})
        assert c1 is not c2

    def test_histogram_create(self, metrics):
        h = metrics.histogram("latency")
        assert h.name == "latency"
        assert h.count == 0

    def test_gauge(self, metrics):
        metrics.gauge("memory_usage", 42.0)
        result = metrics.get_all()
        assert "gauge:memory_usage" in result
        assert result["gauge:memory_usage"]["value"] == 42.0

    def test_gauge_with_labels(self, metrics):
        metrics.gauge("memory_usage", 42.0, labels={"host": "server1"})
        result = metrics.get_all()
        assert any("host=server1" in k for k in result)

    def test_inc_counter(self, metrics):
        metrics.inc_counter("requests", amount=3, labels={"status": "200"})
        result = metrics.get_all()
        key = "counter:requests{status=200}"
        assert result[key]["value"] == 3

    def test_observe_histogram(self, metrics):
        metrics.observe_histogram("latency", 0.5, labels={"endpoint": "/api"})
        result = metrics.get_all()
        key = "histogram:latency{endpoint=/api}"
        assert result[key]["count"] == 1
        assert result[key]["sum"] == 0.5

    def test_timer_context_manager(self, metrics):
        with metrics.timer("operation_duration"):
            time.sleep(0.001)
        result = metrics.get_all()
        key = "histogram:operation_duration"
        assert result[key]["count"] == 1
        assert result[key]["sum"] > 0

    def test_get_all_empty(self, metrics):
        result = metrics.get_all()
        assert result == {}

    def test_export_prometheus_empty(self, metrics):
        output = metrics.export_prometheus()
        assert output == "\n"

    def test_export_prometheus_counters(self, metrics):
        metrics.inc_counter("http_requests", labels={"method": "GET"})
        metrics.inc_counter("http_requests", amount=2, labels={"method": "POST"})
        output = metrics.export_prometheus()
        assert 'http_requests{method="GET"} 1' in output
        assert 'http_requests{method="POST"} 2' in output

    def test_export_prometheus_gauges(self, metrics):
        metrics.gauge("memory_bytes", 1024)
        output = metrics.export_prometheus()
        assert "memory_bytes 1024" in output

    def test_export_prometheus_histograms(self, metrics):
        metrics.observe_histogram("request_duration", 0.5)
        output = metrics.export_prometheus()
        assert "request_duration_count 1" in output
        assert "request_duration_sum" in output


class TestConvenienceFunctions:
    def test_get_metrics_returns_singleton(self):
        m1 = get_metrics()
        m2 = get_metrics()
        assert m1 is m2

    def test_record_agent_request(self):
        m = get_metrics()
        m._counters.clear()
        m._histograms.clear()
        record_agent_request("openai", 0.5)
        result = m.get_all()
        assert any("agent_requests_total" in k for k in result)
        assert any("agent_request_duration_seconds" in k for k in result)

    def test_record_tool_execution_success(self):
        m = get_metrics()
        m._counters.clear()
        m._histograms.clear()
        record_tool_execution("bash", 0.3, success=True)
        result = m.get_all()
        assert any("tool_executions_total" in k and "success" in k for k in result)
        assert any("tool_execution_duration_seconds" in k for k in result)

    def test_record_tool_execution_error(self):
        m = get_metrics()
        m._counters.clear()
        m._histograms.clear()
        record_tool_execution("bash", 0.3, success=False)
        result = m.get_all()
        assert any("tool_executions_total" in k and "error" in k for k in result)
