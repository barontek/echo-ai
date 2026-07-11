"""FastAPI web backend for Echo AI."""

from __future__ import annotations

import ast
import contextlib
import hmac
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Annotated, Any

import httpx
import uvicorn

from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from .constants import ECHO_DATA_DIR, OLLAMA_BASE_URL, LM_STUDIO_BASE_URL, CORS_FRONTEND_PORT, CORS_ALT_FRONTEND_PORT, CORS_STREAMLIT_PORT
from .core import Agent, AgentConfig, create_agent
from .config import DEFAULT_SESSION_DIR, get_safety_config, get_tools, load_config
from .safety import SafetyConfig
from .rate_limit import RateLimiter
from .tools.web import close_http_client
from .web_utils import filter_messages_for_ui
from .logging_utils import set_correlation_id
from .core.router import SemanticRouter
from . import web_models
from .web_models import (
    AppState,
    ChatRequest,
    ConfigPayload,
    PreferencesPayload,
    PUBLIC_PATHS,
    RouteRequest,
    UNLOCK_TOKEN_HEADER,
    get_state,
    require_unlocked,
)


logger = logging.getLogger(__name__)

DEFAULT_WEB_PORT = int(os.environ.get("ECHO_WEB_PORT", "8080"))
DEFAULT_PROVIDER = os.environ.get("ECHO_DEFAULT_PROVIDER", "ollama")
DEFAULT_MODEL = os.environ.get("ECHO_DEFAULT_MODEL", "")  # Model is selected from frontend UI; empty means deferred
FALLBACK_MODELS = ast.literal_eval(os.environ.get("ECHO_FALLBACK_MODELS", '["llama3.2:latest", "phi3.5:latest"]'))
OPENAI_MODELS = ast.literal_eval(os.environ.get("ECHO_OPENAI_MODELS", '["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"]'))
ANTHROPIC_MODELS = ast.literal_eval(os.environ.get(
    "ECHO_ANTHROPIC_MODELS",
    '["claude-sonnet-4-20250514", "claude-4-5-sonnet-20250710", "claude-3-5-sonnet-latest", "claude-3-5-haiku-latest", "claude-3-opus-latest"]',
))

_models_cache: dict[str, tuple[float, dict]] = {}
_MODELS_CACHE_TTL = 60.0

_PREFERENCES_PATH = ECHO_DATA_DIR / "preferences.json"


