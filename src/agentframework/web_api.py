"""FastAPI web backend for Echo AI."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import httpx
import uvicorn
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.agentframework.core import Agent, AgentConfig, create_agent
from src.agentframework.core.session_runtime import deserialize_messages
from src.agentframework.config import DEFAULT_SESSION_DIR, get_safety_config, get_tools, load_config
from src.agentframework.web_utils import filter_messages_for_ui
from src.agentframework.constants import THINKING_END, THINKING_START
from src.agentframework import __version__
from src.agentframework.logging_utils import set_correlation_id
from src.agentframework.core.router import SemanticRouter
from src.agentframework.session import DBSessionModel
from src.workflows import get_workflow, list_workflows

logger = logging.getLogger(__name__)

DEFAULT_WEB_PORT = 8080
DEFAULT_PROVIDER = "ollama"
DEFAULT_MODEL = "qwen3:4b-instruct"
FALLBACK_MODELS = [DEFAULT_MODEL, "llama3.2:latest", "phi3.5:latest"]

_models_cache: dict[str, tuple[float, dict]] = {}
_MODELS_CACHE_TTL = 60.0


@dataclass
class AppState:
    """Application state with dependency injection support."""

    agent: Agent | None = None
    current_session_id: str | None = None
    message_history: list[dict[str, Any]] = field(default_factory=list)


# Module-level state container (initialized on startup)
_state: AppState | None = None


def get_state() -> AppState:
    """Dependency to get the application state."""
    global _state
    if _state is None:
        _state = AppState()
        try:
            _state.agent = _create_runtime_agent(
                provider=DEFAULT_PROVIDER, model=DEFAULT_MODEL
            )
        except Exception as e:
            logger.debug(f"Ollama agent initialization deferred: {e}")
    return _state


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    global _state

    # Initialize Sentry early in startup
    try:
        from src.agentframework.sentry import init_sentry

        init_sentry()
    except Exception as e:
        logger.debug(f"Sentry initialization skipped: {e}")

    logger.info("=" * 50)
    logger.info("  Echo AI - Starting up...")
    logger.info("=" * 50)
    logger.info("  Version: 0.1.0")
    logger.info(f"  Provider: {DEFAULT_PROVIDER}")
    logger.info(f"  Model: {DEFAULT_MODEL}")
    logger.info("=" * 50)

    _state = AppState()
    try:
        _state.agent = _create_runtime_agent(
            provider=DEFAULT_PROVIDER, model=DEFAULT_MODEL
        )
        if _state.agent and _state.agent.session_manager:
            purged = _state.agent.session_manager.purge_empty_sessions()
            if purged > 0:
                logger.info(f"Purged {purged} empty sessions on startup")
    except Exception as e:
        logger.debug(f"Ollama agent initialization deferred: {e}")
    yield
    logger.info("Shutting down Echo AI...")

    # Clean up rate limit storage
    _rate_limit_storage.clear()

    # Close agent and cleanup resources
    if _state and _state.agent:
        try:
            if _state.agent.session_manager:
                _state.agent.session_manager.close()
        except Exception as e:
            logger.debug(f"Error closing session manager: {e}")

        try:
            _state.agent.close()
        except Exception as e:
            logger.debug(f"Error closing agent: {e}")

    _state = None
    logger.info("Shutdown complete")


# Create FastAPI app with lifespan
app = FastAPI(title="Echo AI API", lifespan=lifespan)


# Global exception handler with Sentry capture
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Capture all unhandled exceptions with Sentry."""
    # Handle ExceptionGroup from Python 3.13+ (extract the original exception)
    if isinstance(exc, ExceptionGroup):
        exc = exc.exceptions[0] if exc.exceptions else exc

    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    try:
        from src.agentframework.sentry import captureException

        captureException(exc, extra={"path": str(request.url.path)})
    except Exception:
        pass  # Don't let Sentry errors mask the original error

    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# Handle ExceptionGroup specifically for Python 3.13+
try:

    @app.exception_handler(ExceptionGroup)
    async def exception_group_handler(request: Request, exc: ExceptionGroup):
        """Handle ExceptionGroup from Python 3.13+."""
        return await global_exception_handler(request, exc)
except NameError:
    pass  # ExceptionGroup not available in Python < 3.11


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """Add correlation ID to each request for structured logging."""
    # Check for existing correlation ID in headers
    cid = request.headers.get("X-Correlation-ID")
    if not cid:
        cid = str(uuid.uuid4())[:8]
    set_correlation_id(cid)

    response = await call_next(request)
    response.headers["X-Correlation-ID"] = cid
    return response


# Rate limiting configuration
_rate_limit_storage: dict[str, list[datetime]] = defaultdict(list)
_config = load_config()
_rate_limit_config = _config.get("web", {}).get("rate_limit", {})
_RATE_LIMIT_REQUESTS = _rate_limit_config.get("requests", 60)
_RATE_LIMIT_WINDOW = _rate_limit_config.get("window_seconds", 60)


