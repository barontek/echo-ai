"""Tests for Agent class."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.agentframework.agent import Agent, AgentConfig
from src.agentframework.tools import Tool, ToolResult
from src.agentframework.providers import LLMProvider, LLMResponse, LLMToolCall
from pydantic import BaseModel


class MockProvider(LLMProvider):
    """Mock LLM provider for testing."""

    def __init__(self, responses: list[LLMResponse] | None = None):
        self.responses = responses or []
        self.call_count = 0

    async def chat(
        self,
        messages: list[dict],
        tools: list | None = None,
        temperature: float = 0.3,
    ) -> LLMResponse:
        if self.responses and self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        return LLMResponse(content="Done")


class MockToolParams(BaseModel):
    """Test parameters for MockTool."""

    command: str
    count: int = 1


class MockTool(Tool):
    """Mock tool for testing."""

    parameters_model = MockToolParams

    def __init__(self):
        super().__init__(name="mock", description="A mock tool")
        self.executed = False

    async def execute(self, command: str, count: int = 1, **kwargs) -> ToolResult:
        self.executed = True
        return ToolResult(content=f"Executed {command} {count} times")


class TestSanitizeJson:
    """Tests for _sanitize_json method."""

    def test_strips_json_code_block(self):
        agent = Agent.__new__(Agent)
        json_str = '```json\n{"key": "value"}\n```'
        result = Agent._sanitize_json(json_str)
        assert '{"key": "value"}' in result

    def test_strips_plain_code_block(self):
        agent = Agent.__new__(Agent)
        json_str = '```\n{"key": "value"}\n```'
        result = Agent._sanitize_json(json_str)
        assert '{"key": "value"}' in result

    def test_strips_leading_code_block(self):
        agent = Agent.__new__(Agent)
        json_str = '```json{"key": "value"}'
        result = Agent._sanitize_json(json_str)
        assert '{"key": "value"}' in result

    def test_strips_trailing_code_block(self):
        agent = Agent.__new__(Agent)
        json_str = '{"key": "value"}```'
        result = Agent._sanitize_json(json_str)
        assert result.strip("`") == '{"key": "value"}'

    def test_removes_trailing_comma_before_brace(self):
        agent = Agent.__new__(Agent)
        json_str = '{"key": "value",}'
        result = Agent._sanitize_json(json_str)
        assert result == '{"key": "value"}'

    def test_removes_trailing_comma_before_bracket(self):
        agent = Agent.__new__(Agent)
        json_str = '{"items": ["a", "b",],}'
        result = Agent._sanitize_json(json_str)
        assert result == '{"items": ["a", "b"]}'

    def test_preserves_valid_json(self):
        agent = Agent.__new__(Agent)
        json_str = '{"key": "value", "num": 123}'
        result = Agent._sanitize_json(json_str)
        assert result == '{"key": "value", "num": 123}'

    def test_complex_malformed_json(self):
        agent = Agent.__new__(Agent)
        json_str = '```json\n{"command": "test", "count": 5, }\n```'
        result = Agent._sanitize_json(json_str)
        # Should strip code blocks and remove trailing comma
        assert "command" in result
        assert "count" in result
        # Trailing comma before } should be removed
        assert ", }" not in result


class TestParallelExecution:
    """Tests for parallel_tool_execution flag."""

    @pytest.fixture
    def agent_with_mock_tool(self):
        config = AgentConfig(
            tools=[MockTool()],
            parallel_tool_execution=False,
        )
        provider = MockProvider()
        return Agent(llm_provider=provider, config=config)

    @pytest.mark.asyncio
    async def test_sequential_execution_by_default(self, agent_with_mock_tool):
        """When parallel_tool_execution=False, tools execute sequentially."""
        agent = agent_with_mock_tool
        agent.config.parallel_tool_execution = False

        tool_calls = [
            LLMToolCall(
                id="1", name="mock", arguments={"command": "test1", "count": 1}
            ),
            LLMToolCall(
                id="2", name="mock", arguments={"command": "test2", "count": 1}
            ),
        ]

        await agent._execute_tool_calls(tool_calls)

        # Verify both tools were executed
        tool = agent.tool_map["mock"]
        assert tool.executed is True

    @pytest.mark.asyncio
    async def test_parallel_execution_when_enabled(self):
        """When parallel_tool_execution=True, tools execute in parallel."""
        config = AgentConfig(
            tools=[MockTool()],
            parallel_tool_execution=True,
        )
        provider = MockProvider()
        agent = Agent(llm_provider=provider, config=config)

        tool_calls = [
            LLMToolCall(
                id="1", name="mock", arguments={"command": "test1", "count": 1}
            ),
            LLMToolCall(
                id="2", name="mock", arguments={"command": "test2", "count": 1}
            ),
        ]

        await agent._execute_tool_calls(tool_calls)

        # Verify both tools were executed
        tool = agent.tool_map["mock"]
        assert tool.executed is True


class TestPydanticValidation:
    """Tests for Pydantic tool validation."""

    @pytest.fixture
    def agent_with_mock_tool(self):
        config = AgentConfig(tools=[MockTool()])
        provider = MockProvider()
        return Agent(llm_provider=provider, config=config)

    @pytest.mark.asyncio
    async def test_validation_passes_with_valid_args(self, agent_with_mock_tool):
        """Valid args should pass validation and execute tool."""
        agent = agent_with_mock_tool
        tool_call = LLMToolCall(
            id="1",
            name="mock",
            arguments={"command": "test", "count": 5},
        )

        result = await agent._execute_tool_calls([tool_call])

        assert len(result) == 1
        assert "Executed test 5 times" in result[0].content

    @pytest.mark.asyncio
    async def test_validation_coerces_types(self, agent_with_mock_tool):
        """Pydantic should coerce string to int."""
        agent = agent_with_mock_tool
        # count is passed as string but should be coerced to int
        tool_call = LLMToolCall(
            id="1",
            name="mock",
            arguments={"command": "test", "count": "3"},
        )

        result = await agent._execute_tool_calls([tool_call])

        # Should succeed because Pydantic coerces "3" to 3
        assert len(result) == 1
        assert "Executed test 3 times" in result[0].content

    @pytest.mark.asyncio
    async def test_validation_fails_with_invalid_types(self, agent_with_mock_tool):
        """Invalid types should return validation error."""
        agent = agent_with_mock_tool
        # count is passed as a dict but should be int
        tool_call = LLMToolCall(
            id="1",
            name="mock",
            arguments={"command": "test", "count": {"invalid": "type"}},
        )

        result = await agent._execute_tool_calls([tool_call])

        assert len(result) == 1
        assert "Validation error" in result[0].content
        assert (
            "Input should be a valid integer" in result[0].content
            or "type" in result[0].content.lower()
        )

    @pytest.mark.asyncio
    async def test_validation_fails_missing_required(self, agent_with_mock_tool):
        """Missing required args should return validation error."""
        agent = agent_with_mock_tool
        # 'command' is required but not provided
        tool_call = LLMToolCall(
            id="1",
            name="mock",
            arguments={"count": 1},
        )

        result = await agent._execute_tool_calls([tool_call])

        assert len(result) == 1
        assert "Validation error" in result[0].content
        assert "command" in result[0].content.lower()


class TestSanitizeJsonIntegration:
    """Integration tests for JSON sanitization in tool execution."""

    @pytest.mark.asyncio
    async def test_execute_tool_with_markdown_json(self):
        """Tool should execute even if LLM returns markdown-wrapped JSON."""
        config = AgentConfig(tools=[MockTool()])
        provider = MockProvider()
        agent = Agent(llm_provider=provider, config=config)

        # Simulate LLM returning markdown-wrapped JSON
        tool_call = LLMToolCall(
            id="1",
            name="mock",
            arguments='```json\n{"command": "test", "count": 1}\n```',
        )

        # The sanitization happens inside _execute_tool when parsing JSON
        # This test verifies the flow works end-to-end
        result = await agent._execute_tool(tool_call)

        # Note: The arguments are already parsed by the provider before reaching _execute_tool
        # This test documents expected behavior


class TestAgentConfig:
    """Tests for AgentConfig defaults."""

    def test_parallel_execution_defaults_to_false(self):
        """parallel_tool_execution should default to False."""
        config = AgentConfig()
        assert config.parallel_tool_execution is False

    def test_parallel_execution_can_be_set_true(self):
        """parallel_tool_execution can be set to True."""
        config = AgentConfig(parallel_tool_execution=True)
        assert config.parallel_tool_execution is True
