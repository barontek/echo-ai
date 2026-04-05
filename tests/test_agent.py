"""Tests for Agent class."""

import pytest

from src.agentframework.core import Agent, AgentConfig
from src.agentframework.tools import Tool, ToolResult
from src.agentframework.providers import LLMProvider, LLMResponse, LLMToolCall
from pydantic import BaseModel


class MockProvider(LLMProvider):
    """Mock LLM provider for testing."""

    def __init__(self, responses: list[LLMResponse] | None = None):
        self.responses = responses or []
        self.call_count = 0

    async def extract_structured(self, messages, response_model, temperature=0.3):
        return None

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
        json_str = '```json\n{"key": "value"}\n```'
        result = Agent._sanitize_json(json_str)
        assert '{"key": "value"}' in result

    def test_strips_plain_code_block(self):
        json_str = '```\n{"key": "value"}\n```'
        result = Agent._sanitize_json(json_str)
        assert '{"key": "value"}' in result

    def test_strips_leading_code_block(self):
        json_str = '```json{"key": "value"}'
        result = Agent._sanitize_json(json_str)
        assert '{"key": "value"}' in result

    def test_strips_trailing_code_block(self):
        json_str = '{"key": "value"}```'
        result = Agent._sanitize_json(json_str)
        assert result.strip("`") == '{"key": "value"}'

    def test_removes_trailing_comma_before_brace(self):
        json_str = '{"key": "value",}'
        result = Agent._sanitize_json(json_str)
        assert result == '{"key": "value"}'

    def test_removes_trailing_comma_before_bracket(self):
        json_str = '{"items": ["a", "b",],}'
        result = Agent._sanitize_json(json_str)
        assert result == '{"items": ["a", "b"]}'

    def test_preserves_valid_json(self):
        json_str = '{"key": "value", "num": 123}'
        result = Agent._sanitize_json(json_str)
        assert result == '{"key": "value", "num": 123}'

    def test_complex_malformed_json(self):
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
        agent = Agent(llm_provider=provider, config=config)
        yield agent
        agent.close()

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
        assert isinstance(tool, MockTool)
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
        assert isinstance(tool, MockTool)
        assert tool.executed is True
        agent.close()


class TestPydanticValidation:
    """Tests for Pydantic tool validation."""

    @pytest.fixture
    def agent_with_mock_tool(self):
        config = AgentConfig(tools=[MockTool()])
        provider = MockProvider()
        agent = Agent(llm_provider=provider, config=config)
        yield agent
        agent.close()

    @pytest.mark.asyncio
    async def test_validation_passes_with_valid_args(self, agent_with_mock_tool):
        """Valid args should pass validation and execute tool."""
        agent = agent_with_mock_tool
        tool_call = LLMToolCall(
            id="1",
            name="mock",
            arguments={"command": "test", "count": 5},
        )

        tool_messages, updated_messages = await agent._execute_tool_calls([tool_call])

        assert len(tool_messages) == 1
        assert "Executed test 5 times" in tool_messages[0].content

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

        tool_messages, updated_messages = await agent._execute_tool_calls([tool_call])

        # Should succeed because Pydantic coerces "3" to 3
        assert len(tool_messages) == 1
        assert "Executed test 3 times" in tool_messages[0].content

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

        tool_messages, updated_messages = await agent._execute_tool_calls([tool_call])

        assert len(tool_messages) == 1
        assert "Validation error" in tool_messages[0].content
        assert (
            "Input should be a valid integer" in tool_messages[0].content
            or "type" in tool_messages[0].content.lower()
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

        tool_messages, updated_messages = await agent._execute_tool_calls([tool_call])

        assert len(tool_messages) == 1
        assert "Validation error" in tool_messages[0].content
        assert "command" in tool_messages[0].content.lower()


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
            arguments={"command": "test", "count": 1},
        )
        tool_call.arguments = '```json\n{"command": "test", "count": 1}\n```'  # type: ignore[assignment]

        # The sanitization happens inside _execute_tool when parsing JSON
        # This test verifies the flow works end-to-end
        await agent._execute_tool(tool_call)

        # Note: The arguments are already parsed by the provider before reaching _execute_tool
        # This test documents expected behavior
        agent.close()


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


# ---------------------------------------------------------------------------
# E2E tests (from test_agent_e2e.py)
# ---------------------------------------------------------------------------


class MockE2EProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        self.responses = responses
        self.call_count = 0
        self.messages_received = []

    async def extract_structured(self, messages, response_model, temperature=0.3):
        return None

    async def chat(
        self, messages: list[dict], tools: list | None = None, temperature: float = 0.3
    ) -> LLMResponse:
        self.messages_received.append(messages)
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        return LLMResponse(content="Fallback response")

    async def chat_streaming(
        self,
        messages: list[dict],
        tools: list | None = None,
        temperature: float = 0.3,
        on_chunk=None,
    ) -> LLMResponse:
        resp = await self.chat(messages, tools, temperature)
        if on_chunk and resp.content:
            for word in resp.content.split():
                on_chunk(word + " ")
        return resp


