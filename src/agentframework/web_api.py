"""FastAPI web backend for Echo AI."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
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
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from src.agentframework.agent import Agent, AgentConfig, create_agent
from src.agentframework.config import get_safety_config, get_tools, load_config
from src.agentframework.constants import THINKING_END, THINKING_START
from src.agentframework.logging_utils import set_correlation_id
from src.agentframework.session import DBSessionModel
from src.workflows import get_workflow, list_workflows

logger = logging.getLogger(__name__)

DEFAULT_WEB_PORT = 8080
DEFAULT_PROVIDER = "ollama"
DEFAULT_MODEL = "qwen3:4b-instruct"
FALLBACK_MODELS = [DEFAULT_MODEL, "llama3.2:latest", "phi3.5:latest"]

# Pre-compiled patterns for message filtering (performance optimization)
_INTERNAL_PATTERNS = [
    re.compile(r"System Note: Tools executed"),
    re.compile(r"Tool '.*' returned:"),
    re.compile(r"^FAILED: .*"),
    re.compile(r"\[Persistent Memory\]"),
]


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


def __getattr__(name: str) -> Any:
    """Module-level attribute access for backward compatibility."""
    if name == "agent":
        return _state.agent if _state else None
    if name == "current_session_id":
        return _state.current_session_id if _state else None
    if name == "message_history":
        return _state.message_history if _state else []
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __setattr__(name: str, value: Any) -> None:
    """Module-level attribute setting for backward compatibility."""
    if name in ("agent", "current_session_id", "message_history"):
        if _state is not None:
            object.__setattr__(_state, name, value)
    else:
        raise AttributeError(f"cannot set attribute {name!r}")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    global _state
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
    if _state and _state.agent:
        _state.agent.close()
    _state = None


# Create FastAPI app with lifespan
app = FastAPI(title="Echo AI API", lifespan=lifespan)

# Mount FastHTML UI at /ui
try:
    from src.agentframework.ui.app import app as ui_app

    app.mount("/ui", ui_app)
except ImportError:
    logger.warning("FastHTML UI not available (python-fasthtml not installed)")


@app.get("/", include_in_schema=False)
async def root_redirect():
    """Redirect root path to FastHTML UI."""
    return RedirectResponse(url="/ui", status_code=302)


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
_RATE_LIMIT_REQUESTS = 60  # requests per window
_RATE_LIMIT_WINDOW = 60  # seconds


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


def _get_cors_config() -> dict:
    """Get CORS configuration from config.yaml."""
    config = load_config()
    web_config = config.get("web", {})
    cors_config = web_config.get("cors", {})
    return {
        "origins": cors_config.get(
            "origins",
            [
                "http://localhost:3000",
                f"http://localhost:{DEFAULT_WEB_PORT}",
                f"http://127.0.0.1:{DEFAULT_WEB_PORT}",
                "http://localhost:8501",
                "http://127.0.0.1:8501",
            ],
        ),
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
    """List available Ollama models for API callers."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:11434/api/tags", timeout=5.0)
            response.raise_for_status()
            models = response.json().get("models", [])
            return {"models": [m["name"] for m in models]}
    except Exception as e:
        logger.error("Failed to fetch Ollama models: %s", e)
        return {
            "models": FALLBACK_MODELS,
            "error": "Could not reach Ollama at http://localhost:11434/api/tags. Showing fallback models.",
        }


def get_models_sync() -> dict[str, Any]:
    """List available Ollama models for in-process UI callers."""
    try:
        response = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
        response.raise_for_status()
        models = response.json().get("models", [])
        return {"models": [m["name"] for m in models]}
    except Exception as e:
        logger.error("Failed to fetch Ollama models: %s", e)
        return {
            "models": FALLBACK_MODELS,
            "error": "Could not reach Ollama at http://localhost:11434/api/tags. Showing fallback models.",
        }


def get_sessions_data(state: AppState) -> dict[str, Any]:
    """Return session metadata for the current runtime agent."""
    active_agent = ensure_runtime_agent(state)
    if active_agent and active_agent.session_manager:
        sessions = [
            {"id": s.id, "title": s.title, "created_at": s.created_at.isoformat()}
            for s in active_agent.session_manager.list_sessions()
        ]
        return {"sessions": sessions}
    return {"sessions": []}


def create_session_data(state: AppState) -> dict[str, Any]:
    """Create a fresh chat session for the shared UI/backend state."""
    active_agent = ensure_runtime_agent(state)
    if active_agent and active_agent.session_manager:
        active_agent.session_manager.create_session()
        if active_agent.session_manager.current_session:
            state.current_session_id = active_agent.session_manager.current_session.id
            active_agent.messages = []
            state.message_history = []
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
        state.message_history = filter_messages_for_ui(active_agent.messages)
        title = None
        if active_agent.session_manager.current_session:
            title = active_agent.session_manager.current_session.title
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


