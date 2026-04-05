"""CLI for the agent framework."""

import asyncio
import sys

from rich.console import Console
from rich.markdown import Markdown

from .core import Agent
from .bootstrap import setup_agent
from .client import (
    EchoClient,
    ContentEvent,
    ThinkingEvent,
    CommandResultEvent,
    ErrorEvent,
)

console = Console(color_system="256")

HELP_TEXT = """
# Echo AI - Command Line Interface

## Usage

```bash
# Single task
agent "your task here"

# Interactive mode
agent
```

## Commands

| Command | Description |
|---------|-------------|
| `/new` | Start a new conversation |
| `/save <name>` | Save current chat |
| `/load <name>` | Load a saved chat |
| `/chats` | List all saved chats |
| `/model <name>` | Switch to a different model |
| `/undo` | Undo last file change |
| `/redo` | Redo last undone change |
| `/clear` | Clear the screen |
| `/help` | Show this help |
| `/exit` | Exit the program |

## Examples

```bash
# Ask a question
agent "What is the weather in Tokyo?"

# Multi-step task
agent "Create a Python script that fetches data from an API and saves it to a JSON file"

# Interactive mode
agent
> What files are in the current directory?
> /chats
> /exit
```

## Environment Variables

- `ECHO_PROVIDER` - Set the LLM provider (ollama, openai, anthropic)
- `ECHO_MODEL` - Set the model name
- `ECHO_WORKSPACE` - Set the workspace directory
"""


def show_help():
    """Display help text."""
    console.print(Markdown(HELP_TEXT))


async def interactive_mode(agent: Agent):
    """Run the agent in interactive mode."""
    console.print("[bold cyan]Echo AI[/bold cyan] - Interactive Mode")
    console.print("[dim]Type /help for commands, /exit to quit[/dim]\n")

    client = EchoClient(agent)

    while True:
        try:
            user_input = console.input("[bold green]>[/bold green] ")
            if not user_input.strip():
                continue

            async for event in client.stream_chat(user_input):
                if isinstance(event, CommandResultEvent):
                    if event.should_exit:
                        # Auto-save and cleanup on exit
                        agent.save_session()
                        agent.close()
                        console.print("\n[dim]Session saved. Goodbye![/dim]")
                        return
                    else:
                        console.print(f"[cyan]{event.result}[/cyan]")

                elif isinstance(event, ThinkingEvent):
                    sys.stdout.write("\033[90m" + event.content + "\033[0m")
                    sys.stdout.flush()

                elif isinstance(event, ContentEvent):
                    sys.stdout.write(event.content)
                    sys.stdout.flush()

                elif isinstance(event, ErrorEvent):
                    console.print(f"\n[red]Error:[/red] {event.error}")

            # Add newline after response stream finishes
            sys.stdout.write("\n")
            sys.stdout.flush()
        except KeyboardInterrupt:
            break
        except Exception as e:
            console.print(f"[red]Fatal Error:[/red] {e}")

    # Auto-save and cleanup on exit
    agent.save_session()
    agent.close()
    console.print("\n[dim]Session saved. Goodbye![/dim]")


async def run_single(agent: Agent, task: str):
    """Run a single task with streaming output."""
    if task.lower() in ("help", "--help", "-h"):
        show_help()
        return

    client = EchoClient(agent)

    async for event in client.stream_chat(task):
        if isinstance(event, ThinkingEvent):
            sys.stdout.write("\033[90m" + event.content + "\033[0m")
        elif isinstance(event, ContentEvent):
            sys.stdout.write(event.content)
        elif isinstance(event, ErrorEvent):
            console.print(f"\n[red]Error:[/red] {event.error}")
        sys.stdout.flush()
    sys.stdout.write("\n")


def main():
    """Main entry point."""
    args = [a for a in sys.argv[1:] if a not in {"--debug", "--debug-json"}]

    if not args or args[0].lower() in ("help", "--help", "-h"):
        show_help()
        return

    agent = setup_agent()

    if len(args) == 1 and args[0].lower() == "--version":
        console.print("[bold]Echo AI[/bold] version 0.1.0")
        return

    task = " ".join(args)
    asyncio.run(run_single(agent, task))

    # Final cleanup
    agent.close()


if __name__ == "__main__":
    main()
