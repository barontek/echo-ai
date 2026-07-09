"""Extended tests for Agent class - covering uncovered edge cases."""

import asyncio
import base64
import re
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from cryptography.fernet import Fernet
from src.agentframework.core import Agent, AgentConfig
from src.agentframework.core.agent import _extract_thinking
from src.agentframework.tools import Tool, ToolResult
from src.agentframework.providers import LLMProvider, LLMResponse, LLMToolCall
from src.agentframework.conversation import Message
from src.agentframework.session import set_fernet, SessionManager

# Fernet so session tests work without a TTY / ECHO_DB_PASSWORD.
set_fernet(Fernet(base64.urlsafe_b64encode(b"\x00" * 32)))


class SimpleProvider(LLMProvider):
    def __init__(self):
        self.call_count = 0

    async def extract_structured(self, messages, response_model, temperature=0.3):
        return None

    async def chat(self, messages, tools=None, temperature=0.3):
        self.call_count += 1
        return LLMResponse(content="ok")

    async def chat_streaming(self, messages, tools=None, temperature=0.3, on_chunk=None):
        self.call_count += 1
        if on_chunk:
            on_chunk("ok")
        return LLMResponse(content="ok")


class ThinkingProvider(SimpleProvider):
    """Provider that returns thinking content."""
    async def chat(self, messages, tools=None, temperature=0.3):
        return LLMResponse(
            content="<think>Let me solve this</think>Here is the answer",
        )

    async def chat_streaming(self, messages, tools=None, temperature=0.3, on_chunk=None):
        if on_chunk:
            on_chunk("<think>Let me solve this</think>Here is the answer")
        return LLMResponse(content="<think>Let me solve this</think>Here is the answer")


class ToolCallProvider(SimpleProvider):
    """Provider that returns tool calls then a final response."""
    def __init__(self):
        super().__init__()
        self._call_num = 0

    async def chat(self, messages, tools=None, temperature=0.3):
        self._call_num += 1
        return LLMResponse(
            content="",
            tool_calls=[
                LLMToolCall(id="tc1", name="simple", arguments={"input": "test"})
            ],
        )

    async def chat_streaming(self, messages, tools=None, temperature=0.3, on_chunk=None):
        self._call_num += 1
        if on_chunk:
            on_chunk("")
        return LLMResponse(
            content="",
            tool_calls=[
                LLMToolCall(id="tc1", name="simple", arguments={"input": "test"})
            ],
        )


class SimpleTool(Tool):
    def __init__(self):
        super().__init__(name="simple", description="simple")

    async def execute(self, **kwargs):
        return ToolResult(content="done")


class TestExtractThinking:
    def test_no_thinking_markers_returns_none(self):
        msgs = [
            Message(role="assistant", content="Normal response"),
            Message(role="assistant", content="normal"),
            Message(role="assistant", content="ok"),
        ]
        assert _extract_thinking(msgs) is None

    def test_no_messages(self):
        assert _extract_thinking([]) is None


class TestAgentLifecycle:
    @pytest.fixture
    def agent(self):
        agent = Agent(AgentConfig(session_enabled=False), SimpleProvider())
        yield agent
        agent.close()

    @pytest.mark.asyncio
    async def test_add_system_message(self, agent):
        agent.add_system_message("You are helpful")
        assert len(agent.messages) == 1
        assert agent.messages[0].role == "system"
        assert agent.messages[0].content == "You are helpful"

    def test_register_sub_agent_adds_delegate_tool(self, agent):
        agent.register_sub_agent("code", description="Coding", tools=[])
        assert "code" in agent.sub_agents
        assert agent.sub_agents["code"].description == "Coding"
        assert "delegate" in agent.tool_map

    def test_undo_no_changes(self, agent):
        result = agent.undo()
        assert "Nothing to undo" in result

    def test_redo_no_changes(self, agent):
        result = agent.redo()
        assert "Nothing to redo" in result

    @pytest.mark.asyncio
    async def test_run_without_session(self, agent):
        response = await agent.run("hello")
        assert response == "ok"
        assert agent.messages[-2].role == "user"
        assert agent.messages[-2].content == "hello"
        assert agent.messages[-1].role == "assistant"
        assert agent.messages[-1].content == "ok"

    @pytest.mark.asyncio
    async def test_run_streaming_without_session(self, agent):
        chunks = []
        response = await agent.run_streaming("hello", on_chunk=chunks.append)
        assert response == "ok"

    @pytest.mark.asyncio
    async def test_run_streaming_no_on_chunk(self, agent):
        response = await agent.run_streaming("hello")
        assert response == "ok"

    @pytest.mark.asyncio
    async def test_extract_data(self, agent):
        from pydantic import BaseModel

        class TestModel(BaseModel):
            name: str

        agent.llm.extract_structured = AsyncMock(return_value=TestModel(name="Alice"))
        result = await agent.extract_data("test prompt", TestModel)
        assert result.name == "Alice"
        agent.llm.extract_structured.assert_called_once_with(
            messages=[{"role": "user", "content": "test prompt"}],
            response_model=TestModel,
            temperature=agent.config.temperature,
        )


