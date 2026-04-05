"""Tests for session continuity and timestamp handling."""

import pytest
import tempfile
from datetime import datetime

from src.agentframework.core import Agent, AgentConfig
from src.agentframework.core.session_runtime import (
    serialize_messages,
    deserialize_messages,
)
from src.agentframework.providers import LLMProvider, LLMResponse
from src.agentframework.web_api import filter_messages_for_ui
from src.agentframework.session import SessionManager


class MockProvider(LLMProvider):
    """Mock LLM provider for testing."""

    def __init__(self, responses=None):
        self.responses = responses or [LLMResponse(content="Mock response")]
        self.call_count = 0

    async def chat(self, messages, tools=None, temperature=0.3):
        resp = self.responses[self.call_count % len(self.responses)]
        self.call_count += 1
        return resp

    async def chat_streaming(
        self, messages, tools=None, temperature=0.3, on_chunk=None
    ):
        resp = await self.chat(messages, tools, temperature)
        if on_chunk:
            on_chunk(resp.content)
        return resp

    async def extract_structured(self, messages, response_model, temperature=0.3):
        return response_model()


class TestSessionTimestampSerialization:
    """Tests for timestamp serialization/deserialization."""

    def test_serialize_messages_with_timestamps(self):
        """Messages with timestamps should serialize correctly."""
        from src.agentframework.conversation import Message

        messages = [
            Message(role="user", content="hello", timestamp="14:30"),
            Message(role="assistant", content="hi", timestamp="14:31"),
        ]

        serialized = serialize_messages(messages)

        assert serialized[0]["timestamp"] == "14:30"
        assert serialized[1]["timestamp"] == "14:31"

    def test_deserialize_messages_with_timestamps(self):
        """Messages with timestamps should deserialize correctly."""

        data = [
            {"role": "user", "content": "hello", "timestamp": "14:30"},
            {"role": "assistant", "content": "hi", "timestamp": "14:31"},
        ]

        messages = deserialize_messages(data)

        assert messages[0].timestamp == "14:30"
        assert messages[1].timestamp == "14:31"

    def test_deserialize_messages_without_timestamps(self):
        """Messages without timestamps should work (backward compatibility)."""

        data = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]

        messages = deserialize_messages(data)

        assert messages[0].timestamp is None
        assert messages[1].timestamp is None

    def test_serialize_messages_without_timestamps(self):
        """Messages without timestamps should serialize correctly."""
        from src.agentframework.conversation import Message

        messages = [
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi"),
        ]

        serialized = serialize_messages(messages)

        assert "timestamp" in serialized[0]
        assert serialized[0]["timestamp"] is None


class TestFilterMessagesTimestamp:
    """Tests for filter_messages_for_ui timestamp handling."""

    def test_filter_uses_message_timestamp(self):
        """Messages with existing timestamps should be preserved."""
        from src.agentframework.conversation import Message

        messages = [
            Message(role="user", content="hello", timestamp="14:30"),
            Message(role="assistant", content="hi", timestamp="14:31"),
        ]

        result = filter_messages_for_ui(messages)

        assert result[0]["timestamp"] == "14:30"
        assert result[1]["timestamp"] == "14:31"

    def test_filter_uses_session_creation_time_as_fallback(self):
        """Messages without timestamps should use session creation time."""
        from src.agentframework.conversation import Message

        messages = [
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi"),
        ]

        session_created = datetime(2024, 1, 1, 16, 9)
        result = filter_messages_for_ui(messages, session_created_at=session_created)

        assert result[0]["timestamp"] == "16:09"
        assert result[1]["timestamp"] == "16:09"

    def test_filter_uses_current_time_when_no_session_time(self):
        """Messages without timestamps and no session should use current time."""
        from src.agentframework.conversation import Message

        messages = [
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi"),
        ]

        result = filter_messages_for_ui(messages)

        # Should have a timestamp (current time fallback)
        assert result[0]["timestamp"] is not None
        assert ":" in result[0]["timestamp"]


class TestSessionContinuity:
    """Tests for session continuity - ensuring messages continue the correct session."""

    @pytest.fixture
    def temp_session_dir(self):
        """Create a temporary directory for sessions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.mark.asyncio
    async def test_session_adds_timestamps_to_messages(self, temp_session_dir):
        """Running an agent should add timestamps to session messages."""
        config = AgentConfig(
            tools=[],
            session_enabled=True,
            session_dir=temp_session_dir,
        )
        agent = Agent(config, MockProvider())
        agent.session_manager.create_session("test-session")

        await agent.run("hello")

        # Check session messages have timestamps
        session = agent.session_manager.current_session
        assert session is not None
        for msg in session.messages:
            assert "timestamp" in msg, f"Message missing timestamp: {msg}"
            assert msg["timestamp"] is not None

        agent.close()

    @pytest.mark.asyncio
    async def test_continuing_existing_session_adds_to_it(self, temp_session_dir):
        """Continuing an existing session should add messages to it, not create new."""
        config = AgentConfig(
            tools=[],
            session_enabled=True,
            session_dir=temp_session_dir,
        )
        agent = Agent(config, MockProvider())

        # Create a session
        session = agent.session_manager.create_session("existing-session")
        session_id = session.id
        assert session_id == "existing-session"

        # Send first message
        await agent.run("first message")

        # Get the session ID again
        first_session_id = agent.session_manager.current_session.id
        message_count_after_first = len(agent.session_manager.current_session.messages)

        # Send second message
        await agent.run("second message")

        # Should be same session
        assert agent.session_manager.current_session.id == first_session_id
        # Should have more messages
        assert (
            len(agent.session_manager.current_session.messages)
            > message_count_after_first
        )

        agent.close()

    @pytest.mark.asyncio
    async def test_load_session_preserves_timestamps(self, temp_session_dir):
        """Loading a session should preserve message timestamps."""
        from src.agentframework.conversation import Message

        config = AgentConfig(
            tools=[],
            session_enabled=True,
            session_dir=temp_session_dir,
        )
        agent = Agent(config, MockProvider())
        agent.session_manager.create_session("test-load")

        # Add messages directly to agent.messages (which is what gets serialized)
        agent.messages.append(Message(role="user", content="hello", timestamp="10:30"))
        agent.messages.append(
            Message(role="assistant", content="hi there", timestamp="10:31")
        )

        # Save session (serializes agent.messages)
        agent.save_session()

        # Verify saved to DB
        manager = SessionManager(temp_session_dir)
        loaded = manager.load_session("test-load")
        assert loaded is not None
        assert len(loaded.messages) >= 2

        user_msg = next((m for m in loaded.messages if m.get("role") == "user"), None)
        assert user_msg is not None
        assert user_msg.get("timestamp") == "10:30"

        agent.close()


class TestMessageField:
    """Tests for Message dataclass timestamp field."""

    def test_message_has_timestamp_field(self):
        """Message dataclass should have a timestamp field."""
        from src.agentframework.conversation import Message

        msg = Message(role="user", content="hello", timestamp="14:30")
        assert msg.timestamp == "14:30"

    def test_message_timestamp_defaults_to_none(self):
        """Message timestamp should default to None."""
        from src.agentframework.conversation import Message

        msg = Message(role="user", content="hello")
        assert msg.timestamp is None
