"""Chat container component for NiceGUI."""

from nicegui import ui

from .message import message_bubble


class ChatContainer:
    """Manages the chat message container with reactive updates."""

    def __init__(self, on_quick_action=None):
        self.container = None
        self.messages = []
        self._stream_update_callback = None
        self.on_quick_action = on_quick_action

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
        if not self.container:
            return

        with self.container:
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
        is_first = len(self.messages) == 0
        self.messages.append(msg)

        if self.container:
            if is_first:
                self._render()
            else:
                with self.container:
                    self._render_message(msg)
        self.scroll_to_bottom()

    def clear(self):
        """Clear all messages."""
        self.messages = []
        if self.container:
            self.container.clear()

    def scroll_to_bottom(self):
        """Scroll container to bottom unconditionally."""
        ui.run_javascript("if(window.chatScrollSystem) window.chatScrollSystem.forceScroll();")

    def set_stream_callback(self, callback):
        """Set callback for streaming updates."""
        self._stream_update_callback = callback


def empty_state(self_ref):
    """Render empty chat state."""
    with ui.column().classes("empty-state w-full h-full justify-center items-center"):
        ui.html("<h2>How can I help you today?</h2>")

        def make_action(query: str):
            async def handler():
                if self_ref.on_quick_action:
                    res = self_ref.on_quick_action(query)
                    import inspect
                    if inspect.isawaitable(res):
                        await res
            return handler

        with ui.row().classes("quick-actions"):
            with ui.card().classes("quick-action-card").on("click", make_action("Search the web for the latest news on Artificial Intelligence")):
                ui.label("Search AI News").classes("q-title")
                ui.label("Find latest updates on LLMs and AI advancements").classes("q-desc")

            with ui.card().classes("quick-action-card").on("click", make_action("Write a python script that implements a simple FastAPI server")):
                ui.label("Write Python Server").classes("q-title")
                ui.label("Generate a FastAPI backend template").classes("q-desc")

            with ui.card().classes("quick-action-card").on("click", make_action("Help me extract structured entity data from a messy block of text")):
                ui.label("Extract Data").classes("q-title")
                ui.label("Parse messy text into structured JSON").classes("q-desc")


def quick_action(query: str):
    pass


def chat_header(model: str, message_count: int):
    """Render chat header."""
    badge_text = f"{message_count} messages" if message_count > 0 else "New chat"
    with ui.row().classes("chat-header w-full"):
        ui.label("💬").classes("text-lg")
        ui.label(badge_text).classes("text-grey-6")
        ui.space()
        if message_count > 0:
            ui.label(f"Model: {model}").classes("text-grey-6 text-sm")