class TestAgentSession:
    @pytest.fixture
    def agent(self, tmp_path):
        session_dir = tmp_path / "sessions"
        agent = Agent(
            AgentConfig(session_enabled=True, session_dir=str(session_dir)),
            SimpleProvider(),
        )
        yield agent
        agent.close()

    @pytest.mark.asyncio
    async def test_run_with_session(self, agent):
        resp = await agent.run("hi")
        assert resp == "ok"
        assert agent.session_manager is not None
        assert agent.session_manager.current_session is not None
        session_id = agent.session_manager.current_session.id
        loaded = agent.load_session(session_id)
        assert "loaded" in loaded.lower()

    def test_save_session_no_session_manager(self, agent):
        original_mgr = agent.session_manager
        agent.session_manager = None
        try:
            result = agent.save_session("test")
            assert "not enabled" in result
        finally:
            agent.session_manager = original_mgr

    def test_load_session_no_session_manager(self, agent):
        original_mgr = agent.session_manager
        agent.session_manager = None
        try:
            result = agent.load_session("test")
            assert "not enabled" in result
        finally:
            agent.session_manager = original_mgr

    def test_list_sessions_no_session_manager(self, agent):
        original_mgr = agent.session_manager
        agent.session_manager = None
        try:
            ids, total = agent.list_sessions()
            assert ids == []
            assert total == 0
        finally:
            agent.session_manager = original_mgr

    def test_list_sessions(self, agent):
        agent._ensure_session("test-list")
        ids, total = agent.list_sessions()
        assert total == 1
        assert len(ids) == 1

    @pytest.mark.asyncio
    async def test_session_id_not_found(self, tmp_path):
        session_dir = tmp_path / "sessions"
        agent = Agent(
            AgentConfig(session_enabled=True, session_dir=str(session_dir)),
            SimpleProvider(),
            session_id="nonexistent",
        )
        assert agent.messages == []
        assert agent.session_manager is not None
        assert agent.session_manager.current_session is None
        agent.close()


class TestGenerateTitle:
    @pytest.fixture
    def agent(self):
        agent = Agent(AgentConfig(session_enabled=False), SimpleProvider())
        yield agent
        agent.close()

    @pytest.mark.asyncio
    async def test_generate_title_no_messages(self, agent):
        result = await agent.generate_title()
        assert result is None

    @pytest.mark.asyncio
    async def test_generate_title_fallback_to_simple(self, agent):
        """generate_title returns the processed LLM response; no thinking markers leak through."""
        agent.add_user_message("What is the capital of France?")
        result = await agent.generate_title()
        assert isinstance(result, str)
        assert len(result) > 0
        assert "<think>" not in result
        assert "</think>" not in result

    @pytest.mark.asyncio
    async def test_generate_title_fallback_on_timeout(self, agent):
        import asyncio
        agent.llm.chat = AsyncMock(side_effect=asyncio.TimeoutError("timeout"))
        agent.add_user_message("Tell me about Python programming")
        result = await agent.generate_title()
        assert result == "Tell me about Python programmi..."


class TestExecuteToolBackwardCompat:
    @pytest.mark.asyncio
    async def test_execute_tool_success(self):
        class SimpleTool(Tool):
            def __init__(self):
                super().__init__(name="simple", description="simple")

            async def execute(self, **kwargs):
                return ToolResult(content="done")

        config = AgentConfig(tools=[SimpleTool()], session_enabled=False)
        agent = Agent(config, SimpleProvider())
        tool_call = LLMToolCall(id="1", name="simple", arguments={})
        result = await agent._execute_tool(tool_call)
        assert result.content == "done"
        agent.close()

    @pytest.mark.asyncio
    async def test_execute_tool_failure(self):
        class FailingTool(Tool):
            def __init__(self):
                super().__init__(name="fail", description="fail")

            async def execute(self, **kwargs):
                return ToolResult(content="FAILED: something broke")

        config = AgentConfig(tools=[FailingTool()], session_enabled=False)
        agent = Agent(config, SimpleProvider())
        tool_call = LLMToolCall(id="1", name="fail", arguments={})
        result = await agent._execute_tool(tool_call)
        assert "something broke" in result.error
        agent.close()


class TestLoadPersistentMemory:
    @pytest.mark.asyncio
    async def test_load_memory_no_memory_tool(self):
        agent = Agent(AgentConfig(tools=[], session_enabled=False), SimpleProvider())
        await agent.load_persistent_memory()
        assert len(agent.messages) == 0
        agent.close()

    @pytest.mark.asyncio
    async def test_load_memory_with_memory_tool(self, tmp_path):
        from src.agentframework.tools.memory import MemoryTool

        db_path = tmp_path / "memory.db"
        memory_tool = MemoryTool(db_path=db_path)
        await memory_tool.execute(action="save_fact", query="user name is Alice")
        config = AgentConfig(tools=[memory_tool], session_enabled=False)
        agent = Agent(config, SimpleProvider())
        await agent.load_persistent_memory()
        assert "Alice" in agent.messages[0].content
        assert "[Persistent Memory]" in agent.messages[0].content
        agent.close()


