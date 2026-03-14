"""CLI for the agent framework."""

import asyncio
import sys

from rich.console import Console

from .agent import Agent
from .bootstrap import setup_agent
from .chat_commands import normalize_command

console = Console(color_system="256")




async def interactive_mode(agent: Agent):
    """Run the agent in interactive mode."""
    console.print("[bold blue]Agent Framework[/bold blue]")
    console.print("[dim]Commands: /save, /load, /chats, /undo, /redo, /exit[/dim]\n")

    while True:
        try:
            user_input = console.input("[bold green]>[/bold green] ")

            # Handle commands
            if user_input.strip().startswith("/"):
                cmd = normalize_command(user_input.strip().split()[0].lower())
                args = (
                    user_input.strip().split(maxsplit=1)[1]
                    if len(user_input.strip().split()) > 1
                    else ""
                )

                if cmd == "/exit":
                    break
                elif cmd == "/save":
                    result = agent.save_session(args if args else None)
                    console.print(f"[cyan]{result}[/cyan]")
                    continue
                elif cmd == "/load":
                    if args:
                        result = agent.load_session(args)
                        console.print(f"[cyan]{result}[/cyan]")
                    else:
                        console.print("[yellow]Usage: /load <session_id>[/yellow]")
                    continue
                elif cmd == "/chats":
                    sessions = agent.list_sessions()
                    if sessions:
                        console.print("[cyan]Saved sessions:[/cyan]")
                        for s in sessions:
                            console.print(f"  - {s}")
                    else:
                        console.print("[dim]No saved sessions[/dim]")
                    continue
                elif cmd == "/undo":
                    result = agent.undo()
                    console.print(f"[cyan]{result}[/cyan]")
                    continue
                elif cmd == "/redo":
                    result = agent.redo()
                    console.print(f"[cyan]{result}[/cyan]")
                    continue
                elif cmd == "/help":
                    console.print("[cyan]Commands:[/cyan]")
                    console.print("  /save [name] - Save current session")
                    console.print("  /load <name> - Load a session")
                    console.print("  /chats       - List saved sessions")
                    console.print("  /undo        - Undo last file change")
                    console.print("  /redo        - Redo last undone change")
                    console.print("  /exit        - Exit")
                    continue

            if not user_input.strip():
                continue

            # Streaming output
            in_thinking = False

            def on_chunk(chunk: str):
                nonlocal in_thinking

                # Handle thinking markers
                if "__THINKING__" in chunk:
                    in_thinking = True
                    chunk = chunk.replace("__THINKING__", "")
                    if not chunk:
                        return
                if "__THINKING_END__" in chunk:
                    in_thinking = False
                    chunk = chunk.replace("__THINKING_END__", "")
                    if not chunk:
                        return

                # Use stdout.write for immediate output
                if in_thinking:
                    sys.stdout.write("\033[90m" + chunk + "\033[0m")
                else:
                    sys.stdout.write(chunk)
                sys.stdout.flush()

            await agent.run_streaming(user_input, on_chunk=on_chunk)
            # Add newline after streaming response
            sys.stdout.write("\n")
            sys.stdout.flush()
        except KeyboardInterrupt:
            break
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")

    # Auto-save and cleanup on exit
    agent.save_session()
    agent.close()
    console.print("\n[dim]Session saved. Goodbye![/dim]")


async def run_single(agent: Agent, task: str):
    """Run a single task with streaming output."""
    in_thinking = False

    def on_chunk(chunk: str):
        nonlocal in_thinking

        if "__THINKING__" in chunk:
            in_thinking = True
            chunk = chunk.replace("__THINKING__", "")
            if not chunk:
                return
        if "__THINKING_END__" in chunk:
            in_thinking = False
            chunk = chunk.replace("__THINKING_END__", "")
            if not chunk:
                return

        if in_thinking:
            sys.stdout.write("\033[90m" + chunk + "\033[0m")
        else:
            sys.stdout.write(chunk)
        sys.stdout.flush()

    await agent.run_streaming(task, on_chunk=on_chunk)
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
