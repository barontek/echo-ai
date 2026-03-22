"""Chat input component for NiceGUI."""

from nicegui import ui

from ..state import get_state


class ChatInput:
    """Chat input with model selector and send functionality."""

    def __init__(self, on_submit):
        self.on_submit = on_submit
        self.input_field = None
        self.model_select = None
        self.send_button = None
        self.container = None

    def create(self):
        """Create the chat input."""
        self.container = (
            ui.row()
            .classes("chat-input-container")
            .style(
                "display: flex; gap: 0.5rem; align-items: center; "
                "padding: 1rem; border-top: 1px solid var(--border-color); "
                "background: var(--bg-secondary);"
            )
        )

        with self.container:
            self.model_select = (
                ui.select(
                    options=get_models(),
                    value=get_state().model,
                )
                .props("outlined dense")
                .style("width: 150px;")
            )

            self.input_field = (
                ui.input(placeholder="Type your message... (Enter to send)")
                .props("outlined dense")
                .style("flex: 1;")
                .on("keydown.enter", self._handle_submit)
            )

            self.send_button = ui.button(
                "Send",
                icon="send",
                on_click=self._handle_submit,
            ).props("flat color=primary")

        return self.container

    def _handle_submit(self):
        """Handle message submission."""
        message = self.input_field.value.strip()
        if not message:
            return

        model = self.model_select.value
        self.input_field.value = ""
        self.on_submit(message, model)

    def disable(self):
        """Disable the input during streaming."""
        self.input_field.disable()
        self.send_button.disable()
        self.model_select.disable()

    def enable(self):
        """Enable the input after streaming."""
        self.input_field.enable()
        self.send_button.enable()
        self.model_select.enable()


def get_models():
    """Get available models."""
    from ..state import get_models

    try:
        return get_models()
    except Exception:
        return ["qwen3:4b-instruct"]


def chat_input(on_submit) -> ChatInput:
    """Create chat input component."""
    chat_input_instance = ChatInput(on_submit)
    chat_input_instance.create()
    return chat_input_instance
