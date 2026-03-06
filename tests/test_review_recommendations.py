"""Tests covering recommendations implemented from project review."""

import asyncio

import pytest

from src.agentframework.agent import Agent, AgentConfig
from src.agentframework.chat import ensure_provider_credentials as ensure_chat_provider_credentials
from src.agentframework.cli import ensure_provider_credentials as ensure_cli_provider_credentials
from src.agentframework.conversation import Message
from src.agentframework.providers import LLMProvider, LLMResponse, LLMToolCall
from src.agentframework.tool_runtime import execute_single_tool
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
    def __init__(self, responses):
        self.responses = list(responses)
        self.idx = 0

    async def chat(self, messages, tools=None, temperature=0.3):
        if self.idx < len(self.responses):
            response = self.responses[self.idx]
            self.idx += 1
            return response
        return LLMResponse(content="done")


class SummaryProvider(LLMProvider):
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
                tool_calls=[LLMToolCall(id="1", name="deny_tool", arguments={})],
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


@pytest.mark.asyncio
async def test_tool_failure_categories_surface():
    explode_tool = ExplodeTool()

    msg_exec, _ = await execute_single_tool(
        LLMToolCall(id="1", name="explode", arguments={}),
        {"explode": explode_tool},
    )
    assert msg_exec.error_category == "execution_error"

    msg_missing, _ = await execute_single_tool(
        LLMToolCall(id="2", name="missing", arguments={}),
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
    assert any(
        m["role"] == "system" and "summary: important context" in m["content"]
        for m in prepared
    )


@pytest.mark.parametrize(
    "provider,expected",
    [
        ("openai", "OPENAI_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
    ],
)
def test_provider_credential_errors_are_clear(provider, expected):
    with pytest.raises(SystemExit) as chat_err:
        ensure_chat_provider_credentials(provider, None)
    with pytest.raises(SystemExit) as cli_err:
        ensure_cli_provider_credentials(provider, None)

    assert expected in str(chat_err.value)
    assert expected in str(cli_err.value)
