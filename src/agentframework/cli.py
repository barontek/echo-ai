"""CLI for the agent framework."""

import asyncio
import os
import logging
import sys
from pathlib import Path

from rich.console import Console

from .agent import Agent, AgentConfig, create_agent
from .config import (
    find_config_path as shared_find_config_path,
    get_safety_config as shared_get_safety_config,
    get_tools as shared_get_tools,
    load_config as shared_load_config,
)

console = Console(color_system="256")


def find_config_path(path: str | None = None) -> Path | None:
    """Proxy to shared config path lookup."""
    return shared_find_config_path(path)


def load_config(path: str | None = None) -> dict:
    """Proxy to shared YAML config loader."""
    return shared_load_config(path)


def get_safety_config(config: dict):
    """Proxy to shared safety configuration builder."""
    return shared_get_safety_config(config)


def get_tools(config: dict, safety_config):
    """Proxy to shared tool bootstrap."""
    return shared_get_tools(config, safety_config)


async def interactive_mode(agent: Agent):
    """Run the agent in interactive mode."""
    console.print("[bold blue]Agent Framework[/bold blue]")
    console.print("[dim]Commands: /save, /load, /chats, /undo, /redo, /exit[/dim]\n")

    while True:
        try:
            user_input = console.input("[bold green]>[/bold green] ")

            # Handle commands
            if user_input.strip().startswith("/"):
                cmd = user_input.strip().split()[0].lower()
                args = (
                    user_input.strip().split(maxsplit=1)[1]
                    if len(user_input.strip().split()) > 1
                    else ""
                )

                if cmd == "/exit" or cmd == "/quit":
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
                elif cmd == "/chats" or cmd == "/sessions":
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

    # Auto-save on exit
    agent.save_session()
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
    if sys.version_info < (3, 11):
        console.print("[red]Python 3.11+ is required to run Vibe AI.[/red]")
        raise SystemExit(1)
    debug_enabled = "--debug" in sys.argv
    if debug_enabled:
        logging.basicConfig(
            level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s %(message)s"
        )

    config = load_config()
    config_path = find_config_path()
    safety_config = get_safety_config(config)

    agent_config = AgentConfig(
        provider=config.get("model", {}).get("provider", "ollama"),
        model=config.get("model", {}).get("name", "qwen3:4b-instruct"),
        temperature=config.get("model", {}).get("temperature", 0.3),
        max_iterations=config.get("agent", {}).get("max_iterations", 50),
        system_prompt=config.get("agent", {}).get("system_prompt", ""),
        tools=get_tools(config, safety_config),
        base_url=config.get("model", {}).get("base_url"),
        session_enabled=config.get("agent", {}).get("session_enabled", True),
        session_dir=config.get("agent", {}).get("session_dir", ".agent_sessions"),
    )

    # Inject environment info into system prompt
    workspace = safety_config.workspace or "."
    cwd = os.getcwd()
    env_info = f"\n\n## Environment\n- Current working directory: {cwd}\n- Workspace (file operations confined to): {workspace}\n"
    if agent_config.system_prompt:
        agent_config.system_prompt += env_info
    else:
        agent_config.system_prompt = (
            f"You are an AI assistant with access to various tools.{env_info}"
        )

    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")

    agent = create_agent(agent_config, api_key)

    console.print(
        f"[dim]Config: {config_path if config_path else '<none>'} | Provider: {agent_config.provider} | Model: {agent_config.model}[/dim]"
    )

    args = [a for a in sys.argv[1:] if a != "--debug"]
    if args:
        task = " ".join(args)
        asyncio.run(run_single(agent, task))
    else:
        asyncio.run(interactive_mode(agent))


if __name__ == "__main__":
    main()
