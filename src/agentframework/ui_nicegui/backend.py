"""Backend integration for NiceGUI UI.

This module provides a bridge between NiceGUI and the existing
backend functionality from web_api.py.
"""

from typing import Any


def get_backend_state() -> Any:
    """Get the shared backend state."""
    from src.agentframework.web_api import get_state

    return get_state()


def create_session_data(state: Any) -> dict:
    """Create a new session."""
    from src.agentframework.web_api import create_session_data as backend_create

    return backend_create(state)


def load_session_data(session_id: str, state: Any) -> dict:
    """Load session data by ID."""
    from src.agentframework.web_api import load_session_data as backend_load

    return backend_load(session_id, state)


def delete_session_data(session_id: str, state: Any) -> dict:
    """Delete a session by ID."""
    from src.agentframework.web_api import delete_session_data as backend_delete

    return backend_delete(session_id, state)


def get_sessions_data(state: Any) -> dict:
    """Get all sessions data."""
    from src.agentframework.web_api import get_sessions_data as backend_sessions

    return backend_sessions(state)


def save_messages(session_id: str, messages: list, state: Any) -> dict:
    """Save messages for a session."""
    from src.agentframework.web_api import save_messages as backend_save

    return backend_save(session_id, messages, state)


def get_models_sync() -> dict:
    """Get available models synchronously."""
    from src.agentframework.web_api import get_models_sync as backend_models

    return backend_models()


def create_runtime_agent(model: str):
    """Create a runtime agent with the given model."""
    from src.agentframework.web_api import _create_runtime_agent

    return _create_runtime_agent(provider="ollama", model=model)