def _load_preferences() -> dict[str, str]:
    _PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _PREFERENCES_PATH.exists():
        try:
            return json.loads(_PREFERENCES_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            logger.debug("Failed to load preferences: %s", e)
    return {}


def _save_preferences(prefs: dict[str, str]) -> None:
    _PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PREFERENCES_PATH.write_text(json.dumps(prefs, indent=2), encoding="utf-8")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""

    logger.info("=" * 50)
    logger.info("  Echo AI - Starting up...")
    logger.info("=" * 50)
    logger.info("  Version: 0.1.0")
    logger.info(f"  Provider: {DEFAULT_PROVIDER}")
    logger.info("  Model: selected from frontend UI")
    logger.info("=" * 50)

    # Ensure state container exists (lazily created on first access)
    get_state()
    # Agent creation is deferred — the frontend sends model/provider via WebSocket
    yield
    logger.info("Shutting down Echo AI...")

    # Close shared HTTP client
    await close_http_client()

    # Clean up rate limiter
    _rate_limiter.close()

    # Close agent and cleanup resources
    if web_models._state and web_models._state.agent:
        try:
            if web_models._state.agent.session_manager:
                web_models._state.agent.session_manager.close()
        except Exception as e:
            logger.debug(f"Error closing session manager: {e}")

        try:
            web_models._state.agent.close()
        except Exception as e:
            logger.debug(f"Error closing agent: {e}")

    web_models._state = None
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


# Rate limiting configuration
_rate_limiter = RateLimiter()
_rate_config = load_config().get("web", {}).get("rate_limit", {})
_RATE_LIMIT_REQUESTS = _rate_config.get("requests", 60)
_RATE_LIMIT_WINDOW = _rate_config.get("window_seconds", 60)


def _get_api_key() -> str | None:
    """Load the API key from config (fresh every call)."""
    return load_config().get("web", {}).get("api_key")


async def _check_rate_limit(client_ip: str) -> tuple[bool, int]:
    """Check if client IP is within rate limits. Returns (allowed, remaining)."""
    return await _rate_limiter.check(client_ip, _RATE_LIMIT_REQUESTS, _RATE_LIMIT_WINDOW)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Require Bearer token on /api/* if ECHO_API_KEY is configured."""
    api_key = _get_api_key()
    if api_key is None:
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
        if not hmac.compare_digest(token, api_key):
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

    allowed, remaining = await _check_rate_limit(client_ip)
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
async def unlock_token_middleware(request: Request, call_next):
    """Require a valid unlock token on protected /api/* paths.

    The unlock token is issued by ``POST /api/unlock`` or
    ``POST /api/setup``.  Public paths (status, health, model
    listing, etc.) are exempt.

    If the database is locked (no agent), the token check is
    skipped and ``require_unlocked()`` in each route handler
    will reject the request with 423 instead.
    """
    path = request.url.path

    # Skip public paths
    if path in PUBLIC_PATHS or path.startswith("/ws"):
        return await call_next(request)

    if path.startswith("/api/"):
        state = get_state()
        # Only require token if database is unlocked and tokens exist
        if state.agent is not None and state.active_tokens:
            token = request.headers.get(UNLOCK_TOKEN_HEADER, "")
            if not token or token not in state.active_tokens:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or missing unlock token"},
                )

    return await call_next(request)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log all HTTP requests and responses for debugging."""

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


def _extract_tool_calls_info(
    tool_calls: list, messages: list[Any] | None = None
) -> list[dict]:
    tool_calls_info: list[dict] = []

    # Build tool_call_id -> result mapping from tool messages (role="tool")
    result_map: dict[str, dict] = {}
    if messages is not None:
        for msg in messages:
            if isinstance(msg, dict):
                if msg.get("role") == "tool":
                    tc_id = msg.get("tool_call_id")
                    if tc_id:
                        result_map[tc_id] = {
                            "content": msg.get("content"),
                            "error": msg.get("error_category"),
                        }
            elif getattr(msg, "role", None) == "tool":
                tc_id = getattr(msg, "tool_call_id", None)
                if tc_id:
                    result_map[tc_id] = {
                        "content": getattr(msg, "content", None),
                        "error": getattr(msg, "error_category", None),
                    }

    for t in tool_calls:
        name: str = "unknown"
        args: dict = {}
        tc_id: str | None = None
        if isinstance(t, dict):
            name = t.get("function", {}).get("name", "unknown")
            raw_args = t.get("function", {}).get("arguments", {})
            tc_id = t.get("id") or t.get("function", {}).get("id")
        else:
            name = getattr(t, "name", "unknown")
            raw_args = getattr(t, "arguments", {})
            tc_id = getattr(t, "id", None)

        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                try:
                    unescaped = raw_args.encode().decode("unicode_escape")
                    args = json.loads(unescaped)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    args = {"raw": raw_args}
        elif isinstance(raw_args, dict):
            args = raw_args
        else:
            args = {"raw": str(raw_args)}

        tc_info: dict = {"name": name, "arguments": args}
        if tc_id and tc_id in result_map:
            tc_info["result"] = result_map[tc_id]
        tool_calls_info.append(tc_info)
    return tool_calls_info


def _get_cors_config() -> dict:
    """Get CORS configuration from config.yaml."""

    config = load_config()
    web_config = config.get("web", {})
    cors_config = web_config.get("cors", {})

    if os.environ.get("ALLOW_ALL_ORIGINS", "").lower() in ("1", "true", "yes"):
        return {
            "origins": ["*"],
            "credentials": False,
            "methods": cors_config.get("allow_methods", ["*"]),
            "headers": cors_config.get("allow_headers", ["*"]),
        }

    local_network_origins = []
    try:
        import socket

        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        local_network_origins = [
            f"http://{local_ip}:{CORS_FRONTEND_PORT}",
            f"http://{local_ip}:{DEFAULT_WEB_PORT}",
            f"http://{local_ip}:{CORS_ALT_FRONTEND_PORT}",
        ]
    except (OSError, socket.gaierror) as e:
        logger.debug("Could not resolve local network origins: %s", e)

    default_origins = [
        f"http://localhost:{CORS_FRONTEND_PORT}",
        f"http://localhost:{DEFAULT_WEB_PORT}",
        f"http://127.0.0.1:{DEFAULT_WEB_PORT}",
        f"http://localhost:{CORS_STREAMLIT_PORT}",
        f"http://127.0.0.1:{CORS_STREAMLIT_PORT}",
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



async def get_models_data(provider: str = "ollama", base_url: str | None = None) -> dict[str, Any]:
    """List available models for the given provider (with caching)."""
    cache_key = f"models_async_{provider}"
    now = time.monotonic()

    # Check cache
    if cache_key in _models_cache:
        cached_time, cached_data = _models_cache[cache_key]
        if now - cached_time < _MODELS_CACHE_TTL:
            return cached_data

    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            if provider == "ollama":
                url = f"{base_url or OLLAMA_BASE_URL}/api/tags"
                response = await client.get(url, timeout=5.0)
                response.raise_for_status()
                models = response.json().get("models", [])
                result = {"models": [m["name"] for m in models]}
            elif provider == "lm_studio":
                url = f"{base_url or LM_STUDIO_BASE_URL}/v1/models"
                response = await client.get(url, timeout=5.0)
                response.raise_for_status()
                models = response.json().get("data", [])
                result = {"models": [m["id"] for m in models]}
            elif provider == "openai":
                return {"models": OPENAI_MODELS}
            elif provider == "anthropic":
                return {"models": ANTHROPIC_MODELS}
            else:
                return {"models": FALLBACK_MODELS}

            # Update cache
            _models_cache[cache_key] = (now, result)
            return result
    except Exception as e:
        logger.debug("Failed to fetch %s models: %s", provider, e)
        fallback = {
            "ollama": FALLBACK_MODELS,
            "lm_studio": FALLBACK_MODELS,
            "openai": OPENAI_MODELS,
            "anthropic": ANTHROPIC_MODELS,
        }.get(provider, FALLBACK_MODELS)
        return {
            "models": fallback,
            "error": f"Could not reach {provider}. Showing fallback models.",
        }


def get_models_sync(provider: str = "ollama", base_url: str | None = None) -> dict[str, Any]:
    """List available models for the given provider, sync version (with caching)."""
    cache_key = f"models_sync_{provider}"
    now = time.monotonic()

    # Check cache
    if cache_key in _models_cache:
        cached_time, cached_data = _models_cache[cache_key]
        if now - cached_time < _MODELS_CACHE_TTL:
            return cached_data

    try:
        if provider == "ollama":
            url = f"{base_url or OLLAMA_BASE_URL}/api/tags"
            response = httpx.get(url, timeout=5.0)
            response.raise_for_status()
            models = response.json().get("models", [])
            result = {"models": [m["name"] for m in models]}
        elif provider == "lm_studio":
            url = f"{base_url or LM_STUDIO_BASE_URL}/v1/models"
            response = httpx.get(url, timeout=5.0)
            response.raise_for_status()
            models = response.json().get("data", [])
            result = {"models": [m["id"] for m in models]}
        elif provider == "openai":
            return {"models": OPENAI_MODELS}
        elif provider == "anthropic":
            return {"models": ANTHROPIC_MODELS}
        else:
            return {"models": FALLBACK_MODELS}

        # Update cache
        _models_cache[cache_key] = (now, result)
        return result
    except Exception as e:
        logger.debug("Failed to fetch %s models: %s", provider, e)
        fallback = {
            "ollama": FALLBACK_MODELS,
            "lm_studio": FALLBACK_MODELS,
            "openai": OPENAI_MODELS,
            "anthropic": ANTHROPIC_MODELS,
        }.get(provider, FALLBACK_MODELS)
        return {
            "models": fallback,
            "error": f"Could not reach {provider}. Showing fallback models.",
        }


def get_sessions_data(state: AppState) -> dict[str, Any]:
    """Return session metadata for the current runtime agent."""
    active_agent = state.agent
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
    active_agent = state.agent
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
    active_agent = state.agent
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
    active_agent = state.agent
    if active_agent and active_agent.session_manager:
        active_agent.session_manager.delete_session(session_id)

    if state.current_session_id == session_id:
        state.current_session_id = None
        state.message_history = []
        if active_agent:
            active_agent.messages = []

    return {"status": "ok"}


def _create_runtime_agent(
    provider: str,
    model: str,
    api_key: str | None = None,
    session_id: str | None = None,
    safety_config_override: SafetyConfig | None = None,
    fernet: Fernet | None = None,
) -> Agent:
    """Create an agent for the web UI with the same tool config as CLI."""
    if not model:
        raise ValueError("Model name is required. Select a model from the frontend UI.")
    if fernet is None:
        fernet = get_state().fernet
    config = load_config()
    safety_config = safety_config_override or get_safety_config(config)
    tools = get_tools(config, safety_config)

    base_url = config.get("model", {}).get("base_url")
    if provider in ("openai", "anthropic"):
        base_url = None  # Cloud providers don't need a base URL from config

    agent_config = AgentConfig(
        provider=provider,
        model=model,
        temperature=config.get("model", {}).get("temperature", 0.3),
        timeout=config.get("model", {}).get("timeout", 60),
        max_iterations=config.get("agent", {}).get("max_iterations", 50),
        system_prompt=config.get("agent", {}).get("system_prompt", ""),
        tools=tools,
        base_url=base_url,
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

    return create_agent(agent_config, api_key=api_key, session_id=session_id, fernet=fernet)





@app.get("/", include_in_schema=False)
async def index():
    """Redirect to React UI."""
    frontend_url = os.environ.get("ECHO_FRONTEND_URL", "http://localhost:3000")
    return RedirectResponse(url=frontend_url, status_code=302)



@app.get("/api/preferences", tags=["Preferences"])
async def get_preferences():
    """Get user preferences (last used model)."""
    return _load_preferences()


@app.post("/api/preferences", tags=["Preferences"])
async def update_preferences(payload: PreferencesPayload):
    """Persist user preferences (last used model and provider)."""
    prefs = _load_preferences()
    prefs["model"] = payload.model
    if payload.provider:
        prefs["provider"] = payload.provider
    _save_preferences(prefs)
    return {"status": "ok"}


@app.get("/api/config", tags=["Configuration"])
async def get_config(
    state: Annotated[AppState, Depends(get_state)],
):
    """Get the current agent configuration.

    Returns the current LLM provider, model, and other settings.
    If no agent is initialized yet, returns defaults from config.yaml.

    Returns:
        {"config": {"provider": "...", "model": "...", ...}}
    """
    if state.agent:
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
    # No agent yet — return the file-config defaults (model will be empty,
    # provider comes from config.yaml)
    cfg = load_config()
    model_cfg = cfg.get("model", {})
    agent_cfg = cfg.get("agent", {})
    return {
        "config": {
            "provider": model_cfg.get("provider", "ollama"),
            "model": model_cfg.get("name", ""),
            "temperature": model_cfg.get("temperature", 0.3),
            "max_iterations": agent_cfg.get("max_iterations", 50),
            "session_enabled": agent_cfg.get("session_enabled", True),
        }
    }


@app.post("/api/config", tags=["Configuration"])
async def update_config(
    config: ConfigPayload,
    state: Annotated[AppState, Depends(get_state)],
    _unlocked: None = Depends(require_unlocked),
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
    old_agent = state.agent
    state.agent = _create_runtime_agent(
        config.provider, config.model, api_key=config.api_key, fernet=state.fernet
    )
    if old_agent:
        try:
            if old_agent.session_manager:
                old_agent.session_manager.close()
            old_agent.close()
        except Exception as e:
            logger.debug(f"Error closing old agent: {e}")
    return {
        "status": "ok",
        "config": {"provider": config.provider, "model": config.model},
    }


async def _generate_title_async(
    active_agent: "Agent",
    websocket: Any | None = None,
) -> None:
    """Generate title in background without blocking."""
    try:
        if (
            not active_agent.session_manager
            or not active_agent.session_manager.current_session
            or active_agent.session_manager.current_session.title
            or getattr(active_agent.session_manager.current_session, 'title_generation_attempted', None) is True
        ):
            return

        session = active_agent.session_manager.current_session
        session.title_generation_attempted = True
        active_agent.save_session()

        new_title = await active_agent.generate_title()
        if (
            new_title
            and active_agent.session_manager
            and active_agent.session_manager.current_session
            and not active_agent.session_manager.current_session.title
        ):
            session = active_agent.session_manager.current_session
            session.title = new_title
            active_agent.save_session()
            if websocket:
                try:
                    await websocket.send_json({
                        "type": "title_updated",
                        "session_id": session.id,
                        "title": new_title,
                    })
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"Background title generation failed: {e}")


@app.get("/api/review")
async def review_document():
    """Expose review recommendations for UI hints."""
    review_path = Path(os.environ.get("ECHO_REVIEW_DOC_PATH", "docs/WEB_UI_REVIEW.md"))
    if not review_path.exists():
        return {"sections": []}

    lines = review_path.read_text(encoding="utf-8").splitlines()
    sections: list[str] = []
    for line in lines:
        if line.startswith("## "):
            sections.append(line.removeprefix("## ").strip())
    return {"sections": sections}


def get_or_create_agent(req: ChatRequest) -> Agent:
    """Retrieve an existing agent for a session or create a new one."""
    state = get_state()
    if state.agent is None:
        if not req.model:
            raise HTTPException(
                status_code=400,
                detail="Model name is required. Select a model from the frontend UI.",
            )
        state.agent = _create_runtime_agent(
            provider=req.provider, model=req.model, api_key=req.api_key, fernet=state.fernet
        )

    agent = state.agent
    if req.session_id and agent.session_manager:
        existing = agent.session_manager.load_session(req.session_id)
        if not existing:
            agent.session_manager.create_session(req.session_id)

    return agent


@app.post("/route", tags=["Routing"])
async def route_intent(
    request: RouteRequest,
    _unlocked: None = Depends(require_unlocked),
):
    """Determine the optimal sub-agent for a user prompt via Semantic Routing."""
    state = get_state()
    if state.agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    router = SemanticRouter(state.agent)
    target = await router.route(request.prompt)
    return {"target_agent": target}


from .routers.chat import router as chat_router  # noqa: E402
from .routers.health import router as health_router  # noqa: E402
from .routers.models import router as models_router  # noqa: E402
from .routers.sessions import router as sessions_router  # noqa: E402
from .routers.workflows import router as workflows_router  # noqa: E402
from .routers.unlock import router as unlock_router  # noqa: E402

app.include_router(chat_router)
app.include_router(health_router)
app.include_router(models_router)
app.include_router(sessions_router)
app.include_router(workflows_router)
app.include_router(unlock_router)


def run_server(host: str | None = None, port: int | None = None):
    """Run the FastAPI server.

    If *host* is not provided, the ``ECHO_HOST`` environment variable is
    read; if that is also unset, ``"127.0.0.1"`` is used (safe default).
    If *port* is not provided, ``ECHO_WEB_PORT`` (or ``8080``) is used.
    """
    if host is None:
        host = os.environ.get("ECHO_HOST", "127.0.0.1")
    if port is None:
        port = DEFAULT_WEB_PORT
    if host not in ("127.0.0.1", "localhost", "::1", "::ffff:127.0.0.1"):
        logger.warning(
            "Binding to %s:%d — the server is exposed beyond localhost. "
            "Use a reverse proxy with TLS (e.g. nginx + Let's Encrypt, "
            "Caddy, or cloudflare tunnel) to protect API keys and session "
            "data in transit.",
            host,
            port,
        )
    logger.info("Listening on %s:%d", host, port)
    # The database password is now resolved lazily via POST /api/unlock.
    uvicorn.run(app, host=host, port=port, reload=False, log_level="info")


if __name__ == "__main__":
    run_server()
