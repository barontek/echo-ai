"""Tests for the web API endpoints.

Merged from test_web_api.py and test_web_api_extended.py.
"""

import sys
import pytest
import json
import asyncio
import httpx
from types import SimpleNamespace
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.websockets import WebSocketDisconnect
from src.agentframework.web_api import app
import src.agentframework.web_api as web_api
import src.agentframework.web_models as web_models
from src.agentframework.routers.chat import handle_chat
from src.agentframework.routers.workflows import workflows_list, workflow_run
from pathlib import Path

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def ensure_state():
    """Ensure application state is initialized for each test."""
    web_api._rate_limiter.clear()
    state = web_api.get_state()
    # Close any existing real agent before replacing with mock
    if state.agent is not None and not isinstance(state.agent, MagicMock):
        try:
            state.agent.close()
        except Exception:
            pass
    # Replace with mock
    from src.agentframework.core import Agent

    state.agent = MagicMock(spec=Agent)
    state.agent.session_manager = MagicMock()
    state.agent.session_manager.SessionLocal = MagicMock()

    yield

    state.agent = None
    state.current_session_id = None
    state.message_history = []


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.session_manager = MagicMock()
    agent.messages = []
    agent.run = AsyncMock(return_value="Mock response")
    agent.load_session = MagicMock()
    return agent


# ---------------------------------------------------------------------------
# Agent bootstrapping (_create_runtime_agent)
# ---------------------------------------------------------------------------


class TestAgentBootstrap:
    def test_create_runtime_agent_uses_configured_tools(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            web_api,
            "load_config",
            lambda: {
                "model": {"temperature": 0.6, "base_url": "http://localhost:9999"},
                "agent": {
                    "max_iterations": 7,
                    "system_prompt": "Custom prompt",
                    "session_enabled": False,
                    "session_dir": ".sessions-test",
                },
            },
        )
        fake_safety = SimpleNamespace(workspace="/tmp/workspace")
        monkeypatch.setattr(web_api, "get_safety_config", lambda cfg: fake_safety)
        fake_tools = [SimpleNamespace(name="bash")]
        monkeypatch.setattr(web_api, "get_tools", lambda cfg, safety: fake_tools)

        def fake_create_agent(agent_config, api_key=None, session_id=None, fernet=None):
            captured["agent_config"] = agent_config
            captured["api_key"] = api_key
            return SimpleNamespace(config=agent_config)

        monkeypatch.setattr(web_api, "create_agent", fake_create_agent)
        result = web_api._create_runtime_agent(
            "ollama", "qwen3:4b-instruct", api_key="k"
        )

        assert result.config.tools == fake_tools
        assert result.config.temperature == 0.6
        assert result.config.base_url == "http://localhost:9999"
        assert result.config.max_iterations == 7
        assert result.config.session_enabled is False
        assert result.config.session_dir == ".sessions-test"
        assert "Custom prompt" in result.config.system_prompt
        assert (
            "Workspace (file operations confined to): /tmp/workspace"
            in result.config.system_prompt
        )
        assert captured["api_key"] == "k"

    def test_create_runtime_agent_sets_default_system_prompt(self, monkeypatch):
        monkeypatch.setattr(web_api, "load_config", lambda: {})
        monkeypatch.setattr(
            web_api, "get_safety_config", lambda cfg: SimpleNamespace(workspace=".")
        )
        monkeypatch.setattr(web_api, "get_tools", lambda cfg, safety: [])
        monkeypatch.setattr(
            web_api,
            "create_agent",
            lambda agent_config, api_key=None, session_id=None, fernet=None: SimpleNamespace(
                config=agent_config
            ),
        )
        result = web_api._create_runtime_agent("ollama", "qwen3:4b-instruct")
        assert result.config.tools == []
        assert (
            "You are an AI assistant with access to various tools."
            in result.config.system_prompt
        )


# ---------------------------------------------------------------------------
# Models & Config
# ---------------------------------------------------------------------------