def filter_messages_for_ui(messages: list[Any]) -> list[dict[str, Any]]:
    """Filter messages for UI rendering, removing raw tool/system noise."""
    filtered = []

    for msg in messages:
        role = getattr(msg, "role", msg.get("role") if isinstance(msg, dict) else "")
        content = (
            getattr(msg, "content", msg.get("content") if isinstance(msg, dict) else "")
            or ""
        )

        # Extract metadata if available
        metadata = getattr(
            msg, "metadata", msg.get("metadata") if isinstance(msg, dict) else None
        )
        timestamp = getattr(
            msg, "timestamp", msg.get("timestamp") if isinstance(msg, dict) else ""
        )
        thinking = getattr(
            msg, "thinking", msg.get("thinking") if isinstance(msg, dict) else ""
        )

        if metadata and isinstance(metadata, dict):
            timestamp = timestamp or metadata.get("timestamp", "")
            thinking = thinking or metadata.get("thinking", "")

        # Handle tool calls
        tool_calls = getattr(
            msg, "tool_calls", msg.get("tool_calls") if isinstance(msg, dict) else None
        )
        has_tools = bool(tool_calls)

        # Skip system and tool messages
        if role == "tool":
            continue
        if role == "system":
            continue

        # Assistant messages with tool_calls should always be included
        # Otherwise, check skip conditions:
        if not has_tools:
            # Drop if it's truly empty assistant message
            if role == "assistant" and not content.strip():
                continue

            # Ignore internal framework strings (using pre-compiled patterns)
            is_internal = any(pattern.search(content) for pattern in _INTERNAL_PATTERNS)
            if is_internal:
                continue

        # 3. Extract thinking content if present (stored with markers)
        display_content = content
        if not thinking and THINKING_START in content and THINKING_END in content:
            parts = content.split(THINKING_END, 1)
            thinking = parts[0].replace(THINKING_START, "").strip()
            display_content = parts[1].strip()

        msg_dict = {
            "role": role,
            "content": display_content,
            "timestamp": timestamp,
            "has_tools": has_tools,
        }
        if thinking:
            msg_dict["thinking"] = thinking
        if tool_calls:
            # Normalize tool_calls structure for frontend
            normalized = []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    if "function" in tc:
                        normalized.append(
                            {
                                "name": tc["function"].get("name", "unknown"),
                                "arguments": tc["function"].get("arguments", {}),
                            }
                        )
                    else:
                        normalized.append(
                            {
                                "name": tc.get("name", "unknown"),
                                "arguments": tc.get("arguments", {}),
                            }
                        )
                else:
                    normalized.append(
                        {
                            "name": getattr(tc, "name", "unknown"),
                            "arguments": getattr(tc, "arguments", {}),
                        }
                    )
            msg_dict["tool_calls"] = normalized

        filtered.append(msg_dict)

    return filtered


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
        session_dir=config.get("agent", {}).get("session_dir", ".agent_sessions"),
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


class WorkflowRunPayload(BaseModel):
    workflow_id: str = Field(min_length=1)
    topic: str = Field(min_length=1)


@app.get("/")
async def index():
    """Serve the main HTML page."""
    return FileResponse("static/index.html")


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
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/chat", include_in_schema=False)
async def chat_ui(message: ChatPayload, state: Annotated[AppState, Depends(get_state)]):
    """Legacy chat endpoint for UI compatibility. Redirects to /api/chat."""
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

    Connect to: `ws://localhost:8080/ws/chat`

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
    const ws = new WebSocket('ws://localhost:8080/ws/chat');
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'content') {
            console.log('Received:', data.content);
        }
    };
    ws.send(JSON.stringify({type: 'message', content: 'Hi!'}));
    ```
    """
    await websocket.accept()

    # Get state from app state (accessed via module-level _state for WebSocket)
    state = _state
    if state is None:
        await websocket.send_json(
            {"type": "error", "content": "Server not initialized"}
        )
        return

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

        timestamp = datetime.now().strftime("%H:%M")
        state.message_history.append(
            {"role": "user", "content": prompt, "timestamp": timestamp}
        )
        await websocket.send_json(
            {
                "type": "message",
                "role": "user",
                "content": prompt,
                "timestamp": timestamp,
            }
        )

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

            if THINKING_START in chunk:
                chunk = chunk.replace(THINKING_START, "")
                in_thinking = True
            if THINKING_END in chunk:
                chunk = chunk.replace(THINKING_END, "")
                in_thinking = False

            if in_thinking:
                thinking_content += chunk
                payload = {"type": "thinking", "content": thinking_content}
            else:
                accumulated_content += chunk
                payload = {"type": "content", "content": accumulated_content}

            with contextlib.suppress(asyncio.QueueFull):
                send_queue.put_nowait(payload)

        has_tools = False
        tool_calls_info = []

        try:
            response = await active_agent.run_streaming(prompt, on_chunk=on_chunk)
            for msg in active_agent.messages:
                tc = getattr(msg, "tool_calls", None)
                if tc:
                    has_tools = True
                    for t in tc:
                        if isinstance(t, dict):
                            tool_calls_info.append(
                                {
                                    "name": t.get("function", {}).get(
                                        "name", "unknown"
                                    ),
                                    "arguments": t.get("function", {}).get(
                                        "arguments", {}
                                    ),
                                }
                            )
                        else:
                            tool_calls_info.append(
                                {
                                    "name": getattr(t, "name", "unknown"),
                                    "arguments": getattr(t, "arguments", {}),
                                }
                            )

            if not accumulated_content:
                accumulated_content = response

        except asyncio.CancelledError:
            accumulated_content = "Response stopped by user."
            thinking_content = ""
            has_tools = False
            tool_calls_info = []
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

        state.message_history.append(
            {
                "role": "assistant",
                "content": accumulated_content,
                "timestamp": timestamp,
                "thinking": thinking_content,
                "has_tools": has_tools,
            }
        )

        # Send done message first
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

            if message.type == "message" or not message.type:
                prompt = (message.content or "").strip()
                if not prompt:
                    continue

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


def run_server(host: str = "127.0.0.1", port: int = DEFAULT_WEB_PORT):
    """Run the FastAPI server."""
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
