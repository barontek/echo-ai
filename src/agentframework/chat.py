"""Chat interface for the agent framework."""

import asyncio
import os
import logging
import re
import sys
from pathlib import Path

import aiohttp
import yaml
from rich.console import Console
from rich.prompt import Prompt

from .agent import Agent, AgentConfig, create_agent
from .providers import get_provider
from .safety import SafetyConfig, SecurityValidator
from .tools import TOOL_REGISTRY, TOOL_CONFIG_KEYS

console = Console(color_system="256")


def find_config_path(path: str | None = None) -> Path | None:
    if path is not None:
        config_path = Path(path)
        return config_path if config_path.exists() else None

    script_dir = Path(__file__).parent.parent.parent
    search_paths = [
        Path.cwd() / "config.yaml",
        script_dir / "config.yaml",
        Path.home() / "vibe-ai" / "config.yaml",
    ]
    for config_path in search_paths:
        if config_path.exists():
            return config_path
    return None


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


# Enable command history with readline
try:
    import readline
    from rlcompleter import Completer

    histfile = Path.home() / ".cache" / "agentframework" / "history"
    histfile.parent.mkdir(parents=True, exist_ok=True)
    if histfile.exists():
        readline.read_history_file(str(histfile))
    import atexit

    atexit.register(readline.write_history_file, str(histfile))

    # Define slash commands for tab completion
    SLASH_COMMANDS = [
        "/exit",
        "/quit",
        "/new",
        "/save",
        "/load",
        "/chats",
        "/undo",
        "/redo",
        "/clear",
        "/help",
        "/models",
        "/model",
        "/temperature",
        "/context",
        "/tokens",
    ]

    class CommandCompleter(Completer):
        def complete(self, text, state):
            if not text.startswith("/"):
                return None
            matches = [cmd for cmd in SLASH_COMMANDS if cmd.startswith(text)]
            if matches:
                return matches[state] if state < len(matches) else None
            return None

    readline.set_completer(CommandCompleter().complete)
    readline.parse_and_bind("tab: complete")
    readline.set_completer_delims("")

except ImportError:
    pass  # readline not available on all platforms


def load_config(path: str | None = None) -> dict:
    config_path = find_config_path(path)
    if config_path:
        with open(config_path) as f:
            return yaml.safe_load(f)
    return {}


def get_safety_config(config: dict) -> SafetyConfig:
    safety = config.get("safety", {})
    tools_config = config.get("tools", {})

    validator = SecurityValidator(
        SafetyConfig(
            workspace=safety.get("workspace", "."),
        )
    )

    def approval_callback(tool: str, details: str) -> bool:
        warning_msg = ""

        if tool == "bash":
            destructive = validator.check_destructive_keywords(details)
            if destructive:
                warning_msg = f" [red]⚠️ DESTRUCTIVE keywords detected: {', '.join(destructive)}[/red]"

        if tool == "write_file":
            try:
                from pathlib import Path

                path = details.replace("write: ", "")
                file_path = Path(path)
                if file_path.exists():
                    warning_msg = " [red]⚠️ File exists - will overwrite![/red]"
            except Exception:
                pass

        if tool == "read_file":
            try:
                from pathlib import Path

                path = details.replace("read: ", "")
                file_path = Path(path)
                if file_path.exists():
                    size = file_path.stat().st_size
                    threshold = safety.get("read_size_threshold", 102400)
                    if size > threshold:
                        warning_msg = (
                            f" [yellow]⚠️ Large file ({size // 1024} KB)[/yellow]"
                        )
            except Exception:
                pass

        console.print(
            f"[yellow]Approval required for {tool}:[/yellow] {details}{warning_msg}"
        )
        response = Prompt.ask("[bold]Allow? (y/N)[/bold]", default="n")
        return response.lower() in ("y", "yes")

    return SafetyConfig(
        workspace=safety.get("workspace", "."),
        allowed_commands=tools_config.get("bash", {}).get("allowed_commands", ["*"]),
        blocked_commands=safety.get("blocked_commands", []),
        allow_network=safety.get("allow_network", False),
        allowed_domains=safety.get("allowed_domains", []),
        max_file_size=safety.get("max_file_size", 10 * 1024 * 1024),
        max_execution_time=safety.get("max_execution_time", 60),
        require_approval_for=safety.get("require_approval_for", ["bash", "write_file"]),
        approval_callback=approval_callback,
        audit_log_path=safety.get("audit_log_path"),
        read_requires_approval=safety.get("read_requires_approval", False),
        read_size_threshold=safety.get("read_size_threshold", 102400),
    )


