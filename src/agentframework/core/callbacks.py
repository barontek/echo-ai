"""Event callback system for observability and tracing."""

from abc import ABC
from typing import Any
import time

class AgentCallback(ABC):
    """Base class for agent event callbacks.

    Implement this interface to hook into the agent's execution lifecycle
    for logging, tracing (e.g., OpenTelemetry), or UI updates.
    """

    def on_run_start(self, run_id: str, prompt: str) -> None:
        """Called when a new run begins."""
        pass

    def on_run_end(self, run_id: str, response: str) -> None:
        """Called when a run completes successfully."""
        pass

    def on_run_error(self, run_id: str, error: Exception) -> None:
        """Called when a run fails."""
        pass

    def on_llm_start(self, run_id: str, messages: list[dict[str, Any]]) -> None:
        """Called before sending a request to the LLM."""
        pass

    def on_llm_end(self, run_id: str, response: Any) -> None:
        """Called after receiving a response from the LLM."""
        pass

    def on_tool_start(self, run_id: str, tool_name: str, tool_kwargs: dict[str, Any]) -> None:
        """Called before a tool executes."""
        pass

    def on_tool_end(self, run_id: str, tool_name: str, result: str) -> None:
        """Called after a tool executes successfully."""
        pass

    def on_tool_error(self, run_id: str, tool_name: str, error: str) -> None:
        """Called if a tool execution fails."""
        pass


class CallbackManager:
    """Manages publishing events to registered callbacks."""

    def __init__(self, callbacks: list[AgentCallback] | None = None):
        self.callbacks = callbacks or []

    def add_callback(self, callback: AgentCallback) -> None:
        self.callbacks.append(callback)

    def on_run_start(self, run_id: str, prompt: str) -> None:
        for cb in self.callbacks:
            cb.on_run_start(run_id, prompt)

    def on_run_end(self, run_id: str, response: str) -> None:
        for cb in self.callbacks:
            cb.on_run_end(run_id, response)

    def on_run_error(self, run_id: str, error: Exception) -> None:
        for cb in self.callbacks:
            cb.on_run_error(run_id, error)

    def on_llm_start(self, run_id: str, messages: list[dict[str, Any]]) -> None:
        for cb in self.callbacks:
            cb.on_llm_start(run_id, messages)

    def on_llm_end(self, run_id: str, response: Any) -> None:
        for cb in self.callbacks:
            cb.on_llm_end(run_id, response)

    def on_tool_start(self, run_id: str, tool_name: str, tool_kwargs: dict[str, Any]) -> None:
        for cb in self.callbacks:
            cb.on_tool_start(run_id, tool_name, tool_kwargs)

    def on_tool_end(self, run_id: str, tool_name: str, result: str) -> None:
        for cb in self.callbacks:
            cb.on_tool_end(run_id, tool_name, result)

    def on_tool_error(self, run_id: str, tool_name: str, error: str) -> None:
        for cb in self.callbacks:
            cb.on_tool_error(run_id, tool_name, error)


class BasicTracerCallback(AgentCallback):
    """A simple CLI tracer for measuring latency."""

    def __init__(self):
        self.run_starts = {}
        self.llm_starts = {}
        self.tool_starts = {}

    def on_run_start(self, run_id: str, prompt: str) -> None:
        self.run_starts[run_id] = time.time()
        print(f"[TRACER] Run {run_id} started.")

    def on_run_end(self, run_id: str, response: str) -> None:
        if run_id in self.run_starts:
            elapsed = time.time() - self.run_starts[run_id]
            print(f"[TRACER] Run {run_id} completed in {elapsed:.2f}s.")

    def on_llm_start(self, run_id: str, messages: list[dict[str, Any]]) -> None:
        self.llm_starts[run_id] = time.time()

    def on_llm_end(self, run_id: str, response: Any) -> None:
        if run_id in self.llm_starts:
            elapsed = time.time() - self.llm_starts[run_id]
            print(f"[TRACER] LLM generation completed in {elapsed:.2f}s.")

    def on_tool_start(self, run_id: str, tool_name: str, tool_kwargs: dict[str, Any]) -> None:
        self.tool_starts[f"{run_id}_{tool_name}"] = time.time()

    def on_tool_end(self, run_id: str, tool_name: str, result: str) -> None:
        key = f"{run_id}_{tool_name}"
        if key in self.tool_starts:
            elapsed = time.time() - self.tool_starts[key]
            print(f"[TRACER] Tool '{tool_name}' executed in {elapsed:.2f}s.")
