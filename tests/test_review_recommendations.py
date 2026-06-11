"""Tests covering recommendations implemented from project review."""

import asyncio

import pytest

from src.agentframework.core import Agent, AgentConfig
from src.agentframework.providers import get_provider
from src.agentframework.conversation import Message
from src.agentframework.providers import LLMProvider, LLMResponse, LLMToolCall
from src.agentframework.core import execute_single_tool
from src.agentframework.tools import Tool, ToolResult


class DenyTool(Tool):
    def __init__(self):
        super().__init__(name="deny_tool", description="Always deny")

    async def execute(self, **kwargs):
        return ToolResult(error="Denied by policy")


class ExplodeTool(Tool):
    def __init__(self):
        super().__init__(name="explode", description="Always explode")

    async def execute(self, **kwargs):
        raise RuntimeError("boom")


class SequencedProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        self.responses = responses
        self.call_count = 0

    async def extract_structured(self, messages, response_model, temperature=0.3):
        return None

    async def chat(self, messages, tools=None, temperature=0.3):
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            return response
        return LLMResponse(content="done")


class SummaryProvider(LLMProvider):
    async def extract_structured(self, messages, response_model, temperature=0.3):
        return None

    async def chat(self, messages, tools=None, temperature=0.3):
        prompt = messages[-1]["content"]
        if "Summarize this conversation" in prompt:
            return LLMResponse(content="summary: important context")
        return LLMResponse(content="ok")


@pytest.mark.asyncio
async def test_safety_denial_then_recovery_flow():
    provider = SequencedProvider(
        [
            LLMResponse(
                content="Trying tool",
                tool_calls=[LLMToolCall(id="call_1", name="deny_tool", arguments={})],
            ),
            LLMResponse(content="Recovered after denial"),
        ]
    )
    agent = Agent(AgentConfig(tools=[DenyTool()], session_enabled=False), provider)

    output = await agent.run("do thing")

    assert output == "Recovered after denial"
    tool_messages = [m for m in agent.messages if m.role == "tool"]
    assert tool_messages
    assert tool_messages[0].error_category == "policy_denied"
    agent.close()


@pytest.mark.asyncio
async def test_tool_failure_categories_surface():
    explode_tool = ExplodeTool()

    msg_exec, _ = await execute_single_tool(
        LLMToolCall(id="call_1", name="explode", arguments={}),
        {"explode": explode_tool},
    )
    assert msg_exec.error_category == "execution_error"

    msg_missing, _ = await execute_single_tool(
        LLMToolCall(id="call_2", name="missing", arguments={}),
        {"explode": explode_tool},
    )
    assert msg_missing.error_category == "tool_not_found"


def test_context_summarization_content_included():
    provider = SummaryProvider()
    agent = Agent(
        AgentConfig(
            tools=[],
            session_enabled=False,
            max_context_chars=20,
            max_context_messages=12,
        ),
        provider,
    )
    for i in range(40):
        agent.messages.append(Message(role="user", content=f"long message {i} " * 20))

    prepared = asyncio.run(agent._prepare_messages(agent.messages))

    # With lazy summarization, messages are truncated but no summary is added yet
    # The dropped messages are stored in _pending_summary for background processing
    assert len(prepared) <= 12  # Truncated to max_context_messages
    assert (
        agent._pending_summary is not None
    )  # Dropped messages captured for background summarization

    agent.close()


@pytest.mark.parametrize(
    "provider,expected",
    [
        ("openai", "OPENAI_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
    ],
)
def test_provider_credential_errors_are_clear(provider, expected, monkeypatch):
    monkeypatch.delenv(expected, raising=False)
    with pytest.raises(ValueError) as err:
        get_provider(provider, model="some_model")

    assert expected in str(err.value)