def _check_rate_limit(client_ip: str) -> tuple[bool, int]:
    """Check if client IP is within rate limits. Returns (allowed, remaining)."""
    now = datetime.now()
    cutoff = now - timedelta(seconds=_RATE_LIMIT_WINDOW)

    # Clean old entries
    _rate_limit_storage[client_ip] = [
        ts for ts in _rate_limit_storage[client_ip] if ts > cutoff
    ]

    current_count = len(_rate_limit_storage[client_ip])
    if current_count >= _RATE_LIMIT_REQUESTS:
        return False, 0

    _rate_limit_storage[client_ip].append(now)
    return True, _RATE_LIMIT_REQUESTS - current_count - 1


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Apply rate limiting based on client IP."""
    client_ip = request.client.host if request.client else "unknown"

    # Skip rate limiting for health checks
    if request.url.path == "/health":
        return await call_next(request)

    # Skip rate limiting for local requests
    if client_ip in ("127.0.0.1", "localhost", "::1", "::ffff:127.0.0.1"):
        return await call_next(request)

    allowed, remaining = _check_rate_limit(client_ip)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={
                "error": "Rate limit exceeded",
                "detail": f"Too many requests. Please wait {_RATE_LIMIT_WINDOW} seconds.",
            },
            headers={"Retry-After": str(_RATE_LIMIT_WINDOW)},
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Limit"] = str(_RATE_LIMIT_REQUESTS)
    return response


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log all HTTP requests and responses for debugging."""
    import time

    # Skip logging for static files and WebSocket upgrades
    skip_paths = {"/favicon.ico", "/static", "/docs", "/openapi.json", "/redoc"}
    if request.url.path in skip_paths:
        return await call_next(request)

    start_time = time.perf_counter()
    cid = request.headers.get("X-Correlation-ID", "no-cid")

    # Log request
    logger.debug(f"[{cid}] --> {request.method} {request.url.path}")

    try:
        response = await call_next(request)
    except Exception:
        # Let FastAPI's exception handler deal with it
        raise
    finally:
        duration = time.perf_counter() - start_time
        # Log after response is ready (or on error)
        logger.debug(
            f"[{cid}] <-- {request.method} {request.url.path} ({duration * 1000:.1f}ms)"
        )

    # Add timing header
    response.headers["X-Response-Time"] = f"{duration * 1000:.1f}ms"

    return response


def _get_cors_config() -> dict:
    """Get CORS configuration from config.yaml."""
    import os

    config = load_config()
    web_config = config.get("web", {})
    cors_config = web_config.get("cors", {})

    if os.environ.get("ALLOW_ALL_ORIGINS", "").lower() in ("1", "true", "yes"):
        return {
            "origins": ["*"],
            "credentials": cors_config.get("allow_credentials", True),
            "methods": cors_config.get("allow_methods", ["*"]),
            "headers": cors_config.get("allow_headers", ["*"]),
        }

    local_network_origins = []
    try:
        import socket

        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        local_network_origins = [
            f"http://{local_ip}:3000",
            f"http://{local_ip}:8080",
            f"http://{local_ip}:3001",
        ]
    except Exception:
        pass

    default_origins = [
        "http://localhost:3000",
        f"http://localhost:{DEFAULT_WEB_PORT}",
        f"http://127.0.0.1:{DEFAULT_WEB_PORT}",
        "http://localhost:8501",
        "http://127.0.0.1:8501",
    ]

    all_origins = cors_config.get("origins", default_origins + local_network_origins)

    return {
        "origins": all_origins,
        "credentials": cors_config.get("allow_credentials", True),
        "methods": cors_config.get("allow_methods", ["*"]),
        "headers": cors_config.get("allow_headers", ["*"]),
    }


def _configure_cors():
    """Configure CORS middleware from config."""
    config = _get_cors_config()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config["origins"],
        allow_credentials=config["credentials"],
        allow_methods=config["methods"],
        allow_headers=config["headers"],
    )


_configure_cors()


def ensure_runtime_agent(state: AppState) -> Agent | None:
    """Ensure application state has a usable runtime agent."""
    if state.agent is None:
        try:
            state.agent = _create_runtime_agent(
                provider=DEFAULT_PROVIDER, model=DEFAULT_MODEL
            )
        except Exception as e:
            logger.debug(f"Deferred agent creation failed: {e}")
    return state.agent


async def get_models_data() -> dict[str, Any]:
    """List available Ollama models for API callers (with caching)."""
    cache_key = "models_async"
    now = time.monotonic()

    # Check cache
    if cache_key in _models_cache:
        cached_time, cached_data = _models_cache[cache_key]
        if now - cached_time < _MODELS_CACHE_TTL:
            return cached_data

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:11434/api/tags", timeout=5.0)
            response.raise_for_status()
            models = response.json().get("models", [])
            result = {"models": [m["name"] for m in models]}

            # Update cache
            _models_cache[cache_key] = (now, result)
            return result
    except Exception as e:
        logger.debug("Failed to fetch Ollama models: %s", e)
        return {
            "models": FALLBACK_MODELS,
            "error": "Could not reach Ollama. Showing fallback models.",
        }


def get_models_sync() -> dict[str, Any]:
    """List available Ollama models for in-process UI callers (with caching)."""
    cache_key = "models_sync"
    now = time.monotonic()

    # Check cache
    if cache_key in _models_cache:
        cached_time, cached_data = _models_cache[cache_key]
        if now - cached_time < _MODELS_CACHE_TTL:
            return cached_data

    try:
        response = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
        response.raise_for_status()
        models = response.json().get("models", [])
        result = {"models": [m["name"] for m in models]}

        # Update cache
        _models_cache[cache_key] = (now, result)
        return result
    except Exception as e:
        logger.debug("Failed to fetch Ollama models: %s", e)
        return {
            "models": FALLBACK_MODELS,
            "error": "Could not reach Ollama. Showing fallback models.",
        }


def get_sessions_data(state: AppState) -> dict[str, Any]:
    """Return session metadata for the current runtime agent."""
    active_agent = ensure_runtime_agent(state)
    if active_agent and active_agent.session_manager:
        sessions_list, total = active_agent.session_manager.list_sessions()
        sessions = [
            {"id": s.id, "title": s.title, "created_at": s.created_at.isoformat()}
            for s in sessions_list
        ]
        return {"sessions": sessions, "total": total}
    return {"sessions": [], "total": 0}


