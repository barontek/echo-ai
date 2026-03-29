"""Main NiceGUI application for Echo AI.

Run standalone with:
    uv run python -m src.agentframework.ui.app

Or run the combined web_api which serves both FastAPI and NiceGUI.
"""

import logging
from typing import Optional

from nicegui import ui

from .theme import setup_theme
from .components import (
    chat_header,
    chat_input,
    sidebar_header,
    model_selector,
    session_list,
    new_chat_button,
    search_sessions,
    ChatContainer,
    streaming_message,
    finish_streaming,
)
from .state import get_state

logger = logging.getLogger(__name__)

# Initialize Sentry at module level BEFORE ui.run()
# Uses the centralized init_sentry() to avoid dual initialization conflicts
try:
    from src.agentframework.sentry import init_sentry, captureMessage

    if init_sentry():
        captureMessage("NiceGUI app started", level="info")
except Exception as e:
    logger.debug(f"Sentry initialization skipped: {e}")

_app_started = False

CHATS_SCROLL_JS = """
<script>
window.chatScrollSystem = {
    isAutoScrollEnabled: true,
    init: function() {
        const el = document.querySelector('.chat-container');
        if (!el) return;
        if (el.dataset.scrollInit) return;
        el.dataset.scrollInit = "true";

        el.addEventListener('scroll', () => {
            const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
            window.chatScrollSystem.isAutoScrollEnabled = atBottom;
        });

        const observer = new MutationObserver(() => {
            if (window.chatScrollSystem.isAutoScrollEnabled) {
                el.scrollTop = el.scrollHeight;
            }
        });

        observer.observe(el, { childList: true, subtree: true, characterData: true });
        el.scrollTop = el.scrollHeight;
    },
    forceScroll: function() {
        const el = document.querySelector('.chat-container');
        if (el) {
            window.chatScrollSystem.isAutoScrollEnabled = true;
            el.scrollTop = el.scrollHeight;
        }
    }
};
</script>
"""


@ui.page("/")
async def main_page():
    """Main chat page."""
    ui.add_head_html(CHATS_SCROLL_JS)
    setup_theme(dark_mode=True)

    state = get_state()
    state.current_session_id = None
    state.messages = []

    sessions = _get_all_sessions()
    models = _get_models()

    container = ChatContainer()

    with ui.row().classes("app-container no-wrap"):
        with ui.column().classes("sidebar gap-0"):
            sidebar_header()
            model_selector(models, state.model)
            with (
                ui.column()
                .classes("sidebar-section w-full gap-0")
                .style("padding-bottom: 0;")
            ):
                new_chat_button()
                search_sessions(sessions, active_id="")
            with (
                ui.column()
                .classes("w-full")
                .style(
                    "flex: 1; min-height: 0; overflow-y: auto; padding: 0 0.25rem; box-sizing: border-box; overflow-x: hidden; gap: 0;"
                )
            ):
                session_list(sessions, active_id="")

        with ui.column().classes("main-content"):
            chat_header(state.model, 0)

            async def submit(msg):
                await handle_message(msg, container)

            container.on_quick_action = submit
            container.create()
            chat_input(submit)
            ui.run_javascript("setTimeout(() => window.chatScrollSystem.init(), 100);")


@ui.page("/sessions/{session_id}")
async def session_page(session_id: str):
    """Load a specific session."""
    ui.add_head_html(CHATS_SCROLL_JS)
    setup_theme(dark_mode=True)

    state = get_state()
    state.current_session_id = session_id
    _load_session(session_id)

    sessions = _get_all_sessions()
    models = _get_models()

    container = ChatContainer()

    with ui.row().classes("app-container no-wrap"):
        with ui.column().classes("sidebar gap-0"):
            sidebar_header()
            model_selector(models, state.model)
            with (
                ui.column()
                .classes("sidebar-section w-full gap-0")
                .style("padding-bottom: 0;")
            ):
                new_chat_button()
                search_sessions(sessions, active_id=session_id or "")
            with (
                ui.column()
                .classes("w-full")
                .style(
                    "flex: 1; min-height: 0; overflow-y: auto; padding: 0 0.25rem; box-sizing: border-box; overflow-x: hidden; gap: 0;"
                )
            ):
                session_list(sessions, active_id=session_id or "")

        with ui.column().classes("main-content"):
            chat_header(state.model, len(state.messages))

            async def submit(msg):
                await handle_message(msg, container)

            container.on_quick_action = submit
            container.create()
            container.update(state.messages)
            chat_input(submit)
            ui.run_javascript("setTimeout(() => window.chatScrollSystem.init(), 100);")


