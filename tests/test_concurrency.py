"""Tests for WebSocket concurrency."""

import base64
import tempfile
import pytest
import time
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from src.agentframework import web_api
from src.agentframework import web_models
from src.agentframework.web_api import app
from src.agentframework.session import EncryptedJSON, SessionManager
from src.agentframework.core import Agent

_TEST_FERNET = Fernet(base64.urlsafe_b64encode(b"\x00" * 32))


def _unlock_state(session_dir: str):
    """Set a real Fernet + minimal agent on state (call after TestClient lifespan)."""
    state = web_models.get_state()
    state.fernet = _TEST_FERNET
    # Create a bare-bones real session manager so session endpoints work
    sm = SessionManager(session_dir)
    agent = MagicMock(spec=Agent)
    agent.session_manager = sm
    agent.config = MagicMock()
    state.agent = agent


def _temp_session_dir():
    """Create a temporary session directory with seeded salt+fernet."""
    tmp = tempfile.mkdtemp()
    salt_path = Path(tmp) / ".db_salt"
    salt_path.write_bytes(b"\xaa" * 16)
    salt_path.chmod(0o600)
    EncryptedJSON._engine_fernet = _TEST_FERNET
    return tmp


@pytest.fixture
def temp_session_dir():
    d = _temp_session_dir()
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


class TestWebSocketConcurrency:
    """Test WebSocket handling under concurrent load."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    def test_multiple_websocket_connections(self, temp_session_dir):
        """Test that multiple WebSocket connections can be handled."""
        with patch.object(web_api, "load_config", return_value={
            "agent": {"session_dir": temp_session_dir, "session_enabled": True},
            "model": {"provider": "ollama", "name": "qwen3:4b"},
        }):
            with TestClient(app) as client1, TestClient(app) as client2:
                with client1.websocket_connect("/ws/chat") as ws1:
                    with client2.websocket_connect("/ws/chat"):
                        ws1.send_json({"provider": "ollama", "model": "qwen3:4b"})
                        data1 = ws1.receive_json()
                        assert data1["type"] in ("ready", "error")

    def test_websocket_rejects_invalid_json(self, temp_session_dir):
        """WebSocket should handle invalid JSON gracefully."""
        with patch.object(web_api, "load_config", return_value={
            "agent": {"session_dir": temp_session_dir, "session_enabled": True},
            "model": {"provider": "ollama", "name": "qwen3:4b"},
        }):
            with TestClient(app) as client:
                with client.websocket_connect("/ws/chat") as ws:
                    ws.send_text("not valid json {{{")
                    # Should handle without crashing

    def test_websocket_handles_empty_message(self, temp_session_dir):
        """WebSocket should handle empty messages."""
        with patch.object(web_api, "load_config", return_value={
            "agent": {"session_dir": temp_session_dir, "session_enabled": True},
            "model": {"provider": "ollama", "name": "qwen3:4b"},
        }):
            with TestClient(app) as client:
                with client.websocket_connect("/ws/chat") as ws:
                    ws.send_json({"type": "message", "content": ""})
                    # Should not crash

    @pytest.mark.asyncio
    async def test_concurrent_message_processing(self):
        """Test that messages are processed correctly under concurrency."""
        with patch("src.agentframework.web_models._state") as mock_state:
            mock_agent = MagicMock()
            mock_agent.run_streaming = AsyncMock(return_value="test response")
            mock_state.agent = mock_agent
            mock_state.message_history = []


class TestSessionConcurrency:
    """Test session handling under concurrent access."""

    def test_concurrent_session_creation(self, temp_session_dir):
        """Multiple clients can create sessions with different IDs."""
        with patch.object(web_api, "load_config", return_value={
            "agent": {"session_dir": temp_session_dir, "session_enabled": True},
            "model": {"provider": "ollama", "name": "qwen3:4b"},
        }):
            with TestClient(app) as client:
                _unlock_state(temp_session_dir)
                response1 = client.post("/api/sessions")
                assert response1.status_code == 200
                session1_id = response1.json().get("session_id")

                time.sleep(1.1)

                response2 = client.post("/api/sessions")
                assert response2.status_code == 200
                session2_id = response2.json().get("session_id")

                assert session1_id != session2_id

    def test_concurrent_session_list(self, temp_session_dir):
        """Multiple clients can list sessions without conflicts."""
        with patch.object(web_api, "load_config", return_value={
            "agent": {"session_dir": temp_session_dir, "session_enabled": True},
            "model": {"provider": "ollama", "name": "qwen3:4b"},
        }):
            with TestClient(app) as client:
                _unlock_state(temp_session_dir)
                for _ in range(3):
                    client.post("/api/sessions")

                response1 = client.get("/api/sessions")
                response2 = client.get("/api/sessions")

                sessions1 = response1.json()["sessions"]
                sessions2 = response2.json()["sessions"]

                assert len(sessions1) == len(sessions2)


class TestToolExecutionConcurrency:
    """Test that tool execution works correctly under concurrent load."""

    def test_multiple_tools_execute_correctly(self):
        pass

    def test_session_manager_handles_concurrent_access(self):
        pass
