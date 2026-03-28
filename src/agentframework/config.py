"""Configuration management for the agent framework."""

import os
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.prompt import Prompt

from .safety import SafetyConfig, SecurityValidator
from .tools import TOOL_CONFIG_KEYS, TOOL_REGISTRY

console = Console(color_system="256")


ENV_VAR_MAPPING = {
    "ECHO_PROVIDER": ("model", "provider"),
    "ECHO_MODEL": ("model", "name"),
    "ECHO_BASE_URL": ("model", "base_url"),
    "ECHO_TEMPERATURE": ("model", "temperature"),
    "ECHO_WORKSPACE": ("safety", "workspace"),
    "ECHO_ALLOW_NETWORK": ("safety", "allow_network"),
    "ECHO_SESSION_DIR": ("agent", "session_dir"),
    "ECHO_MAX_ITERATIONS": ("agent", "max_iterations"),
}


def apply_env_overrides(config: dict) -> dict:
    """Apply environment variable overrides to config.

    Environment variables take precedence over config file values.
    Supported variables:
    - ECHO_PROVIDER: LLM provider (ollama, openai, anthropic)
    - ECHO_MODEL: Model name
    - ECHO_BASE_URL: Base URL for Ollama
    - ECHO_TEMPERATURE: Model temperature
    - ECHO_WORKSPACE: Workspace directory
    - ECHO_ALLOW_NETWORK: Enable network access
    - ECHO_SESSION_DIR: Session storage directory
    - ECHO_MAX_ITERATIONS: Max agent iterations
    - ANTHROPIC_API_KEY: Anthropic API key
    - OPENAI_API_KEY: OpenAI API key
    """
    for env_var, path in ENV_VAR_MAPPING.items():
        value = os.environ.get(env_var)
        if value is not None:
            _set_nested(config, path, _parse_value(value))

    if os.environ.get("ANTHROPIC_API_KEY"):
        config.setdefault("api_keys", {})["anthropic"] = os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("OPENAI_API_KEY"):
        config.setdefault("api_keys", {})["openai"] = os.environ["OPENAI_API_KEY"]

    return config


def _set_nested(config: dict, path: tuple, value: Any) -> None:
    """Set a nested value in config dict."""
    current = config
    for key in path[:-1]:
        current = current.setdefault(key, {})
    current[path[-1]] = value


def _parse_value(value: str) -> Any:
    """Parse string value to appropriate type."""
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    if value.isdigit():
        return int(value)
    try:
        return float(value)
    except ValueError:
        return value


def find_config_path(path: str | None = None) -> Path | None:
    """Find configuration path from explicit path or common locations."""
    if path is not None:
        config_path = Path(path)
        return config_path if config_path.exists() else None

    script_dir = Path(__file__).parent.parent.parent
    search_paths = [
        Path.cwd() / "config.yaml",
        script_dir / "config.yaml",
        Path.home() / "echo-ai" / "config.yaml",
    ]
    for config_path in search_paths:
        if config_path.exists():
            return config_path
    return None


def load_config(path: str | None = None) -> dict:
    """Load configuration from YAML file or return empty config.

    Environment variables can override config file values.
    See apply_env_overrides() for supported variables.
    """
    config_path = find_config_path(path)
    if config_path:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    return apply_env_overrides(config)


def get_limits_config(config: dict) -> dict:
    """Get limits configuration with sensible defaults."""
    limits = config.get("limits", {})
    return {
        "max_web_fetch_chars": limits.get("max_web_fetch_chars", 15000),
        "max_search_result_snippet": limits.get("max_search_result_snippet", 500),
        "min_fetch_content_chars": limits.get("min_fetch_content_chars", 50),
        "search_result_truncate": limits.get("search_result_truncate", 1000),
        "max_glob_results": limits.get("max_glob_results", 100),
        "max_grep_results": limits.get("max_grep_results", 100),
        "max_search_query_length": limits.get("max_search_query_length", 500),
        "max_file_read_size": limits.get("max_file_read_size", 10 * 1024 * 1024),
        "max_file_write_size": limits.get("max_file_write_size", 5 * 1024 * 1024),
        "max_sessions_per_page": limits.get("max_sessions_per_page", 50),
        "max_sessions_total": limits.get("max_sessions_total", 1000),
    }


def get_safety_config(config: dict) -> SafetyConfig:
    """Create safety configuration from the overall config dictionary."""
    safety = config.get("safety", {})
    tools_config = config.get("tools", {})

    validator = SecurityValidator(
        SafetyConfig(
            workspace=safety.get("workspace", "."),
        )
    )

    def approval_callback(tool: str, details: str) -> bool:
        """Request user approval for potentially dangerous operations."""
        warning_msg = ""

        if tool == "bash":
            destructive = validator.check_destructive_keywords(details)
            if destructive:
                warning_msg = (
                    " [red]WARNING DESTRUCTIVE keywords detected: "
                    + ", ".join(destructive)
                    + "[/red]"
                )

        if tool == "write_file":
            try:
                path_str = details.replace("write: ", "")
                file_path = Path(path_str)
                if file_path.exists():
                    warning_msg = " [red]WARNING File exists - will overwrite![/red]"
            except OSError:
                pass

        if tool == "read_file":
            try:
                path_str = details.replace("read: ", "")
                file_path = Path(path_str)
                if file_path.exists():
                    size = file_path.stat().st_size
                    threshold = safety.get("read_size_threshold", 102400)
                    if size > threshold:
                        warning_msg = (
                            f" [yellow]WARNING Large file ({size // 1024} KB)[/yellow]"
                        )
            except OSError:
                pass

        if tool == "memory":
            warning_msg = (
                " [red]WARNING This will permanently delete stored memories![/red]"
            )

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
        require_approval_for=safety.get(
            "require_approval_for", ["bash", "write_file", "memory"]
        ),
        approval_callback=approval_callback,
        audit_log_path=safety.get("audit_log_path"),
        read_requires_approval=safety.get("read_requires_approval", False),
        read_size_threshold=safety.get("read_size_threshold", 102400),
    )


def get_tools(config: dict, safety_config: SafetyConfig) -> list:
    """Instantiate and return enabled tools based on configuration."""
    tools = []
    enabled = config.get("tools", {}).get("enabled", [])

    for tool_name in enabled:
        tool_class = TOOL_REGISTRY.get(tool_name)
        if tool_class is None:
            continue

        # Assuming ConfigDict is imported or defined elsewhere if needed,
        # but based on the instruction, it's inserted as is.
        # This line's indentation is corrected to be inside the loop.
        # model_config = ConfigDict(arbitrary_types_allowed=True).get(tool_name, {})
        config_defaults = TOOL_CONFIG_KEYS.get(tool_name, {})

        tool_config = config.get("tools", {}).get(tool_name, {})
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
