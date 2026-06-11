import time

from src.agentframework.core import CallbackManager, AgentCallback
from src.agentframework.core.callbacks import BasicTracerCallback


class RecordingCallback(AgentCallback):
    def __init__(self):
        self.events = []

    def on_run_start(self, run_id, prompt):
        self.events.append(("run_start", run_id, prompt))

    def on_run_end(self, run_id, response):
        self.events.append(("run_end", run_id, response))

    def on_run_error(self, run_id, error):
        self.events.append(("run_error", run_id, str(error)))

    def on_llm_start(self, run_id, messages):
        self.events.append(("llm_start", run_id, messages))

    def on_llm_end(self, run_id, response):
        self.events.append(("llm_end", run_id, response))

    def on_tool_start(self, run_id, tool_name, tool_kwargs):
        self.events.append(("tool_start", run_id, tool_name, tool_kwargs))

    def on_tool_end(self, run_id, tool_name, result):
        self.events.append(("tool_end", run_id, tool_name, result))

    def on_tool_error(self, run_id, tool_name, error):
        self.events.append(("tool_error", run_id, tool_name, error))


def test_callback_manager_broadcasts_all_events():
    cb = RecordingCallback()
    manager = CallbackManager([cb])

    manager.on_run_start("run-1", "hello")
    manager.on_llm_start("run-1", [{"role": "user", "content": "hello"}])
    manager.on_tool_start("run-1", "search", {"query": "python"})
    manager.on_tool_end("run-1", "search", "done")
    manager.on_tool_error("run-1", "search", "failure")
    manager.on_llm_end("run-1", {"text": "ok"})
    manager.on_run_error("run-1", RuntimeError("boom"))
    manager.on_run_end("run-1", "response")

    assert cb.events == [
        ("run_start", "run-1", "hello"),
        ("llm_start", "run-1", [{"role": "user", "content": "hello"}]),
        ("tool_start", "run-1", "search", {"query": "python"}),
        ("tool_end", "run-1", "search", "done"),
        ("tool_error", "run-1", "search", "failure"),
        ("llm_end", "run-1", {"text": "ok"}),
        ("run_error", "run-1", "boom"),
        ("run_end", "run-1", "response"),
    ]


def test_callback_manager_add_callback_registers_later_listener():
    cb1 = RecordingCallback()
    cb2 = RecordingCallback()
    manager = CallbackManager([cb1])

    manager.add_callback(cb2)
    manager.on_run_start("run-2", "prompt")

    assert cb1.events == [("run_start", "run-2", "prompt")]
    assert cb2.events == [("run_start", "run-2", "prompt")]


def test_basic_tracer_callback_logs_with_elapsed_times(capsys):
    tracer = BasicTracerCallback()

    tracer.on_run_start("run-3", "prompt")
    tracer.on_llm_start("run-3", [])
    tracer.on_tool_start("run-3", "grep", {"pattern": "x"})

    time.sleep(0.01)

    tracer.on_llm_end("run-3", "response")
    tracer.on_tool_end("run-3", "grep", "result")
    tracer.on_run_end("run-3", "done")

    output = capsys.readouterr().out
    assert "[TRACER] Run run-3 started." in output
    assert "[TRACER] LLM generation completed in" in output
    assert "[TRACER] Tool 'grep' executed in" in output
    assert "[TRACER] Run run-3 completed in" in output


def test_basic_tracer_callback_ignores_end_events_without_starts(capsys):
    tracer = BasicTracerCallback()

    tracer.on_run_end("missing", "done")
    tracer.on_llm_end("missing", "response")
    tracer.on_tool_end("missing", "tool", "result")

    assert capsys.readouterr().out == ""