def create_session_data(state: AppState) -> dict[str, Any]:
    """Create a fresh chat session for the shared UI/backend state."""
    active_agent = ensure_runtime_agent(state)
    if active_agent and active_agent.session_manager:
        active_agent.session_manager.create_session()
        if active_agent.session_manager.current_session:
            state.current_session_id = active_agent.session_manager.current_session.id
            active_agent.messages = []
            state.message_history = []
            logger.warning(
                "ws:trace create_session session=%s db_path=%s",
                state.current_session_id,
                str(active_agent.session_manager.db_path),
            )
            return {"session_id": state.current_session_id}
    state.message_history = []
    return {
        "session_id": state.current_session_id,
        "error": "Session manager unavailable.",
    }


def load_session_data(session_id: str, state: AppState) -> dict[str, Any]:
    """Load a session and normalize messages for the UI."""
    active_agent = ensure_runtime_agent(state)
    if active_agent and active_agent.session_manager:
        active_agent.load_session(session_id)
        state.current_session_id = session_id

        # Get session creation time for fallback timestamps
        session_created_at = None
        if active_agent.session_manager.current_session:
            session_created_at = active_agent.session_manager.current_session.created_at
            title = active_agent.session_manager.current_session.title
        else:
            title = None

        state.message_history = filter_messages_for_ui(
            active_agent.messages, session_created_at=session_created_at
        )
        return {
            "session_id": session_id,
            "title": title,
            "messages": state.message_history,
        }

    return {
        "session_id": session_id,
        "messages": [],
        "title": None,
        "error": "Session manager unavailable.",
    }


def delete_session_data(session_id: str, state: AppState) -> dict[str, Any]:
    """Delete a persisted chat session."""
    active_agent = ensure_runtime_agent(state)
    if not (active_agent and active_agent.session_manager):
        return {"status": "ok"}

    with active_agent.session_manager.SessionLocal() as db:
        db.query(DBSessionModel).filter(DBSessionModel.id == session_id).delete()
        db.commit()

    if state.current_session_id == session_id:
        state.current_session_id = None
        state.message_history = []
        active_agent.messages = []

    return {"status": "ok"}


def _create_runtime_agent(
    provider: str,
    model: str,
    api_key: str | None = None,
    session_id: str | None = None,
) -> Agent:
    """Create an agent for the web UI with the same tool config as CLI."""
    # Safety check for model name
    if not model or model == "Loading models..." or "models..." in model:
        model = DEFAULT_MODEL
    config = load_config()
    safety_config = get_safety_config(config)
    tools = get_tools(config, safety_config)

    agent_config = AgentConfig(
        provider=provider,
        model=model,
        temperature=config.get("model", {}).get("temperature", 0.3),
        max_iterations=config.get("agent", {}).get("max_iterations", 50),
        system_prompt=config.get("agent", {}).get("system_prompt", ""),
        tools=tools,
        base_url=config.get("model", {}).get("base_url"),
        session_enabled=config.get("agent", {}).get("session_enabled", True),
        session_dir=config.get("agent", {}).get("session_dir", DEFAULT_SESSION_DIR),
        num_ctx=config.get("model", {}).get("num_ctx"),
    )

    env_info = (
        "\n\n## Environment\n"
        f"- Current working directory: {Path.cwd()}\n"
        f"- Workspace (file operations confined to): {safety_config.workspace or '.'}\n"
    )
    if agent_config.system_prompt:
        agent_config.system_prompt += env_info
    else:
        agent_config.system_prompt = (
            "You are an AI assistant with access to various tools." + env_info
        )

    return create_agent(agent_config, api_key=api_key, session_id=session_id)


class ConfigPayload(BaseModel):
    provider: str = "ollama"
    model: str = "qwen3:4b-instruct"
    api_key: str | None = None


class ChatPayload(BaseModel):
    content: str = Field(default="", min_length=1)


class SessionRenamePayload(BaseModel):
    session_id: str
    new_title: str = Field(min_length=1)


class WsConfigPayload(BaseModel):
    provider: str = "ollama"
    model: str = Field(default="qwen3:4b-instruct", min_length=1)
    api_key: str | None = None
    session_id: str | None = None


class WsMessagePayload(BaseModel):
    type: str | None = None
    content: str | None = None
    session_id: str | None = None
    index: int | None = None


class WorkflowRunPayload(BaseModel):
    workflow_id: str = Field(min_length=1)
    topic: str = Field(min_length=1)


@app.get("/", include_in_schema=False)
async def index():
    """Redirect to React UI."""
    return RedirectResponse(url="http://localhost:3000", status_code=302)