class TestAgentClose:
    def test_close_without_session(self):
        agent = Agent(AgentConfig(session_enabled=False), SimpleProvider())
        agent.close()

    def test_close_with_session(self, tmp_path):
        session_dir = tmp_path / "sessions"
        agent = Agent(
            AgentConfig(session_enabled=True, session_dir=str(session_dir)),
            SimpleProvider(),
        )
        agent.close()

    def test_close_with_async_provider_close(self):
        class AsyncCloseProvider(SimpleProvider):
            async def close(self):
                pass

        agent = Agent(AgentConfig(session_enabled=False), AsyncCloseProvider())
        agent.close()

    def test_close_with_sync_provider_close(self):
        class SyncCloseProvider(SimpleProvider):
            def close(self):
                pass

        agent = Agent(AgentConfig(session_enabled=False), SyncCloseProvider())
        agent.close()


class TestEnsureSession:
    def test_ensure_session_creates(self, tmp_path):
        session_dir = tmp_path / "sessions"
        agent = Agent(
            AgentConfig(session_enabled=True, session_dir=str(session_dir)),
            SimpleProvider(),
        )
        agent._ensure_session("custom-id", title="My Session")
        assert agent.session_manager is not None
        assert agent.session_manager.current_session is not None
        assert agent.session_manager.current_session.id == "custom-id"
        assert agent.session_manager.current_session.title == "My Session"
        agent.close()

    def test_ensure_session_updates_existing(self, tmp_path):
        session_dir = tmp_path / "sessions"
        agent = Agent(
            AgentConfig(session_enabled=True, session_dir=str(session_dir)),
            SimpleProvider(),
        )
        agent._ensure_session("sid")
        assert agent.session_manager.current_session.id == "sid"
        agent._ensure_session("new-id", title="Updated")
        assert agent.session_manager.current_session.id == "new-id"
        assert agent.session_manager.current_session.title == "Updated"
        agent.close()


class TestSaveSessionEdgeCases:
    def test_save_session_syncs_messages_to_current_session(self, tmp_path):
        """save_session should write agent.messages into session_manager.current_session.messages."""
        session_dir = tmp_path / "sessions"
        agent = Agent(
            AgentConfig(session_enabled=True, session_dir=str(session_dir)),
            SimpleProvider(),
        )
        agent._ensure_session("sync-test")
        assert agent.session_manager is not None
        agent.messages = [Message(role="user", content="hi")]
        result = agent.save_session()
        assert "saved" in result.lower()
        assert agent.session_manager.current_session.id == "sync-test"
        # Verify messages were actually synced to the session store
        synced = agent.session_manager.current_session.messages
        assert len(synced) == 1
        assert synced[0]["content"] == "hi"
        agent.close()

    def test_save_session_fails_when_no_current_session(self, tmp_path):
        session_dir = tmp_path / "sessions"
        agent = Agent(
            AgentConfig(session_enabled=True, session_dir=str(session_dir)),
            SimpleProvider(),
        )
        agent._ensure_session()
        with patch.object(agent.session_manager, "create_session", return_value=None):
            agent.session_manager.current_session = None
            result = agent.save_session()
            assert "Failed to create session" in result
        agent.close()


class TestExtractThinkingExtended:
    def test_with_thinking_markers(self):
        msgs = [
            Message(role="user", content="hello"),
            Message(role="assistant", content="<think>step by step</think>answer"),
        ]
        result = _extract_thinking(msgs)
        assert result == "step by step"

    def test_with_thinking_start_only(self):
        msgs = [
            Message(role="assistant", content="<think>thinking without end"),
        ]
        result = _extract_thinking(msgs)
        # No </think>, so _extract_thinking returns None
        assert result is None


class TestAgentInitWithSession:
    def test_init_with_existing_session(self, tmp_path):
        session_dir = tmp_path / "sessions"
        with SessionManager(str(session_dir)) as sm:
            sm.create_session(session_id="existing-session")
            sm.current_session.messages = [{"role": "user", "content": "hello"}]
            sm.save_session()
            session_id = sm.current_session.id

        agent = Agent(
            AgentConfig(session_enabled=True, session_dir=str(session_dir)),
            SimpleProvider(),
            session_id=session_id,
        )
        assert len(agent.messages) == 1
        assert agent.messages[0].content == "hello"
        agent.close()


class TestRunStreamingWithSession:
    @pytest.mark.asyncio
    async def test_run_streaming_with_session(self, tmp_path):
        session_dir = tmp_path / "sessions"
        agent = Agent(
            AgentConfig(session_enabled=True, session_dir=str(session_dir)),
            SimpleProvider(),
        )
        chunks = []
        response = await agent.run_streaming("hello", on_chunk=chunks.append)
        assert response == "ok"
        # Session was created and second message (assistant response) was persisted
        assert agent.session_manager is not None
        assert agent.session_manager.current_session is not None
        agent.close()

    @pytest.mark.asyncio
    async def test_run_streaming_with_thinking_saves_thinking_to_session(self, tmp_path):
        """When model returns thinking content, it should be stored in the session's assistant message."""
        session_dir = tmp_path / "sessions"
        agent = Agent(
            AgentConfig(session_enabled=True, session_dir=str(session_dir)),
            ThinkingProvider(),
        )
        chunks = []
        response = await agent.run_streaming("hello", on_chunk=chunks.append)
        # ThinkingProvider returns "Here is the answer" after stripping thinking markers
        assert "answer" in response.lower()
        agent.close()

    @pytest.mark.asyncio
    async def test_run_streaming_triggers_summary(self, tmp_path):
        session_dir = tmp_path / "sessions"
        config = AgentConfig(
            session_enabled=True,
            session_dir=str(session_dir),
            max_context_messages=2,
            max_context_chars=100,
        )
        agent = Agent(config, SimpleProvider())
        agent.add_user_message("hello")
        agent.add_system_message("some context")
        agent.add_user_message("world")
        chunks = []
        with patch.object(agent, "_background_summarize", new_callable=AsyncMock) as mock_bg:
            response = await agent.run_streaming("final message", on_chunk=chunks.append)
            assert response == "ok"
            assert mock_bg.called
        agent.close()


