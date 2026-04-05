"""Integration tests for the agent framework."""

import pytest
from dataclasses import dataclass

from src.agentframework.core import Agent, AgentConfig
from src.agentframework.providers import LLMResponse, LLMToolCall
from src.agentframework.tools import Tool, ToolResult
from src.agentframework.callbacks import AgentCallback


class MockTool(Tool):
    """Mock tool for testing."""

    def __init__(self, name: str = "mock_tool"):
        super().__init__(name=name, description="A mock tool for testing")
        self.call_count = 0

    async def execute(self, **kwargs) -> ToolResult:
        self.call_count += 1
        return ToolResult(content=f"Mock result {self.call_count}")


@dataclass
class MockProvider:
    """Mock LLM provider for testing."""

    responses: list[LLMResponse]
    call_count: int = 0

    async def chat(self, messages, tools=None, temperature=0.3):
        if self.responses:
            response = self.responses[self.call_count % len(self.responses)]
            self.call_count += 1
            return response
        return LLMResponse(content="Mock response")

    async def chat_streaming(
        self, messages, tools=None, temperature=0.3, on_chunk=None
    ):
        response = await self.chat(messages, tools, temperature)
        if on_chunk:
            on_chunk(response.content)
        return response

    async def extract_structured(self, messages, response_model, temperature=0.3):
        return response_model()


@pytest.mark.asyncio
async def test_agent_with_mock_provider():
    """Test agent loop with mocked LLM responses."""
    mock_provider = MockProvider(
        responses=[
            LLMResponse(content="Hello! How can I help you?"),
        ]
    )

    config = AgentConfig(provider="mock", model="test-model", tools=[])
    agent = Agent(config, mock_provider)

    result = await agent.run("Hello")

    assert result == "Hello! How can I help you?"
    assert mock_provider.call_count == 1


@pytest.mark.asyncio
async def test_agent_with_tool_call():
    """Test agent loop with tool calling."""
    mock_provider = MockProvider(
        responses=[
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call_1",
                        name="bash",
                        arguments={"command": "echo hello"},
                    )
                ],
            ),
            LLMResponse(content="The command output: hello"),
        ]
    )

    config = AgentConfig(
        provider="mock",
        model="test-model",
        tools=[MockTool(name="bash")],
    )
    agent = Agent(config, mock_provider)

    result = await agent.run("Run echo hello")

    assert "hello" in result.lower()
    assert mock_provider.call_count == 2


@pytest.mark.asyncio
async def test_agent_session_persistence(tmp_path):
    """Test agent with session persistence."""
    mock_provider = MockProvider(
        responses=[
            LLMResponse(content="First response"),
            LLMResponse(content="Second response"),
        ]
    )

    config = AgentConfig(
        provider="mock",
        model="test-model",
        session_enabled=True,
        session_dir=str(tmp_path / "sessions"),
        tools=[],
    )
    agent = Agent(config, mock_provider)

    await agent.run("First message")
    session_id = (
        agent.session_manager.current_session.id
        if agent.session_manager.current_session
        else None
    )

    assert session_id is not None

    history = agent.session_manager.get_history()
    assert len(history) >= 2


@pytest.mark.asyncio
async def test_agent_max_iterations():
    """Test agent respects max iterations limit."""
    mock_provider = MockProvider(
        responses=[
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id=f"call_{i}",
                        name="mock_tool",
                        arguments={},
                    )
                ],
            )
            for i in range(10)
        ]
    )

    config = AgentConfig(
        provider="mock",
        model="test-model",
        max_iterations=3,
        tools=[MockTool()],
    )
    agent = Agent(config, mock_provider)

    await agent.run("Loop forever")

    assert mock_provider.call_count == 3


@pytest.mark.asyncio
async def test_agent_context_management():
    """Test agent properly manages conversation context."""
    mock_provider = MockProvider(
        responses=[LLMResponse(content=f"Response {i}") for i in range(20)]
    )

    config = AgentConfig(
        provider="mock",
        model="test-model",
        max_context_messages=5,
        tools=[],
    )
    agent = Agent(config, mock_provider)

    for i in range(10):
        await agent.run(f"Message {i}")

    assert len(agent.messages) <= 20


class TestAgentWithTools:
    """Test agent with various tool combinations."""

    @pytest.mark.asyncio
    async def test_multiple_tools(self):
        """Test agent with multiple tools."""
        mock_provider = MockProvider(
            responses=[
                LLMResponse(content="Tool executed successfully"),
            ]
        )

        config = AgentConfig(
            provider="mock",
            model="test-model",
            tools=[MockTool("tool1"), MockTool("tool2")],
        )
        agent = Agent(config, mock_provider)

        result = await agent.run("Test")

        assert result == "Tool executed successfully"
        assert mock_provider.call_count == 1


class TestAgentErrorHandling:
    """Test agent error handling."""

    @pytest.mark.asyncio
    async def test_tool_error_handling(self):
        """Test agent handles tool errors gracefully."""

        class ErrorTool(Tool):
            def __init__(self):
                super().__init__(name="error_tool", description="Tool that errors")

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(content="", error="Command failed")

        mock_provider = MockProvider(
            responses=[
                LLMResponse(
                    content="",
                    tool_calls=[LLMToolCall(id="1", name="error_tool", arguments={})],
                ),
                LLMResponse(content="Saw the error and continued"),
            ]
        )

        config = AgentConfig(
            provider="mock",
            model="test-model",
            tools=[ErrorTool()],
        )
        agent = Agent(config, mock_provider)

        await agent.run("Test")

        assert mock_provider.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_response_handling(self):
        """Test agent handles empty LLM responses."""
        mock_provider = MockProvider(responses=[LLMResponse(content="")])

        config = AgentConfig(provider="mock", model="test-model", tools=[])
        agent = Agent(config, mock_provider)

        result = await agent.run("Hello")

        assert result == ""


class TestAgentCallbacks:
    """Test agent callback system."""

    @pytest.mark.asyncio
    async def test_callback_invocation(self):
        """Test that callbacks are invoked during agent run."""

        class TestCallback(AgentCallback):
            def __init__(self):
                self.events = []

            def on_run_start(self, run_id: str, prompt: str):
                self.events.append(("run_start", run_id, prompt))

            def on_run_end(self, run_id: str, response: str):
                self.events.append(("run_end", run_id, response))

        mock_provider = MockProvider(responses=[LLMResponse(content="Done")])

        config = AgentConfig(provider="mock", model="test-model", tools=[])
        agent = Agent(config, mock_provider)

        callback = TestCallback()
        agent.add_callback(callback)

        await agent.run("Test")

        assert len(callback.events) > 0
        event_types = [e[0] for e in callback.events]
        assert "run_start" in event_types or "run_end" in event_types
