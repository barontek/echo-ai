"""FastAPI web backend for Echo AI."""

from __future__ import annotations

import contextlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import httpx
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from src.agentframework.core import Agent, AgentConfig, create_agent
from src.agentframework.config import DEFAULT_SESSION_DIR, get_safety_config, get_tools, load_config
from src.agentframework.rate_limit import RateLimiter
from src.agentframework.web_utils import filter_messages_for_ui
from src.agentframework.logging_utils import set_correlation_id
from src.agentframework.core.router import SemanticRouter
from src.agentframework.session import DBSessionModel

logger = logging.getLogger(__name__)

DEFAULT_WEB_PORT = 8080
DEFAULT_PROVIDER = "ollama"
DEFAULT_MODEL = "qwen3:4b-instruct"
FALLBACK_MODELS = [DEFAULT_MODEL, "llama3.2:latest", "phi3.5:latest"]

_models_cache: dict[str, tuple[float, dict]] = {}
_MODELS_CACHE_TTL = 60.0

_PREFERENCES_PATH = Path.home() / ".echo-ai" / "preferences.json"


def _load_preferences() -> dict[str, str]:
    _PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _PREFERENCES_PATH.exists():
        try:
            return json.loads(_PREFERENCES_PATH.read_text())
        except Exception:
            pass
    return {}


def _save_preferences(prefs: dict[str, str]) -> None:
    _PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PREFERENCES_PATH.write_text(json.dumps(prefs, indent=2))


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

    # Clean up rate limiter
    _rate_limiter.close()

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
    """Capture all unhandled exceptions."""
    # Handle ExceptionGroup from Python 3.13+ (extract the original exception)
    if isinstance(exc, ExceptionGroup):
        exc = exc.exceptions[0] if exc.exceptions else exc

    logger.error(f"Unhandled exception: {exc}", exc_info=True)
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


# API key authentication for Bearer token
_config = load_config()
_api_key: str | None = _config.get("web", {}).get("api_key")
if _api_key:
    logger.info("API key authentication is ENABLED")
else:
    logger.info("API key authentication is DISABLED")

# Rate limiting configuration
_rate_limiter = RateLimiter()
_rate_limit_config = _config.get("web", {}).get("rate_limit", {})
_RATE_LIMIT_REQUESTS = _rate_limit_config.get("requests", 60)
_RATE_LIMIT_WINDOW = _rate_limit_config.get("window_seconds", 60)


def _check_rate_limit(client_ip: str) -> tuple[bool, int]:
    """Check if client IP is within rate limits. Returns (allowed, remaining)."""
    return _rate_limiter.check(client_ip, _RATE_LIMIT_REQUESTS, _RATE_LIMIT_WINDOW)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Require Bearer token on /api/* if ECHO_API_KEY is configured."""
    if _api_key is None:
        return await call_next(request)

    if request.url.path in ("/health", "/health/detailed"):
        return await call_next(request)

    if request.url.path.startswith("/api/") or request.url.path == "/ws/chat":
        auth = request.headers.get("Authorization")
        if not auth:
            return JSONResponse(status_code=401, content={"detail": "Missing authentication"})
        if not auth.startswith("Bearer "):
            return JSONResponse(
                status_code=401, content={"detail": "Invalid authentication scheme"}
            )
        token = auth.removeprefix("Bearer ")
        if token != _api_key:
            return JSONResponse(status_code=401, content={"detail": "Invalid API key"})

    return await call_next(request)


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
    finally:
        duration = time.perf_counter() - start_time
        # Log after response is ready (or on error)
        logger.debug(
            f"[{cid}] <-- {request.method} {request.url.path} ({duration * 1000:.1f}ms)"
        )

    response.headers["X-Response-Time"] = f"{duration * 1000:.1f}ms"
    return response


def _extract_tool_calls_info(tool_calls: list) -> list[dict]:
    tool_calls_info: list[dict] = []
    for t in tool_calls:
        name: str = "unknown"
        args: dict = {}
        if isinstance(t, dict):
            name = t.get("function", {}).get("name", "unknown")
            raw_args = t.get("function", {}).get("arguments", {})
        else:
            name = getattr(t, "name", "unknown")
            raw_args = getattr(t, "arguments", {})

        if isinstance(raw_args, str):
            try:
                unescaped = raw_args.encode().decode("unicode_escape")
                args = json.loads(unescaped)
            except (json.JSONDecodeError, UnicodeDecodeError):
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {"raw": raw_args}
        elif isinstance(raw_args, dict):
            args = raw_args
        else:
            args = {"raw": str(raw_args)}

        tc_info: dict = {"name": name, "arguments": args}
        if isinstance(t, dict) and "result" in t:
            tc_info["result"] = t["result"]
        tool_calls_info.append(tc_info)
    return tool_calls_info


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


class PreferencesPayload(BaseModel):
    model: str


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



@app.get("/api/preferences", tags=["Preferences"])
async def get_preferences():
    """Get user preferences (last used model)."""
    return _load_preferences()


@app.post("/api/preferences", tags=["Preferences"])
async def update_preferences(payload: PreferencesPayload):
    """Persist user preferences (last used model)."""
    prefs = _load_preferences()
    prefs["model"] = payload.model
    _save_preferences(prefs)
    return {"status": "ok"}


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


# Include routers
from src.agentframework.routers.chat import router as chat_router  # noqa: E402
from src.agentframework.routers.health import router as health_router  # noqa: E402
from src.agentframework.routers.models import router as models_router  # noqa: E402
from src.agentframework.routers.sessions import router as sessions_router  # noqa: E402
from src.agentframework.routers.workflows import router as workflows_router  # noqa: E402

app.include_router(chat_router)
app.include_router(health_router)
app.include_router(models_router)
app.include_router(sessions_router)
app.include_router(workflows_router)


def run_server(host: str = "0.0.0.0", port: int = DEFAULT_WEB_PORT):
    """Run the FastAPI server."""
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    run_server()
