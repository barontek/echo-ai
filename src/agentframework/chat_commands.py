"""Shared command registry and helpers for chat interfaces."""

from dataclasses import dataclass


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
