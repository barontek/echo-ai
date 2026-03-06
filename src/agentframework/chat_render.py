"""Rendering helpers for chat terminal output."""

import re

from rich.console import Console

from .chat_commands import help_lines


def make_clickable_links(text: str) -> str:
    """Convert markdown links [text](url) to clickable terminal links."""

    def replace_link(match):
        name = match.group(1)
        url = match.group(2)
        return f"\033]8;;{url}\007{name}\033]8;;\007"

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace_link, text)
    text = re.sub(r"\[(https?://[^]]+)\]\((https?://[^)]+)\)", replace_link, text)
    return text


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


def print_welcome(console: Console):
    """Render welcome banner."""
    console.print("\n[bold blue]╭───────────────────────────────────────╮[/bold blue]")
    console.print(
        "[bold blue]│[/bold blue]     [bold]Agent Framework[/bold]              [bold blue]│[/bold blue]"
    )
    console.print(
        "[bold blue]│[/bold blue]     Type 'help' for commands       [bold blue]│[/bold blue]"
    )
    console.print("[bold blue]╰───────────────────────────────────────╯[/bold blue]\n")


def print_help(console: Console):
    """Render help from the command registry."""
    console.print("\n[bold]Commands:[/bold]")
    for line in help_lines():
        console.print(line)
    console.print()
