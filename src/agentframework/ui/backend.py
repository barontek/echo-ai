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





def get_models_sync() -> dict:
    """Get available models synchronously."""
    from src.agentframework.web_api import get_models_sync as backend_models

    return backend_models()


def create_runtime_agent(model: str, session_id: str | None = None):
    """Create a runtime agent with the given model."""
    from src.agentframework.web_api import _create_runtime_agent

    return _create_runtime_agent(provider="ollama", model=model, session_id=session_id)


def save_messages(session_id: str, messages: list, state: Any):
    """Save messages to a session."""
    if state and state.agent and state.agent.session_manager:
        from src.agentframework.session import Session
        # Create a light Session object to trigger the DB update
        session = Session(id=session_id, messages=messages)
        state.agent.session_manager.save_session(session)
