"""Chat interface for the agent framework."""

import asyncio
import sys

from rich.console import Console

from .agent import Agent
from .bootstrap import setup_agent
from .chat_commands import normalize_command
from .chat_render import print_help, print_welcome, strip_ansi
from .chat_runtime import (
    current_query_tool_messages,
    extract_urls,
    fetch_titles,
    get_input,
)
from .providers import get_provider

console = Console(color_system="256")

RECOMMENDED_MODELS = [
    ("qwen3:4b-instruct", "Best for following instructions and tool calling (default)"),
    ("qwen2.5-coder:3b", "Best for strict tool calling and coding"),
    ("qwen3:4b", "General purpose with strong reasoning"),
    ("qwen3.5:4b", "Latest Qwen with improved reasoning"),
    ("llama3.2", "Meta's lightweight model, great reasoning"),
    ("phi3.5", "Microsoft's highly stable model"),
]


async def chat_session(agent: Agent, session_name: str | None = None):
    """Run a chat session."""
    if session_name:
        agent.load_session(session_name)
        console.print(f"[dim]Loaded chat: {session_name}[/dim]\n")

    while True:
        try:
            user_input = await get_input("\n> ")
            if not user_input.strip():
                continue

            if user_input.strip().startswith("/"):
                cmd = normalize_command(user_input.strip().split()[0].lower())
                args = (
                    user_input.strip().split(maxsplit=1)[1]
                    if len(user_input.strip().split()) > 1
                    else ""
                )

                match cmd, args:
                    case "/exit", _:
                        agent.save_session()
                        console.print("[dim]Chat saved. Goodbye![/dim]")
                        return
                    case "/new", _:
                        agent.save_session()
                        agent.messages.clear()
                        console.clear()
                        print_welcome(console)
                        console.print("[dim]Started new chat[/dim]\n")
                        continue
                    case "/save", name:
                        result = agent.save_session(
                            name.strip() if name and name.strip() else None
                        )
                        console.print(f"[cyan]{result}[/cyan]")
                        continue
                    case "/load", name if name and name.strip():
                        agent.load_session(name.strip())
                        console.print(f"[dim]Loaded: {name.strip()}[/dim]\n")
                        continue
                    case "/load", _:
                        console.print("[yellow]Usage: /load <name>[/yellow]")
                        continue
                    case "/chats", _:
                        sessions = agent.list_sessions()
                        if sessions:
                            console.print("[cyan]Saved chats:[/cyan]")
                            for session in sessions:
                                console.print(f"  • {session}")
                        else:
                            console.print("[dim]No saved chats[/dim]")
                        continue
                    case "/undo", _:
                        console.print(f"[cyan]{agent.undo()}[/cyan]")
                        continue
                    case "/redo", _:
                        console.print(f"[cyan]{agent.redo()}[/cyan]")
                        continue
                    case "/clear", _:
                        console.clear()
                        print_welcome(console)
                        continue
                    case "/help", _:
                        print_help(console)
                        continue
                    case "/models", _:
                        console.print("\n[bold]Recommended Models (4GB VRAM):[/bold]")
                        for model_name, description in RECOMMENDED_MODELS:
                            console.print(
                                f"  [cyan]{model_name}[/cyan] - {description}"
                            )
                        console.print("\n[dim]Use /model <name> to switch[/dim]\n")
                        continue
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
                            console.print(
                                f"[dim]Current model remains: {old_model}[/dim]\n"
                            )
                        continue
                    case "/model", _:
                        console.print("[yellow]Usage: /model <model_name>[/yellow]")
                        console.print(
                            "[dim]Use /models to see available models[/dim]\n"
                        )
                        continue
                    case "/temperature", value if value and value.strip():
                        try:
                            new_temp = float(value.strip())
                            if not 0.0 <= new_temp <= 2.0:
                                raise ValueError(
                                    "Temperature must be between 0.0 and 2.0"
                                )
                            agent.config.temperature = new_temp
                            console.print(
                                f"[green]Temperature set to {new_temp}[/green]\n"
                            )
                        except ValueError as e:
                            console.print(f"[red]Invalid temperature: {e}[/red]")
                            console.print(
                                "[dim]Temperature must be between 0.0 and 2.0[/dim]\n"
                            )
                        continue
                    case "/temperature", _:
                        console.print(
                            f"[cyan]Current temperature: {agent.config.temperature}[/cyan]"
                        )
                        console.print(
                            "[dim]Use /temperature <0.0-2.0> to change[/dim]\n"
                        )
                        continue

            console.print("[dim]Thinking...[/dim]", end="\r")
            in_thinking = False

            def on_chunk(chunk: str):
                nonlocal in_thinking
                if "__THINKING__" in chunk:
                    # Transition from talking to thinking - add newline
                    if not in_thinking:
                        chunk = "\n" + chunk
                    in_thinking = True
                    chunk = chunk.replace("__THINKING__", "")
                    if not chunk:
                        return
                if "__THINKING_END__" in chunk:
                    # Transition from thinking to talking - add newline
                    in_thinking = False
                    chunk = chunk.replace("__THINKING_END__", "\n")
                    if not chunk:
                        return

                if in_thinking:
                    sys.stdout.write("\033[90m" + chunk + "\033[0m")
                else:
                    sys.stdout.write(chunk)
                sys.stdout.flush()

            response = await agent.run_streaming(user_input, on_chunk=on_chunk)
            sys.stdout.write("\n")

            clean_response = strip_ansi(response)
            web_tool_messages = current_query_tool_messages(
                agent.messages, tool_names={"web_search", "web_fetch"}
            )

            if web_tool_messages:
                all_urls, clean_response = extract_urls(
                    clean_response, web_tool_messages
                )
                if all_urls:
                    titles = await fetch_titles(all_urls)
                    console.print("[dim]Sources:[/dim]")
                    for name, url in all_urls:
                        display_name = titles.get(url, name)
                        clickable = f"\033]8;;{url}\007{display_name}\033]8;;\007"
                        print(f"  {clickable}")

            tool_messages = current_query_tool_messages(agent.messages)
            tool_usages = [
                (message.tool_name, message.tool_arguments)
                for message in tool_messages
                if message.tool_name
            ]
            if tool_usages:
                parts: list[str] = []
                for name, args in tool_usages:
                    if args:
                        args_str = ", ".join(f"{k}={repr(v)}" for k, v in args.items())
                        parts.append(f"{name}({args_str})")
                    else:
                        parts.append(name)
                print(f"\033[90mUsed: {', '.join(parts)}\033[0m")

            sys.stdout.flush()

        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")


def main():
    agent = setup_agent(force_session_enabled=True)

    session_name = None
    args = [a for a in sys.argv[1:] if a not in {"--debug", "--debug-json"}]
    if args:
        if args[0] == "--load" and len(args) > 1:
            session_name = args[1]
        elif not args[0].startswith("-"):
            try:
                asyncio.run(agent.run(" ".join(args)))
            except KeyboardInterrupt:
                pass
            agent.save_session()
            return

    console.clear()
    print_welcome(console)
    try:
        asyncio.run(chat_session(agent, session_name))
    except KeyboardInterrupt:
        try:
            agent.save_session()
        except OSError:
            pass
        console.print("\n[dim]Chat saved. Goodbye![/dim]")


if __name__ == "__main__":
    main()
