"""Bootstrap utilities for initializing the agent environment."""

import os
import sys

from rich.console import Console

from .agent import Agent, AgentConfig, create_agent
from .config import (
    find_config_path,
    get_safety_config,
    get_tools,
    load_config,
)
from .logging_utils import configure_logging

console = Console(color_system="256")



def setup_agent(force_session_enabled: bool = False) -> Agent:
    """Initialize and return the configured agent instance."""
    if sys.version_info < (3, 11):
        console.print("[red]Python 3.11+ is required to run Echo AI.[/red]")
        raise SystemExit(1)

    debug_enabled = "--debug" in sys.argv
    debug_json = "--debug-json" in sys.argv
    configure_logging(debug_enabled, debug_json)

    config = load_config()
    config_path = find_config_path()
    safety_config = get_safety_config(config)

    session_enabled = True if force_session_enabled else config.get("agent", {}).get("session_enabled", True)

    agent_config = AgentConfig(
        provider=config.get("model", {}).get("provider", "ollama"),
        model=config.get("model", {}).get("name", "qwen3:4b-instruct"),
        temperature=config.get("model", {}).get("temperature", 0.3),
        max_iterations=config.get("agent", {}).get("max_iterations", 50),
        system_prompt=config.get("agent", {}).get("system_prompt", ""),
        tools=get_tools(config, safety_config),
        base_url=config.get("model", {}).get("base_url"),
        session_enabled=session_enabled,
        session_dir=config.get("agent", {}).get("session_dir", ".agent_sessions"),
    )

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
    
    try:
        agent = create_agent(agent_config, api_key)
    except ValueError as e:
        console.print(f"[red]Provider Configuration Error:[/red] {e}")
        raise SystemExit(1)
    console.print(
        f"[dim]Config: {config_path if config_path else '<none>'} | Provider: {agent_config.provider} | Model: {agent_config.model}[/dim]"
    )

    sub_agents_config = config.get("agent", {}).get("sub_agents", {})
    for name, sub_cfg in sub_agents_config.items():
        agent.register_sub_agent(
            name=name,
            description=sub_cfg.get("description", ""),
            model=sub_cfg.get("model"),
            tools=sub_cfg.get("tools", []),
            system_prompt=sub_cfg.get("system_prompt", ""),
        )

    return agent