async def handle_message(message: str, container: ChatContainer):
    """Handle sending a message and streaming the response."""
    state = get_state()
    model = state.model

    is_new_session = False
    if not state.current_session_id:
        new_session = _create_session()
        if new_session:
            state.current_session_id = new_session["id"]
            ui.context.client.run_javascript(
                f"window.history.pushState({{}}, '', '/sessions/{new_session['id']}');"
            )
            state = get_state()
            is_new_session = True

    state.add_message("user", message)
    user_msg_dict = {"role": "user", "content": message}
    container.add_message(user_msg_dict)

    ui.notify(f"Sending: {message[:50]}...")
    state.is_streaming = True

    from src.agentframework.client import (
        EchoClient,
        ContentEvent,
        ThinkingEvent,
        CommandResultEvent,
        ErrorEvent,
    )

    accumulated_content = ""
    accumulated_thinking = ""
    spinner = None
    update_streaming = None

    if container.container:
        with container.container:
            _, content_label, thinking_label, spinner, update_streaming = (
                streaming_message()
            )
    container.scroll_to_bottom()

    try:
        agent = _create_agent(model, session_id=state.current_session_id)
        client = EchoClient(agent)

        async for event in client.stream_chat(message):
            if isinstance(event, ThinkingEvent):
                accumulated_thinking += event.content
                if update_streaming:
                    update_streaming(accumulated_content, accumulated_thinking)
            elif isinstance(event, ContentEvent):
                accumulated_content += event.content
                if update_streaming:
                    update_streaming(accumulated_content, accumulated_thinking)
            elif isinstance(event, CommandResultEvent):
                if event.should_exit:
                    pass
                else:
                    accumulated_content += f"\nSystem: {event.result}"
                    if update_streaming:
                        update_streaming(accumulated_content, accumulated_thinking)
            elif isinstance(event, ErrorEvent):
                logger.error(f"Error event from client: {event.error}")
                ui.notify(f"Error: {event.error}", type="negative", timeout=0)

        final_msg = agent.messages[-1]
        final_content = final_msg.content or ""
        final_thinking = getattr(final_msg, "thinking", "") or ""

        # Guarantee final output is rendered in the DOM in case chunks were bypassed
        if update_streaming:
            update_streaming(final_content, final_thinking)
        container.scroll_to_bottom()

        state.add_message(
            "assistant",
            final_content,
            thinking=final_thinking,
            tool_calls=getattr(final_msg, "tool_calls", None),
        )
        state.persist_messages()
        finish_streaming(spinner) if spinner else None

        if is_new_session:
            from src.agentframework.web_api import _generate_title_async
            import asyncio

            asyncio.create_task(_generate_title_async(agent))

    except Exception as e:
        logger.error(f"Error during streaming: {e}", exc_info=True)
        ui.notify(f"Error: {str(e)}", type="negative", timeout=0)
        finish_streaming(spinner)

    state.is_streaming = False


def _get_all_sessions() -> list:
    """Get all sessions from backend."""
    from .backend import get_sessions_data, get_backend_state

    state = get_backend_state()
    if state.agent and state.agent.session_manager:
        state.agent.session_manager.purge_empty_sessions()
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

    state = get_state()
    state.messages = data.get("messages", [])


def _create_agent(model: str, session_id: str | None = None):
    """Create an agent with the given model."""
    from .backend import create_runtime_agent

    return create_runtime_agent(model, session_id)


if __name__ == "__main__":
    ui.run(
        title="Echo AI",
        port=8080,
        reload=False,
        show=True,
        storage_secret="echo-ai-nicegui-secret",
    )