@app.get("/sentry-debug", tags=["Debug"])
async def trigger_error():
    """Trigger a test error for Sentry verification."""
    return {"result": 1 / 0}


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint for container orchestration and load balancers.

    Returns 200 OK if the service is running.
    Use this endpoint for:
    - Kubernetes liveness/readiness probes
    - Load balancer health checks
    - Monitoring systems
    """
    return {
        "status": "healthy",
        "service": "echo-ai",
        "version": __version__,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/health/detailed", tags=["Health"])
async def detailed_health_check():
    """Detailed health check with component status.

    Returns detailed status of all components including:
    - LLM provider connectivity
    - Session storage
    - Memory store
    """
    state = get_state()
    components = {
        "service": "healthy",
        "provider": "unknown",
        "sessions": "unknown",
        "memory": "unknown",
    }

    if state.agent:
        components["provider"] = "connected"

    if state.agent and state.agent.session_manager:
        try:
            sessions, total = state.agent.session_manager.list_sessions(limit=1)
            components["sessions"] = f"ok ({total} sessions)"
        except Exception as e:
            components["sessions"] = f"error: {str(e)}"

    if state.agent and state.agent.memory_manager:
        try:
            components["memory"] = "ok"
        except Exception as e:
            components["memory"] = f"error: {str(e)}"

    all_healthy = all(
        v != "error" and not v.startswith("error")
        for v in components.values()
        if v != "unknown"
    )

    return {
        "status": "healthy" if all_healthy else "degraded",
        "service": "echo-ai",
        "version": __version__,
        "components": components,
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/chat", include_in_schema=False)
async def chat_ui(message: ChatPayload, state: Annotated[AppState, Depends(get_state)]):
    """Legacy chat endpoint for UI compatibility."""
    if state.agent is None:
        state.agent = _create_runtime_agent(
            provider=DEFAULT_PROVIDER, model=DEFAULT_MODEL
        )

    response = await state.agent.run(message.content)
    return {"response": response}


@app.get("/api/models", tags=["Models"])
async def list_models():
    """List available Ollama models."""
    return await get_models_data()


@app.get("/api/config", tags=["Configuration"])
async def get_config(
    state: Annotated[AppState, Depends(get_state)],
):
    """Get the current agent configuration.

    Returns the current LLM provider, model, and other settings.

    Returns:
        {"config": {"provider": "...", "model": "...", ...}}
    """
    if not state.agent:
        raise HTTPException(
            status_code=503,
            detail="Agent not initialized. Please start the server first.",
        )
    agent_config = state.agent.config
    return {
        "config": {
            "provider": agent_config.provider,
            "model": agent_config.model,
            "temperature": agent_config.temperature,
            "max_iterations": agent_config.max_iterations,
            "session_enabled": agent_config.session_enabled,
        }
    }


@app.post("/api/config", tags=["Configuration"])
async def update_config(
    config: ConfigPayload,
    state: Annotated[AppState, Depends(get_state)],
):
    """Update the agent configuration.

    Changes the LLM provider and model. Creates a new agent instance
    with the specified configuration.

    Body:
        - provider: "ollama" or "openai"
        - model: Model name (e.g., "qwen3:4b-instruct", "gpt-4")
        - api_key: API key for OpenAI (optional)

    Returns:
        {"status": "ok", "config": {...}}
    """
    state.agent = _create_runtime_agent(
        config.provider, config.model, api_key=config.api_key
    )
    return {
        "status": "ok",
        "config": {"provider": config.provider, "model": config.model},
    }


@app.get("/api/sessions", tags=["Sessions"])
async def list_sessions(
    state: Annotated[AppState, Depends(get_state)],
):
    """List all chat sessions.

    Returns sessions sorted by creation date (newest first).
    Each session includes:
    - id: Session identifier
    - title: Auto-generated or user-defined title
    - created_at: Timestamp

    Returns:
        {"sessions": [{"id": "...", "title": "...", "created_at": "..."}, ...]}
    """
    if state.agent and state.agent.session_manager:
        state.agent.session_manager.purge_empty_sessions()
    return get_sessions_data(state)


@app.post("/api/sessions", tags=["Sessions"])
async def create_session(
    state: Annotated[AppState, Depends(get_state)],
):
    """Create a new chat session.

    Initializes a fresh session for a new conversation.
    The session ID is generated from the current timestamp (YYYYMMDD_HHMMSS).

    Returns:
        {"session_id": "20260319_143052", "title": null}
    """
    return create_session_data(state)


@app.get("/api/sessions/{session_id}", tags=["Sessions"])
async def load_session(
    session_id: str,
    state: Annotated[AppState, Depends(get_state)],
):
    """Load a specific session with its message history.

    Args:
        session_id: The session identifier

    Returns:
        {
            "session_id": "20260319_143052",
            "title": "Weather in Istanbul",
            "messages": [
                {"role": "user", "content": "...", "timestamp": "14:30"},
                {"role": "assistant", "content": "...", "tool_calls": [...], "timestamp": "14:31"}
            ]
        }

    Note:
        Messages are filtered for UI rendering (tool messages removed, thinking extracted)
    """
    return load_session_data(session_id, state)


@app.delete("/api/sessions/{session_id}", tags=["Sessions"])
async def delete_session(
    session_id: str,
    state: Annotated[AppState, Depends(get_state)],
):
    """Delete a chat session.

    Permanently removes the session and all its messages from the database.

    Args:
        session_id: The session identifier to delete

    Returns:
        {"status": "ok"}
    """
    return delete_session_data(session_id, state)


@app.post("/api/sessions/rename", tags=["Sessions"])
async def rename_session(
    payload: SessionRenamePayload,
    state: Annotated[AppState, Depends(get_state)],
):
    """Rename a session by changing its title.

    Body:
        - session_id: The session to rename
        - new_title: The new title for the session

    Returns:
        {"status": "ok", "session_id": "...", "title": "..."}
    """
    if not (state.agent and state.agent.session_manager):
        raise HTTPException(
            status_code=503,
            detail="Session service is unavailable. Please try again later.",
        )

    with state.agent.session_manager.SessionLocal() as db:
        updated = (
            db.query(DBSessionModel)
            .filter(DBSessionModel.id == payload.session_id)
            .update({"title": payload.new_title})
        )
        if updated == 0:
            raise HTTPException(
                status_code=404,
                detail=f"Session with ID '{payload.session_id}' was not found.",
            )
        db.commit()

    if (
        state.agent.session_manager.current_session
        and state.agent.session_manager.current_session.id == payload.session_id
    ):
        state.agent.session_manager.current_session.title = payload.new_title

    return {
        "status": "ok",
        "session_id": payload.session_id,
        "title": payload.new_title,
    }


@app.get("/api/sessions/{session_id}/export", tags=["Sessions"])
async def export_session(
    session_id: str,
    state: Annotated[AppState, Depends(get_state)],
):
    """Export a session to JSON format.

    Args:
        session_id: The session identifier to export

    Returns:
        Session data as JSON dictionary
    """
    if not (state.agent and state.agent.session_manager):
        raise HTTPException(
            status_code=503,
            detail="Session service is unavailable. Please try again later.",
        )

    session_data = state.agent.session_manager.export_session(session_id)
    if session_data is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session with ID '{session_id}' was not found.",
        )

    return session_data


@app.post("/api/sessions/import", tags=["Sessions"])
async def import_session(
    request: Request,
    state: Annotated[AppState, Depends(get_state)],
):
    """Import a session from JSON format.

    Body:
        JSON session data (from export endpoint)

    Returns:
        {"status": "ok", "session_id": "..."}
    """
    if not (state.agent and state.agent.session_manager):
        raise HTTPException(
            status_code=503,
            detail="Session service is unavailable. Please try again later.",
        )

    try:
        data = await request.json()
    except Exception as e:
        logger.warning("Invalid JSON in import request: %s", e)
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON in request body.",
        )

    try:
        session = state.agent.session_manager.import_session(data)
        return {"status": "ok", "session_id": session.id}
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )


@app.post("/api/sessions/purge")
async def purge_sessions(
    state: Annotated[AppState, Depends(get_state)],
    days: int | None = None,
):
    """Purge old or all sessions."""
    if not (state.agent and state.agent.session_manager):
        raise HTTPException(
            status_code=503,
            detail="Session service is unavailable. Please try again later.",
        )

    count = state.agent.session_manager.purge_sessions(older_than_days=days)
    return {"status": "ok", "purged_count": count}


@app.post("/api/sessions/purge-empty")
async def purge_empty_sessions(
    state: Annotated[AppState, Depends(get_state)],
):
    """Purge sessions that have no user messages (empty sessions)."""
    if not (state.agent and state.agent.session_manager):
        raise HTTPException(
            status_code=503,
            detail="Session service is unavailable. Please try again later.",
        )

    count = state.agent.session_manager.purge_empty_sessions()
    return {"status": "ok", "purged_count": count}


@app.get("/api/workflows")
async def workflows_list():
    """List available workflows for UI consumption."""
    return {"workflows": list_workflows()}


@app.post("/api/workflows/run")
async def workflow_run(
    payload: WorkflowRunPayload,
    state: Annotated[AppState, Depends(get_state)],
):
    """Run a selected workflow and return its final output."""
    if state.agent is None:
        state.agent = _create_runtime_agent(
            provider=DEFAULT_PROVIDER, model=DEFAULT_MODEL
        )

    try:
        workflow = get_workflow(payload.workflow_id)
    except KeyError:
        available = list_workflows()
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{payload.workflow_id}' not found. Available: {available}",
        )

    initial_state = {"topic": payload.topic, "agent": state.agent}
    final_state = await workflow.compile_and_run(initial_state)
    content = final_state.get("final") or final_state.get("result") or str(final_state)

    timestamp = datetime.now().strftime("%H:%M")
    user_content = f"[Workflow: {payload.workflow_id}] {payload.topic}"
    state.message_history.append(
        {"role": "user", "content": user_content, "timestamp": timestamp}
    )
    state.message_history.append(
        {"role": "assistant", "content": content, "timestamp": timestamp}
    )

    return {
        "workflow_id": payload.workflow_id,
        "response": content,
        "timestamp": timestamp,
    }


@app.post("/api/chat", tags=["Chat"])
async def chat(
    message: ChatPayload,
    state: Annotated[AppState, Depends(get_state)],
):
    """Non-streaming chat endpoint.

    Sends a message and waits for the complete response.
    Use for simple integrations or testing.

    For real-time streaming, use the WebSocket endpoint `/ws/chat`.

    Body:
        - content: The user's message
        - session_id: Optional session ID to continue a conversation

    Returns:
        {
            "response": "The assistant's response...",
            "messages": [...]
        }

    Example:
        ```bash
        curl -X POST http://localhost:8000/api/chat \\
          -H "Content-Type: application/json" \\
          -d '{"content": "Hello!"}'
        ```
    """
    if state.agent is None:
        state.agent = _create_runtime_agent(
            provider=DEFAULT_PROVIDER, model=DEFAULT_MODEL
        )

    prompt = message.content
    state.message_history.append(
        {
            "role": "user",
            "content": prompt,
            "timestamp": datetime.now().strftime("%H:%M"),
        }
    )

    response = await state.agent.run(prompt)

    state.message_history.append(
        {
            "role": "assistant",
            "content": response,
            "timestamp": datetime.now().strftime("%H:%M"),
        }
    )

    return {"response": response, "messages": state.message_history}


async def _generate_title_async(active_agent: "Agent") -> None:
    """Generate title in background without blocking."""
    try:
        new_title = await active_agent.generate_title()
        if (
            new_title
            and active_agent.session_manager
            and active_agent.session_manager.current_session
        ):
            active_agent.session_manager.current_session.title = new_title
            active_agent.save_session()
    except Exception as e:
        logger.debug(f"Background title generation failed: {e}")


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket chat endpoint for real-time streaming.

    Connect to: `wss://localhost:8080/ws/chat` (HTTPS/WSS required)

    ## Sending Messages

    Send JSON messages to the server:

    ```json
    {"type": "message", "content": "Hello!"}
    ```

    Optional: include session_id to continue a conversation.
    ```json
    {"type": "message", "content": "Hello!", "session_id": "20260319_143052"}
    ```

    To stop generation mid-stream:
    ```json
    {"type": "stop"}
    ```

    ## Receiving Messages

    Server sends JSON events:

    ```json
    {"type": "content", "content": "Hello"}  // Streaming content
    {"type": "thinking", "content": "Let me think..."}  // Model thinking
    {"type": "done", "content": "...", "tool_calls": [...]}  // Complete response
    {"type": "error", "content": "Error message"}  // Error occurred
    ```

    ## JavaScript Example

    ```javascript
    const ws = new WebSocket('wss://localhost:8080/ws/chat');
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'content') {
            console.log('Received:', data.content);
        }
    };
    ws.send(JSON.stringify({type: 'message', content: 'Hi!'}));
    ```
    """
    scheme = websocket.scope.get("scheme", "ws")
    if scheme == "http":
        await websocket.close(code=4001, reason="HTTPS/WSS required")
        return

    await websocket.accept()

    if _state is None:
        await websocket.send_json(
            {"type": "error", "content": "Server not initialized"}
        )
        return

    _ws_message_history: list[dict[str, Any]] = []
    active_agent: Agent | None = None
    streaming_task: asyncio.Task | None = None
    stop_requested = False

    async def send_keepalive() -> None:
        try:
            while True:
                await asyncio.sleep(15)
                await websocket.send_json({"type": "ping"})
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Keepalive error: {e}")

    keepalive_task = asyncio.create_task(send_keepalive())

    async def run_agent(prompt: str):
        nonlocal streaming_task, stop_requested
        if not active_agent:
            return

        # Ensure session exists and send session_start immediately
        if active_agent.session_manager:
            active_agent._ensure_session()
            if active_agent.session_manager.current_session:
                sid = active_agent.session_manager.current_session.id
                logger.warning(
                    "ws:trace run_agent session_start=%s messages=%d",
                    sid,
                    len(active_agent.messages),
                )
                try:
                    await websocket.send_json(
                        {
                            "type": "session_start",
                            "session_id": sid,
                        }
                    )
                except WebSocketDisconnect:
                    return

        timestamp = datetime.now().strftime("%H:%M")
        _ws_message_history.append(
            {"role": "user", "content": prompt, "timestamp": timestamp}
        )
        try:
            await websocket.send_json(
                {
                    "type": "message",
                    "role": "user",
                    "content": prompt,
                    "timestamp": timestamp,
                }
            )
        except WebSocketDisconnect:
            return

        accumulated_content = ""
        thinking_content = ""
        in_thinking = False
        send_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=1024)

        async def sender_loop():
            try:
                while True:
                    msg = await send_queue.get()
                    if msg is None:
                        break
                    try:
                        await websocket.send_json(msg)
                    except (WebSocketDisconnect, RuntimeError):
                        break
            except Exception as e:
                logger.debug(f"WebSocket sender loop error: {e}")

        sender_task = asyncio.create_task(sender_loop())

        def on_chunk(chunk: str) -> None:
            nonlocal accumulated_content, thinking_content, in_thinking
            if stop_requested:
                raise asyncio.CancelledError()

            # Extract any thinking tail before __THINKING_END__ so it goes
            # to thinking_content, not accumulated_content (fixes the bug
            # where "tail.__THINKING_END__\n\nresponse" leaked the tail
            # into the response box).
            thinking_tail = ""
            if THINKING_END in chunk:
                thinking_tail, chunk = chunk.split(THINKING_END, 1)
                in_thinking = False

            if THINKING_START in chunk:
                before, chunk = chunk.split(THINKING_START, 1)
                if not in_thinking and before:
                    accumulated_content += before
                    with contextlib.suppress(asyncio.QueueFull):
                        send_queue.put_nowait(
                            {"type": "content", "content": accumulated_content}
                        )
                in_thinking = True

            # Incorporate any thinking tail that was split from a
            # __THINKING_END__ boundary, then route the rest.
            if thinking_tail:
                thinking_content += thinking_tail
                payload = {"type": "thinking", "content": thinking_content}
            elif in_thinking:
                thinking_content += chunk
                payload = {"type": "thinking", "content": thinking_content}
            else:
                accumulated_content += chunk
                payload = {"type": "content", "content": accumulated_content}

            with contextlib.suppress(asyncio.QueueFull):
                send_queue.put_nowait(payload)

        has_tools = False
        tool_calls_info = []

        # Send session info immediately when AI starts responding
        if (
            active_agent.session_manager
            and active_agent.session_manager.current_session
        ):
            try:
                await websocket.send_json(
                    {
                        "type": "session_start",
                        "session_id": active_agent.session_manager.current_session.id,
                    }
                )
            except WebSocketDisconnect:
                return

        try:
            msg_count_before = len(active_agent.messages)
            response = await active_agent.run_streaming(prompt, on_chunk=on_chunk)
            for msg in active_agent.messages[msg_count_before:]:
                tc = getattr(msg, "tool_calls", None)
                if tc:
                    has_tools = True
                    for t in tc:
                        name = "unknown"
                        args = {}
                        if isinstance(t, dict):
                            name = t.get("function", {}).get("name", "unknown")
                            raw_args = t.get("function", {}).get("arguments", {})
                        else:
                            name = getattr(t, "name", "unknown")
                            raw_args = getattr(t, "arguments", {})

                        # Handle arguments - could be string, dict, or already parsed
                        if isinstance(raw_args, str):
                            # First, fix any escaped unicode (e.g., \\u0131 -> ü)
                            try:
                                # Try to unescape and parse as JSON
                                unescaped = raw_args.encode().decode("unicode_escape")
                                args = json.loads(unescaped)
                            except (json.JSONDecodeError, UnicodeDecodeError):
                                try:
                                    # Try direct parse
                                    args = json.loads(raw_args)
                                except json.JSONDecodeError:
                                    args = {"raw": raw_args}
                        elif isinstance(raw_args, dict):
                            args = raw_args
                        else:
                            args = {"raw": str(raw_args)}

                        tc_info = {"name": name, "arguments": args}
                        if "result" in t:
                            tc_info["result"] = t["result"]
                        tool_calls_info.append(tc_info)

            if not accumulated_content:
                accumulated_content = response

        except asyncio.CancelledError:
            # Keep accumulated_content as-is (partial response preserved)
            thinking_content = ""
            has_tools = False
            tool_calls_info = []
            logger.debug("Generation cancelled, preserving partial content")
        except Exception as e:
            logger.error(f"WebSocket chat error: {e}", exc_info=True)
            await websocket.send_json(
                {
                    "type": "error",
                    "content": "An error occurred while processing your request. Please try again.",
                }
            )
            return
        finally:
            await send_queue.put(None)
            await sender_task
            streaming_task = None

        timestamp = datetime.now().strftime("%H:%M")

        _ws_message_history.append(
            {
                "role": "assistant",
                "content": accumulated_content,
                "timestamp": timestamp,
                "thinking": thinking_content,
                "has_tools": has_tools,
            }
        )

        # Send done message first
        try:
            await websocket.send_json(
                {
                    "type": "done",
                    "content": accumulated_content,
                    "thinking": thinking_content,
                    "timestamp": timestamp,
                    "has_tools": has_tools,
                    "tool_calls": tool_calls_info,
                    "session_id": active_agent.session_manager.current_session.id
                    if active_agent.session_manager
                    and active_agent.session_manager.current_session
                    else None,
                    "title": active_agent.session_manager.current_session.title
                    if active_agent.session_manager
                    and active_agent.session_manager.current_session
                    else None,
                }
            )
        except WebSocketDisconnect:
            pass

        # Generate title in background (after sending done)
        if (
            active_agent.session_manager
            and active_agent.session_manager.current_session
            and not active_agent.session_manager.current_session.title
        ):
            asyncio.create_task(_generate_title_async(active_agent))

    try:
        # 1. Wait for config
        raw_config = await websocket.receive_text()
        config = WsConfigPayload.model_validate_json(raw_config)
        active_agent = _create_runtime_agent(
            config.provider,
            config.model,
            api_key=config.api_key,
            session_id=config.session_id,
        )
        # Trigger auto-title if needed
        if (
            active_agent.session_manager
            and active_agent.session_manager.current_session
            and not active_agent.session_manager.current_session.title
        ):
            new_title = await active_agent.generate_title()
            if new_title:
                active_agent.session_manager.current_session.title = new_title
                active_agent.save_session()

        await websocket.send_json(
            {
                "type": "ready",
                "session_id": active_agent.session_manager.current_session.id
                if active_agent.session_manager
                and active_agent.session_manager.current_session
                else None,
                "title": active_agent.session_manager.current_session.title
                if active_agent.session_manager
                and active_agent.session_manager.current_session
                else None,
            }
        )

        # 2. Continuous message loop
        while True:
            raw_message = await websocket.receive_text()
            message = WsMessagePayload.model_validate_json(raw_message)

            if message.type == "pong":
                continue

            if message.type == "stop":
                stop_requested = True
                if streaming_task and not streaming_task.done():
                    streaming_task.cancel()
                continue

            if message.type == "edit":
                edit_index = message.index
                edit_content = message.content

                logger.debug(
                    "ws:edit",
                    extra={
                        "index": edit_index,
                        "content": edit_content[:30] if edit_content else None,
                        "session_id": message.session_id,
                    },
                )

                if edit_index is None:
                    await websocket.send_json(
                        {"type": "error", "content": "Missing edit index"}
                    )
                    continue

                if not active_agent.session_manager or not message.session_id:
                    await websocket.send_json(
                        {"type": "error", "content": "No active session"}
                    )
                    continue

                session = active_agent.session_manager.load_session(message.session_id)
                if not session:
                    await websocket.send_json(
                        {"type": "error", "content": "Session not found"}
                    )
                    continue
                logger.debug(
                    "ws:edit:session_loaded",
                    extra={
                        "session_id": session.id if session else None,
                        "messages_count": len(session.messages) if session else 0,
                        "all_roles": [m.get("role") for m in session.messages]
                        if session
                        else [],
                    },
                )
                if (
                    not session
                    or edit_index < 0
                    or edit_index >= len(session.messages) - 1
                ):
                    await websocket.send_json(
                        {"type": "error", "content": "Invalid edit index"}
                    )
                    continue

                target_msg = session.messages[edit_index]
                logger.debug(
                    "ws:edit:target_msg",
                    extra={
                        "target_msg": target_msg,
                        "role": target_msg.get("role"),
                        "edit_index": edit_index,
                        "session_messages": session.messages,
                    },
                )

                # Frontend excludes system message from its array, but session includes it
                # So frontend index 0 = session index 1, frontend index N = session index N+1
                target_index = edit_index + 1
                target_msg = session.messages[target_index]

                if not edit_content:
                    await websocket.send_json(
                        {"type": "error", "content": "Missing edit content"}
                    )
                    continue

                logger.debug(
                    "ws:edit:processing",
                    extra={
                        "edit_index": edit_index,
                        "target_index": target_index,
                        "session_messages_before": len(session.messages),
                        "edit_content": edit_content[:50],
                    },
                )

                # Load session and update the target message with new content
                active_agent.session_manager.current_session = session

                session.messages[target_index] = {
                    "role": "user",
                    "content": edit_content,
                    "timestamp": session.messages[target_index].get(
                        "timestamp", datetime.now().strftime("%H:%M")
                    ),
                }

                # Truncate everything at and after target_index
                # This removes the old user message so run_agent can add it fresh
                active_agent.session_manager.truncate_history(target_index)

                # Deserialize session messages to agent messages
                active_agent.messages = deserialize_messages(session.messages)

                # Also update local message_history to match the truncated session
                _ws_message_history[:] = _ws_message_history[:target_index]

                # Truncate any existing streaming task and run agent with new prompt
                if streaming_task and not streaming_task.done():
                    streaming_task.cancel()
                    await asyncio.sleep(0.1)

                stop_requested = False
                streaming_task = asyncio.create_task(run_agent(edit_content))
                continue

            if message.type == "message" or not message.type:
                prompt = (message.content or "").strip()
                if not prompt:
                    continue

                # Load the session if session_id is provided
                if message.session_id and active_agent.session_manager:
                    active_agent.messages = []
                    active_agent._pending_summary = None
                    prev_session_id = (
                        active_agent.session_manager.current_session.id
                        if active_agent.session_manager.current_session
                        else None
                    )
                    prev_msg_count = len(active_agent.messages)
                    load_result = active_agent.load_session(message.session_id)
                    if load_result.startswith("Session not found"):
                        logger.warning(
                            "ws:session not visible, creating directly: %s",
                            message.session_id,
                        )
                        active_agent.session_manager.create_session(
                            session_id=message.session_id
                        )
                        active_agent.messages = []
                        load_result = active_agent.load_session(message.session_id)
                    logger.warning(
                        "ws:trace load_session"
                        " requested=%s prev_session=%s prev_msgs=%d"
                        " result=%s"
                        " now_session=%s now_msgs=%d"
                        " db_path=%s"
                        " messages=%s",
                        message.session_id,
                        prev_session_id,
                        prev_msg_count,
                        load_result,
                        active_agent.session_manager.current_session.id
                        if active_agent.session_manager.current_session
                        else None,
                        len(active_agent.messages),
                        str(active_agent.session_manager.db_path),
                        [m.get("role") if isinstance(m, dict) else getattr(m, "role", "?")
                         for m in active_agent.messages[:3]],
                    )

                if streaming_task and not streaming_task.done():
                    streaming_task.cancel()
                    await asyncio.sleep(0.1)  # Small delay to ensure cleanup

                stop_requested = False
                streaming_task = asyncio.create_task(run_agent(prompt))

    except (WebSocketDisconnect, json.JSONDecodeError, ValueError):
        pass
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}", exc_info=True)
        with contextlib.suppress(Exception):
            await websocket.send_json(
                {
                    "type": "error",
                    "content": "WebSocket connection error. Please refresh and try again.",
                }
            )
    finally:
        if streaming_task and not streaming_task.done():
            streaming_task.cancel()
        keepalive_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await keepalive_task


