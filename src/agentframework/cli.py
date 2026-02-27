"""CLI for the agent framework."""

import asyncio
import os
import sys
from pathlib import Path

import yaml
from rich.console import Console
from rich.markdown import Markdown

from .agent import Agent, AgentConfig, create_agent
from .safety import SafetyConfig
from .tools.bash import BashTool
from .tools.file import ReadFileTool, WriteFileTool, ListDirTool
from .tools.search import GlobTool, GrepTool
from .tools.web import WebFetchTool, WebSearchTool
from .tools.git import GitTool

console = Console(color_system="256")


def load_config(path: str | None = None) -> dict:
    if path is None:
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
    """Create safety config from YAML config."""
    safety = config.get("safety", {})
    tools_config = config.get("tools", {})

    def approval_callback(tool: str, details: str) -> bool:
        """Ask user for approval."""
        console.print(f"[yellow]Approval required for {tool}:[/yellow] {details}")
        response = console.input("[bold]Allow? (y/N): [/bold]")
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
    """Get enabled tools based on config."""
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

    return tools


async def interactive_mode(agent: Agent):
    """Run the agent in interactive mode."""
    console.print("[bold blue]Agent Framework[/bold blue]")
    console.print("[dim]Commands: /save, /load, /sessions, /undo, /redo, /exit[/dim]\n")

    while True:
        try:
            user_input = console.input("[bold green]>[/bold green] ")
            
            # Handle commands
            if user_input.strip().startswith("/"):
                cmd = user_input.strip().split()[0].lower()
                args = user_input.strip().split(maxsplit=1)[1] if len(user_input.strip().split()) > 1 else ""
                
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
                elif cmd == "/sessions":
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
                    console.print("  /sessions    - List saved sessions")
                    console.print("  /undo        - Undo last file change")
                    console.print("  /redo        - Redo last undone change")
                    console.print("  /exit        - Exit")
                    continue
            
            if not user_input.strip():
                continue

            # Streaming output
            stream_console = Console(color_system="256")
            in_thinking = False
            
            def on_chunk(chunk: str):
                nonlocal in_thinking
                
                # Handle thinking markers - these come as separate chunks
                if "__THINKING__" in chunk:
                    in_thinking = True
                    # Remove the marker from the chunk content
                    chunk = chunk.replace("__THINKING__", "")
                    if not chunk:  # If marker was the only content, skip
                        return
                if "__THINKING_END__" in chunk:
                    in_thinking = False
                    chunk = chunk.replace("__THINKING_END__", "")
                    if not chunk:
                        return
                
                if in_thinking:
                    stream_console.print(chunk, style="bright_black", end="")
                else:
                    stream_console.print(chunk, end="")
            
            response = await agent.run_streaming(user_input, on_chunk=on_chunk)
            console.print()
        except KeyboardInterrupt:
            break
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")

    # Auto-save on exit
    agent.save_session()
    console.print("\n[dim]Session saved. Goodbye![/dim]")


async def run_single(agent: Agent, task: str):
    """Run a single task with streaming output."""
    from rich.console import Console
    stream_console = Console(color_system="256")
    
    buffer = ""
    thinking_buffer = ""
    in_thinking = False
    
    def on_chunk(chunk: str):
        nonlocal buffer, thinking_buffer, in_thinking
        
        # Check if we're in thinking mode
        if "__THINKING__" in chunk:
            in_thinking = True
            chunk = chunk.split("__THINKING__")[1] if "__THINKING__" in chunk else ""
        
        if "__THINKING_END__" in chunk:
            in_thinking = False
            chunk = chunk.split("__THINKING_END__")[1] if "__THINKING_END__" in chunk else ""
        
        if in_thinking or "__THINKING__" in buffer:
            thinking_buffer += chunk
        else:
            buffer += chunk
            # Print without newlines for smooth streaming
            stream_console.print(chunk, end="")
    
    response = await agent.run_streaming(task, on_chunk=on_chunk)
    stream_console.print()  # New line after streaming


def main():
    """Main entry point."""
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
        session_enabled=config.get("agent", {}).get("session_enabled", True),
        session_dir=config.get("agent", {}).get("session_dir", ".agent_sessions"),
    )

    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")

    agent = create_agent(agent_config, api_key)

    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
        asyncio.run(run_single(agent, task))
    else:
        asyncio.run(interactive_mode(agent))


if __name__ == "__main__":
    main()
