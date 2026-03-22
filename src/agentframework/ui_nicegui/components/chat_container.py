"""Chat container component for NiceGUI."""

from nicegui import ui

from .message import message_bubble


class ChatContainer:
    """Manages the chat message container with reactive updates."""

    def __init__(self):
        self.container = None
        self.messages = []
        self._stream_update_callback = None

    def create(self):
        """Create the chat container."""
        self.container = (
            ui.column()
            .classes("chat-container")
            .style("flex: 1; overflow-y: auto; padding: 1rem;")
        )
        self._render()
        return self.container

    def _render(self):
        """Render messages in the container."""
        if self.container:
            self.container.clear()

        if not self.messages:
            empty_state(self)
        else:
            for msg in self.messages:
                self._render_message(msg)

    def _render_message(self, msg: dict):
        """Render a single message."""
        role = msg.get("role", "")
        content = msg.get("content", "")
        thinking = msg.get("thinking", "")
        tool_calls = msg.get("tool_calls", [])

        if role in ("user", "assistant"):
            message_bubble(
                role=role,
                content=content,
                thinking=thinking,
                tool_calls=tool_calls if tool_calls else None,
            )

    def update(self, messages: list):
        """Update container with new messages."""
        self.messages = messages
        self._render()
        self.scroll_to_bottom()

    def add_message(self, msg: dict):
        """Add a single message and render it."""
        self.messages.append(msg)
        self._render_message(msg)
        self.scroll_to_bottom()

    def clear(self):
        """Clear all messages."""
        self.messages = []
        if self.container:
            self.container.clear()

    def scroll_to_bottom(self):
        """Scroll to the bottom of the chat."""
        if self.container:
            ui.context.client.run_javascript(
                "setTimeout(() => {"
                "const el = document.querySelector('.chat-container');"
                "if (el) el.scrollTop = el.scrollHeight;"
                "}, 50);"
            )

    def set_stream_callback(self, callback):
        """Set callback for streaming updates."""
        self._stream_update_callback = callback


def empty_state(self_ref):
    """Render empty chat state."""
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
                on_click=lambda: quick_action(
                    "Search the web for the latest news on Artificial Intelligence"
                ),
            ).props("outline")
            ui.button(
                "Write Python Server",
                on_click=lambda: quick_action(
                    "Write a python script that implements a simple FastAPI server"
                ),
            ).props("outline")
            ui.button(
                "Extract Data",
                on_click=lambda: quick_action(
                    "Help me extract structured entity data from a messy block of text"
                ),
            ).props("outline")


def quick_action(query: str):
    """Handle quick action button click."""
    import asyncio
    from ..state import get_state
    from ..app import handle_message

    state = get_state()
    state.add_message("user", query)
    asyncio.create_task(handle_message(query, state.model))


def chat_header(model: str, message_count: int):
    """Render chat header."""
    badge_text = f"{message_count} messages" if message_count > 0 else "New chat"
    with ui.row().classes("chat-header"):
        ui.label("💬").classes("text-lg")
        ui.label(badge_text).classes("text-grey-6")
        ui.space()
        if message_count > 0:
            ui.label(f"Model: {model}").classes("text-grey-6 text-sm")