@app.get("/api/review")
async def review_document():
    """Expose review recommendations for UI hints."""
    review_path = Path("docs/WEB_UI_REVIEW.md")
    if not review_path.exists():
        return {"sections": []}

    lines = review_path.read_text(encoding="utf-8").splitlines()
    sections: list[str] = []
    for line in lines:
        if line.startswith("## "):
            sections.append(line.removeprefix("## ").strip())
    return {"sections": sections}


class ChatRequest(BaseModel):
    session_id: str | None = None
    prompt: str
    provider: str = "ollama"
    model: str = "qwen3:4b-instruct"
    api_key: str | None = None
    stream: bool = False


class RouteRequest(BaseModel):
    prompt: str


def get_or_create_agent(req: ChatRequest) -> Agent:
    """Retrieve an existing agent for a session or create a new one."""
    global _state  # noqa: F821 - global statement
    if _state is None:
        _state = AppState()
    if _state.agent is None:
        _state.agent = _create_runtime_agent(
            provider=req.provider, model=req.model, api_key=req.api_key
        )

    agent = _state.agent
    if req.session_id and agent.session_manager:
        existing = agent.session_manager.load_session(req.session_id)
        if not existing:
            agent.session_manager.create_session(req.session_id)

    return agent


@app.post("/chat", tags=["Chat"])
async def handle_chat(request: ChatRequest):
    """Synchronous chat endpoint."""
    try:
        agent = get_or_create_agent(request)
        response = await agent.run(request.prompt)
        session_id = None
        if agent.session_manager and agent.session_manager.current_session:
            session_id = agent.session_manager.current_session.id
        return {
            "session_id": session_id,
            "response": response,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/route", tags=["Routing"])
async def route_intent(request: RouteRequest):
    """Determine the optimal sub-agent for a user prompt via Semantic Routing."""
    try:
        state = get_state()
        if state.agent is None:
            raise HTTPException(status_code=503, detail="Agent not initialized")
        router = SemanticRouter(state.agent)
        target = await router.route(request.prompt)
        return {"target_agent": target}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stream", tags=["Chat"])
async def stream_chat(
    prompt: str,
    session_id: str | None = None,
    provider: str = "ollama",
    model: str = "qwen3:4b-instruct",
):
    """Server-Sent Events (SSE) streaming endpoint."""
    req = ChatRequest(
        prompt=prompt, session_id=session_id, provider=provider, model=model
    )
    agent = get_or_create_agent(req)

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def on_chunk(chunk: str):
        queue.put_nowait(chunk)

    async def chat_runner():
        try:
            await agent.run_streaming(prompt, on_chunk=on_chunk)
        finally:
            await queue.put(None)

    asyncio.create_task(chat_runner())

    async def event_generator():
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def run_server(host: str = "0.0.0.0", port: int = DEFAULT_WEB_PORT):
    """Run the FastAPI server."""
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    run_server()
