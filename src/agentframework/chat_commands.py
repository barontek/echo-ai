"""Shared command registry and helpers for chat interfaces."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console
    from .core import Agent


@dataclass(frozen=True)
class ChatCommand:
    name: str
    usage: str
    description: str
    aliases: tuple[str, ...] = ()


CHAT_COMMANDS: tuple[ChatCommand, ...] = (
    ChatCommand("/new", "/new", "Start a new chat"),
    ChatCommand("/save", "/save <name>", "Save current chat"),
    ChatCommand("/load", "/load <name>", "Load a saved chat"),
    ChatCommand("/chats", "/chats", "List saved chats", aliases=("/sessions",)),
    ChatCommand("/models", "/models", "List recommended local models"),
    ChatCommand("/model", "/model <name>", "Switch to a different model"),
    ChatCommand("/temperature", "/temperature <val>", "Set temperature (0.0-2.0)"),
    ChatCommand("/undo", "/undo", "Undo last file change"),
    ChatCommand("/redo", "/redo", "Redo last undone change"),
    ChatCommand("/clear", "/clear", "Clear screen"),
    ChatCommand("/help", "/help", "Show this help"),
    ChatCommand("/exit", "/exit", "Exit", aliases=("/quit",)),
)


def all_slash_commands() -> list[str]:
    """Return slash commands and aliases for autocomplete."""
    commands: list[str] = []
    for command in CHAT_COMMANDS:
        commands.append(command.name)
        commands.extend(command.aliases)
    return commands


def normalize_command(command: str) -> str:
    """Normalize command aliases to canonical command names."""
    for command_def in CHAT_COMMANDS:
        if command == command_def.name or command in command_def.aliases:
            return command_def.name
    return command


def help_lines() -> list[str]:
    """Build formatted help lines from command registry."""
    lines = []
    for command in CHAT_COMMANDS:
        lines.append(f"  [bold]{command.usage}[/bold] - {command.description}")
    return lines


def execute_command(cmd: str, args: str, agent: "Agent", console: "Console") -> bool:
    """Execute a normalized slash command. Returns True to continue, False to exit the chat session."""
    from .chat_render import print_help, print_welcome
    from .providers import get_provider

    # These are used to render recommended models when requested
    RECOMMENDED_MODELS = [
        (
            "qwen3:4b-instruct",
            "Best for following instructions and tool calling (default)",
        ),
        ("qwen2.5-coder:3b", "Best for strict tool calling and coding"),
        ("qwen3:4b", "General purpose with strong reasoning"),
        ("qwen3.5:4b", "Latest Qwen with improved reasoning"),
        ("llama3.2", "Meta's lightweight model, great reasoning"),
        ("phi3.5", "Microsoft's highly stable model"),
    ]

    match cmd, args:
        case "/exit", _:
            agent.save_session()
            console.print("[dim]Chat saved. Goodbye![/dim]")
            return False
        case "/new", _:
            agent.save_session()
            agent.messages.clear()
            console.clear()
            print_welcome(console)
            console.print("[dim]Started new chat[/dim]\n")
            return True
        case "/save", name:
            result = agent.save_session(name.strip() if name and name.strip() else None)
            console.print(f"[cyan]{result}[/cyan]")
            return True
        case "/load", name if name and name.strip():
            agent.load_session(name.strip())
            console.print(f"[dim]Loaded: {name.strip()}[/dim]\n")
            return True
        case "/load", _:
            console.print("[yellow]Usage: /load <name>[/yellow]")
            return True
        case "/chats", _:
            sessions, total = agent.list_sessions()
            if sessions:
                console.print(f"[cyan]Saved chats ({total} total):[/cyan]")
                for session in sessions:
                    console.print(f"  • {session}")
            else:
                console.print("[dim]No saved chats[/dim]")
            return True
        case "/undo", _:
            console.print(f"[cyan]{agent.undo()}[/cyan]")
            return True
        case "/redo", _:
            console.print(f"[cyan]{agent.redo()}[/cyan]")
            return True
        case "/clear", _:
            console.clear()
            print_welcome(console)
            return True
        case "/help", _:
            print_help(console)
            return True
        case "/models", _:
            console.print("\n[bold]Recommended Models (4GB VRAM):[/bold]")
            for model_name, description in RECOMMENDED_MODELS:
                console.print(f"  [cyan]{model_name}[/cyan] - {description}")
            console.print("\n[dim]Use /model <name> to switch[/dim]\n")
            return True
        case "/model", model_name if model_name and model_name.strip():
            old_model = agent.config.model
            try:
                new_provider = get_provider(
                    name=agent.config.provider,
                    model=model_name.strip(),
                    base_url=agent.config.base_url,
                )
                agent.llm = new_provider
                agent.config.model = model_name.strip()
                console.print(
                    f"[green]Model successfully switched to {model_name.strip()}[/green]\n"
                )
            except Exception as e:
                console.print(f"[red]Failed to switch model: {e}[/red]")
                console.print(f"[dim]Current model remains: {old_model}[/dim]\n")
            return True
        case "/model", _:
            console.print("[yellow]Usage: /model <model_name>[/yellow]")
            console.print("[dim]Use /models to see available models[/dim]\n")
            return True
        case "/temperature", value if value and value.strip():
            try:
                new_temp = float(value.strip())
                if not 0.0 <= new_temp <= 2.0:
                    raise ValueError("Temperature must be between 0.0 and 2.0")
                agent.config.temperature = new_temp
                console.print(f"[green]Temperature set to {new_temp}[/green]\n")
            except ValueError as e:
                console.print(f"[red]Invalid temperature: {e}[/red]\n")
            return True
        case "/temperature", _:
            console.print(f"[dim]Current temperature: {agent.config.temperature}[/dim]")
            console.print("[yellow]Usage: /temperature <0.0-2.0>[/yellow]\n")
            return True
        case _:
            console.print(f"[red]Unknown command: {cmd}[/red]")
            console.print("[dim]Type /help to see available commands[/dim]\n")
            return True
