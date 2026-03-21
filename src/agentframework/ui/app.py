"""FastHTML app for Echo AI chat UI."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from urllib.parse import parse_qs

from fasthtml.common import *  # noqa: F403, F405, E501

from .components import (
    chat_container,
    main_page,
    message_bubble,
    session_list,
)
from .markdown import format_message_content

logger = logging.getLogger(__name__)

app, rt = fast_app(debug=True, exts=["ws"])


async def _send_error(send, message: str) -> None:
    await send(
        Div(
            message,
            cls="message assistant error-state",
            style="color: red;",
        )
    )


def _render_ui_error(message: str):
    return Div(message, cls="error-state", style="color: red;")


def _extract_current_model(state) -> str:
    if state.agent and getattr(state.agent, "config", None):
        return state.agent.config.model
    return "qwen3:4b-instruct"


def _streaming_message(content: str, *, thinking: str = "", oob: bool = False):
    rendered = format_message_content(content) if content else "Thinking..."
    thinking_div = Div(thinking, cls="thinking") if thinking else None
    parts = [Div("Assistant", cls="role"), Div(rendered, cls="content streaming")]
    if thinking_div:
        parts.append(thinking_div)
    attrs = {"cls": "message assistant", "id": "streaming-message"}
    if oob:
        attrs["hx_swap_oob"] = "true"
    return Div(*parts, **attrs)


@rt("/")
def get():
    """Main chat page using in-process backend helpers instead of localhost HTTP."""
    from src.agentframework.web_api import get_models_sync, get_sessions_data, get_state

    state = get_state()
    models_payload = get_models_sync()
    models = models_payload.get("models", ["qwen3:4b-instruct"])
    sessions = get_sessions_data(state).get("sessions", [])
    current_model = _extract_current_model(state)

    if current_model not in models and current_model:
        models = [current_model, *models]

    page = main_page(models, sessions, [], current_model)
    error = models_payload.get("error")
    if error:
        logger.error("Failed to load models for UI shell: %s", error)
        return (*page, _render_ui_error(error))
    return page


@rt("/sessions/new")
def new_session():
    """Create a new session using shared in-memory state."""
    from src.agentframework.web_api import (
        create_session_data,
        get_state,
        get_sessions_data,
    )

    state = get_state()
    data = create_session_data(state)
    session_id = data.get("session_id")

    if session_id:
        sessions = get_sessions_data(state).get("sessions", [])
        return session_list(sessions, active_id=session_id)

    error = data.get("error", "Failed to create session")
    logger.error("Session creation failed in UI route: %s", error)
    return _render_ui_error(error)


@rt("/sessions/{session_id}")
def get_session(session_id: str):
    """Load a session and return its messages."""
    from src.agentframework.web_api import get_state, load_session_data

    data = load_session_data(session_id, get_state())
    if error := data.get("error"):
        logger.error("Failed to load session %s: %s", session_id, error)
        return _render_ui_error(error)
    return chat_container(data.get("messages", []))


@rt("/models")
def update_model():
    """Refresh model selector options from the local backend helper."""
    from src.agentframework.web_api import get_models_sync

    models_data = get_models_sync()
    if error := models_data.get("error"):
        logger.error("Failed to refresh model list: %s", error)
        return _render_ui_error(error)

    models = models_data.get("models", [])
    options = [Option(m, value=m) for m in models]
    return Select(
        *options,
        id="model-select",
        name="model",
        hx_get="/ui/models",
        hx_target="#model-select",
        hx_swap="outerHTML",
    )


@rt("/chat")
async def chat(message: str = ""):
    """Handle chat message submission."""
    if not message.strip():
        return ""

    user_msg = message_bubble(role="user", content=message)
    return Div(user_msg, id="new-message", cls="new-message")


@rt("/sessions/delete/{session_id}")
def delete_session(session_id: str):
    """Delete a session using shared backend helpers."""
    from src.agentframework.web_api import delete_session_data, get_state

    result = delete_session_data(session_id, get_state())
    if error := result.get("error"):
        logger.error("Failed to delete session %s: %s", session_id, error)
        return _render_ui_error(error)
    return P(f"Deleted: {session_id}", style="color: green;")


@app.ws("/ws/chat")
async def chat_ws(message: str, send):
    """Stream directly from the agent into HTMX without proxying another websocket."""
    from src.agentframework.constants import THINKING_END, THINKING_START
    from src.agentframework.web_api import (
        _create_runtime_agent,
        _generate_title_async,
        get_state,
    )

    parsed = parse_qs(message)
    msg_content = parsed.get("message", [""])[0]
    model = parsed.get("model", ["qwen3:4b-instruct"])[0]

    if not msg_content.strip():
        return

    await send(message_bubble(role="user", content=msg_content))
    await send(_streaming_message(""))

    state = get_state()
    if state.agent is None:
        try:
            state.agent = _create_runtime_agent(provider="ollama", model=model)
        except Exception as exc:
            logger.exception("Failed to initialize agent for UI websocket")
            await _send_error(send, f"Error: {exc}")
            return

    if state.agent.config.model != model:
        state.agent.close()
        state.agent = _create_runtime_agent(
            provider=state.agent.config.provider,
            model=model,
            session_id=state.current_session_id,
        )

    accumulated_content = ""
    thinking_content = ""
    in_thinking = False
    send_queue: asyncio.Queue[tuple[str, str] | None] = asyncio.Queue(maxsize=128)

    async def sender_loop() -> None:
        try:
            while True:
                payload = await send_queue.get()
                if payload is None:
                    break
                content, thinking = payload
                await send(_streaming_message(content, thinking=thinking, oob=True))
        except Exception:
            logger.exception("UI websocket sender loop failed")

    sender_task = asyncio.create_task(sender_loop())

    def on_chunk(chunk: str) -> None:
        nonlocal accumulated_content, thinking_content, in_thinking

        if THINKING_START in chunk:
            chunk = chunk.replace(THINKING_START, "")
            in_thinking = True
        if THINKING_END in chunk:
            chunk = chunk.replace(THINKING_END, "")
            in_thinking = False

        if in_thinking:
            thinking_content += chunk
        else:
            accumulated_content += chunk

        with contextlib.suppress(asyncio.QueueFull):
            send_queue.put_nowait((accumulated_content, thinking_content))

    try:
        response = await state.agent.run_streaming(msg_content, on_chunk=on_chunk)
        if not accumulated_content:
            accumulated_content = response

        await send(
            _streaming_message(accumulated_content, thinking=thinking_content, oob=True)
        )

        if state.agent.session_manager and state.agent.session_manager.current_session:
            state.current_session_id = state.agent.session_manager.current_session.id
            if not state.agent.session_manager.current_session.title:
                asyncio.create_task(_generate_title_async(state.agent))
    except Exception as exc:
        logger.exception("UI websocket chat failed")
        await _send_error(send, f"Error: {exc}")
    finally:
        await send_queue.put(None)
        with contextlib.suppress(asyncio.CancelledError):
            await sender_task
