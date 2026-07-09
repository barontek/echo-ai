"""Shared Pydantic models and application state for the web API."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from cryptography.fernet import Fernet
from pydantic import BaseModel, Field

from .core import Agent

logger = logging.getLogger(__name__)


@dataclass
class AppState:
    """Application state with dependency injection support."""

    agent: Agent | None = None
    fernet: Fernet | None = None
    fernet_key: bytes | None = None
    current_session_id: str | None = None
    message_history: list[dict[str, Any]] = field(default_factory=list)


# Module-level state container (initialized on startup)
_state: AppState | None = None


def get_state() -> AppState:
    """Dependency to get the application state."""
    global _state
    if _state is None:
        _state = AppState()
    return _state


def require_unlocked():
    """FastAPI dependency — reject requests when the database is locked."""
    from fastapi import HTTPException

    state = get_state()
    if state.agent is None:
        raise HTTPException(status_code=423, detail="Database is locked")


class ConfigPayload(BaseModel):
    provider: str = "ollama"
    model: str = ""
    api_key: str | None = None


class PreferencesPayload(BaseModel):
    model: str
    provider: str | None = None


class ChatPayload(BaseModel):
    content: str = Field(default="", min_length=1)


class SessionRenamePayload(BaseModel):
    session_id: str
    new_title: str = Field(min_length=1)


class WsConfigPayload(BaseModel):
    provider: str = "ollama"
    model: str = Field(min_length=1, description="Model name, required for agent creation")
    api_key: str | None = None
    session_id: str | None = None


class WsMessagePayload(BaseModel):
    type: str | None = None
    content: str | None = None
    session_id: str | None = None
    index: int | None = None
    message_id: str | None = None


class WorkflowRunPayload(BaseModel):
    workflow_id: str = Field(min_length=1)
    topic: str = Field(min_length=1)


class ChatRequest(BaseModel):
    session_id: str | None = None
    prompt: str
    provider: str = "ollama"
    model: str = ""
    api_key: str | None = None
    stream: bool = False


class RouteRequest(BaseModel):
    prompt: str
