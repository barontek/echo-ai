"""Main NiceGUI application for Echo AI.

Run standalone with:
    uv run python -m src.agentframework.ui_nicegui.app

Or run the combined web_api which serves both FastAPI and NiceGUI.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from nicegui import app, ui

from .theme import setup_theme
from .components import (
    chat_header,
    chat_input,
    sidebar_header,
    model_selector,
    session_list,
    new_chat_button,
    render_markdown,
)

logger = logging.getLogger(__name__)

_app_started = False


@dataclass
class PageState:
    """Per-client state using NiceGUI's native storage."""

    current_session_id: Optional[str] = None
    messages: list = field(default_factory=list)
    model: str = "qwen3:4b-instruct"
    is_streaming: bool = False

    def add_message(self, role: str, content: str, **kwargs):
        """Add a message to the state."""
        import datetime

        self.messages.append(
            {
                "role": role,
                "content": content,
                "timestamp": datetime.datetime.now().isoformat(),
                **kwargs,
            }
        )


def get_page_state() -> PageState:
    """Get or create page state for current client."""
    if "page_state" not in app.storage.client:
        app.storage.client["page_state"] = PageState()
    return app.storage.client["page_state"]


@ui.page("/")
async def main_page():
    """Main chat page."""
    setup_theme(dark_mode=True)

    state = get_page_state()
    state.current_session_id = None
    state.messages = []

    sessions = _get_all_sessions()
    models = _get_models()

    with ui.column().classes("app-container"):
        with ui.column().classes("sidebar"):
            sidebar_header()
            model_selector(models, state.model)
            with ui.column().classes("sidebar-section flex-grow"):
                _render_session_search()
                session_list(sessions, active_id=state.current_session_id or "")
            with ui.column().classes("sidebar-footer"):
                new_chat_button()

        with ui.column().classes("main-content"):
            chat_header(state.model, 0)
            _render_chat_area(state)
            chat_input(handle_message)


@ui.page("/sessions/{session_id}")
async def session_page(session_id: str):
    """Load a specific session."""
    setup_theme(dark_mode=True)

    state = get_page_state()
    state.current_session_id = session_id
    _load_session(session_id)

    sessions = _get_all_sessions()
    models = _get_models()

    with ui.column().classes("app-container"):
        with ui.column().classes("sidebar"):
            sidebar_header()
            model_selector(models, state.model)
            with ui.column().classes("sidebar-section flex-grow"):
                _render_session_search()
                session_list(sessions, active_id=session_id or "")
            with ui.column().classes("sidebar-footer"):
                new_chat_button()

        with ui.column().classes("main-content"):
            chat_header(state.model, len(state.messages))
            _render_chat_area(state)
            chat_input(handle_message)


def _render_chat_area(state: PageState):
    """Render chat messages area."""
    with (
        ui.column()
        .classes("chat-container")
        .style("flex: 1; overflow-y: auto; padding: 1rem;")
    ):
        if not state.messages:
            _render_empty_state()
        else:
            for msg in state.messages:
                _render_message(msg)


def _render_empty_state():
    """Render empty state with quick actions."""
    with (
        ui.column()
        .classes("empty-state")
        .style(
            "flex: 1; display: flex; flex-direction: column; "
            "align-items: center; justify-content: center;"
        )
    ):
        ui.label("How can I help you today?").classes("text-h4")

        with (
            ui.row()
            .classes("quick-actions")
            .style("gap: 0.5rem; flex-wrap: wrap; margin-top: 1rem;")
        ):
            ui.button(
                "Search AI News",
                on_click=lambda: _quick_action(
                    "Search the web for the latest news on Artificial Intelligence"
                ),
            ).props("outline")
            ui.button(
                "Write Python Server",
                on_click=lambda: _quick_action(
                    "Write a python script that implements a simple FastAPI server"
                ),
            ).props("outline")
            ui.button(
                "Extract Data",
                on_click=lambda: _quick_action(
                    "Help me extract structured entity data from a messy block of text"
                ),
            ).props("outline")


def _render_session_search():
    """Render session search input."""
    ui.input(
        placeholder="Search sessions...",
        on_change=lambda e: _filter_sessions(e.value),
    ).props("outlined dense").classes("w-full").style("margin-bottom: 0.5rem;")


def _filter_sessions(query: str):
    """Filter sessions by query."""
    ui.notify(f"Filtering: {query}")


def _render_message(msg: dict):
    """Render a single message bubble."""
    role = msg.get("role", "")
    content = msg.get("content", "")
    thinking = msg.get("thinking", "")
    tool_calls = msg.get("tool_calls", [])

    if role not in ("user", "assistant"):
        return

    bubble_classes = "message user" if role == "user" else "message assistant"

    with ui.column().classes(bubble_classes).style("width: 100%"):
        with ui.row().classes("message-header"):
            avatar = "👤" if role == "user" else "🤖"
            ui.label(avatar).classes("text-sm")
            ui.label("You" if role == "user" else "Assistant").classes(
                "text-xs text-grey-6"
            )

        if content:
            content_html = render_markdown(content)
            ui.html(f'<div class="message-content">{content_html}</div>')

        if tool_calls:
            _render_tool_calls(tool_calls)

        if thinking:
            _render_thinking(thinking)


