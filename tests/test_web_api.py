"""Tests for the web API endpoints.

Merged from test_web_api.py and test_web_api_extended.py.
"""

import pytest
import json
import asyncio
import httpx
from types import SimpleNamespace
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient
from src.agentframework.web_api import app
import src.agentframework.web_api as web_api

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def ensure_state():
    """Ensure application state is initialized for each test."""
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

        def fake_create_agent(agent_config, api_key=None, session_id=None):
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
            lambda agent_config, api_key=None, session_id=None: SimpleNamespace(
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
        assert "qwen3:4b-instruct" in response.json()["models"]

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

    def test_list_sessions_lazy_init(self, monkeypatch, mock_agent):
        state = web_api.get_state()
        state.agent = None
        monkeypatch.setattr(
            web_api, "_create_runtime_agent", lambda *args, **kwargs: mock_agent
        )
        mock_agent.session_manager.list_sessions.return_value = (
            [MagicMock(id="lazy-session")],
            1,
        )

        response = client.get("/api/sessions")
        assert response.status_code == 200
        assert response.json()["sessions"][0]["id"] == "lazy-session"
        assert state.agent == mock_agent

    def test_create_session(self, monkeypatch, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_agent.session_manager.current_session = MagicMock(id="new-session-id")
        response = client.post("/api/sessions")
        assert response.status_code == 200
        assert response.json() == {"session_id": "new-session-id"}
        assert state.current_session_id == "new-session-id"

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
        assert response.status_code == 200
        assert response.json() == {
            "session_id": "any-session",
            "messages": [],
            "title": None,
        }

    def test_delete_session(self, monkeypatch, mock_agent):
        state = web_api.get_state()
        state.agent = mock_agent
        mock_db = MagicMock()
        mock_agent.session_manager.SessionLocal.return_value.__enter__.return_value = (
            mock_db
        )
        response = client.delete("/api/sessions/session-to-delete")
        assert response.status_code == 200
        assert mock_db.query.called

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
    def test_chat_websocket(self):
        with patch("src.agentframework.web_api._create_runtime_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.session_manager = None
            mock_agent.run_streaming = AsyncMock(return_value="Hello")
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

                msg2 = websocket.receive_json()
                assert msg2["type"] == "done"
                assert msg2["content"] == "Hello"

    def test_chat_websocket_thinking(self):
        with patch("src.agentframework.web_api._create_runtime_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.session_manager = None

            async def mock_run_streaming(prompt, on_chunk=None):
                if on_chunk:
                    on_chunk("__THINKING__")
                    on_chunk("I am thinking...")
                    on_chunk("__THINKING_END__")
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

                t1 = websocket.receive_json()
                assert t1["type"] == "thinking"
                t2 = websocket.receive_json()
                assert t2["type"] == "thinking"
                assert t2["content"] == "I am thinking..."

                c1 = websocket.receive_json()
                assert c1["type"] == "content"
                c2 = websocket.receive_json()
                assert c2["type"] == "content"
                assert "thought" in c2["content"]

                d1 = websocket.receive_json()
                assert d1["type"] == "done"
                assert d1["thinking"] == "I am thinking..."

    def test_chat_websocket_stop(self):
        with patch("src.agentframework.web_api._create_runtime_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.session_manager = None

            async def mock_run_streaming(prompt, on_chunk=None):
                await asyncio.sleep(1)
                if on_chunk:
                    on_chunk("Part 1")
                await asyncio.sleep(2)
                return "Part 2"

            mock_agent.run_streaming = mock_run_streaming
            mock_agent.messages = []
            mock_create.return_value = mock_agent

            with client.websocket_connect("/ws/chat") as websocket:
                websocket.send_text(
                    json.dumps({"provider": "openai", "model": "gpt-4"})
                )
                websocket.receive_json()

                websocket.send_text(
                    json.dumps({"type": "message", "content": "Slow run"})
                )
                websocket.receive_json()

                websocket.send_text(json.dumps({"type": "stop"}))

                while True:
                    msg = websocket.receive_json()
                    if msg["type"] == "done":
                        assert msg["content"] == "Response stopped by user."
                        break


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


class TestWorkflows:
    @pytest.mark.asyncio
    async def test_workflows_list_endpoint(self, monkeypatch):
        monkeypatch.setattr(
            web_api,
            "list_workflows",
            lambda: [{"id": "w1", "title": "W1", "description": "d"}],
        )
        result = await web_api.workflows_list()
        assert result == {
            "workflows": [{"id": "w1", "title": "W1", "description": "d"}]
        }

    @pytest.mark.asyncio
    async def test_workflow_run_endpoint(self, monkeypatch):
        class FakeWorkflow:
            async def compile_and_run(self, state):
                assert state["topic"] == "hello"
                assert state["agent"] == "agent"
                return {"final": "done"}

        state = web_api.get_state()
        state.agent = "agent"  # type: ignore[assignment] - Test mock value
        state.message_history = []
        monkeypatch.setattr(
            web_api, "get_workflow", lambda _workflow_id: FakeWorkflow()
        )

        payload = web_api.WorkflowRunPayload(
            workflow_id="research_and_summarize", topic="hello"
        )
        result = await web_api.workflow_run(payload, state)
        assert result["workflow_id"] == "research_and_summarize"
        assert result["response"] == "done"
        assert len(state.message_history) == 2


# ---------------------------------------------------------------------------
# Review endpoint
# ---------------------------------------------------------------------------


class TestReview:
    def test_static_routes(self):
        response = client.get("/", follow_redirects=False)
        assert response.status_code in [200, 302]

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
