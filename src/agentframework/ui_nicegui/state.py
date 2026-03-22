"""State management for NiceGUI UI."""

from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class ChatState:
    """Per-user chat state."""

    current_session_id: Optional[str] = None
    messages: list = field(default_factory=list)
    model: str = "qwen3:4b-instruct"
    is_streaming: bool = False

    def create_session(self):
        """Create a new session via backend."""
        from ..backend import create_session_data, get_backend_state

        state = get_backend_state()
        data = create_session_data(state)
        if session_id := data.get("session_id"):
            self.current_session_id = session_id
            self.messages = []
            return {"id": session_id, "title": "New Chat"}
        return None

    def load_session(self, session_id: str):
        """Load a session from backend."""
        from ..backend import load_session_data, get_backend_state

        state = get_backend_state()
        data = load_session_data(session_id, state)
        if error := data.get("error"):
            logger.error(f"Failed to load session {session_id}: {error}")
            return False
        self.current_session_id = session_id
        self.messages = data.get("messages", [])
        return True

    def delete_session(self, session_id: str):
        """Delete a session via backend."""
        from ..backend import delete_session_data, get_backend_state

        state = get_backend_state()
        delete_session_data(session_id, state)

    def add_message(self, role: str, content: str, **kwargs):
        """Add a message to the history."""
        import datetime

        self.messages.append(
            {
                "role": role,
                "content": content,
                "timestamp": datetime.datetime.now().isoformat(),
                **kwargs,
            }
        )

    def save_messages(self):
        """Save messages to backend."""
        if not self.current_session_id:
            return
        from ..backend import save_messages, get_backend_state

        state = get_backend_state()
        save_messages(self.current_session_id, self.messages, state)


_user_states: dict[str, ChatState] = {}


def get_state(client_id: Optional[str] = None) -> ChatState:
    """Get or create state for a client."""
    if client_id is None:
        client_id = "default"

    if client_id not in _user_states:
        _user_states[client_id] = ChatState()
    return _user_states[client_id]


def get_all_sessions():
    """Get all sessions from backend."""
    from ..backend import get_sessions_data, get_backend_state

    state = get_backend_state()
    data = get_sessions_data(state)
    return data.get("sessions", [])


def get_models():
    """Get available models from backend."""
    from ..backend import get_models_sync

    data = get_models_sync()
    return data.get("models", ["qwen3:4b-instruct"])


def create_agent(model: str):
    """Create an agent with the given model."""
    from ..backend import create_runtime_agent

    return create_runtime_agent(model)
