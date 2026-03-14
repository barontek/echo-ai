import pytest
from unittest.mock import MagicMock, patch, ANY
from src.agentframework.otel import OpenTelemetryCallback

@pytest.fixture
def mock_tracer():
    with patch("opentelemetry.trace.get_tracer") as mock, \
         patch("opentelemetry.context.attach"), \
         patch("opentelemetry.context.detach"):
        tracer = MagicMock()
        mock.return_value = tracer
        yield tracer

def test_otel_run_lifecycle(mock_tracer):
    cb = OpenTelemetryCallback()

    # Start
    cb.on_run_start("run1", "hello")
    mock_tracer.start_span.assert_called_with("agent_run")
    span = cb.run_spans["run1"]
    span.set_attribute.assert_any_call("run.id", "run1")

    # End
    cb.on_run_end("run1", "response")
    assert "run1" not in cb.run_spans
    span.end.assert_called()

def test_otel_run_error(mock_tracer):
    cb = OpenTelemetryCallback()
    cb.on_run_start("run2", "hi")
    err = ValueError("boom")
    cb.on_run_error("run2", err)

    span = mock_tracer.start_span.return_value
    span.record_exception.assert_called_with(err)
    span.end.assert_called()

def test_otel_llm_lifecycle(mock_tracer):
    cb = OpenTelemetryCallback()
    cb.on_llm_start("run1", [{"role": "user", "content": "hi"}])

    mock_tracer.start_span.assert_called_with("llm_chat", context=ANY)
    span = cb.llm_spans["run1"]

    res = MagicMock()
    res.content = "response content"
    res.tool_calls = [1, 2]
    cb.on_llm_end("run1", res)

    span.set_attribute.assert_any_call("llm.response_length", len("response content"))
    span.set_attribute.assert_any_call("llm.tool_calls_count", 2)

def test_otel_tool_lifecycle(mock_tracer):
    cb = OpenTelemetryCallback()
    kwargs = {"a": 1}
    cb.on_tool_start("run1", "search", kwargs)

    mock_tracer.start_span.assert_called_with("tool_search", context=ANY)

    cb.on_tool_end("run1", "search", "result string")
    span = mock_tracer.start_span.return_value
    span.set_attribute.assert_any_call("tool.result_length", len("result string"))

def test_otel_tool_error(mock_tracer):
    cb = OpenTelemetryCallback()
    cb.on_tool_start("run1", "bash", {})
    cb.on_tool_error("run1", "bash", "command failed")

    span = mock_tracer.start_span.return_value
    span.set_attribute.assert_any_call("tool.error", "command failed")
