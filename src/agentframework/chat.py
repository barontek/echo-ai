"""Chat interface for the agent framework."""

import asyncio
import os
import re
import sys
from pathlib import Path

import aiohttp
import yaml
from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Prompt

from .agent import Agent, AgentConfig, create_agent
from .providers import get_provider
from .safety import SafetyConfig
from .tools.bash import BashTool
from .tools.file import ReadFileTool, WriteFileTool, ListDirTool
from .tools.search import GlobTool, GrepTool
from .tools.web import WebFetchTool, WebSearchTool
from .tools.git import GitTool

console = Console(color_system="256")


def make_clickable_links(text: str) -> str:
    """Convert markdown links [text](url) to clickable terminal links."""
    def replace_link(match):
        name = match.group(1)
        url = match.group(2)
        return f"\033]8;;{url}\007{name}\033]8;;\007"
    
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_link, text)
    
    text = re.sub(r'\[(https?://[^]]+)\]\((https?://[^)]+)\)', replace_link, text)
    
    return text


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)


# Enable command history with readline
try:
    import readline
    histfile = Path.home() / ".cache" / "agentframework" / "history"
    histfile.parent.mkdir(parents=True, exist_ok=True)
    if histfile.exists():
        readline.read_history_file(str(histfile))
    import atexit
    atexit.register(readline.write_history_file, str(histfile))
except ImportError:
    pass  # readline not available on all platforms


def load_config(path: str | None = None) -> dict:
    if path is None:
        # Try to find config.yaml in common locations
        script_dir = Path(__file__).parent.parent.parent
        search_paths = [
            Path.cwd() / "config.yaml",
            script_dir / "config.yaml",
            Path.home() / "vibe-ai" / "config.yaml",
        ]
        for config_path in search_paths:
            if config_path.exists():
                with open(config_path) as f:
                    return yaml.safe_load(f)
        return {}
    config_path = Path(path)
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f)
    return {}


def get_safety_config(config: dict) -> SafetyConfig:
    safety = config.get("safety", {})
    tools_config = config.get("tools", {})

    def approval_callback(tool: str, details: str) -> bool:
        console.print(f"[yellow]Approval required for {tool}:[/yellow] {details}")
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
        require_approval_for=safety.get("require_approval_for", []),
        approval_callback=approval_callback,
    )


def get_tools(config: dict, safety_config: SafetyConfig) -> list:
    tools = []
    enabled = config.get("tools", {}).get("enabled", [])

    if "bash" in enabled:
        bash_config = config.get("tools", {}).get("bash", {})
        tools.append(BashTool(
            timeout=bash_config.get("timeout", 60),
            allowed_commands=bash_config.get("allowed_commands"),
            safety_config=safety_config,
        ))

    if "read_file" in enabled:
        tools.append(ReadFileTool(safety_config=safety_config))

    if "write_file" in enabled:
        tools.append(WriteFileTool(safety_config=safety_config))

    if "list_dir" in enabled:
        tools.append(ListDirTool(safety_config=safety_config))

    if "glob" in enabled:
        tools.append(GlobTool(safety_config=safety_config))

    if "grep" in enabled:
        tools.append(GrepTool(safety_config=safety_config))

    if "web_fetch" in enabled:
        tools.append(WebFetchTool(safety_config=safety_config))

    if "web_search" in enabled:
        tools.append(WebSearchTool(safety_config=safety_config))

    if "git" in enabled:
        tools.append(GitTool(safety_config=safety_config))

    if "memory" in enabled:
        from .tools.memory import MemoryTool
        tools.append(MemoryTool())

    if "notes" in enabled:
        from .tools.notes import PersonalNotesTool
        tools.append(PersonalNotesTool())

    return tools


def print_welcome():
    console.print("\n[bold blue]╭───────────────────────────────────────╮[/bold blue]")
    console.print("[bold blue]│[/bold blue]     [bold]Agent Framework[/bold]              [bold blue]│[/bold blue]")
    console.print("[bold blue]│[/bold blue]     Type 'help' for commands       [bold blue]│[/bold blue]")
    console.print("[bold blue]╰───────────────────────────────────────╯[/bold blue]\n")