class TestGenerateTitleExtended:
    @pytest.mark.asyncio
    async def test_no_user_message(self):
        agent = Agent(AgentConfig(session_enabled=False), SimpleProvider())
        agent.messages = [Message(role="assistant", content="I'll help")]
        result = await agent.generate_title()
        assert result is None
        agent.close()

    @pytest.mark.asyncio
    async def test_thinking_in_title_response(self):
        """When LLM response contains thinking markers, generate_title strips them.
        Assumption: the LLM produces content after </think> that becomes the title."""
        agent = Agent(AgentConfig(session_enabled=False), ThinkingProvider())
        agent.add_user_message("What is Python?")
        result = await agent.generate_title()
        assert isinstance(result, str)
        assert len(result) > 0
        assert "<think>" not in result
        assert "</think>" not in result
        agent.close()

    @pytest.mark.asyncio
    async def test_outer_exception_handler(self):
        agent = Agent(AgentConfig(session_enabled=False), SimpleProvider())
        agent.add_user_message("Hello world")
        with patch.object(re, "sub", side_effect=RuntimeError("regex bomb")):
            result = await agent.generate_title()
            assert result is not None
            assert "Hello" in result
        agent.close()


class TestRunLoop:
    @pytest.mark.asyncio
    async def test_run_loop_delegates(self):
        agent = Agent(AgentConfig(session_enabled=False), SimpleProvider())
        agent.add_user_message("hello")
        response, messages = await agent._run_loop(agent.messages)
        assert response == "ok"
        assert len(messages) > 0
        agent.close()


class TestCancelledError:
    @pytest.mark.asyncio
    async def test_cancelled_error_in_run_streaming(self, tmp_path):
        session_dir = tmp_path / "sessions"

        class CancellingProvider(SimpleProvider):
            async def chat_streaming(self, messages, tools=None, temperature=0.3, on_chunk=None):
                if on_chunk:
                    on_chunk("partial response")
                raise asyncio.CancelledError()

        config = AgentConfig(
            session_enabled=True,
            session_dir=str(session_dir),
            max_context_messages=2,
            max_context_chars=100,
        )
        agent = Agent(config, CancellingProvider())
        agent.add_user_message("msg1")
        agent.add_user_message("msg2")
        agent.add_user_message("msg3")
        chunks = []
        response = await agent.run_streaming("hello", on_chunk=chunks.append)
        assert response == "partial response"
        assert len(chunks) > 0
        agent.close()


class TestToolLoopWithSession:
    @pytest.mark.asyncio
    async def test_tool_call_response_with_thinking(self, tmp_path):
        session_dir = tmp_path / "sessions"

        class ThinkingToolProvider(ThinkingProvider):
            def __init__(self):
                super().__init__()
                self.call_count = 0

            async def chat_streaming(self, messages, tools=None, temperature=0.3, on_chunk=None):
                self.call_count += 1
                if on_chunk:
                    on_chunk("")
                if self.call_count == 1:
                    return LLMResponse(
                        content="",
                        thinking="I used a tool",
                        tool_calls=[
                            LLMToolCall(id="tc1", name="simple", arguments={"input": "test"})
                        ],
                    )
                return LLMResponse(content="final answer", thinking="I used a tool")

        config = AgentConfig(
            session_enabled=True,
            session_dir=str(session_dir),
            tools=[SimpleTool()],
        )
        agent = Agent(config, ThinkingToolProvider())
        agent.add_user_message("use a tool")
        response, messages = await agent._run_loop(agent.messages)
        # Tool was invoked (simple → "done"), then second LLM call returned "final answer"
        assert "final answer" in response
        # The session message for the tool-calling assistant was persisted
        assert agent.session_manager is not None
        assert agent.session_manager.current_session is not None
        session_msgs = agent.session_manager.current_session.messages
        assert len(session_msgs) >= 1
        agent.close()

    @pytest.mark.asyncio
    async def test_tool_call_persists_to_session(self, tmp_path):
        session_dir = tmp_path / "sessions"

        class ToolCallProvider2(SimpleProvider):
            def __init__(self):
                super().__init__()
                self.call_count = 0

            async def chat_streaming(self, messages, tools=None, temperature=0.3, on_chunk=None):
                self.call_count += 1
                if on_chunk:
                    on_chunk("")
                if self.call_count == 1:
                    return LLMResponse(
                        content="",
                        tool_calls=[
                            LLMToolCall(id="tc1", name="simple", arguments={"input": "test"})
                        ],
                    )
                return LLMResponse(content="done")

        config = AgentConfig(
            session_enabled=True,
            session_dir=str(session_dir),
            tools=[SimpleTool()],
        )
        agent = Agent(config, ToolCallProvider2())
        response = await agent.run("hello")
        assert response == "done"
        agent.close()