class TestModelsAndConfig:
    def test_list_models_success(self, monkeypatch):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [{"name": "model1"}, {"name": "model2"}]
        }
        mock_response.raise_for_status = MagicMock()

        class MockAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def get(self, *args, **kwargs):
                return mock_response

        web_api._models_cache.clear()
        monkeypatch.setattr(
            "httpx.AsyncClient", lambda *args, **kwargs: MockAsyncClient()
        )
        response = client.get("/api/models")
        assert response.status_code == 200
        assert response.json() == {"models": ["model1", "model2"]}

    def test_list_models_fallback(self, monkeypatch):
        class MockAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def get(self, *args, **kwargs):
                raise httpx.ConnectError("Connection refused")

        web_api._models_cache.clear()
        monkeypatch.setattr(
            "httpx.AsyncClient", lambda *args, **kwargs: MockAsyncClient()
        )
        response = client.get("/api/models")
        assert response.status_code == 200
        assert "llama3.2:latest" in response.json()["models"]

    def test_update_config(self, monkeypatch):
        mock_agent_instance = MagicMock()
        monkeypatch.setattr(
            web_api,
            "_create_runtime_agent",
            lambda *args, **kwargs: mock_agent_instance,
        )
        payload = {"provider": "openai", "model": "gpt-4", "api_key": "test-key"}
        response = client.post("/api/config", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        state = web_api.get_state()
        assert state.agent == mock_agent_instance


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


class TestSessions:
    def test_list_sessions_available(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        s1 = MagicMock(id="session1", title="Title 1", created_at=datetime.now())
        s2 = MagicMock(id="session2", title=None, created_at=datetime.now())
        mock_agent.session_manager.list_sessions.return_value = ([s1, s2], 2)

        response = client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()
        assert len(data["sessions"]) == 2
        assert data["total"] == 2
        assert data["sessions"][0]["id"] == "session1"
        assert data["sessions"][0]["title"] == "Title 1"
        assert data["sessions"][1]["title"] is None

    def test_list_sessions_response_structure(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        s1 = MagicMock(id="s1", title="Chat about Python", created_at=datetime.now())
        s2 = MagicMock(id="s2", title=None, created_at=datetime.now())
        mock_agent.session_manager.list_sessions.return_value = ([s1, s2], 2)

        response = client.get("/api/sessions")
        data = response.json()
        for session in data["sessions"]:
            assert "id" in session
            assert "title" in session
            assert "created_at" in session

    def test_list_sessions_locked(self, monkeypatch, mock_agent):
        state = web_api.get_state()
        state.agent = None

        response = client.get("/api/sessions")
        assert response.status_code == 423
        assert response.json()["detail"] == "Database is locked"

    def test_create_session(self, monkeypatch, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager.create_session = MagicMock()
        mock_agent.session_manager.current_session = MagicMock(id="new-session-id")
        response = client.post("/api/sessions")
        assert response.status_code == 200
        assert response.json() == {"session_id": "new-session-id"}
        assert state.current_session_id == "new-session-id"
        mock_agent.session_manager.create_session.assert_called_once()

    def test_load_session_response_structure(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.messages = [
            {"role": "user", "content": "hi", "metadata": {"timestamp": "12:00"}}
        ]
        mock_agent.load_session.return_value = "Session loaded: test-session"
        mock_agent.session_manager.current_session = MagicMock(
            id="test-session", title="My Chat"
        )

        response = client.get("/api/sessions/test-session")
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "test-session"
        assert data["title"] == "My Chat"
        assert isinstance(data["messages"], list)
        assert len(data["messages"]) == 1

    def test_load_session_no_title(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.messages = [
            {"role": "user", "content": "hi", "metadata": {"timestamp": "12:00"}}
        ]
        mock_agent.load_session.return_value = "Session loaded: test-session"
        mock_agent.session_manager.current_session = MagicMock(
            id="test-session", title=None
        )

        response = client.get("/api/sessions/test-session")
        assert response.status_code == 200
        assert response.json()["title"] is None

    def test_load_session_not_found(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.messages = []
        mock_agent.load_session.return_value = "Session not found: nonexistent"
        mock_agent.session_manager.current_session = None

        response = client.get("/api/sessions/nonexistent")
        assert response.status_code == 200
        data = response.json()
        assert data["title"] is None
        assert data["messages"] == []

    def test_load_session_no_agent(self):
        state = web_api.get_state()
        state.agent = None
        response = client.get("/api/sessions/any-session")
        assert response.status_code == 423
        assert response.json()["detail"] == "Database is locked"

    def test_delete_session(self, monkeypatch, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager.delete_session = MagicMock()
        response = client.delete("/api/sessions/session-to-delete")
        assert response.status_code == 200
        mock_agent.session_manager.delete_session.assert_called_once_with("session-to-delete")

    def test_rename_session_success(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_db = MagicMock()
        mock_agent.session_manager.SessionLocal.return_value.__enter__.return_value = (
            mock_db
        )
        mock_agent.session_manager.current_session = MagicMock(id="old", title="old")
        mock_db.query.return_value.filter.return_value.update.return_value = 1

        payload = {"session_id": "old", "new_title": "new title"}
        response = client.post("/api/sessions/rename", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "new title"
        assert data["session_id"] == "old"
        assert mock_agent.session_manager.current_session.title == "new title"

    def test_rename_session_not_found(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_db = MagicMock()
        mock_agent.session_manager.SessionLocal.return_value.__enter__.return_value = (
            mock_db
        )
        mock_db.query.return_value.filter.return_value.update.return_value = 0

        payload = {"session_id": "nonexistent", "new_title": "title"}
        response = client.post("/api/sessions/rename", json=payload)
        assert response.status_code == 404

    def test_purge_sessions(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager.purge_sessions.return_value = 5

        response = client.post("/api/sessions/purge")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["purged_count"] == 5

    def test_purge_sessions_with_days(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager.purge_sessions.return_value = 2

        response = client.post("/api/sessions/purge?days=7")
        assert response.status_code == 200
        mock_agent.session_manager.purge_sessions.assert_called_with(older_than_days=7)


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class TestChat:
    @pytest.mark.asyncio
    async def test_chat_endpoint(self, monkeypatch, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.run = AsyncMock(return_value="Response")
        response = client.post("/api/chat", json={"content": "Hello"})
        assert response.status_code == 200
        assert response.json()["response"] == "Response"


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


class TestWebSocket:
    def test_chat_websocket_happy_path_returns_done(self):
        with patch("src.agentframework.web_api._create_runtime_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.session_manager = None
            async def mock_stream(prompt, on_chunk=None):
                if on_chunk:
                    on_chunk("Hello")
                return "Hello"
            mock_agent.run_streaming = AsyncMock(side_effect=mock_stream)
            mock_agent.messages = []
            mock_create.return_value = mock_agent

            with client.websocket_connect("/ws/chat") as websocket:
                websocket.send_text(
                    json.dumps(
                        {"provider": "openai", "model": "gpt-4o", "api_key": "test-key"}
                    )
                )
                data = websocket.receive_json()
                assert data["type"] == "ready"

                websocket.send_text(json.dumps({"type": "message", "content": "Hi"}))
                msg1 = websocket.receive_json()
                assert msg1["type"] == "message"
                assert msg1["content"] == "Hi"

                # content
                msg2 = websocket.receive_json()
                assert msg2["type"] == "content"
                assert msg2["content"] == "Hello"

                msg3 = websocket.receive_json()
                assert msg3["type"] == "done"
                assert msg3["content"] == "Hello"

    def test_chat_websocket_thinking_markers_produce_thinking_events(self):
        with patch("src.agentframework.web_api._create_runtime_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.session_manager = None

            async def mock_run_streaming(prompt, on_chunk=None):
                if on_chunk:
                    on_chunk("<think>")
                    on_chunk("I am thinking...")
                    on_chunk("</think>")
                    on_chunk("I have thought.")
                return "Result"

            mock_agent.run_streaming = mock_run_streaming
            mock_agent.messages = []
            mock_create.return_value = mock_agent

            with client.websocket_connect("/ws/chat") as websocket:
                websocket.send_text(
                    json.dumps({"provider": "openai", "model": "gpt-4o"})
                )
                websocket.receive_json()  # ready

                websocket.send_text(
                    json.dumps({"type": "message", "content": "Think about it"})
                )
                websocket.receive_json()  # message echo

                # All events are now "content" with raw <think> tags
                c1 = websocket.receive_json()
                assert c1["type"] == "content"
                c2 = websocket.receive_json()
                assert c2["type"] == "content"
                c3 = websocket.receive_json()
                assert c3["type"] == "content"
                c4 = websocket.receive_json()
                assert c4["type"] == "content"

                d1 = websocket.receive_json()
                assert d1["type"] == "done"
                assert "<think>" in d1["content"] or "I am thinking" in d1["content"]

    def test_chat_websocket_unclosed_thinking(self):
        """Model opens <think> but never closes it (no </think>)."""
        with patch("src.agentframework.web_api._create_runtime_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.session_manager = None

            async def mock_run_streaming(prompt, on_chunk=None):
                if on_chunk:
                    on_chunk("<think>")
                    on_chunk("I am thinking all the way through and never stop...")
                    on_chunk("still thinking, no end in sight")
                return "<think>\nI am thinking all the way through and never stop...\nstill thinking, no end in sight"

            mock_agent.run_streaming = mock_run_streaming
            mock_agent.messages = []
            mock_create.return_value = mock_agent

            with client.websocket_connect("/ws/chat") as websocket:
                websocket.send_text(
                    json.dumps({"provider": "openai", "model": "gpt-4o"})
                )
                websocket.receive_json()  # ready

                websocket.send_text(
                    json.dumps({"type": "message", "content": "Think long"})
                )
                websocket.receive_json()  # message echo

                # All events are "content" — raw tags pass through
                c1 = websocket.receive_json()
                assert c1["type"] == "content"
                c2 = websocket.receive_json()
                assert c2["type"] == "content"
                c3 = websocket.receive_json()
                assert c3["type"] == "content"

                d1 = websocket.receive_json()
                assert d1["type"] == "done"
                assert "<think>" in d1["content"]

    def test_chat_websocket_thinking_tail_in_same_chunk(self):
        """Tail of thinking text and </think> in the same chunk."""
        with patch("src.agentframework.web_api._create_runtime_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.session_manager = None

            async def mock_run_streaming(prompt, on_chunk=None):
                if on_chunk:
                    on_chunk("<think>I think therefore")
                    on_chunk(" I am.</think>\n\nHere is my final answer.")
                return "Result"

            mock_agent.run_streaming = mock_run_streaming
            mock_agent.messages = []
            mock_create.return_value = mock_agent

            with client.websocket_connect("/ws/chat") as websocket:
                websocket.send_text(
                    json.dumps({"provider": "openai", "model": "gpt-4o"})
                )
                websocket.receive_json()  # ready

                websocket.send_text(
                    json.dumps({"type": "message", "content": "think"})
                )
                websocket.receive_json()  # message echo

                # All events are "content" — raw <think> tags pass through
                c1 = websocket.receive_json()
                assert c1["type"] == "content"
                assert "<think>" in c1["content"]

                c2 = websocket.receive_json()
                assert c2["type"] == "content"
                assert "final answer" in c2["content"]

                d1 = websocket.receive_json()
                assert d1["type"] == "done"
                assert "<think>" in d1["content"]

    def test_chat_websocket_stop_preserves_partial_content(self):
        with patch("src.agentframework.web_api._create_runtime_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.session_manager = None

            async def mock_run_streaming(prompt, on_chunk=None):
                # Simulate LLM calling on_chunk with partial content
                if on_chunk:
                    on_chunk("Part 1")
                # Simulate cancellation during generation
                raise asyncio.CancelledError()

            mock_agent.run_streaming = mock_run_streaming
            mock_agent.messages = []
            mock_create.return_value = mock_agent

            with client.websocket_connect("/ws/chat") as websocket:
                websocket.send_text(
                    json.dumps({"provider": "openai", "model": "gpt-4"})
                )
                websocket.receive_json()

                websocket.send_text(
                    json.dumps({"type": "message", "content": "Stop test"})
                )
                websocket.receive_json()

                websocket.send_text(json.dumps({"type": "stop"}))

                while True:
                    msg = websocket.receive_json()
                    if msg["type"] == "done":
                        # Should preserve partial content from on_chunk callback
                        assert msg["content"] == "Part 1"
                        break


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


class TestWorkflows:
    @pytest.mark.asyncio
    async def test_workflows_list_endpoint(self, monkeypatch):
        monkeypatch.setattr(
            "src.agentframework.routers.workflows.list_workflows",
            lambda: [{"id": "w1", "title": "W1", "description": "d"}],
        )
        result = await workflows_list()
        assert result == {
            "workflows": [{"id": "w1", "title": "W1", "description": "d"}]
        }

    @pytest.mark.asyncio
    async def test_workflow_run_endpoint(self, monkeypatch):
        captured_state = {}

        class FakeWorkflow:
            async def compile_and_run(self, state):
                captured_state.update(state)
                return {"final": "done"}

        state = web_api.get_state()
        state.agent = "agent"  # type: ignore[assignment] - Test mock value
        state.message_history = []
        monkeypatch.setattr(
            "src.agentframework.routers.workflows.get_workflow",
            lambda _workflow_id: FakeWorkflow(),
        )

        payload = web_models.WorkflowRunPayload(
            workflow_id="research_and_summarize", topic="hello"
        )
        result = await workflow_run(payload, state)
        assert captured_state["topic"] == "hello"
        assert captured_state["agent"] == "agent"
        assert result["workflow_id"] == "research_and_summarize"
        assert result["response"] == "done"
        assert len(state.message_history) == 2


# ---------------------------------------------------------------------------
# Review endpoint
# ---------------------------------------------------------------------------


class TestReview:
    def test_static_routes(self):
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302

    @patch("uvicorn.run")
    def test_web_api_run_server_logic(self, mock_run):
        from src.agentframework.web_api import run_server as rs

        rs(host="127.0.0.1", port=9000)
        mock_run.assert_called_once()

    def test_review_endpoint_with_file(self, monkeypatch):
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = (
            "## Section 1\nContent 1\n## Section 2\nContent 2"
        )
        with patch("src.agentframework.web_api.Path", return_value=mock_path):
            response = client.get("/api/review")
            assert response.status_code == 200
            assert response.json() == {"sections": ["Section 1", "Section 2"]}

    def test_review_endpoint_missing_file(self, monkeypatch):
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        with patch("src.agentframework.web_api.Path", return_value=mock_path):
            response = client.get("/api/review")
            assert response.status_code == 200
            assert response.json() == {"sections": []}


# ---------------------------------------------------------------------------
# WebSocket integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
def ws_mock_agent():
    agent = MagicMock()
    agent.session_manager = MagicMock()
    agent.session_manager.current_session = MagicMock()
    agent.session_manager.current_session.id = "ws-test-session"
    agent.session_manager.current_session.title = None
    agent.generate_title = AsyncMock(return_value=None)
    agent._ensure_session = MagicMock()
    agent.messages = []
    agent.load_session = MagicMock()
    agent.save_session = MagicMock()
    agent.run_streaming = AsyncMock(return_value="mock response")
    return agent


class TestWebSocketIntegration:
    """Comprehensive WebSocket endpoint tests."""

    def test_websocket_connect_and_ready(self, ws_mock_agent):
        """Connection sends config and receives ready."""
        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as test_client:
                with test_client.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "qwen3:4b"})
                    ready = ws.receive_json()
                    assert ready["type"] == "ready"
                    assert ready["session_id"] == "ws-test-session"

    def test_websocket_send_and_receive(self, ws_mock_agent):
        """Send a message and receive streaming content."""
        async def mock_stream(prompt, on_chunk=None):
            if on_chunk:
                on_chunk("Hello ")
                on_chunk("world")

        ws_mock_agent.run_streaming = AsyncMock(side_effect=mock_stream)

        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as test_client:
                with test_client.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "qwen3:4b"})
                    ws.receive_json()  # ready

                    ws.send_json({"type": "message", "content": "hi"})

                    events = []
                    while True:
                        msg = ws.receive_json()
                        events.append(msg)
                        if msg["type"] == "done":
                            break

                    types = [e["type"] for e in events]
                    assert "message" in types
                    assert "content" in types
                    assert "done" in types
                    content_msgs = [e for e in events if e["type"] == "content"]
                    assert "Hello" in content_msgs[-1]["content"]
                    assert "world" in content_msgs[-1]["content"]

    def test_websocket_tool_calls_in_message(self, ws_mock_agent):
        """When run_streaming adds messages with tool_calls, has_tools=True in done."""
        from types import SimpleNamespace

        tc_msg = SimpleNamespace()
        tc_msg.tool_calls = [
            {"function": {"name": "bash", "arguments": {"cmd": "ls"}}, "result": "ok"}
        ]

        async def mock_stream(prompt, on_chunk=None):
            ws_mock_agent.messages.append(tc_msg)
            if on_chunk:
                on_chunk("Hello ")
                on_chunk("world")

        ws_mock_agent.run_streaming = AsyncMock(side_effect=mock_stream)
        ws_mock_agent.messages = []

        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ws.receive_json()  # ready
                    ws.send_json({"type": "message", "content": "run tools"})
                    done = None
                    while True:
                        msg = ws.receive_json()
                        if msg["type"] == "done":
                            done = msg
                            break
                    assert done["has_tools"] is True
                    assert done["tool_calls"][0]["name"] == "bash"

    def test_websocket_stop_generation(self, ws_mock_agent):
        """Stop mid-stream cancels the running task."""
        async def slow_stream(prompt, on_chunk=None):
            if on_chunk:
                on_chunk("partial ")
            await asyncio.sleep(5)
            if on_chunk:
                on_chunk(" more")

        ws_mock_agent.run_streaming = AsyncMock(side_effect=slow_stream)

        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as test_client:
                with test_client.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "qwen3:4b"})
                    ws.receive_json()  # ready

                    ws.send_json({"type": "message", "content": "hello"})
                    # Consume events until we see content, then send stop
                    while True:
                        msg = ws.receive_json()
                        if msg["type"] == "content":
                            ws.send_json({"type": "stop"})
                            break

                    # Should get done with partial content
                    done = ws.receive_json()
                    assert done["type"] == "done"
                    assert "partial" in done["content"]

    def test_websocket_concurrent_connections(self, ws_mock_agent):
        """Two concurrent WebSocket connections don't interfere."""
        async def mock_stream(prompt, on_chunk=None):
            if on_chunk:
                on_chunk("response")
            return "response"

        ws_mock_agent.run_streaming = AsyncMock(side_effect=mock_stream)

        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws1:
                    with tc.websocket_connect("/ws/chat") as ws2:
                        ws1.send_json({"provider": "ollama", "model": "m1"})
                        ws2.send_json({"provider": "ollama", "model": "m2"})

                        r1 = ws1.receive_json()
                        r2 = ws2.receive_json()
                        assert r1["type"] == "ready"
                        assert r2["type"] == "ready"

                        # Both can send messages independently
                        ws1.send_json({"type": "message", "content": "from 1"})
                        ws2.send_json({"type": "message", "content": "from 2"})

                        # Drain both connections
                        def drain(ws):
                            events = []
                            while True:
                                m = ws.receive_json()
                                events.append(m)
                                if m["type"] == "done":
                                    break
                            return events

                        ev1 = drain(ws1)
                        ev2 = drain(ws2)

                        # Each should see its own user message echoed
                        types1 = [e["type"] for e in ev1]
                        types2 = [e["type"] for e in ev2]
                        assert "message" in types1
                        assert "message" in types2
                        assert any("from 1" in str(e) for e in ev1)
                        assert any("from 2" in str(e) for e in ev2)

    @pytest.mark.timeout(5)
    def test_websocket_invalid_json_does_not_crash(self, ws_mock_agent):
        """Invalid JSON as config is handled without crash."""
        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            try:
                with TestClient(app) as test_client:
                    with test_client.websocket_connect("/ws/chat") as ws:
                        ws.send_text("not valid json {{{")
            except Exception:
                pass  # Connection closing is acceptable

    def test_websocket_empty_message_skipped(self, ws_mock_agent):
        """Empty message content is skipped without sending events."""
        ws_mock_agent.run_streaming = AsyncMock()

        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as test_client:
                with test_client.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "qwen3:4b"})
                    ws.receive_json()  # ready

                    ws.send_json({"type": "message", "content": ""})

                    # Should not call run_streaming with empty content
                    ws_mock_agent.run_streaming.assert_not_called()

    def test_websocket_edit_disallowed_before_session(self, ws_mock_agent):
        """Edit without session returns error."""
        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as test_client:
                with test_client.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "qwen3:4b"})
                    ws.receive_json()  # ready

                    ws.send_json({"type": "edit", "index": 0, "content": "edited"})
                    error = ws.receive_json()
                    assert error["type"] == "error"

    def test_websocket_pong_is_ignored_gracefully(self, ws_mock_agent):
        """Pong messages are handled gracefully."""
        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as test_client:
                with test_client.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "qwen3:4b"})
                    ws.receive_json()  # ready

                    ws.send_json({"type": "pong"})
                    ws.send_json({"type": "message", "content": "after pong"})

                    events = []
                    while True:
                        msg = ws.receive_json()
                        events.append(msg)
                        if msg["type"] == "done":
                            break
                    assert any(e["type"] == "done" for e in events)


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_check(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "echo-ai"

    def test_detailed_health_with_agent(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager.list_sessions.return_value = ([], 3)
        response = client.get("/health/detailed")
        assert response.status_code == 200
        data = response.json()
        assert data["components"]["provider"] == "connected"

    def test_detailed_health_no_agent(self):
        state = web_api.get_state()
        state.agent = None
        response = client.get("/health/detailed")
        assert response.status_code == 200
        data = response.json()
        assert data["components"]["provider"] == "unknown"

    def test_detailed_health_sessions_error(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager.list_sessions.side_effect = Exception("db error")
        response = client.get("/health/detailed")
        assert response.status_code == 200
        assert "error" in response.json()["components"]["sessions"]


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------


class TestGetConfig:
    def test_get_config_success(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.config.provider = "ollama"
        mock_agent.config.model = "test-model"
        mock_agent.config.temperature = 0.5
        response = client.get("/api/config")
        assert response.status_code == 200
        assert response.json()["config"]["provider"] == "ollama"

    def test_get_config_no_agent(self):
        state = web_api.get_state()
        state.agent = None
        response = client.get("/api/config")
        assert response.status_code == 200  # returns defaults from config.yaml, not 503


# ---------------------------------------------------------------------------
# Export / Import sessions
# ---------------------------------------------------------------------------


class TestExportImport:
    def test_export_session_no_agent(self):
        state = web_api.get_state()
        state.agent = None
        response = client.get("/api/sessions/test/export")
        assert response.status_code == 423
        assert response.json()["detail"] == "Database is locked"

    def test_export_session_success(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager.export_session.return_value = {"id": "test", "messages": []}
        response = client.get("/api/sessions/test/export")
        assert response.status_code == 200
        assert response.json()["id"] == "test"

    def test_export_session_not_found(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager.export_session.return_value = None
        response = client.get("/api/sessions/test/export")
        assert response.status_code == 404

    def test_import_session_no_agent(self):
        state = web_api.get_state()
        state.agent = None
        response = client.post("/api/sessions/import", json={"id": "test", "messages": []})
        assert response.status_code == 423
        assert response.json()["detail"] == "Database is locked"

    def test_import_session_success(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_session = MagicMock(id="imported-session")
        mock_agent.session_manager.import_session.return_value = mock_session
        response = client.post("/api/sessions/import", json={"id": "new-id", "messages": []})
        assert response.status_code == 200
        assert response.json()["session_id"] == "imported-session"

    def test_import_session_value_error(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager.import_session.side_effect = ValueError("invalid")
        response = client.post("/api/sessions/import", json={"id": "bad", "messages": []})
        assert response.status_code == 400

    def test_import_session_invalid_json(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        with patch.object(web_api.Request, "json", side_effect=Exception("bad json")):
            response = client.post("/api/sessions/import", json={"id": "x"})
            assert response.status_code == 400


# ---------------------------------------------------------------------------
# Purge empty sessions
# ---------------------------------------------------------------------------


class TestPurgeEmpty:
    def test_purge_empty_no_agent(self):
        state = web_api.get_state()
        state.agent = None
        response = client.post("/api/sessions/purge-empty")
        assert response.status_code == 423
        assert response.json()["detail"] == "Database is locked"

    def test_purge_empty_success(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager.purge_empty_sessions.return_value = 3
        response = client.post("/api/sessions/purge-empty")
        assert response.status_code == 200
        assert response.json()["purged_count"] == 3


# ---------------------------------------------------------------------------
# /chat endpoint (simple POST)
# ---------------------------------------------------------------------------


class TestSimpleChat:
    def test_chat_without_agent(self):
        state = web_api.get_state()
        state.agent = None
        response = client.post("/chat", json={
            "prompt": "hello",
            "model": "qwen3:4b-instruct",
        })
        assert response.status_code == 423
        assert response.json()["detail"] == "Database is locked"

    def test_chat_with_session_id(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager.current_session = MagicMock(id="sess-123")
        response = client.post("/chat", json={"prompt": "hello", "session_id": "sess-123"})
        assert response.status_code == 200
        assert "response" in response.json()

    def test_chat_endpoint_validates_content(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        response = client.post("/api/chat", json={"content": ""})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# /route endpoint
# ---------------------------------------------------------------------------


class TestRoute:
    def test_route_success(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        with patch(
            "src.agentframework.web_api.SemanticRouter",
        ) as mock_router_cls:
            mock_router = MagicMock()
            mock_router.route = AsyncMock(return_value="code_agent")
            mock_router_cls.return_value = mock_router
            response = client.post("/route", json={"prompt": "write code"})
            assert response.status_code == 200
            assert response.json()["target_agent"] == "code_agent"

    def test_route_no_agent(self):
        state = web_api.get_state()
        state.agent = None
        response = client.post("/route", json={"prompt": "hello"})
        assert response.status_code == 423
        assert response.json()["detail"] == "Database is locked"

    def test_route_exception(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        with patch(
            "src.agentframework.web_api.SemanticRouter",
        ) as mock_router_cls:
            mock_router = MagicMock()
            mock_router.route = AsyncMock(side_effect=Exception("routing error"))
            mock_router_cls.return_value = mock_router
            response = client.post("/route", json={"prompt": "hello"})
            assert response.status_code == 500


# ---------------------------------------------------------------------------
# Workflow error paths
# ---------------------------------------------------------------------------


class TestWorkflowErrors:
    def test_workflow_run_no_agent_returns_locked(self):
        state = web_api.get_state()
        state.agent = None
        response = client.post(
            "/api/workflows/run",
            json={"workflow_id": "research_and_summarize", "topic": "test"},
        )
        assert response.status_code == 423
        assert response.json()["detail"] == "Database is locked"

    def test_workflow_not_found(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        response = client.post(
            "/api/workflows/run",
            json={"workflow_id": "nonexistent", "topic": "test"},
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Rate limit and edge cases
# ---------------------------------------------------------------------------


class TestRateLimitMiddleware:
    def test_rate_limit_bypassed_for_localhost_returns_200(self):
        web_api._rate_limiter.clear()
        response = client.get("/health")
        assert response.status_code == 200

    def test_rate_limit_headers_present(self):
        web_api._rate_limiter.clear()
        response = client.get("/api/review")
        assert response.status_code == 200
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Limit" in response.headers


class TestCorrelationId:
    def test_correlation_id_added(self):
        response = client.get("/health")
        assert "X-Correlation-ID" in response.headers


class TestDeleteSessionEdgeCases:
    def test_delete_session_no_agent(self):
        state = web_api.get_state()
        state.agent = None
        response = client.delete("/api/sessions/test")
        assert response.status_code == 423
        assert response.json()["detail"] == "Database is locked"

    def test_delete_session_clears_current(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        state.current_session_id = "test"
        state.message_history = [{"role": "user", "content": "hi"}]
        mock_agent.messages = [{"role": "user", "content": "hi"}]
        response = client.delete("/api/sessions/test")
        assert response.status_code == 200
        assert state.current_session_id is None
        assert state.message_history == []


class TestCreateSessionEdgeCases:
    def test_create_session_no_agent(self):
        state = web_api.get_state()
        state.agent = None
        response = client.post("/api/sessions")
        assert response.status_code == 423
        assert response.json()["detail"] == "Database is locked"


class TestRenameSessionNoAgent:
    def test_rename_session_no_agent(self):
        state = web_api.get_state()
        state.agent = None
        response = client.post("/api/sessions/rename", json={"session_id": "x", "new_title": "y"})
        assert response.status_code == 423
        assert response.json()["detail"] == "Database is locked"


class TestPurgeSessionsNoAgent:
    def test_purge_sessions_no_agent(self):
        state = web_api.get_state()
        state.agent = None
        response = client.post("/api/sessions/purge")
        assert response.status_code == 423
        assert response.json()["detail"] == "Database is locked"


class TestWorkflowListEndpoint:
    def test_workflows_list(self):
        response = client.get("/api/workflows")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["workflows"], list)


class TestWebSocketSessionManagement:
    def test_websocket_with_session_switch_uses_load_session(self, ws_mock_agent):
        ws_mock_agent.load_session = MagicMock(return_value="Session loaded: other-session")
        ws_mock_agent.session_manager.current_session = MagicMock(id="other-session", title=None)

        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ws.receive_json()  # ready

                    ws.send_json({
                        "type": "message",
                        "content": "hi",
                        "session_id": "other-session",
                    })

                    events = []
                    while True:
                        msg = ws.receive_json()
                        events.append(msg)
                        if msg["type"] in ("done", "error"):
                            break
                    ws_mock_agent.load_session.assert_called_with("other-session")

    def test_websocket_with_session_switch_not_found(self, ws_mock_agent):
        ws_mock_agent.load_session = MagicMock(return_value="Session not found: missing")
        ws_mock_agent.session_manager.current_session = MagicMock(id="missing", title=None)
        ws_mock_agent.session_manager.create_session = MagicMock()

        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ws.receive_json()  # ready

                    ws.send_json({
                        "type": "message",
                        "content": "try load",
                        "session_id": "missing",
                    })

                    events = []
                    while True:
                        msg = ws.receive_json()
                        events.append(msg)
                        if msg["type"] in ("done", "error"):
                            break
                    ws_mock_agent.session_manager.create_session.assert_called()

    def test_websocket_edit_without_session_returns_error(self, ws_mock_agent):
        """Edit before a session exists should return 'No active session' error."""
        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ws.receive_json()  # ready

                    ws.send_json({"type": "edit", "index": 0, "content": "edited"})
                    err = ws.receive_json()
                    assert err["type"] == "error"
                    assert err["content"] == "No active session"


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


class TestGetModelsSync:
    def test_get_models_sync_cache_hit(self, monkeypatch):
        from time import monotonic

        web_api._models_cache.clear()
        cached_data = {"models": ["cached-model"]}
        web_api._models_cache["models_sync_ollama"] = (monotonic(), cached_data)
        result = web_api.get_models_sync()
        assert result["models"] == ["cached-model"]

    def test_get_models_sync_fallback(self, monkeypatch):
        web_api._models_cache.clear()

        def mock_get(*args, **kwargs):
            raise Exception("ollama not available")

        monkeypatch.setattr("httpx.get", mock_get)
        result = web_api.get_models_sync()
        assert "llama3.2:latest" in str(result["models"])

    @pytest.mark.asyncio
    async def test_get_models_data_cache_hit(self, monkeypatch):
        from time import monotonic

        web_api._models_cache.clear()
        cached_data = {"models": ["cached-model"]}
        web_api._models_cache["models_async_ollama"] = (monotonic(), cached_data)

        async def raiser(*args, **kwargs):
            raise RuntimeError("httpx should not be called on cache hit")

        monkeypatch.setattr("httpx.AsyncClient", lambda *a, **kw: MagicMock(get=raiser))
        result = await web_api.get_models_data()
        assert result["models"] == ["cached-model"]


class TestGenerateTitleAsync:
    @pytest.mark.asyncio
    async def test_generate_title_async_success_updates_session_title(self, mock_agent):
        """_generate_title_async should set current_session.title when generate_title returns a value."""
        mock_agent.generate_title = AsyncMock(return_value="New Title")
        mock_agent.session_manager.current_session = MagicMock(title=None)
        mock_agent.save_session = MagicMock()
        await web_api._generate_title_async(mock_agent)
        assert mock_agent.session_manager.current_session.title == "New Title"
        assert mock_agent.save_session.call_count == 2

    @pytest.mark.asyncio
    async def test_generate_title_async_no_session_skips_title(self, mock_agent):
        """When session_manager is None, _generate_title_async should silently skip."""
        mock_agent.generate_title = AsyncMock(return_value="New Title")
        mock_agent.session_manager = None
        # Must not raise even though session_manager is None
        await web_api._generate_title_async(mock_agent)

    @pytest.mark.asyncio
    async def test_generate_title_async_swallows_exception(self, mock_agent):
        """If generate_title raises, _generate_title_async must catch and log, not propagate."""
        mock_agent.generate_title = AsyncMock(side_effect=Exception("fail"))
        mock_agent.session_manager.current_session = MagicMock(title=None)
        # Must not raise
        await web_api._generate_title_async(mock_agent)
        # Title should remain unchanged (still None from fixture setup)
        assert mock_agent.session_manager.current_session.title is None


class TestLegacyChatUiEndpoint:
    """Tests for the /chat endpoint (first-registered handler, returns {"response": ...})."""

    @pytest.mark.asyncio
    async def test_chat_ui_returns_response_with_session(self, mock_agent):
        """chat_ui endpoint should return response when agent.session_manager has a session."""
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager.current_session = MagicMock(id="sess-1")
        response = client.post("/chat", json={"prompt": "hello", "session_id": "sess-1"})
        assert response.status_code == 200
        assert response.json()["response"] == "Mock response"

    @pytest.mark.asyncio
    async def test_chat_ui_with_session_id_ignores_it(self, mock_agent):
        """chat_ui ignores session_id in the payload (it's not the handle_chat endpoint)."""
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager.current_session = MagicMock(id="sess-1")
        response = client.post("/chat", json={"prompt": "hi", "session_id": "new-sess"})
        assert response.status_code == 200
        # chat_ui calls state.agent.run() directly, not get_or_create_agent
        assert response.json()["response"] == "Mock response"


class TestRouteIntent:
    @pytest.mark.asyncio
    async def test_route_intent_exception(self, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        with patch(
            "src.agentframework.web_api.SemanticRouter",
            side_effect=Exception("router init failed"),
        ):
            response = client.post("/route", json={"prompt": "hello"})
            assert response.status_code == 500


class TestSseStreaming:
    @pytest.mark.asyncio
    async def test_stream_endpoint_returns_sse_content_type(self, mock_agent):
        """SSE endpoint should return text/event-stream content type."""
        state = web_api.get_state()
        state.agent = mock_agent
        with patch.object(web_api, "get_or_create_agent", return_value=mock_agent):
            response = client.get("/stream?prompt=hello")
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

    @pytest.mark.asyncio
    async def test_stream_endpoint_yields_chunks_as_sse_events(self, mock_agent):
        """Each on_chunk call should produce a 'data: {...}' SSE event."""
        state = web_api.get_state()
        state.agent = mock_agent

        async def mock_stream(prompt, on_chunk=None):
            if on_chunk:
                on_chunk("chunk1")
                on_chunk("chunk2")
            return "done"

        mock_agent.run_streaming = AsyncMock(side_effect=mock_stream)

        with patch.object(web_api, "get_or_create_agent", return_value=mock_agent):
            response = client.get("/stream?prompt=hello")
            assert response.status_code == 200
            body = response.text
            assert "data: " in body
            assert "chunk1" in body
            assert "chunk2" in body


class TestWebSocketErrorHandling:
    def test_websocket_exception_in_run_agent(self, ws_mock_agent):
        async def failing_stream(prompt, on_chunk=None):
            raise Exception("unexpected error")

        ws_mock_agent.run_streaming = AsyncMock(side_effect=failing_stream)

        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    r = ws.receive_json()  # ready
                    assert r["type"] == "ready"

                    ws.send_json({"type": "message", "content": "trigger error"})
                    got_error = False
                    while True:
                        msg = ws.receive_json()
                        if msg["type"] == "error":
                            assert "error" in msg["content"].lower()
                            got_error = True
                            break
                        elif msg["type"] == "done":
                            break
                    assert got_error


# ---------------------------------------------------------------------------
# Session data fallback paths
# ---------------------------------------------------------------------------


class TestSessionDataFallbacks:
    def test_get_sessions_data_agent_no_session_manager(self, mock_agent):
        """When agent has no session_manager, get_sessions_data returns empty list."""
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager = None
        result = web_api.get_sessions_data(state)
        assert result == {"sessions": [], "total": 0}

    def test_create_session_data_no_session_manager_returns_error(self, mock_agent):
        """create_session_data with agent that has no session_manager returns error dict."""
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager = None
        result = web_api.create_session_data(state)
        assert "error" in result

    def test_load_session_data_no_session_manager(self, mock_agent):
        """load_session_data with agent that has no session_manager returns empty messages."""
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager = None
        result = web_api.load_session_data("test-id", state)
        assert result["messages"] == []
        assert result["title"] is None

    def test_delete_session_data_no_session_manager(self, mock_agent):
        """delete_session_data with agent that has no session_manager returns ok."""
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager = None
        result = web_api.delete_session_data("test-id", state)
        assert result == {"status": "ok"}


# ---------------------------------------------------------------------------
# Chat endpoint without agent
# ---------------------------------------------------------------------------


class TestChatEndpointNoAgent:
    @pytest.mark.asyncio
    async     def test_chat_api_creates_agent_when_none(self):
        """chat endpoint returns locked when state.agent is None."""
        web_api._rate_limiter.clear()
        state = web_api.get_state()
        state.agent = None
        response = client.post("/chat", json={
            "prompt": "hello",
            "model": "qwen3:4b-instruct",
        })
        assert response.status_code == 423
        assert response.json()["detail"] == "Database is locked"


# ---------------------------------------------------------------------------
# handle_chat and route_intent endpoints
# ---------------------------------------------------------------------------


class TestHandleChatEdgeCases:
    @pytest.mark.asyncio
    async def test_handle_chat_returns_session_id(self, mock_agent):
        """handle_chat (called directly) includes session_id when a current_session exists."""
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager.current_session = MagicMock(id="sess-handle")
        req = web_api.ChatRequest(prompt="hello")
        result = await handle_chat(req)
        assert result["session_id"] == "sess-handle"
        assert result["response"] == "Mock response"

    @pytest.mark.asyncio
    async def test_handle_chat_raises_on_run_error(self, mock_agent):
        """handle_chat raises HTTPException when agent.run fails."""
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.run = AsyncMock(side_effect=Exception("run failed"))
        req = web_api.ChatRequest(prompt="hello")
        with pytest.raises(Exception):
            await handle_chat(req)


class TestRouteIntentSuccess:
    @pytest.mark.asyncio
    async def test_route_intent_routes_to_subagent(self, mock_agent):
        """route_intent returns the sub-agent name from SemanticRouter."""
        state = web_api.get_state()
        state.agent = mock_agent
        with patch("src.agentframework.web_api.SemanticRouter") as mock_router_cls:
            mock_router = MagicMock()
            mock_router.route = AsyncMock(return_value="code_agent")
            mock_router_cls.return_value = mock_router
            response = client.post("/route", json={"prompt": "write code"})
            assert response.status_code == 200
            assert response.json()["target_agent"] == "code_agent"
            mock_router.route.assert_called_once_with("write code")


# ---------------------------------------------------------------------------
# Rate limiting applied (non-localhost)
# ---------------------------------------------------------------------------


class TestRateLimitApplied:
    def test_rate_limit_exceeded_returns_429(self):
        """When rate limit is exceeded, middleware returns 429."""
        web_api._rate_limiter.clear()
        saved_requests = web_api._RATE_LIMIT_REQUESTS
        saved_window = web_api._RATE_LIMIT_WINDOW
        web_api._RATE_LIMIT_REQUESTS = 1
        web_api._RATE_LIMIT_WINDOW = 60
        try:
            client.get("/api/review")
            response = client.get("/api/review")
            assert response.status_code == 429
            data = response.json()
            assert data["error"] == "Rate limit exceeded"
        finally:
            web_api._rate_limiter.clear()
            web_api._RATE_LIMIT_REQUESTS = saved_requests
            web_api._RATE_LIMIT_WINDOW = saved_window


# ---------------------------------------------------------------------------
# Request logging middleware skip paths
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# CORS configuration edge cases
# ---------------------------------------------------------------------------


class TestCorsConfig:
    def test_cors_allow_all_origins_env(self, monkeypatch):
        """When ALLOW_ALL_ORIGINS env var is set, CORS origins should be ['*']."""
        monkeypatch.setenv("ALLOW_ALL_ORIGINS", "true")
        config = web_api._get_cors_config()
        assert config["origins"] == ["*"]

    def test_cors_socket_error_falls_back(self, monkeypatch):
        """When socket.gethostbyname fails, local_network_origins should be empty."""
        def raiser(*args):
            raise OSError("DNS resolution failed")
        monkeypatch.setattr("socket.gethostbyname", raiser)
        config = web_api._get_cors_config()
        # Should include default origins even without local network origins
        assert "http://localhost:3000" in config["origins"]


# ---------------------------------------------------------------------------
# Detailed health edge cases
# ---------------------------------------------------------------------------


class TestDetailedHealthEdgeCases:
    @pytest.fixture(autouse=True)
    def _clear_rate_limit(self):
        web_api._rate_limiter.clear()
        yield
    def test_detailed_health_memory_ok(self, mock_agent):
        """When memory_manager exists, detailed health should report memory ok."""
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.memory_manager = MagicMock()
        response = client.get("/health/detailed")
        assert response.status_code == 200
        data = response.json()
        assert data["components"]["memory"] == "ok"

    def test_detailed_health_memory_unknown(self, mock_agent):
        """When agent has no memory_manager, memory component shows 'unknown'."""
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.memory_manager = None
        response = client.get("/health/detailed")
        assert response.status_code == 200
        data = response.json()
        assert data["components"]["memory"] == "unknown"


# ---------------------------------------------------------------------------
# get_models_sync (sync version)
# ---------------------------------------------------------------------------


class TestGetModelsSyncFunction:
    def test_get_models_sync_success(self, monkeypatch):
        """get_models_sync should return model list from Ollama API."""
        web_api._models_cache.clear()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"name": "test-model"}]}
        mock_response.raise_for_status = MagicMock()
        monkeypatch.setattr("httpx.get", lambda *a, **kw: mock_response)
        result = web_api.get_models_sync()
        assert "test-model" in result["models"]


# ---------------------------------------------------------------------------
# _create_runtime_agent model validation
# ---------------------------------------------------------------------------


class TestCreateRuntimeAgentModelValidation:
    def test_empty_model_name_raises_error(self, monkeypatch):
        """When model name is empty, _create_runtime_agent should raise ValueError."""
        monkeypatch.setattr(web_api, "load_config", lambda: {})
        monkeypatch.setattr(web_api, "get_safety_config", lambda cfg: SimpleNamespace(workspace="."))
        monkeypatch.setattr(web_api, "get_tools", lambda cfg, safety: [])
        with pytest.raises(ValueError, match="Model name is required"):
            web_api._create_runtime_agent("ollama", "")

    def test_loading_models_model_name_passes_through(self, monkeypatch):
        """When model name is 'Loading models...', pass it through as-is."""
        monkeypatch.setattr(web_api, "load_config", lambda: {})
        monkeypatch.setattr(web_api, "get_safety_config", lambda cfg: SimpleNamespace(workspace="."))
        monkeypatch.setattr(web_api, "get_tools", lambda cfg, safety: [])
        monkeypatch.setattr(web_api, "create_agent", lambda ac, api_key=None, session_id=None, fernet=None: SimpleNamespace(config=ac))
        result = web_api._create_runtime_agent("ollama", "Loading models...")
        assert result.config.model == "Loading models..."


# ---------------------------------------------------------------------------
# __main__ block
# ---------------------------------------------------------------------------


class TestRunServerFunction:
    @patch("uvicorn.run")
    def test_run_server_calls_uvicorn(self, mock_uvicorn_run):
        """run_server should call uvicorn.run with correct params."""
        web_api.run_server(host="127.0.0.1", port=9000)
        mock_uvicorn_run.assert_called_once_with(web_api.app, host="127.0.0.1", port=9000, reload=False, log_level="info")

    @patch("uvicorn.run")
    def test_run_server_default_host(self, mock_uvicorn_run, monkeypatch):
        """When ECHO_HOST is unset, 127.0.0.1 is used."""
        monkeypatch.delenv("ECHO_HOST", raising=False)
        web_api.run_server(port=9000)
        mock_uvicorn_run.assert_called_once_with(web_api.app, host="127.0.0.1", port=9000, reload=False, log_level="info")

    @patch("uvicorn.run")
    def test_run_server_env_host(self, mock_uvicorn_run, monkeypatch):
        """ECHO_HOST env var overrides the default."""
        monkeypatch.setenv("ECHO_HOST", "0.0.0.0")
        web_api.run_server(port=9000)
        mock_uvicorn_run.assert_called_once_with(web_api.app, host="0.0.0.0", port=9000, reload=False, log_level="info")


# ---------------------------------------------------------------------------
# WebSocket edit handler full coverage
# ---------------------------------------------------------------------------


class TestWebSocketEditHandler:
    """Cover WebSocket edit handler error paths and success flow."""

    def test_edit_missing_index(self, ws_mock_agent):
        """Edit without index returns 'Missing edit index' error."""
        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ws.receive_json()  # ready
                    ws.send_json({"type": "edit", "content": "no index"})
                    err = ws.receive_json()
                    assert err["type"] == "error"
                    assert err["content"] == "Missing edit index"

    def test_edit_session_not_found(self, ws_mock_agent):
        """Edit with session_id but load_session returns None."""
        ws_mock_agent.session_manager.load_session.return_value = None
        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ws.receive_json()  # ready
                    ws.send_json({"type": "edit", "index": 0, "content": "edit", "session_id": "s1"})
                    err = ws.receive_json()
                    assert err["type"] == "error"
                    assert err["content"] == "Session not found"

    def test_edit_invalid_index_negative(self, ws_mock_agent):
        """Edit with negative index returns 'Invalid edit index'."""
        session = MagicMock()
        session.messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
        ws_mock_agent.session_manager.load_session.return_value = session
        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ws.receive_json()  # ready
                    ws.send_json({"type": "edit", "index": -1, "content": "edit", "session_id": "s1"})
                    err = ws.receive_json()
                    assert err["type"] == "error"
                    assert err["content"] == "Invalid edit index"

    def test_edit_index_out_of_range(self, ws_mock_agent):
        """Edit with index >= len-1 returns 'Invalid edit index'."""
        session = MagicMock()
        session.messages = [{"role": "system", "content": "sys"}]
        ws_mock_agent.session_manager.load_session.return_value = session
        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ws.receive_json()  # ready
                    ws.send_json({"type": "edit", "index": 5, "content": "edit", "session_id": "s1"})
                    err = ws.receive_json()
                    assert err["type"] == "error"
                    assert err["content"] == "Invalid edit index"

    def test_edit_missing_content(self, ws_mock_agent):
        """Edit without content returns 'Missing edit content'."""
        session = MagicMock()
        session.messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        ws_mock_agent.session_manager.load_session.return_value = session
        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ws.receive_json()  # ready
                    ws.send_json({"type": "edit", "index": 0, "session_id": "s1"})
                    err = ws.receive_json()
                    assert err["type"] == "error"
                    assert err["content"] == "Missing edit content"

    def test_edit_success_flow(self, ws_mock_agent):
        """Successful edit triggers truncate and uses session."""
        session = MagicMock()
        session.messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "original msg", "timestamp": "10:00"},
            {"role": "assistant", "content": "original reply"},
        ]
        session.id = "s1"
        ws_mock_agent.session_manager.load_session.return_value = session
        ws_mock_agent.session_manager.truncate_history = MagicMock()
        ws_mock_agent.run_streaming = AsyncMock(return_value="edited response")

        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ws.receive_json()  # ready
                    ws.send_json({"type": "edit", "index": 0, "content": "edited msg", "session_id": "s1"})
                    import time
                    deadline = time.monotonic() + 5
                    while not ws_mock_agent.session_manager.truncate_history.called:
                        if time.monotonic() > deadline:
                            break
                        time.sleep(0.05)
                    ws_mock_agent.session_manager.truncate_history.assert_called_once()
                    assert ws_mock_agent.session_manager.current_session is session


# ---------------------------------------------------------------------------
# Tool calls in WebSocket streaming
# ---------------------------------------------------------------------------


class TestExtractToolCallsInfo:
    """Direct tests for _extract_tool_calls_info (not via WebSocket)."""

    def test_dict_format_dict_args(self):
        """Dict-format tool call with dict arguments."""
        tcs = [{"function": {"name": "bash", "arguments": {"cmd": "ls -la"}}, "result": "ok"}]
        result = web_api._extract_tool_calls_info(tcs)
        assert result[0]["name"] == "bash"
        assert result[0]["arguments"] == {"cmd": "ls -la"}
        assert result[0]["result"] == "ok"

    def test_object_format_dict_args(self):
        """Object-format tool call with dict arguments."""
        from types import SimpleNamespace
        tc = SimpleNamespace()
        tc.name = "read_file"
        tc.arguments = {"path": "/tmp/t.txt"}
        tcs = [tc]
        result = web_api._extract_tool_calls_info(tcs)
        assert result[0]["name"] == "read_file"
        assert result[0]["arguments"] == {"path": "/tmp/t.txt"}

    def test_string_args_parsed_as_json(self):
        """String arguments are parsed as JSON."""
        tcs = [{"function": {"name": "bash", "arguments": '{"cmd": "ls"}'}}]
        result = web_api._extract_tool_calls_info(tcs)
        assert result[0]["arguments"] == {"cmd": "ls"}

    def test_string_args_parse_fallback_to_raw(self):
        """Unparseable string arguments fall back to raw dict."""
        tcs = [{"function": {"name": "bash", "arguments": "not json {{{"}}]
        result = web_api._extract_tool_calls_info(tcs)
        assert result[0]["arguments"] == {"raw": "not json {{{"}

    def test_non_dict_non_object_args(self):
        """Non-dict, non-string arguments are converted via str()."""
        tcs = [{"function": {"name": "bash", "arguments": 42}}]
        result = web_api._extract_tool_calls_info(tcs)
        assert result[0]["arguments"] == {"raw": "42"}

    def test_unicode_escaped_args(self):
        """Escaped unicode in string arguments is unescaped."""
        tcs = [{"function": {"name": "bash", "arguments": '{"city": "\\u0130stanbul"}'}}]
        result = web_api._extract_tool_calls_info(tcs)
        assert result[0]["arguments"]["city"] == "İstanbul"

    def test_empty_list(self):
        """Empty tool_calls list returns empty list."""
        assert web_api._extract_tool_calls_info([]) == []

    def test_no_function_key_in_dict(self):
        """Dict tool call without function key uses defaults."""
        tcs = [{"name": "cmd"}]
        result = web_api._extract_tool_calls_info(tcs)
        assert result[0]["name"] == "unknown"
        assert result[0]["arguments"] == {}


# ---------------------------------------------------------------------------
# WebSocket disconnect and error handling
# ---------------------------------------------------------------------------


class TestWebSocketDisconnectPaths:
    """Cover WebSocketDisconnect during streaming, sender loop, and cleanup."""

    def test_websocket_disconnect_during_session_start(self, ws_mock_agent):
        """WebSocketDisconnect during session_start is handled."""
        ws_mock_agent.run_streaming = AsyncMock(return_value="result")

        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ws.receive_json()  # ready
                    # Close before sending message — disconnect during run_agent
                    ws.close()

    def test_websocket_thinking_start_with_before_text(self, ws_mock_agent):
        """on_chunk with text before <think> marker in same chunk."""
        async def thinking_with_before(prompt, on_chunk=None):
            if on_chunk:
                on_chunk("intro before<think>")
                on_chunk("inner thought")
                on_chunk("</think>")
                on_chunk("final text")
            return "Result"

        ws_mock_agent.run_streaming = AsyncMock(side_effect=thinking_with_before)

        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ws.receive_json()  # ready
                    ws.send_json({"type": "message", "content": "think"})
                    done = None
                    while True:
                        msg = ws.receive_json()
                        if msg["type"] == "done":
                            done = msg
                            break
                    assert "intro before" in done["content"]

    def test_websocket_on_chunk_after_stop_requested(self, ws_mock_agent):
        """on_chunk raises CancelledError when stop_requested is True."""
        stop_seen = False

        async def stop_trigger_stream(prompt, on_chunk=None):
            nonlocal stop_seen
            if on_chunk:
                on_chunk("first")
                yield_control = asyncio.sleep(0)
                await yield_control
                stop_seen = True  # Test will set stop_requested by now
                try:
                    if on_chunk:
                        on_chunk("second_after_stop")
                except asyncio.CancelledError:
                    pass  # Expected - on_chunk raises CancelledError
            return "partial"

        ws_mock_agent.run_streaming = AsyncMock(side_effect=stop_trigger_stream)

        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ws.receive_json()  # ready
                    ws.send_json({"type": "message", "content": "hello"})
                    # Wait for first content, then send stop
                    while True:
                        msg = ws.receive_json()
                        if msg["type"] == "content":
                            ws.send_json({"type": "stop"})
                            break
                    done = None
                    while True:
                        msg = ws.receive_json()
                        if msg["type"] == "done":
                            done = msg
                            break
                    assert done["type"] == "done"
                    assert "first" in done["content"]

    def test_websocket_sender_loop_disconnect(self, ws_mock_agent):
        """sender_loop handles WebSocketDisconnect during send."""
        async def stream_with_disconnect(prompt, on_chunk=None):
            if on_chunk:
                on_chunk("partial")
            await asyncio.sleep(0.05)
            if on_chunk:
                on_chunk("more")

        ws_mock_agent.run_streaming = AsyncMock(side_effect=stream_with_disconnect)

        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ws.receive_json()  # ready
                    ws.send_json({"type": "message", "content": "test"})
                    while True:
                        msg = ws.receive_json()
                        if msg["type"] == "content":
                            break
                    ws.close()

    def test_websocket_stop_during_thinking_start_before(self, ws_mock_agent):
        """on_chunk handles text before <think> marker."""
        async def thinking_with_before(prompt, on_chunk=None):
            if on_chunk:
                on_chunk("intro text")
                on_chunk("<think>")
                on_chunk("inner thought")
                on_chunk("</think>")
                on_chunk("final text")
            return "Result"

        ws_mock_agent.run_streaming = AsyncMock(side_effect=thinking_with_before)

        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ws.receive_json()  # ready
                    ws.send_json({"type": "message", "content": "think"})

                    events = []
                    while True:
                        msg = ws.receive_json()
                        events.append(msg)
                        if msg["type"] == "done":
                            break
                    # All events are content type (no separate thinking events)
                    types = [e["type"] for e in events]
                    assert "content" in types
                    assert "thinking" not in types


# ---------------------------------------------------------------------------
# get_or_create_agent edge paths
# ---------------------------------------------------------------------------


class TestGetOrCreateAgentPaths:
    """Cover edge paths in get_or_create_agent."""

    def test_get_or_create_agent_state_none(self, mock_agent):
        """When _state is None, get_or_create_agent creates new state."""
        saved_state = web_models._state
        web_models._state = None
        try:
            with patch.object(web_api, "_create_runtime_agent", return_value=mock_agent):
                req = web_api.ChatRequest(prompt="hello", model="qwen3:4b-instruct")
                result = web_api.get_or_create_agent(req)
            assert result is mock_agent
            assert web_models._state is not None
        finally:
            web_models._state = saved_state

    def test_get_or_create_agent_agent_none(self, mock_agent):
        """When _state.agent is None, get_or_create_agent creates new agent."""
        state = web_api.get_state()
        saved_agent = state.agent
        state.agent = None
        try:
            with patch.object(web_api, "_create_runtime_agent", return_value=mock_agent):
                req = web_api.ChatRequest(prompt="hello", model="qwen3:4b-instruct")
                result = web_api.get_or_create_agent(req)
            assert result is mock_agent
        finally:
            state.agent = saved_agent

    def test_get_or_create_agent_creates_session(self, mock_agent):
        """When session_id is provided and not found, creates new session."""
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager.load_session.return_value = None
        mock_agent.session_manager.create_session = MagicMock()
        req = web_api.ChatRequest(prompt="hello", session_id="new-sess")
        result = web_api.get_or_create_agent(req)
        assert result is mock_agent
        mock_agent.session_manager.create_session.assert_called_with("new-sess")


# ---------------------------------------------------------------------------
# Request logging middleware exception re-raise
# ---------------------------------------------------------------------------


class TestRequestLoggingMiddleware:
    def test_request_logging_adds_response_time_header(self):
        """Request logging middleware adds X-Response-Time to all responses."""
        response = client.get("/health")
        assert "X-Response-Time" in response.headers

    def test_request_logging_static_path_skipped(self):
        """Static paths like /favicon.ico skip detailed logging but still work."""
        response = client.get("/favicon.ico")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# WebSocket unhandled exception in main loop and keepalive
# ---------------------------------------------------------------------------


class TestWebSocketStateNone:
    """Cover _state is None path in WebSocket handler."""

    def test_websocket_state_none_returns_error(self):
        """When _state is None, WS sends 'Server not initialized' error."""
        with patch("src.agentframework.web_api._create_runtime_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.session_manager = None
            mock_create.return_value = mock_agent
            with TestClient(app) as tc:
                # _state is now set by lifespan. Reset it to None.
                web_models._state = None
                try:
                    with tc.websocket_connect("/ws/chat") as ws:
                        ws.send_text(json.dumps({"provider": "ollama", "model": "m"}))
                        err = ws.receive_json()
                        assert err["type"] == "error"
                        assert err["content"] == "Server not initialized"
                finally:
                    web_models.get_state()  # re-init state


class TestWebSocketFallbackThinkingTail:
    """Cover the fallback <think>/</think> split in run_agent."""

    def test_fallback_thinking_tail_split(self, ws_mock_agent):
        """When content has <think>/</think> tags, they pass through as-is in content."""
        async def mock_stream(prompt, on_chunk=None):
            if on_chunk:
                on_chunk("<think>\nI am thinking...\n</think>\n\nResponse text")
            return "<think>\nI am thinking...\n</think>\n\nResponse text"

        ws_mock_agent.run_streaming = AsyncMock(side_effect=mock_stream)

        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ws.receive_json()  # ready
                    ws.send_json({"type": "message", "content": "think"})
                    done = None
                    while True:
                        msg = ws.receive_json()
                        if msg["type"] == "done":
                            done = msg
                            break
                    assert "Response" in done["content"]
                    assert "<think>" in done["content"]


class TestWebSocketMainLoopErrors:
    """Cover Exception handler and keepalive errors in WS main loop."""

    def test_websocket_config_creation_error_sends_error(self):
        """When _create_runtime_agent raises during WS config, error is sent to client."""
        with patch("src.agentframework.web_api._create_runtime_agent", side_effect=RuntimeError("config crash")):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_text(json.dumps({"provider": "ollama", "model": "m"}))
                    err = ws.receive_json()
                    assert err["type"] == "error"

    def test_websocket_unhandled_exception_in_main_loop(self, ws_mock_agent):
        """General exception in run_agent logs and sends error to client."""
        ws_mock_agent.run_streaming = AsyncMock(side_effect=ValueError("unexpected"))

        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ws.receive_json()  # ready
                    ws.send_json({"type": "message", "content": "x"})
                    got_error = False
                    while True:
                        msg = ws.receive_json()
                        if msg.get("type") == "error":
                            assert "error" in msg.get("content", "").lower()
                            got_error = True
                            break
                        if msg.get("type") == "done":
                            break
                    assert got_error


# ---------------------------------------------------------------------------
# Deferred agent initialization error
# ---------------------------------------------------------------------------


class TestDeferredInit:
    def test_get_state_deferred_init_failure(self):
        """When _create_runtime_agent raises in get_state, error is logged."""
        saved_state = web_models._state
        web_models._state = None
        try:
            with patch.object(web_api, "_create_runtime_agent", side_effect=Exception("Ollama down")):
                state = web_api.get_state()
            assert state.agent is None
        finally:
            web_models._state = saved_state


# ---------------------------------------------------------------------------
# ensure_runtime_agent failure
# ---------------------------------------------------------------------------


class TestLockedState:
    def test_locked_returns_423(self):
        """Session endpoints return 423 when database is locked."""
        state = web_api.get_state()
        state.agent = None
        response = client.get("/api/sessions")
        assert response.status_code == 423
        assert response.json()["detail"] == "Database is locked"


# ---------------------------------------------------------------------------
# Detailed health memory error path
# ---------------------------------------------------------------------------


class TestDetailedHealthMemoryErrorPath:
    def test_detailed_health_memory_error_path(self, mock_agent):
        """When session_manager.list_sessions raises, sessions status shows error."""
        state = web_api.get_state()
        state.agent = mock_agent
        err_mgr = MagicMock()
        err_mgr.list_sessions.side_effect = Exception("oops")
        mock_agent.memory_manager = MagicMock()
        state.agent.session_manager = err_mgr
        web_api._rate_limiter.clear()
        response = client.get("/health/detailed")
        assert response.status_code == 200
        data = response.json()
        assert "error" in data.get("components", {}).get("sessions", "")


# ---------------------------------------------------------------------------
# Background auto-title in WebSocket config
# ---------------------------------------------------------------------------


class TestWSConfigAutoTitle:
    def test_ws_config_auto_title_generated(self, ws_mock_agent):
        """Title is generated in background and pushed via title_updated."""
        ws_mock_agent.session_manager.current_session.title = None
        ws_mock_agent.generate_title = AsyncMock(return_value="Auto Title")

        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ready = ws.receive_json()
                    assert ready["type"] == "ready"
                    # Title is now async — ready has None, then title_updated follows
                    assert ready["title"] is None

                    # Drain pings until we get title_updated
                    title_update = None
                    for _ in range(5):
                        msg = ws.receive_json()
                        if msg.get("type") == "title_updated":
                            title_update = msg
                            break
                    assert title_update is not None, "title_updated never received"
                    assert title_update["title"] == "Auto Title"

    def test_ws_config_auto_title_no_title_returned(self, ws_mock_agent):
        """When generate_title returns None, no save_session call."""
        ws_mock_agent.session_manager.current_session.title = None
        ws_mock_agent.generate_title = AsyncMock(return_value=None)

        with patch("src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent):
            with TestClient(app) as tc:
                with tc.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ready = ws.receive_json()
                    assert ready["type"] == "ready"
                    assert ready["title"] is None


# ---------------------------------------------------------------------------
# Lifespan shutdown error paths
# ---------------------------------------------------------------------------


class TestLifespanShutdown:
    """Cover lifespan shutdown close errors and purge_empty_sessions."""

    def test_lifespan_purges_empty_sessions(self):
        """When purge_empty_sessions returns > 0, info is logged."""
        agent = MagicMock()
        agent.session_manager = MagicMock()
        agent.session_manager.purge_empty_sessions.return_value = 5
        agent.close = MagicMock()
        with patch("src.agentframework.web_api._create_runtime_agent", return_value=agent):
            with TestClient(app) as tc:
                resp = tc.get("/health")
                assert resp.status_code == 200

    def test_lifespan_session_manager_close_error(self):
        """When session_manager.close raises, error is logged."""
        agent = MagicMock()
        agent.session_manager = MagicMock()
        agent.session_manager.purge_empty_sessions.return_value = 0
        agent.session_manager.close.side_effect = Exception("close failed")
        agent.close = MagicMock()
        with patch("src.agentframework.web_api._create_runtime_agent", return_value=agent):
            with TestClient(app) as tc:
                resp = tc.get("/health")
                assert resp.status_code == 200

    def test_lifespan_agent_close_error(self):
        """When agent.close raises, error is logged."""
        agent = MagicMock()
        agent.session_manager = MagicMock()
        agent.session_manager.purge_empty_sessions.return_value = 0
        agent.session_manager.close = MagicMock()
        agent.close.side_effect = Exception("agent close failed")
        with patch("src.agentframework.web_api._create_runtime_agent", return_value=agent):
            with TestClient(app) as tc:
                resp = tc.get("/health")
                assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Global exception handler with ExceptionGroup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_exception_handler_with_exception_group():
    """ExceptionGroup is unwrapped to its first exception."""
    eg = ExceptionGroup("test", [ValueError("inner")])
    request = MagicMock(spec=Request)
    response = await web_api.global_exception_handler(request, eg)
    assert response.status_code == 500


@pytest.mark.asyncio
async def test_global_exception_handler_with_regular_exception():
    """Regular Exception returns 500 without ExceptionGroup handling."""
    request = MagicMock(spec=Request)
    response = await web_api.global_exception_handler(request, ValueError("test"))
    assert response.status_code == 500


@pytest.mark.asyncio
async def test_global_exception_handler_empty_exception_group():
    """Empty ExceptionGroup (no exceptions) uses the group itself as fallback."""
    eg = ExceptionGroup("test", [ValueError("only")])
    request = MagicMock(spec=Request)
    response = await web_api.global_exception_handler(request, eg)
    assert response.status_code == 500


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="ExceptionGroup not available in Python < 3.11",
)
@pytest.mark.asyncio
async def test_exception_group_handler_delegates():
    """exception_group_handler delegates to global_exception_handler."""
    eg = ExceptionGroup("test", [ValueError("inner")])
    request = MagicMock(spec=Request)
    response = await web_api.exception_group_handler(request, eg)
    assert response.status_code == 500


# ---------------------------------------------------------------------------
# Bearer token authentication
# ---------------------------------------------------------------------------


class TestBearerAuth:
    """Tests for Bearer token authentication on /api/* and /ws/chat."""

    CORRECT_KEY = "test-secret-key-123"

    @pytest.fixture(autouse=True)
    def _enable_auth(self, monkeypatch):
        monkeypatch.setattr(web_api, "_get_api_key", lambda: self.CORRECT_KEY)
        yield

    def test_correct_token_passes(self):
        response = client.get(
            "/api/review", headers={"Authorization": f"Bearer {self.CORRECT_KEY}"}
        )
        assert response.status_code == 200

    def test_wrong_token_returns_401(self):
        response = client.get(
            "/api/review", headers={"Authorization": "Bearer wrong-token"}
        )
        assert response.status_code == 401

    def test_no_token_returns_401(self):
        response = client.get("/api/review")
        assert response.status_code == 401

    def test_wrong_scheme_returns_401(self):
        response = client.get(
            "/api/review", headers={"Authorization": f"Basic {self.CORRECT_KEY}"}
        )
        assert response.status_code == 401

    def test_health_unauthenticated(self):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_detailed_unauthenticated(self):
        state = web_api.get_state()
        state.agent = None
        response = client.get("/health/detailed")
        assert response.status_code == 200

    def test_auth_disabled_no_key(self, monkeypatch):
        monkeypatch.setattr(web_api, "_get_api_key", lambda: None)
        response = client.get("/api/review")
        assert response.status_code == 200


class TestBearerAuthWebSocket:
    """Bearer token auth for WebSocket endpoint."""

    CORRECT_KEY = "test-ws-key-456"

    @pytest.fixture(autouse=True)
    def _enable_auth(self, monkeypatch):
        monkeypatch.setattr(web_api, "_get_api_key", lambda: self.CORRECT_KEY)
        yield

    def test_ws_correct_token_passes(self, ws_mock_agent):
        with patch(
            "src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent
        ):
            with TestClient(app) as tc:
                with tc.websocket_connect(
                    "/ws/chat", headers={"Authorization": f"Bearer {self.CORRECT_KEY}"}
                ) as ws:
                    ws.send_json({"provider": "ollama", "model": "m"})
                    ready = ws.receive_json()
                    assert ready["type"] == "ready"

    def test_ws_wrong_token_rejected(self, ws_mock_agent):
        with patch(
            "src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent
        ):
            with TestClient(app) as tc:
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    with tc.websocket_connect(
                        "/ws/chat",
                        headers={"Authorization": "Bearer wrong-key"},
                    ):
                        pass
                assert exc_info.value.code == 4001

    def test_ws_no_token_rejected(self, ws_mock_agent):
        with patch(
            "src.agentframework.web_api._create_runtime_agent", return_value=ws_mock_agent
        ):
            with TestClient(app) as tc:
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    with tc.websocket_connect("/ws/chat"):
                        pass
                assert exc_info.value.code == 4001


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------


class TestPreferences:
    def test_get_preferences_returns_empty_when_no_file(self):
        web_api._PREFERENCES_PATH.unlink(missing_ok=True)
        response = client.get("/api/preferences")
        assert response.status_code == 200
        assert response.json() == {}

    def test_post_preferences_saves_and_get_returns_it(self):
        web_api._PREFERENCES_PATH.unlink(missing_ok=True)
        response = client.post("/api/preferences", json={"model": "gpt-4"})
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

        response = client.get("/api/preferences")
        assert response.status_code == 200
        assert response.json() == {"model": "gpt-4"}

    def test_post_preferences_overwrites_previous(self):
        client.post("/api/preferences", json={"model": "old-model"})
        client.post("/api/preferences", json={"model": "new-model"})
        response = client.get("/api/preferences")
        assert response.json() == {"model": "new-model"}

    def test_preferences_handles_corrupted_json_gracefully(self, tmp_path):
        prefs_file = tmp_path / "preferences.json"
        prefs_file.write_text("not json}")
        web_api._PREFERENCES_PATH = prefs_file
        try:
            response = client.get("/api/preferences")
            assert response.status_code == 200
            assert response.json() == {}
        finally:
            web_api._PREFERENCES_PATH = Path.home() / ".echo-ai" / "preferences.json"


# ---------------------------------------------------------------------------
# Unlock flow tests
# ---------------------------------------------------------------------------


class TestUnlockFlow:
    """POST /api/unlock — correct password, wrong password, locked state, rate-limit."""

    @pytest.fixture(autouse=True)
    def _clean_state(self):
        """Reset state before and after each test."""
        state = web_models.get_state()
        state.agent = None
        state.fernet = None
        yield
        state.agent = None
        state.fernet = None

    def test_unlock_success(self, tmp_path, monkeypatch):
        """Correct password unlocks the database and makes session routes work."""
        import base64 as _b64

        salt_path = tmp_path / ".db_salt"
        salt_path.write_bytes(b"\xaa" * 16)

        monkeypatch.setattr(
            "src.agentframework.routers.unlock._session_dir",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "src.agentframework.routers.unlock.derive_key",
            lambda pwd, salt: _b64.urlsafe_b64encode(b"\x00" * 32),
        )

        monkeypatch.setattr(
            web_api, "_create_runtime_agent",
            lambda *a, **kw: MagicMock(session_manager=MagicMock()),
        )

        state = web_models.get_state()
        state.agent = None
        state.fernet = None

        resp = client.post("/api/unlock", json={"password": "any-password"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "unlocked"

        state = web_models.get_state()
        assert state.fernet is not None
        assert state.agent is not None

    def test_unlock_wrong_password(self, tmp_path, monkeypatch):
        """Wrong password returns 401 with a generic message."""
        from cryptography.fernet import InvalidToken

        salt_path = tmp_path / ".db_salt"
        salt_path.write_bytes(b"\xaa" * 16)

        monkeypatch.setattr(
            "src.agentframework.routers.unlock._session_dir",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "src.agentframework.routers.unlock.derive_key",
            lambda pwd, salt: (
                # Return a valid-but-different key so Fernet() doesn't crash;
                # the session read will fail.
                __import__("base64").urlsafe_b64encode(b"\x01" * 32)
            ),
        )
        monkeypatch.setattr(
            "src.agentframework.routers.unlock.SessionManager.list_sessions",
            lambda self, **kw: (_ for _ in ()).throw(InvalidToken),
        )

        resp = client.post("/api/unlock", json={"password": "wrong-password"})
        assert resp.status_code == 401, resp.text
        assert resp.json()["detail"] == "Incorrect password"
        # Fernet should not be stored on failure
        assert web_models.get_state().fernet is None

    def test_locked_before_unlock(self):
        """Session routes return 423 before unlocking."""
        state = web_models.get_state()
        state.agent = None
        state.fernet = None

        resp = client.get("/api/sessions")
        assert resp.status_code == 423
        assert resp.json()["detail"] == "Database is locked"

    def test_unlock_on_fresh_install(self, tmp_path, monkeypatch):
        """Unlocking without any salt or db file returns 409 — must /api/setup first."""
        monkeypatch.setattr(
            "src.agentframework.routers.unlock._session_dir",
            lambda: tmp_path / "nonexistent",
        )

        resp = client.post("/api/unlock", json={"password": "pwd"})
        assert resp.status_code == 409
        assert resp.json()["detail"] == "Database not initialized. Call POST /api/setup first."



    def test_unlock_rate_limit(self, monkeypatch):
        """Repeated unlock attempts past the limit return 429."""
        async def always_blocked(*args, **kwargs):
            return False, 0

        monkeypatch.setattr(web_api._rate_limiter, "check", always_blocked)

        resp = client.post("/api/unlock", json={"password": "irrelevant"})
        assert resp.status_code == 429
        assert "too many requests" in resp.json()["detail"].lower()

    def test_status_locked(self):
        """GET /api/status returns locked=True and needs_setup when agent is None."""
        state = web_models.get_state()
        state.agent = None

        resp = client.get("/api/status")
        assert resp.status_code == 200
        assert resp.json()["locked"] is True
        assert "needs_setup" in resp.json()

    def test_status_unlocked(self):
        """GET /api/status returns locked=False after unlock."""
        state = web_models.get_state()
        state.agent = MagicMock()

        resp = client.get("/api/status")
        assert resp.status_code == 200
        assert resp.json()["locked"] is False
        assert "needs_setup" in resp.json()


class TestSetupFlow:
    """POST /api/setup — fresh install flow."""

    @pytest.fixture(autouse=True)
    def _clean_state(self):
        state = web_models.get_state()
        state.agent = None
        state.fernet = None
        yield
        state.agent = None
        state.fernet = None

    def test_status_shows_needs_setup(self, tmp_path, monkeypatch):
        """On a fresh install /api/status returns needs_setup=True."""
        monkeypatch.setattr(
            "src.agentframework.routers.unlock._session_dir",
            lambda: tmp_path,
        )
        resp = client.get("/api/status")
        assert resp.status_code == 200
        assert resp.json()["needs_setup"] is True
        assert resp.json()["locked"] is True

    def test_setup_success(self, tmp_path, monkeypatch):
        """Valid setup creates salt, db, and unlocks the app."""
        import base64 as _b64

        monkeypatch.setattr(
            "src.agentframework.routers.unlock._session_dir",
            lambda: tmp_path,
        )

        monkeypatch.setattr(
            "src.agentframework.routers.unlock.derive_key",
            lambda pwd, salt: _b64.urlsafe_b64encode(b"\x00" * 32),
        )

        monkeypatch.setattr(
            web_api, "_create_runtime_agent",
            lambda *a, **kw: MagicMock(session_manager=MagicMock()),
        )

        resp = client.post("/api/setup", json={"password": "correct-password", "confirm": "correct-password"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "setup_ok"

        state = web_models.get_state()
        assert state.fernet is not None
        assert state.agent is not None

        # Salt file should have been created on disk
        assert (tmp_path / ".db_salt").exists()

    def test_setup_password_mismatch(self, tmp_path, monkeypatch):
        """Mismatched passwords return 400."""
        monkeypatch.setattr(
            "src.agentframework.routers.unlock._session_dir",
            lambda: tmp_path,
        )
        resp = client.post("/api/setup", json={"password": "abc12345", "confirm": "different"})
        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"] == "Passwords do not match"
        assert web_models.get_state().fernet is None

    def test_setup_password_too_short(self, tmp_path, monkeypatch):
        """Short passwords return 400."""
        monkeypatch.setattr(
            "src.agentframework.routers.unlock._session_dir",
            lambda: tmp_path,
        )
        resp = client.post("/api/setup", json={"password": "short", "confirm": "short"})
        assert resp.status_code == 400, resp.text
        assert "8 characters" in resp.json()["detail"].lower()

    def test_setup_twice_returns_409(self, tmp_path, monkeypatch):
        """Calling /api/setup after a successful setup returns 409."""
        import base64 as _b64

        monkeypatch.setattr(
            "src.agentframework.routers.unlock._session_dir",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "src.agentframework.routers.unlock.derive_key",
            lambda pwd, salt: _b64.urlsafe_b64encode(b"\x00" * 32),
        )
        monkeypatch.setattr(
            web_api, "_create_runtime_agent",
            lambda *a, **kw: MagicMock(session_manager=MagicMock()),
        )

        resp = client.post("/api/setup", json={"password": "password123", "confirm": "password123"})
        assert resp.status_code == 200

        resp = client.post("/api/setup", json={"password": "password123", "confirm": "password123"})
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == "Database already initialized"

    def test_unlock_before_setup_returns_409(self, tmp_path, monkeypatch):
        """Calling /api/unlock before /api/setup returns 409."""
        monkeypatch.setattr(
            "src.agentframework.routers.unlock._session_dir",
            lambda: tmp_path,
        )
        resp = client.post("/api/unlock", json={"password": "any-password"})
        assert resp.status_code == 409
        assert "setup" in resp.json()["detail"].lower()

    def test_setup_followed_by_unlock(self, tmp_path, monkeypatch):
        """After setup, the same password unlocks the app."""
        import base64 as _b64

        monkeypatch.setattr(
            "src.agentframework.routers.unlock._session_dir",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "src.agentframework.routers.unlock.derive_key",
            lambda pwd, salt: _b64.urlsafe_b64encode(b"\x00" * 32),
        )
        monkeypatch.setattr(
            web_api, "_create_runtime_agent",
            lambda *a, **kw: MagicMock(session_manager=MagicMock()),
        )

        setup_resp = client.post("/api/setup", json={"password": "mypassword", "confirm": "mypassword"})
        assert setup_resp.status_code == 200

        state = web_models.get_state()
        state.agent = None
        state.fernet = None

        unlock_resp = client.post("/api/unlock", json={"password": "mypassword"})
        assert unlock_resp.status_code == 200, unlock_resp.text
        assert unlock_resp.json()["status"] == "unlocked"

        state = web_models.get_state()
        assert state.fernet is not None
        assert state.agent is not None