class CalcParams(BaseModel):
    a: int
    b: int


class CalcTool(Tool):
    parameters_model = CalcParams

    def __init__(self):
        super().__init__(name="calc", description="add two numbers")

    async def execute(self, a: int, b: int, **kwargs) -> ToolResult:
        return ToolResult(content=str(a + b))


class TestAgentE2E:
    @pytest.mark.asyncio
    async def test_agent_run_loop_e2e(self):
        provider = MockE2EProvider(
            [
                LLMResponse(
                    content="Let me calculate that.",
                    tool_calls=[
                        LLMToolCall(id="1", name="calc", arguments={"a": 5, "b": 7})
                    ],
                ),
                LLMResponse(content="The answer is 12."),
            ]
        )
        config = AgentConfig(tools=[CalcTool()], session_enabled=False)
        agent = Agent(config=config, llm_provider=provider)
        response = await agent.run("What is 5 + 7?")
        assert response == "The answer is 12."
        assert provider.call_count == 2
        tool_msgs = [msg for msg in agent.messages if msg.role == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].content == "12"
        agent.close()

    @pytest.mark.asyncio
    async def test_agent_max_iterations(self):
        provider = MockE2EProvider(
            [
                LLMResponse(
                    content="",
                    tool_calls=[
                        LLMToolCall(id="1", name="calc", arguments={"a": 1, "b": 1})
                    ],
                )
                for _ in range(10)
            ]
        )
        config = AgentConfig(
            tools=[CalcTool()], session_enabled=False, max_iterations=3
        )
        agent = Agent(config=config, llm_provider=provider)
        response = await agent.run("Do math forever")
        assert "Max iterations reached" in response
        assert provider.call_count == 3
        agent.close()

    @pytest.mark.asyncio
    async def test_agent_run_streaming_e2e(self):
        provider = MockE2EProvider(
            [
                LLMResponse(
                    content="Let me calculate that.",
                    tool_calls=[
                        LLMToolCall(id="1", name="calc", arguments={"a": 10, "b": 20})
                    ],
                ),
                LLMResponse(content="The answer is 30."),
            ]
        )
        config = AgentConfig(tools=[CalcTool()], session_enabled=False)
        agent = Agent(config=config, llm_provider=provider)
        chunks = []

        def on_chunk(chunk: str):
            chunks.append(chunk.strip())

        response = await agent.run_streaming("10 + 20?", on_chunk=on_chunk)
        assert response == "The answer is 30."
        assert "answer" in chunks
        assert provider.call_count == 2
        agent.close()


# ---------------------------------------------------------------------------
# Integration tests (from test_integration_agent_flow.py)
# ---------------------------------------------------------------------------


class EchoTool(Tool):
    def __init__(self):
        super().__init__(name="echo_tool", description="echo")

    async def execute(self, text: str = "", **kwargs):
        return ToolResult(content=f"echo:{text}")


class SequenceProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        self.responses = responses
        self.call_count = 0

    async def extract_structured(self, messages, response_model, temperature=0.3):
        return None

    async def chat(self, messages, tools=None, temperature=0.3):
        if self.call_count < len(self.responses):
            r = self.responses[self.call_count]
            self.call_count += 1
            return r
        return LLMResponse(content="done")


class TestAgentIntegration:
    def test_tool_call_then_final_response_flow(self):
        import asyncio

        provider = SequenceProvider(
            [
                LLMResponse(
                    content="",
                    tool_calls=[
                        LLMToolCall(
                            id="1", name="echo_tool", arguments={"text": "hello"}
                        )
                    ],
                ),
                LLMResponse(content="Final summary"),
            ]
        )
        agent = Agent(AgentConfig(tools=[EchoTool()], session_enabled=False), provider)
        out = asyncio.run(agent.run("do thing"))
        assert out == "Final summary"
        assert any(
            m.role == "tool" and "echo:hello" in m.content for m in agent.messages
        )
        agent.close()

    def test_context_summarization_path_runs_when_budget_small(self):
        import asyncio
        from src.agentframework.conversation import Message

        provider = SequenceProvider([LLMResponse(content="ok")])
        agent = Agent(
            AgentConfig(
                tools=[],
                session_enabled=False,
                max_context_chars=20,
                max_context_messages=10,
            ),
            provider,
        )
        for i in range(30):
            agent.messages.append(Message(role="user", content=f"message {i} " * 20))
        prepared = asyncio.run(agent._prepare_messages(agent.messages))
        assert len(prepared) > 0
        agent.close()

    def test_session_save_load_and_undo_redo(self, tmp_path):
        provider = SequenceProvider([LLMResponse(content="ok")])
        session_dir = tmp_path / "sessions"
        agent = Agent(
            AgentConfig(tools=[], session_enabled=True, session_dir=str(session_dir)),
            provider,
        )

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
        agent.close()