RECOMMENDED_MODELS = [
    ("qwen3:4b-instruct", "Best for following instructions and tool calling (default)"),
    ("qwen2.5-coder:3b", "Best for strict tool calling and coding"),
    ("qwen3:4b", "General purpose with strong reasoning"),
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
                args = user_input.strip().split(maxsplit=1)[1] if len(user_input.strip().split()) > 1 else ""
                
                if cmd in ("/exit", "/quit"):
                    agent.save_session()
                    console.print("[dim]Chat saved. Goodbye![/dim]")
                    return
                
                elif cmd == "/new":
                    agent.save_session()
                    agent.messages.clear()
                    console.clear()
                    print_welcome()
                    console.print("[dim]Started new chat[/dim]\n")
                    continue
                
                elif cmd == "/save":
                    name = args.strip() if args.strip() else None
                    result = agent.save_session(name)
                    console.print(f"[cyan]{result}[/cyan]")
                    continue
                
                elif cmd == "/load":
                    if args.strip():
                        agent.load_session(args.strip())
                        console.print(f"[dim]Loaded: {args.strip()}[/dim]\n")
                    else:
                        console.print("[yellow]Usage: /load <name>[/yellow]")
                    continue
                
                elif cmd == "/chats":
                    sessions = agent.list_sessions()
                    if sessions:
                        console.print("[cyan]Saved chats:[/cyan]")
                        for s in sessions:
                            console.print(f"  • {s}")
                    else:
                        console.print("[dim]No saved chats[/dim]")
                    continue
                
                elif cmd == "/undo":
                    result = agent.undo()
                    console.print(f"[cyan]{result}[/cyan]")
                    continue
                
                elif cmd == "/redo":
                    result = agent.redo()
                    console.print(f"[cyan]{result}[/cyan]")
                    continue
                
                elif cmd == "/clear":
                    console.clear()
                    print_welcome()
                    continue
                
                elif cmd == "/help":
                    print_help()
                    continue
                
                elif cmd == "/models":
                    console.print("\n[bold]Recommended Models (4GB VRAM):[/bold]")
                    for model_name, description in RECOMMENDED_MODELS:
                        console.print(f"  [cyan]{model_name}[/cyan] - {description}")
                    console.print("\n[dim]Use /model <name> to switch[/dim]\n")
                    continue
                
                elif cmd == "/model":
                    if not args.strip():
                        console.print("[yellow]Usage: /model <model_name>[/yellow]")
                        console.print("[dim]Use /models to see available models[/dim]\n")
                        continue
                    
                    new_model = args.strip()
                    old_model = agent.config.model
                    
                    try:
                        # Get existing provider settings
                        provider_name = agent.config.provider
                        base_url = agent.config.base_url
                        temperature = agent.config.temperature
                        tools = agent.config.tools
                        
                        # Create new provider with new model
                        new_provider = get_provider(
                            name=provider_name,
                            model=new_model,
                            base_url=base_url,
                        )
                        
                        # Update agent
                        agent.llm = new_provider
                        agent.config.model = new_model
                        
                        console.print(f"[green]Model successfully switched to {new_model}[/green]\n")
                    except Exception as e:
                        console.print(f"[red]Failed to switch model: {e}[/red]")
                        console.print(f"[dim]Current model remains: {old_model}[/dim]\n")
                    continue
            
            # Regular message - stream output with Rich
            console.print("[dim]Thinking...[/dim]", end="\r")
            
            in_thinking = False
            
            def on_chunk(chunk: str):
                nonlocal in_thinking
                
                if '__THINKING__' in chunk:
                    in_thinking = True
                    chunk = chunk.replace('__THINKING__', '')
                    if not chunk:
                        return
                if '__THINKING_END__' in chunk:
                    in_thinking = False
                    chunk = chunk.replace('__THINKING_END__', '')
                    if not chunk:
                        return
                
                # Use stdout directly for unbuffered streaming
                import sys
                if in_thinking:
                    sys.stdout.write('\033[90m' + chunk + '\033[0m')
                else:
                    sys.stdout.write(chunk)
                sys.stdout.flush()
            
            response = await agent.run_streaming(user_input, on_chunk=on_chunk)
            
            import sys
            sys.stdout.write('\n')
            
            # Extract and display clickable links from the response
            clean_response = strip_ansi(response)
            
            # Find markdown links [text](url)
            links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', clean_response)
            
            # Extract URLs from tool results (web searches)
            tool_urls = set()
            for msg in agent.messages:
                if msg.role == "tool" and msg.tool_name in ("web_search", "web_fetch"):
                    # Extract URLs from tool content
                    found = re.findall(r'(https?://[^\s\)"\']+)', msg.content or "")
                    tool_urls.update(found)
            
            # Also extract plain URLs from AI response
            url_only = re.findall(r'\((https?://[^)]+)\)', clean_response)
            
            # Combine and deduplicate
            all_urls = list(links)
            seen_urls = set(pair[1] for pair in links)
            
            for url in url_only:
                if url not in seen_urls:
                    all_urls.append((url, url))
                    seen_urls.add(url)
            
            for url in tool_urls:
                if url not in seen_urls:
                    # Try to get domain as name
                    name = url.split('/')[2] if len(url.split('/')) > 2 else url
                    all_urls.append((name, url))
                    seen_urls.add(url)
            
            if all_urls:
                # Fetch titles for URLs
                async def fetch_titles():
                    titles = {}
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as session:
                        for name, url in all_urls:
                            try:
                                async with session.get(url, ssl=False) as resp:
                                    if resp.status == 200:
                                        html = await resp.text()
                                        match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
                                        if match:
                                            titles[url] = match.group(1).strip()[:60]
                            except Exception:
                                pass
                    return titles
                
                titles = await fetch_titles()
                
                console.print("[dim]Sources:[/dim]")
                for name, url in all_urls:
                    display_name = titles.get(url, name)
                    clickable = f"\033]8;;{url}\007{display_name}\033]8;;\007"
                    print(f"  {clickable}")
            
            # Print which tools were used (in gray)
            tool_names = set()
            for msg in agent.messages:
                if msg.role == "tool" and msg.tool_name:
                    tool_names.add(msg.tool_name)
            if tool_names:
                print(f"\033[90mUsed: {', '.join(tool_names)}\033[0m")
            
            sys.stdout.flush()
            
        except KeyboardInterrupt:
            agent.save_session()
            console.print("\n[dim]Chat saved. Goodbye![/dim]")
            return
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")


def main():
    config = load_config()
    safety_config = get_safety_config(config)

    agent_config = AgentConfig(
        provider=config.get("model", {}).get("provider", "anthropic"),
        model=config.get("model", {}).get("name", "claude-sonnet-4-20250514"),
        temperature=config.get("model", {}).get("temperature", 0.3),
        max_iterations=config.get("agent", {}).get("max_iterations", 50),
        system_prompt=config.get("agent", {}).get("system_prompt", ""),
        tools=get_tools(config, safety_config),
        base_url=config.get("model", {}).get("base_url"),
        session_enabled=True,
        session_dir=config.get("agent", {}).get("session_dir", ".agent_sessions"),
    )

    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")
    agent = create_agent(agent_config, api_key)

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
    if len(sys.argv) > 1:
        if sys.argv[1] == "--load" and len(sys.argv) > 2:
            session_name = sys.argv[2]
        elif not sys.argv[1].startswith("-"):
            asyncio.run(agent.run(" ".join(sys.argv[1:])))
            agent.save_session()
            return

    console.clear()
    print_welcome()
    asyncio.run(chat_session(agent, session_name))


if __name__ == "__main__":
    main()
