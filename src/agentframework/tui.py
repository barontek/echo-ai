"""Textual UI dashboard for real-time agent monitoring."""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Header, Footer, Log, Static, Input
from textual.reactive import reactive

from typing import Any
from .callbacks import AgentCallback
from .core import Agent, AgentConfig, create_agent


class TuiCallback(AgentCallback):
    """Bridge between the Agent execution loop and the Textual UI logging widgets."""

    def __init__(self, app: "AgentDashboard"):
        self.app = app

    def on_run_start(self, run_id: str, prompt: str) -> None:
        self.app.call_from_thread(
            self.app.log_panel.write_line,
            f"[bold green]Starting Run:[/bold green] {run_id}",
        )
        self.app.call_from_thread(
            self.app.log_panel.write_line, f"[italic]{prompt}[/italic]"
        )
        self.app.call_from_thread(self.app.update_status, "Running...")

    def on_run_end(self, run_id: str, response: str) -> None:
        self.app.call_from_thread(
            self.app.log_panel.write_line,
            f"[bold blue]Run Completed:[/bold blue] {run_id}",
        )
        self.app.call_from_thread(self.app.update_status, "Idle")

    def on_run_error(self, run_id: str, error: Exception) -> None:
        self.app.call_from_thread(
            self.app.log_panel.write_line, f"[bold red]Run Error:[/bold red] {error}"
        )
        self.app.call_from_thread(self.app.update_status, "Error")

    def on_llm_start(self, run_id: str, messages: list[dict[str, Any]]) -> None:
        pass

    def on_llm_end(self, run_id: str, response: Any) -> None:
        pass

    def on_tool_start(
        self, run_id: str, tool_name: str, tool_kwargs: dict[str, Any]
    ) -> None:
        self.app.call_from_thread(
            self.app.tools_panel.write_line, f"Executing: {tool_name}"
        )

    def on_tool_end(self, run_id: str, tool_name: str, result: str) -> None:
        self.app.call_from_thread(
            self.app.tools_panel.write_line, f"Completed: {tool_name}"
        )

    def on_tool_error(self, run_id: str, tool_name: str, error: str) -> None:
        self.app.call_from_thread(
            self.app.tools_panel.write_line, f"Failed: {tool_name} - {error}"
        )


class AgentDashboard(App):
    """Main Textual Application for Echo AI."""

    CSS = """
    #main_container {
        height: 100%;
        margin: 1 2;
    }
    #top_panels {
        height: 60%;
        margin-bottom: 1;
    }
    .panel {
        border: round white;
        height: 100%;
        width: 1fr;
    }
    #chat_input {
        dock: bottom;
        margin: 1 2;
    }
    #status_bar {
        dock: top;
        height: 1;
        background: $boost;
        color: $text;
        content-align: center middle;
    }
    """

    status_text = reactive("Initializing...")

    def __init__(self, agent: Agent):
        super().__init__()
        self.agent = agent
        # Inject the TUI bridge callback into the running agent instance
        self.agent.add_callback(TuiCallback(self))

        self.log_panel = Log(id="agent_log", classes="panel")
        self.tools_panel = Log(id="tool_log", classes="panel")
        self.status_bar = Static(id="status_bar")

    def compose(self) -> ComposeResult:
        yield Header()
        yield self.status_bar
        with Container(id="main_container"):
            with Horizontal(id="top_panels"):
                yield self.log_panel
                yield self.tools_panel
        yield Input(placeholder="Send a message to the agent...", id="chat_input")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Echo AI Dashboard"
        self.log_panel.border_title = "Agent Stream"
        self.tools_panel.border_title = "Active Tools"
        self.status_text = "Idle"
        self.log_panel.write_line("Welcome to the Echo AI TUI Dashboard.")

    def watch_status_text(self, old_value: str, new_value: str) -> None:
        self.status_bar.update(new_value)

    def update_status(self, status: str) -> None:
        self.status_text = status

    async def on_input_submitted(self, message: Input.Submitted) -> None:
        if message.value:
            user_input = message.value
            message.input.value = ""
            self.log_panel.write_line(
                f"[bold magenta]User:[/bold magenta] {user_input}"
            )

            # Spin off the agent run to a background task so UI doesn't freeze
            self.run_worker(self._run_agent(user_input), exclusive=True)

    async def _run_agent(self, user_input: str) -> None:
        try:
            from src.agentframework.client import (
                EchoClient,
                ContentEvent,
                ThinkingEvent,
                CommandResultEvent,
                ErrorEvent,
            )

            client = EchoClient(self.agent)

            # Use call_from_thread to write incrementally
            self.call_from_thread(
                self.log_panel.write_line, "[bold cyan]Agent is typing...[/bold cyan]"
            )

            current_line = ""
            async for event in client.stream_chat(user_input):
                if isinstance(event, ContentEvent):
                    # For TUI we batch line by line to avoid flickering
                    current_line += event.content
                    if "\n" in current_line:
                        lines = current_line.split("\n")
                        for line in lines[:-1]:
                            self.call_from_thread(self.log_panel.write_line, line)
                        current_line = lines[-1]
                elif isinstance(event, ThinkingEvent):
                    # We can log thinking process directly
                    pass
                elif isinstance(event, CommandResultEvent):
                    self.call_from_thread(
                        self.log_panel.write_line,
                        f"[yellow]System:[/yellow] {event.result}",
                    )
                elif isinstance(event, ErrorEvent):
                    self.call_from_thread(
                        self.log_panel.write_line,
                        f"[bold red]Error:[/bold red] {event.error}",
                    )

            if current_line:
                self.call_from_thread(self.log_panel.write_line, current_line)

        except Exception as e:
            self.call_from_thread(
                self.log_panel.write_line,
                f"[bold red]System Error:[/bold red] {str(e)}",
            )


def run_dashboard():
    """Entry point for the terminal UI."""
    config = AgentConfig(provider="ollama", model="qwen3:4b-instruct")
    agent = create_agent(config)
    app = AgentDashboard(agent)
    app.run()
