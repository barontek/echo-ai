"""CLI for the agent framework."""

import asyncio
import sys

from rich.console import Console

from .agent import Agent
from .bootstrap import setup_agent
from .client import EchoClient, ContentEvent, ThinkingEvent, CommandResultEvent, ErrorEvent

console = Console(color_system="256")

async def interactive_mode(agent: Agent):
    """Run the agent in interactive mode."""
    console.print("[bold blue]Agent Framework[/bold blue]")
    console.print("[dim]Commands: /save, /load, /chats, /undo, /redo, /exit[/dim]\n")

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
    agent = setup_agent()
    args = [a for a in sys.argv[1:] if a not in {"--debug", "--debug-json"}]

    if args:
        task = " ".join(args)
        asyncio.run(run_single(agent, task))
    else:
        asyncio.run(interactive_mode(agent))

    # Final cleanup
    agent.close()


if __name__ == "__main__":
    main()