def get_tools(config: dict, safety_config: SafetyConfig) -> list:
    tools = []
    enabled = config.get("tools", {}).get("enabled", [])

    for tool_name in enabled:
        tool_class = TOOL_REGISTRY.get(tool_name)
        if tool_class is None:
            continue

        tool_config = config.get("tools", {}).get(tool_name, {})
        config_defaults = TOOL_CONFIG_KEYS.get(tool_name, {})

        kwargs = {}
        for key, default_value in config_defaults.items():
            if key in tool_config:
                kwargs[key] = tool_config[key]
            elif default_value is not None:
                kwargs[key] = default_value

        if "safety_config" in config_defaults and "safety_config" not in kwargs:
            kwargs["safety_config"] = safety_config

        tools.append(tool_class(**kwargs))

    return tools


def print_welcome():
    console.print("\n[bold blue]╭───────────────────────────────────────╮[/bold blue]")
    console.print(
        "[bold blue]│[/bold blue]     [bold]Agent Framework[/bold]              [bold blue]│[/bold blue]"
    )
    console.print(
        "[bold blue]│[/bold blue]     Type 'help' for commands       [bold blue]│[/bold blue]"
    )
    console.print("[bold blue]╰───────────────────────────────────────╯[/bold blue]\n")


RECOMMENDED_MODELS = [
    ("qwen3:4b-instruct", "Best for following instructions and tool calling (default)"),
    ("qwen2.5-coder:3b", "Best for strict tool calling and coding"),
    ("qwen3:4b", "General purpose with strong reasoning"),
    ("qwen3.5:4b", "Latest Qwen with improved reasoning"),
    ("llama3.2", "Meta's lightweight model, great reasoning"),
    ("phi3.5", "Microsoft's highly stable model"),
]


def print_help():
    console.print("\n[bold]Commands:[/bold]")
    console.print("  [bold]/new[/bold]     - Start a new chat")
    console.print("  [bold]/save <name>[/bold] - Save current chat")
    console.print("  [bold]/load <name>[/bold] - Load a saved chat")
    console.print("  [bold]/chats[/bold]     - List saved chats")
    console.print("  [bold]/models[/bold]    - List recommended local models")
    console.print("  [bold]/model <name>[/bold] - Switch to a different model")
    console.print("  [bold]/temperature <val>[/bold] - Set temperature (0.0-2.0)")
    console.print("  [bold]/undo[/bold]      - Undo last file change")
    console.print("  [bold]/redo[/bold]      - Redo last undone change")
    console.print("  [bold]/clear[/bold]     - Clear screen")
    console.print("  [bold]/help[/bold]      - Show this help")
    console.print("  [bold]/exit[/bold]      - Exit\n")


