"""Integration tests for agent runtime flows."""

from src.agentframework.agent import Agent, AgentConfig, Message
from src.agentframework.providers import LLMProvider, LLMResponse, LLMToolCall
from src.agentframework.tools import Tool, ToolResult


class EchoTool(Tool):
    def __init__(self):
        super().__init__(name="echo_tool", description="echo")

    async def execute(self, text: str = "", **kwargs):
        return ToolResult(content=f"echo:{text}")


class SequenceProvider(LLMProvider):
    def __init__(self, responses):
        self.responses = responses
        self.i = 0

    async def chat(self, messages, tools=None, temperature=0.3):
        if self.i < len(self.responses):
            r = self.responses[self.i]
            self.i += 1
            return r
        return LLMResponse(content="done")


def test_tool_call_then_final_response_flow():
    provider = SequenceProvider([
        LLMResponse(content="", tool_calls=[LLMToolCall(id="1", name="echo_tool", arguments={"text": "hello"})]),
        LLMResponse(content="Final summary"),
    ])
    agent = Agent(AgentConfig(tools=[EchoTool()], session_enabled=False), provider)

    import asyncio
    out = asyncio.run(agent.run("do thing"))
    assert out == "Final summary"
    assert any(m.role == "tool" and "echo:hello" in m.content for m in agent.messages)


def test_context_summarization_path_runs_when_budget_small():
    provider = SequenceProvider([LLMResponse(content="ok")])
    agent = Agent(AgentConfig(tools=[], session_enabled=False, max_context_chars=20, max_context_messages=10), provider)
    for i in range(30):
        agent.messages.append(Message(role="user", content=f"message {i} " * 20))

    import asyncio
    prepared = asyncio.run(agent._prepare_messages(agent.messages))
    assert len(prepared) > 0


def test_session_save_load_and_undo_redo(tmp_path):
    provider = SequenceProvider([LLMResponse(content="ok")])
    session_dir = tmp_path / "sessions"
    agent = Agent(AgentConfig(tools=[], session_enabled=True, session_dir=str(session_dir)), provider)

    target = tmp_path / "x.txt"
    target.write_text("before")
    agent.change_tracker.record_change("write", str(target), "before", "after")
    assert "Undid write" in agent.undo()
    assert target.read_text() == "before"
    assert "Redid write" in agent.redo()
    assert target.read_text() == "after"

    agent.add_user_message("hi")
    saved = agent.save_session("t1")
    assert "t1" in saved

    agent.messages = []
    loaded = agent.load_session("t1")
    assert "loaded" in loaded.lower()
    assert agent.messages
