"""Chat input component for NiceGUI."""

from nicegui import ui


class ChatInput:
    """Chat input with send functionality."""

    def __init__(self, on_submit):
        self.on_submit = on_submit
        self.input_field = None
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
            self.input_field = (
                ui.input(placeholder="Type your message... (Enter to send)")
                .props("outlined dense")
                .style("flex: 1;")
            )
            self.input_field.on("keydown.enter", self._handle_submit)

            self.send_button = ui.button(
                "Send",
                icon="send",
                on_click=self._handle_submit,
            ).props("flat color=primary")

        return self.container

    def _handle_submit(self):
        """Handle message submission."""
        if not self.input_field:
            return
        message = self.input_field.value.strip()
        if not message:
            return

        self.input_field.value = ""
        self.on_submit(message)

    def disable(self):
        """Disable the input during streaming."""
        if self.input_field:
            self.input_field.disable()
        if self.send_button:
            self.send_button.disable()

    def enable(self):
        """Enable the input after streaming."""
        if self.input_field:
            self.input_field.enable()
        if self.send_button:
            self.send_button.enable()


def chat_input(on_submit) -> ChatInput:
    """Create chat input component."""
    chat_input_instance = ChatInput(on_submit)
    chat_input_instance.create()
    return chat_input_instance