async def chat_session(agent: Agent, session_name: str | None = None):
    """Run a chat session."""
    if session_name:
        agent.load_session(session_name)
        console.print(f"[dim]Loaded chat: {session_name}[/dim]\n")

    while True:
        try:
            # Use better readline compatibility input() for
            user_input = input("\n> ")

            if not user_input.strip():
                continue

            # Handle commands
            if user_input.strip().startswith("/"):
                cmd = user_input.strip().split()[0].lower()
                args = (
                    user_input.strip().split(maxsplit=1)[1]
                    if len(user_input.strip().split()) > 1
                    else ""
                )

                # Handle commands with structural pattern matching
                match cmd, args:
                    case "/exit" | "/quit", _:
                        agent.save_session()
                        console.print("[dim]Chat saved. Goodbye![/dim]")
                        return

                    case "/new", _:
                        agent.save_session()
                        agent.messages.clear()
                        console.clear()
                        print_welcome()
                        console.print("[dim]Started new chat[/dim]\n")
                        continue

                    case "/save", name:
                        name = name.strip() if name and name.strip() else None
                        result = agent.save_session(name)
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
                            for s in sessions:
                                console.print(f"  • {s}")
                        else:
                            console.print("[dim]No saved chats[/dim]")
                        continue

                    case "/undo", _:
                        result = agent.undo()
                        console.print(f"[cyan]{result}[/cyan]")
                        continue

                    case "/redo", _:
                        result = agent.redo()
                        console.print(f"[cyan]{result}[/cyan]")
                        continue

                    case "/clear", _:
                        console.clear()
                        print_welcome()
                        continue

                    case "/help", _:
                        print_help()
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
                            provider_name = agent.config.provider
                            base_url = agent.config.base_url

                            new_provider = get_provider(
                                name=provider_name,
                                model=model_name.strip(),
                                base_url=base_url,
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

            # Regular message - stream output with Rich
            console.print("[dim]Thinking...[/dim]", end="\r")

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

                # Use stdout directly for unbuffered streaming
                import sys

                if in_thinking:
                    sys.stdout.write("\033[90m" + chunk + "\033[0m")
                else:
                    sys.stdout.write(chunk)
                sys.stdout.flush()

            response = await agent.run_streaming(user_input, on_chunk=on_chunk)

            import sys

            sys.stdout.write("\n")

            # Extract and display clickable links from the response
            clean_response = strip_ansi(response)

            # Only show sources if this query had web search/fetch tool calls
            # Check tool messages between the last two user messages (current query)
            has_web_tool = False
            user_messages = [
                i for i, m in enumerate(agent.messages) if m.role == "user"
            ]

            if len(user_messages) >= 2:
                # Check messages between last two user messages
                for msg in agent.messages[user_messages[-2] + 1 : user_messages[-1]]:
                    if msg.role == "tool" and msg.tool_name in (
                        "web_search",
                        "web_fetch",
                    ):
                        has_web_tool = True
                        break
            elif len(user_messages) == 1:
                # First query - check all tool messages
                for msg in agent.messages:
                    if msg.role == "tool" and msg.tool_name in (
                        "web_search",
                        "web_fetch",
                    ):
                        has_web_tool = True
                        break

            if has_web_tool:
                # Find markdown links [text](url)
                links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", clean_response)

                # Extract URLs from tool results in current query
                tool_urls = set()
                user_messages = [
                    i for i, m in enumerate(agent.messages) if m.role == "user"
                ]

                if len(user_messages) >= 2:
                    for msg in agent.messages[
                        user_messages[-2] + 1 : user_messages[-1]
                    ]:
                        if msg.role == "tool" and msg.tool_name in (
                            "web_search",
                            "web_fetch",
                        ):
                            found = re.findall(
                                r'(https?://[^\s\)"\']+)', msg.content or ""
                            )
                            tool_urls.update(found)
                elif len(user_messages) == 1:
                    for msg in agent.messages:
                        if msg.role == "tool" and msg.tool_name in (
                            "web_search",
                            "web_fetch",
                        ):
                            found = re.findall(
                                r'(https?://[^\s\)"\']+)', msg.content or ""
                            )
                            tool_urls.update(found)

                # Also extract plain URLs from AI response
                url_only = re.findall(r"\((https?://[^)]+)\)", clean_response)

                # Combine and deduplicate
                all_urls = list(links)
                seen_urls = set(pair[1] for pair in links)

                for url in url_only:
                    if url not in seen_urls:
                        all_urls.append((url, url))
                        seen_urls.add(url)

                for url in tool_urls:
                    if url not in seen_urls:
                        name = url.split("/")[2] if len(url.split("/")) > 2 else url
                        all_urls.append((name, url))
                        seen_urls.add(url)

                if all_urls:
                    # Fetch titles for URLs
                    async def fetch_titles():
                        titles = {}
                        async with aiohttp.ClientSession(
                            timeout=aiohttp.ClientTimeout(total=3)
                        ) as session:
                            for name, url in all_urls:
                                try:
                                    async with session.get(url, ssl=False) as resp:
                                        if resp.status == 200:
                                            html = await resp.text()
                                            match = re.search(
                                                r"<title[^>]*>([^<]+)</title>",
                                                html,
                                                re.IGNORECASE,
                                            )
                                            if match:
                                                titles[url] = match.group(1).strip()[
                                                    :60
                                                ]
                                except Exception:
                                    pass
                        return titles

                    titles = await fetch_titles()

                    console.print("[dim]Sources:[/dim]")
                    for name, url in all_urls:
                        display_name = titles.get(url, name)
                        clickable = f"\033]8;;{url}\007{display_name}\033]8;;\007"
                        print(f"  {clickable}")

            # Print which tools were used in this query only
            tool_usages = []
            user_messages = [
                i for i, m in enumerate(agent.messages) if m.role == "user"
            ]

            if len(user_messages) >= 2:
                for msg in agent.messages[user_messages[-2] + 1 : user_messages[-1]]:
                    if msg.role == "tool" and msg.tool_name:
                        tool_usages.append((msg.tool_name, msg.tool_arguments))
            elif len(user_messages) == 1:
                for msg in agent.messages:
                    if msg.role == "tool" and msg.tool_name:
                        tool_usages.append((msg.tool_name, msg.tool_arguments))

            if tool_usages:
                parts = []
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
        session_enabled=True,
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

    # Load sub-agents from config
    sub_agents_config = config.get("agent", {}).get("sub_agents", {})
    for name, sub_cfg in sub_agents_config.items():
        agent.register_sub_agent(
            name=name,
            description=sub_cfg.get("description", ""),
            model=sub_cfg.get("model"),
            tools=sub_cfg.get("tools", []),
            system_prompt=sub_cfg.get("system_prompt", ""),
        )

    # Check for session to load
    session_name = None
    args = [a for a in sys.argv[1:] if a != "--debug"]
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
    print_welcome()
    try:
        asyncio.run(chat_session(agent, session_name))
    except KeyboardInterrupt:
        try:
            agent.save_session()
        except Exception:
            pass
        console.print("\n[dim]Chat saved. Goodbye![/dim]")


if __name__ == "__main__":
    main()
