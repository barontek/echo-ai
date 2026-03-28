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
        self.container = ui.row().classes("chat-input-wrapper w-full")

        with self.container:
            with ui.row().classes("chat-input-pill w-full"):
                self.input_field = (
                    ui.input(placeholder="Message Echo AI...")
                    .props("borderless")
                    .classes("chat-input-field flex-grow")
                )
                self.input_field.on("keydown.enter", self._handle_submit)

                self.send_button = ui.button(
                    icon="arrow_upward",
                    on_click=self._handle_submit,
                ).props("unelevated round").classes("btn-send")

        return self.container

    async def _handle_submit(self):
        """Handle message submission."""
        if not self.input_field:
            return
        message = self.input_field.value.strip()
        if not message:
            return

        self.input_field.value = ""
        res = self.on_submit(message)
        import inspect
        if inspect.isawaitable(res):
            await res

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