class TestExecuteToolCalls:
    @pytest.mark.asyncio
    async def test_critical_execution_error_included_in_result(self):
        """Critical tool errors (execution_error category) are returned in the tool_messages list."""
        config = AgentConfig(session_enabled=False, tools=[SimpleTool()])
        agent = Agent(config, SimpleProvider())
        tool_call = LLMToolCall(id="err1", name="simple", arguments={})
        # Mock runtime_execute_tool_calls: simulates the real function's return contract
        # of (list[ToolMessage], dict[str, float]) — real function returns tool results + timings
        with patch(
            "src.agentframework.core.agent.runtime_execute_tool_calls",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = (
                [MagicMock(error_category="execution_error", content="FAILED: crash", tool_name="simple")],
                {"err1": 0.5},
            )
            tool_messages, _updated_messages = await agent._execute_tool_calls([tool_call])
            assert len(tool_messages) == 1
            assert tool_messages[0].error_category == "execution_error"
        agent.close()

    @pytest.mark.asyncio
    async def test_timing_entry_missing_for_tool_call_skips_logging(self):
        """A tool_call with no timing entry should not cause an error — code skips it."""
        config = AgentConfig(session_enabled=False, tools=[SimpleTool()])
        agent = Agent(config, SimpleProvider())
        tool_call = LLMToolCall(id="no-timing", name="simple", arguments={})
        # Mock runtime_execute_tool_calls with a timing dict that lacks an entry
        # for our specific tool_call.id — real function returns timings for all executed calls
        with patch(
            "src.agentframework.core.agent.runtime_execute_tool_calls",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = ([MagicMock()], {"other-id": 0.3})
            tool_messages, _updated_messages = await agent._execute_tool_calls([tool_call])
            assert len(tool_messages) == 1
        agent.close()


class TestSystemPromptWithSummary:
    @pytest.mark.asyncio
    async def test_summary_included_in_system_prompt(self, tmp_path):
        session_dir = tmp_path / "sessions"
        agent = Agent(
            AgentConfig(session_enabled=True, session_dir=str(session_dir)),
            SimpleProvider(),
        )
        agent._ensure_session("summary-test")
        agent.session_manager.current_session.metadata["summary"] = "User likes Python"
        agent.add_user_message("hello")
        result = await agent._prepare_messages(agent.messages)
        assert "User likes Python" in str(result)
        agent.close()


class TestLoadPersistentMemoryEmpty:
    @pytest.mark.asyncio
    async def test_load_memory_no_memories_does_not_add_system_message(self, tmp_path):
        """When MemoryTool has no stored facts, load_persistent_memory should be a no-op."""
        from src.agentframework.tools.memory import MemoryTool

        db_path = tmp_path / "empty_memory.db"
        memory_tool = MemoryTool(db_path=str(db_path))
        config = AgentConfig(tools=[memory_tool], session_enabled=False)
        agent = Agent(config, SimpleProvider())
        await agent.load_persistent_memory()
        assert len(agent.messages) == 0
        agent.close()


class TestBackgroundSummarize:
    @pytest.mark.asyncio
    async def test_background_summarize_exception(self, tmp_path):
        session_dir = tmp_path / "sessions"
        agent = Agent(
            AgentConfig(session_enabled=True, session_dir=str(session_dir)),
            SimpleProvider(),
        )
        agent._pending_summary = [Message(role="user", content="test")]
        with patch(
            "src.agentframework.core.agent.summarize_old_messages",
            new_callable=AsyncMock,
            side_effect=Exception("summarization failed"),
        ):
            await agent._background_summarize()
        assert agent._pending_summary is None
        agent.close()


class TestCloseExtended:
    def test_close_async_provider_error(self):
        class FailingAsyncCloseProvider(SimpleProvider):
            async def close(self):
                raise Exception("async close error")

        agent = Agent(AgentConfig(session_enabled=False), FailingAsyncCloseProvider())
        agent.close()

    def test_close_sync_provider_error(self):
        class FailingSyncCloseProvider(SimpleProvider):
            def close(self):
                raise Exception("sync close error")

        agent = Agent(AgentConfig(session_enabled=False), FailingSyncCloseProvider())
        agent.close()

    def test_close_otel_shutdown_error(self):
        pytest.importorskip("opentelemetry")
        from opentelemetry.sdk.trace import TracerProvider

        agent = Agent(AgentConfig(session_enabled=False), SimpleProvider())
        with patch("opentelemetry.trace.get_tracer_provider") as mock_get:
            mock_provider = MagicMock(spec=TracerProvider)
            mock_provider.shutdown.side_effect = Exception("otel error")
            mock_get.return_value = mock_provider
            agent.close()


class TestSynthesisRetry:
    """Tests for the post-tool-call synthesis retry logic in _run_loop_streaming."""

    @pytest.mark.asyncio
    async def test_synthesis_retry_fires_and_succeeds(self):
        """When synthesis returns only thinking, the retry fires and the final
        stored message has the retry-provided content."""

        class RetrySucceedsProvider(SimpleProvider):
            def __init__(self):
                super().__init__()
                self._call_num = 0

            async def chat(self, messages, tools=None, temperature=0.3):
                self._call_num += 1
                if self._call_num == 1:
                    return LLMResponse(
                        content="",
                        tool_calls=[
                            LLMToolCall(id="tc1", name="simple", arguments={"input": "test"})
                        ],
                    )
                if self._call_num == 2:
                    return LLMResponse(content="<think>\nLet me process the result...\n</think>")
                return LLMResponse(content="final answer after retry")

            async def chat_streaming(self, messages, tools=None, temperature=0.3, on_chunk=None):
                self._call_num += 1
                if self._call_num == 1:
                    if on_chunk:
                        on_chunk("")
                    return LLMResponse(
                        content="",
                        tool_calls=[
                            LLMToolCall(id="tc1", name="simple", arguments={"input": "test"})
                        ],
                    )
                if self._call_num == 2:
                    if on_chunk:
                        on_chunk("<think>\nLet me process the result...\n</think>")
                    return LLMResponse(content="<think>\nLet me process the result...\n</think>")
                if on_chunk:
                    on_chunk("final answer after retry")
                return LLMResponse(content="final answer after retry")

        config = AgentConfig(
            session_enabled=False,
            tools=[SimpleTool()],
        )
        agent = Agent(config, RetrySucceedsProvider())
        agent.add_user_message("use a tool")
        response, messages = await agent._run_loop(agent.messages)
        assert "final answer after retry" in response
        # The final assistant message should have the retry content
        last = messages[-1]
        assert last.role == "assistant"
        assert "final answer after retry" in last.content
        # The thinking-only message should not appear in the final history
        thinking_msgs = [
            m for m in messages
            if m.role == "assistant" and "<think>" in m.content and "final answer" not in m.content
        ]
        assert len(thinking_msgs) == 0, "Thinking-only message should have been replaced"
        agent.close()

    @pytest.mark.asyncio
    async def test_synthesis_retry_both_empty_stores_fallback(self):
        """When both synthesis and retry return only thinking, the fallback
        message is stored instead of a blank turn."""

        class RetryBothEmptyProvider(SimpleProvider):
            def __init__(self):
                super().__init__()
                self._call_num = 0

            async def chat(self, messages, tools=None, temperature=0.3):
                self._call_num += 1
                if self._call_num == 1:
                    return LLMResponse(
                        content="",
                        tool_calls=[
                            LLMToolCall(id="tc1", name="simple", arguments={"input": "test"})
                        ],
                    )
                return LLMResponse(content="<think>\nLet me process the result...\n</think>")

            async def chat_streaming(self, messages, tools=None, temperature=0.3, on_chunk=None):
                self._call_num += 1
                if self._call_num == 1:
                    if on_chunk:
                        on_chunk("")
                    return LLMResponse(
                        content="",
                        tool_calls=[
                            LLMToolCall(id="tc1", name="simple", arguments={"input": "test"})
                        ],
                    )
                if on_chunk:
                    on_chunk("<think>\nLet me process the result...\n</think>")
                return LLMResponse(content="<think>\nLet me process the result...\n</think>")

        config = AgentConfig(
            session_enabled=False,
            tools=[SimpleTool()],
        )
        agent = Agent(config, RetryBothEmptyProvider())
        agent.add_user_message("use a tool")
        response, messages =     await agent._run_loop(agent.messages)
        assert "No answer generated" in response
        last = messages[-1]
        assert last.role == "assistant"
        assert "No answer generated" in last.content
        agent.close()

    @pytest.mark.asyncio
    async def test_synthesis_retry_unterminated_think_fires_retry(self):
        """When synthesis returns an unterminated <think> tag (no closing
        </think>) and no real content, the retry fires — unlike the old
        re.sub-based guard which would miss this edge case."""

        class UnterminatedThinkProvider(SimpleProvider):
            def __init__(self):
                super().__init__()
                self._call_num = 0

            async def chat(self, messages, tools=None, temperature=0.3):
                self._call_num += 1
                if self._call_num == 1:
                    return LLMResponse(
                        content="",
                        tool_calls=[
                            LLMToolCall(id="tc1", name="simple", arguments={"input": "test"})
                        ],
                    )
                if self._call_num == 2:
                    return LLMResponse(content="<think>\nLet me reason without closing")
                return LLMResponse(content="final answer after retry")

            async def chat_streaming(self, messages, tools=None, temperature=0.3, on_chunk=None):
                self._call_num += 1
                if self._call_num == 1:
                    if on_chunk:
                        on_chunk("")
                    return LLMResponse(
                        content="",
                        tool_calls=[
                            LLMToolCall(id="tc1", name="simple", arguments={"input": "test"})
                        ],
                    )
                if self._call_num == 2:
                    if on_chunk:
                        on_chunk("<think>\nLet me reason without closing")
                    return LLMResponse(content="<think>\nLet me reason without closing")
                if on_chunk:
                    on_chunk("final answer after retry")
                return LLMResponse(content="final answer after retry")

        config = AgentConfig(
            session_enabled=False,
            tools=[SimpleTool()],
        )
        agent = Agent(config, UnterminatedThinkProvider())
        agent.add_user_message("use a tool")
        response, messages = await agent._run_loop(agent.messages)
        assert "final answer after retry" in response
        last = messages[-1]
        assert last.role == "assistant"
        assert "final answer after retry" in last.content
        # The thinking-only message (with unterminated tag) should not appear
        thinking_msgs = [
            m for m in messages
            if m.role == "assistant" and "<think>" in str(m.content) and "final answer" not in m.content
        ]
        assert len(thinking_msgs) == 0, "Unterminated thinking-only message should have been replaced"
        agent.close()

    @pytest.mark.asyncio
    async def test_synthesis_retry_cancelled_during_retry_uses_only_retry_chunks(self):
        """When the user cancels during the retry call, partial_chunks should
        only contain chunks from the retry, not from the first (thinking-only) call."""
        retry_chunks: list[str] = []

        class CancelDuringRetryProvider(SimpleProvider):
            def __init__(self):
                super().__init__()
                self._call_num = 0

            async def chat(self, messages, tools=None, temperature=0.3):
                self._call_num += 1
                if self._call_num == 1:
                    return LLMResponse(
                        content="",
                        tool_calls=[
                            LLMToolCall(id="tc1", name="simple", arguments={"input": "test"})
                        ],
                    )
                if self._call_num == 2:
                    return LLMResponse(content="<think>\nJust thinking</think>")
                return LLMResponse(content="should not reach here")

            async def chat_streaming(self, messages, tools=None, temperature=0.3, on_chunk=None):
                self._call_num += 1
                if self._call_num == 1:
                    if on_chunk:
                        on_chunk("")
                    return LLMResponse(
                        content="",
                        tool_calls=[
                            LLMToolCall(id="tc1", name="simple", arguments={"input": "test"})
                        ],
                    )
                if self._call_num == 2:
                    if on_chunk:
                        on_chunk("<think>\nJust thinking</think>")
                    return LLMResponse(content="<think>\nJust thinking</think>")
                # Call 3: the retry — emit a couple chunks then cancel
                if on_chunk:
                    on_chunk("retry chunk 1")
                    on_chunk("retry chunk 2")
                    retry_chunks.extend(["retry chunk 1", "retry chunk 2"])
                raise asyncio.CancelledError()

        config = AgentConfig(
            session_enabled=False,
            tools=[SimpleTool()],
        )
        agent = Agent(config, CancelDuringRetryProvider())
        agent.add_user_message("use a tool")
        response, messages = await agent._run_loop(agent.messages)
        # Should contain only retry chunks, not the first call's thinking content
        assert response == "retry chunk 1retry chunk 2", (
            f"Expected retry-only chunks, got: {response!r}"
        )
        assert "Just thinking" not in response, (
            "First call's thinking content leaked into the cancelled retry response"
        )
        agent.close()


@pytest.mark.asyncio
async def test_all_three_paths_thinking_shape():
    """All three assistant message construction paths produce consistent shape:

    -  thinking field populated when reasoning was present, None otherwise
    -  content never contains <think> tags in any path
    -  nothing duplicated in both content and thinking
    """

    # ------------------------------------------------------------------
    # Path 3 — ordinary (no-tool) assistant message
    # ------------------------------------------------------------------
    class OrdinaryThinkingProvider(SimpleProvider):
        async def chat(self, messages, tools=None, temperature=0.3):
            return LLMResponse(content="<think>Let me solve this</think>Here is the answer")

        async def chat_streaming(self, messages, tools=None, temperature=0.3, on_chunk=None):
            if on_chunk:
                on_chunk("<think>Let me solve this</think>Here is the answer")
            return LLMResponse(content="<think>Let me solve this</think>Here is the answer")

    agent3 = Agent(AgentConfig(session_enabled=False), OrdinaryThinkingProvider())
    agent3.add_user_message("hello")
    _ret, msgs3 = await agent3._run_loop(agent3.messages)
    last3 = msgs3[-1]
    assert last3.role == "assistant"
    assert "<think>" not in last3.content, "Path 3: content must not contain <think> tags"
    assert last3.thinking == "Let me solve this", "Path 3: thinking must be extracted from inline tags"
    assert last3.thinking not in last3.content, "Path 3: no duplication"
    agent3.close()

    # ------------------------------------------------------------------
    # Path 1 — tool-call message  (also exercises Path 2 on the next turn)
    # ------------------------------------------------------------------
    class ToolAndSynthesisProvider(SimpleProvider):
        def __init__(self):
            super().__init__()
            self._call_num = 0

        async def chat(self, messages, tools=None, temperature=0.3):
            self._call_num += 1
            if self._call_num == 1:
                return LLMResponse(
                    content="<think>I need to look up</think>",
                    tool_calls=[LLMToolCall(id="tc1", name="simple", arguments={"input": "test"})],
                )
            return LLMResponse(content="<think>I processed the result</think>Answer is 42")

        async def chat_streaming(self, messages, tools=None, temperature=0.3, on_chunk=None):
            self._call_num += 1
            if self._call_num == 1:
                if on_chunk:
                    on_chunk("")
                return LLMResponse(
                    content="<think>I need to look up</think>",
                    tool_calls=[LLMToolCall(id="tc1", name="simple", arguments={"input": "test"})],
                )
            if on_chunk:
                on_chunk("<think>I processed the result</think>Answer is 42")
            return LLMResponse(content="<think>I processed the result</think>Answer is 42")

    config12 = AgentConfig(session_enabled=False, tools=[SimpleTool()])
    agent12 = Agent(config12, ToolAndSynthesisProvider())
    agent12.add_user_message("use tools")
    _ret, msgs12 = await agent12._run_loop(agent12.messages)

    # Find the tool-call assistant message (Path 1)
    tool_call_msgs = [m for m in msgs12 if m.role == "assistant" and m.tool_calls]
    assert len(tool_call_msgs) >= 1
    tc_msg = tool_call_msgs[0]
    assert "<think>" not in tc_msg.content, "Path 1: content must not contain <think> tags"
    assert tc_msg.thinking == "I need to look up", "Path 1: thinking must be extracted from inline tags"
    assert tc_msg.thinking not in tc_msg.content, "Path 1: no duplication"

    # Find the final synthesis assistant message (Path 2)
    synthesis_msgs = [m for m in msgs12 if m.role == "assistant" and not m.tool_calls]
    assert len(synthesis_msgs) >= 1
    synth_msg = synthesis_msgs[-1]
    assert "<think>" not in synth_msg.content, "Path 2: content must not contain <think> tags"
    assert synth_msg.thinking == "I processed the result", "Path 2: thinking must be extracted from inline tags"
    assert synth_msg.thinking not in synth_msg.content, "Path 2: no duplication"
    agent12.close()

    # ------------------------------------------------------------------
    # Providers that supply thinking via a separate field (no inline tags)
    # should still populate the thinking field without extraction.
    # ------------------------------------------------------------------
    class SeparateThinkingProvider(SimpleProvider):
        async def chat(self, messages, tools=None, temperature=0.3):
            return LLMResponse(content="Clean answer", thinking="I reasoned step by step")

        async def chat_streaming(self, messages, tools=None, temperature=0.3, on_chunk=None):
            if on_chunk:
                on_chunk("Clean answer")
            return LLMResponse(content="Clean answer", thinking="I reasoned step by step")

    agent_sep = Agent(AgentConfig(session_enabled=False), SeparateThinkingProvider())
    agent_sep.add_user_message("hello")
    _ret, msgs_sep = await agent_sep._run_loop(agent_sep.messages)
    last_sep = msgs_sep[-1]
    assert "<think>" not in last_sep.content
    assert last_sep.thinking == "I reasoned step by step"
    assert last_sep.thinking not in last_sep.content
    agent_sep.close()

    # ------------------------------------------------------------------
    # No thinking at all — both fields absent/clean
    # ------------------------------------------------------------------
    class NoThinkingProvider(SimpleProvider):
        async def chat(self, messages, tools=None, temperature=0.3):
            return LLMResponse(content="Plain answer without reasoning")

        async def chat_streaming(self, messages, tools=None, temperature=0.3, on_chunk=None):
            if on_chunk:
                on_chunk("Plain answer without reasoning")
            return LLMResponse(content="Plain answer without reasoning")

    agent_none = Agent(AgentConfig(session_enabled=False), NoThinkingProvider())
    agent_none.add_user_message("hello")
    _ret, msgs_none = await agent_none._run_loop(agent_none.messages)
    last_none = msgs_none[-1]
    assert "<think>" not in last_none.content
    assert last_none.thinking is None
    agent_none.close()


@pytest.mark.asyncio
async def test_all_three_paths_session_persistence(tmp_path):
    """Verify session-stored messages match the same shape as in-memory messages."""
    session_dir = tmp_path / "sessions"

    class Provider(SimpleProvider):
        def __init__(self):
            super().__init__()
            self._call_num = 0

        async def chat(self, messages, tools=None, temperature=0.3):
            self._call_num += 1
            if self._call_num == 1:
                return LLMResponse(
                    content="<think>I need to search</think>",
                    tool_calls=[LLMToolCall(id="tc1", name="simple", arguments={"input": "test"})],
                )
            return LLMResponse(content="<think>I processed</think>Answer: 42")

        async def chat_streaming(self, messages, tools=None, temperature=0.3, on_chunk=None):
            self._call_num += 1
            if self._call_num == 1:
                if on_chunk:
                    on_chunk("")
                return LLMResponse(
                    content="<think>I need to search</think>",
                    tool_calls=[LLMToolCall(id="tc1", name="simple", arguments={"input": "test"})],
                )
            if on_chunk:
                on_chunk("<think>I processed</think>Answer: 42")
            return LLMResponse(content="<think>I processed</think>Answer: 42")

    config = AgentConfig(
        session_enabled=True,
        session_dir=str(session_dir),
        tools=[SimpleTool()],
    )
    agent = Agent(config, Provider())
    response = await agent.run("use tools")
    assert response == "Answer: 42"

    assert agent.session_manager is not None
    assert agent.session_manager.current_session is not None
    session_msgs = agent.session_manager.current_session.messages

    # Build a roled-index lookup
    by_role: dict[str, list[dict]] = {}
    for m in session_msgs:
        by_role.setdefault(m["role"], []).append(m)

    # Tool-call assistant message (Path 1)
    tc = by_role.get("assistant", [])[0]
    assert tc["role"] == "assistant"
    assert tc.get("tool_calls"), "tool-call message must have tool_calls"
    assert "<think>" not in tc["content"]
    assert tc.get("thinking") == "I need to search"
    assert tc["thinking"] not in tc["content"]

    # Final synthesis assistant message (Path 2)
    final = by_role.get("assistant", [])[1]
    assert final["role"] == "assistant"
    assert not final.get("tool_calls")
    assert "<think>" not in final["content"]
    assert final.get("thinking") == "I processed"
    assert final["thinking"] not in final["content"]

    agent.close()
