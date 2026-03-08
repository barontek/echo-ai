"""OpenTelemetry integration for agent tracing."""

import json
from typing import Any
from opentelemetry import trace
from opentelemetry.trace.status import Status, StatusCode
from .callbacks import AgentCallback

class OpenTelemetryCallback(AgentCallback):
    """Callback that emits OpenTelemetry traces for agent execution."""

    def __init__(self, tracer_name: str = "echo-ai.agent"):
        self.tracer = trace.get_tracer(tracer_name)
        self.run_spans = {}
        self.llm_spans = {}
        self.tool_spans = {}

    def on_run_start(self, run_id: str, prompt: str) -> None:
        span = self.tracer.start_span("agent_run")
        span.set_attribute("run.id", run_id)
        span.set_attribute("run.prompt", prompt)
        self.run_spans[run_id] = span

    def on_run_end(self, run_id: str, response: str) -> None:
        if span := self.run_spans.pop(run_id, None):
            span.set_attribute("run.response", response)
            span.set_status(Status(StatusCode.OK))
            span.end()

    def on_run_error(self, run_id: str, error: Exception) -> None:
        if span := self.run_spans.pop(run_id, None):
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, str(error)))
            span.end()

    def on_llm_start(self, run_id: str, messages: list[dict[str, Any]]) -> None:
        # Link to the parent run span if available
        # Note: in a real implementation we might use a context manager
        # but here we span manually
        span = self.tracer.start_span("llm_chat")
        span.set_attribute("run.id", run_id)
        span.set_attribute("llm.messages_count", len(messages))
        self.llm_spans[run_id] = span

    def on_llm_end(self, run_id: str, response: Any) -> None:
        if span := self.llm_spans.pop(run_id, None):
            if hasattr(response, 'content'):
                span.set_attribute("llm.response_length", len(response.content or ""))
            if hasattr(response, 'tool_calls') and response.tool_calls:
                span.set_attribute("llm.tool_calls_count", len(response.tool_calls))
            span.set_status(Status(StatusCode.OK))
            span.end()

    def on_tool_start(self, run_id: str, tool_name: str, tool_kwargs: dict[str, Any]) -> None:
        span = self.tracer.start_span(f"tool_{tool_name}")
        span.set_attribute("run.id", run_id)
        span.set_attribute("tool.name", tool_name)

        # safely stringify kwargs
        try:
            span.set_attribute("tool.kwargs", json.dumps(tool_kwargs))
        except Exception:
            span.set_attribute("tool.kwargs", str(tool_kwargs))

        self.tool_spans[f"{run_id}_{tool_name}"] = span

    def on_tool_end(self, run_id: str, tool_name: str, result: str) -> None:
        key = f"{run_id}_{tool_name}"
        if span := self.tool_spans.pop(key, None):
            span.set_attribute("tool.result_length", len(result))
            span.set_status(Status(StatusCode.OK))
            span.end()

    def on_tool_error(self, run_id: str, tool_name: str, error: str) -> None:
        key = f"{run_id}_{tool_name}"
        if span := self.tool_spans.pop(key, None):
            span.set_attribute("tool.error", error)
            span.set_status(Status(StatusCode.ERROR, error))
            span.end()
