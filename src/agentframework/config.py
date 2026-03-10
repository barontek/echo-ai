"""Configuration management for the agent framework."""

from pathlib import Path

import yaml
from rich.console import Console
from rich.prompt import Prompt

from .safety import SafetyConfig, SecurityValidator
from .tools import TOOL_CONFIG_KEYS, TOOL_REGISTRY

console = Console(color_system="256")


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
    """Load configuration from YAML file or return empty config."""
    config_path = find_config_path(path)
    if config_path:
        with open(config_path) as f:
            return yaml.safe_load(f)
    return {}


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
                    " [red]⚠️ DESTRUCTIVE keywords detected: "
                    + ", ".join(destructive)
                    + "[/red]"
                )

        if tool == "write_file":
            try:
                path_str = details.replace("write: ", "")
                file_path = Path(path_str)
                if file_path.exists():
                    warning_msg = " [red]⚠️ File exists - will overwrite![/red]"
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
                            f" [yellow]⚠️ Large file ({size // 1024} KB)[/yellow]"
                        )
            except OSError:
                pass

        if tool == "memory":
            warning_msg = " [red]⚠️ This will permanently delete stored memories![/red]"

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
        require_approval_for=safety.get("require_approval_for", ["bash", "write_file", "memory"]),
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

        max_history_messages: int = 50  # Limit before sqlite summarization
        # Assuming ConfigDict is imported or defined elsewhere if needed,
        # but based on the instruction, it's inserted as is.
        # This line's indentation is corrected to be inside the loop.
        model_config = {} # Placeholder for ConfigDict if not defined
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