def _render_tool_calls(tool_calls: list):
    """Render collapsible tool calls."""
    import json

    with ui.expansion("Tool Calls", icon="build").classes("tool-calls"):
        for tool in tool_calls:
            name = tool.get("name", "Unknown")
            arguments = tool.get("arguments", {})
            with (
                ui.card()
                .classes("tool-call")
                .style(
                    "background: var(--bg-tertiary); padding: 0.5rem; margin-bottom: 0.5rem;"
                )
            ):
                ui.label(f"🔧 {name}").classes("font-bold text-sm")
                ui.code(
                    json.dumps(arguments, indent=2),
                ).style("font-size: 0.75rem; max-height: 200px; overflow: auto;")


def _render_thinking(thinking: str):
    """Render collapsible thinking section."""
    thinking_html = render_markdown(thinking)
    with ui.expansion("Thinking", icon="psychology").classes("thinking-section"):
        ui.html(f'<div class="message-content">{thinking_html}</div>')


def _quick_action(query: str):
    """Handle quick action button click."""
    state = get_page_state()
    state.add_message("user", query)
    ui.notify(f"Quick action: {query[:30]}...")


async def handle_message(message: str, model: str):
    """Handle sending a message and streaming the response."""
    state = get_page_state()
    state.model = model

    if not state.current_session_id:
        new_session = _create_session()
        if new_session:
            state.current_session_id = new_session["id"]
            ui.navigate.to(f"/sessions/{new_session['id']}")
            await asyncio.sleep(0.3)
            state = get_page_state()

    state.add_message("user", message)

    ui.notify(f"Sending: {message[:50]}...")

    state.is_streaming = True
    accumulated_content = ""
    accumulated_thinking = ""
    in_thinking = False

    with (
        ui.column()
        .classes("message assistant")
        .style(
            "width: 100%; padding: 1rem; border-radius: 8px; "
            "background: var(--bg-secondary); margin-bottom: 1rem;"
        )
    ):
        with ui.row().classes("message-header"):
            ui.label("🤖").classes("text-sm")
            ui.label("Assistant").classes("text-xs text-grey-6")
            spinner = ui.html('<div class="loading-spinner"></div>')

        content_html = ui.html('<div class="message-content"></div>')

    def on_chunk(chunk: str):
        nonlocal accumulated_content, accumulated_thinking, in_thinking

        if "__THINKING__" in chunk:
            in_thinking = True
            chunk = chunk.replace("__THINKING__", "")
        if "__THINKING_END__" in chunk:
            in_thinking = False
            chunk = chunk.replace("__THINKING_END__", "")

        if in_thinking:
            accumulated_thinking += chunk
        else:
            accumulated_content += chunk

        def update_ui():
            content_label = render_markdown(accumulated_content)
            content_html.clear()
            with content_html:
                ui.html(f'<div class="message-content">{content_label}</div>')

        ui.context.client.safe_invoke(update_ui)

    try:
        agent = _create_agent(model)
        await agent.run_streaming(message, on_chunk=on_chunk)

        state.add_message(
            "assistant",
            accumulated_content,
            thinking=accumulated_thinking,
        )
        _save_session(state)

        spinner.delete()

    except Exception as e:
        logger.error(f"Error during streaming: {e}", exc_info=True)
        ui.notify(f"Error: {str(e)}", type="negative", timeout=0)
        spinner.delete()

    state.is_streaming = False


def _get_all_sessions() -> list:
    """Get all sessions from backend."""
    from .backend import get_sessions_data, get_backend_state

    state = get_backend_state()
    data = get_sessions_data(state)
    return data.get("sessions", [])


def _get_models() -> list:
    """Get available models."""
    from .backend import get_models_sync

    data = get_models_sync()
    return data.get("models", ["qwen3:4b-instruct"])


def _create_session() -> Optional[dict]:
    """Create a new session."""
    from .backend import create_session_data, get_backend_state

    backend_state = get_backend_state()
    data = create_session_data(backend_state)
    if session_id := data.get("session_id"):
        return {"id": session_id, "title": "New Chat"}
    return None


def _load_session(session_id: str):
    """Load a session from backend."""
    from .backend import load_session_data, get_backend_state

    backend_state = get_backend_state()
    data = load_session_data(session_id, backend_state)
    if error := data.get("error"):
        logger.error(f"Failed to load session {session_id}: {error}")
        return

    state = get_page_state()
    state.messages = data.get("messages", [])


def _save_session(state: PageState):
    """Save session messages to backend."""
    if not state.current_session_id:
        return
    from .backend import save_messages, get_backend_state

    backend_state = get_backend_state()
    save_messages(state.current_session_id, state.messages, backend_state)


def _create_agent(model: str):
    """Create an agent with the given model."""
    from .backend import create_runtime_agent

    return create_runtime_agent(model)


def run():
    """Run the NiceGUI application."""
    ui.run(
        title="Echo AI",
        port=8080,
        reload=False,
        show=True,
        storage_secret="echo-ai-nicegui-secret",
    )


if __name__ == "__main__":
    run()
