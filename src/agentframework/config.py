"""Configuration management for the agent framework."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator
from rich.console import Console

from .safety import SafetyConfig, SecurityValidator
from .tools import TOOL_CONFIG_KEYS, TOOL_REGISTRY

DEFAULT_SESSION_DIR = str(Path.home() / ".echo-ai" / "sessions")
DEFAULT_CONFIG_PATH = str(Path.home() / ".echo-ai" / "config.yaml")


class ModelConfig(BaseModel):
    """Model configuration schema."""

    provider: str = Field(
        default="ollama", description="LLM provider: anthropic, openai, or ollama"
    )
    name: str = Field(default="qwen3:4b-instruct", description="Model name")
    base_url: str | None = Field(default=None, description="Base URL for Ollama")
    temperature: float = Field(
        default=0.3, ge=0.0, le=2.0, description="Model temperature"
    )
    timeout: int = Field(
        default=60, ge=10, le=600, description="HTTP timeout in seconds"
    )
    num_ctx: int | None = Field(
        default=None, ge=256, le=262144, description="Ollama context window size"
    )


class ToolsBashConfig(BaseModel):
    """Bash tool configuration schema."""

    allowed_commands: list[str] = Field(default_factory=lambda: ["*"])
    timeout: int = Field(default=60, ge=1, le=300)


class ToolsConfig(BaseModel):
    """Tools configuration schema."""

    enabled: list[str] = Field(default_factory=list)
    bash: ToolsBashConfig = Field(default_factory=ToolsBashConfig)


class SafetyConfigSchema(BaseModel):
    """Safety configuration schema."""

    workspace: str = Field(default=".", description="Allowed workspace directory")
    allow_network: bool = Field(default=False)
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_commands: list[str] = Field(default_factory=list)
    max_file_size: int = Field(default=10 * 1024 * 1024, ge=0)
    max_execution_time: int = Field(default=60, ge=1, le=300)
    require_approval_for: list[str] = Field(default_factory=list)
    audit_log_path: str | None = Field(default=None)
    read_requires_approval: bool = Field(default=False)
    read_size_threshold: int = Field(default=102400, ge=0)


class AgentConfigSchema(BaseModel):
    """Agent configuration schema."""

    max_iterations: int = Field(default=50, ge=1, le=1000)
    max_context_messages: int = Field(default=50, ge=0)
    max_context_chars: int = Field(default=100000, ge=0)
    token_reserve_ratio: float = Field(default=0.7, ge=0.1, le=0.9)
    session_dir: str = Field(default=DEFAULT_SESSION_DIR)
    session_enabled: bool = Field(default=True)


class LimitsConfig(BaseModel):
    """Limits configuration schema."""

    max_web_fetch_chars: int = Field(default=15000, ge=0)
    max_search_result_snippet: int = Field(default=500, ge=0)
    min_fetch_content_chars: int = Field(default=50, ge=0)
    search_result_truncate: int = Field(default=1000, ge=0)
    max_glob_results: int = Field(default=100, ge=0)
    max_grep_results: int = Field(default=100, ge=0)
    max_search_query_length: int = Field(default=500, ge=0)
    max_file_read_size: int = Field(default=10 * 1024 * 1024, ge=0)
    max_file_write_size: int = Field(default=5 * 1024 * 1024, ge=0)
    max_sessions_per_page: int = Field(default=50, ge=1)
    max_sessions_total: int = Field(default=1000, ge=1)

    @field_validator("max_file_read_size", "max_file_write_size")
    @classmethod
    def validate_file_size(cls, v: int) -> int:
        if v > 100 * 1024 * 1024:
            raise ValueError("File size cannot exceed 100MB")
        return v


class ObservabilityConfig(BaseModel):
    """Observability configuration schema."""

    otel_enabled: bool = Field(default=False)
    console_export: bool = Field(default=False)
    otlp_endpoint: str = Field(default="http://localhost:4317")
    service_name: str = Field(default="echo-ai")


class WebConfig(BaseModel):
    """Web server configuration schema."""

    cors_origins: list[str] = Field(default_factory=list)
    cors_allow_credentials: bool = Field(default=True)
    cors_allow_methods: list[str] = Field(default_factory=lambda: ["*"])
    cors_allow_headers: list[str] = Field(default_factory=lambda: ["*"])
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080, ge=1, le=65535)

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, v: list[str]) -> list[str]:
        for origin in v:
            if not (
                origin.startswith("http://")
                or origin.startswith("https://")
                or origin == "*"
            ):
                raise ValueError(f"Invalid CORS origin: {origin}")
        return v


class AppConfig(BaseModel):
    """Main application configuration schema."""

    model: ModelConfig = Field(default_factory=ModelConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    safety: SafetyConfigSchema = Field(default_factory=SafetyConfigSchema)
    agent: AgentConfigSchema = Field(default_factory=AgentConfigSchema)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    web: WebConfig = Field(default_factory=WebConfig)


def validate_config_schema(config: dict) -> "ConfigValidationResult":
    """Validate configuration using Pydantic schema.

    Returns:
        ConfigValidationResult with any errors or warnings.
    """
    errors: list[ValidationError] = []
    warnings: list[str] = []

    try:
        AppConfig(**config)
    except Exception as e:
        errors.append(ValidationError(field="root", message=str(e)))

    result = ConfigValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )

    return result


console = Console(color_system="256")
logger = logging.getLogger(__name__)

VALID_PROVIDERS = {"ollama", "openai", "anthropic"}
VALID_TOOLS = set(TOOL_REGISTRY.keys())


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
        Path(DEFAULT_CONFIG_PATH),
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

    def _tool_warning(tool: str, details: str) -> str:
        """Get warning message for tool approval. Pure function, testable."""
        warning_msg = ""
        if tool == "bash":
            destructive = validator.check_destructive_keywords(details)
            if destructive:
                warning_msg = (
                    " [red]WARNING DESTRUCTIVE keywords detected: "
                    + ", ".join(destructive)
                    + "[/red]"
                )
        elif tool == "write_file":
            try:
                path_str = details.replace("write: ", "")
                file_path = Path(path_str)
                if file_path.exists():
                    warning_msg = " [red]WARNING File exists - will overwrite![/red]"
            except OSError:
                pass
        elif tool == "read_file":
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
        elif tool == "memory":
            warning_msg = (
                " [red]WARNING This will permanently delete stored memories![/red]"
            )
        return warning_msg

    approval_timeout = safety.get("approval_timeout", 30)

    def approval_callback(tool: str, details: str) -> bool:
        """Request user approval for potentially dangerous operations.

        Uses select.select() for timeout on stdin instead of threading.
        """
        import select
        import sys

        warning_msg = _tool_warning(tool, details)
        console.print(
            f"[yellow]Approval required for {tool}:[/yellow] {details}{warning_msg}"
        )

        print("Allow? (y/N): ", end="", flush=True)
        ready, _, _ = select.select([sys.stdin], [], [], approval_timeout)
        if not ready:
            console.print(
                f"[red]Approval timed out after {approval_timeout}s. Denying.[/red]"
            )
            return False

        response = sys.stdin.readline().strip().lower()
        return response in ("y", "yes")

    return SafetyConfig(
        workspace=safety.get("workspace", "."),
        allowed_commands=tools_config.get("bash", {}).get("allowed_commands", ["*"]),
        blocked_commands=safety.get("blocked_commands", []),
        allow_network=safety.get("allow_network", False),
        enable_domain_allowlist=safety.get("enable_domain_allowlist", False),
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


@dataclass
class ValidationError:
    """A configuration validation error."""

    field: str
    message: str


@dataclass
class ConfigValidationResult:
    """Result of configuration validation."""

    valid: bool
    errors: list[ValidationError]
    warnings: list[str]

    def __bool__(self) -> bool:
        return self.valid


def validate_config(config: dict) -> ConfigValidationResult:
    """Validate configuration and return any errors or warnings.

    Checks:
    - Required fields present
    - Valid provider names
    - Valid tool names
    - Workspace directory exists or can be created
    - Temperature within valid range
    - Pydantic schema validation
    """
    errors: list[ValidationError] = []
    warnings: list[str] = []

    schema_result = validate_config_schema(config)
    if not schema_result.valid:
        return schema_result

    model_config = config.get("model", {})
    provider = model_config.get("provider", "ollama")
    if provider not in VALID_PROVIDERS:
        errors.append(
            ValidationError(
                field="model.provider",
                message=f"Invalid provider '{provider}'. Must be one of: {', '.join(VALID_PROVIDERS)}",
            )
        )

    temperature = model_config.get("temperature", 0.3)
    if not isinstance(temperature, (int, float)):
        errors.append(
            ValidationError(
                field="model.temperature",
                message=f"Temperature must be a number, got {type(temperature).__name__}",
            )
        )
    elif temperature < 0 or temperature > 2:
        warnings.append(f"Temperature {temperature} is outside recommended range (0-2)")

    tools_config = config.get("tools", {})
    enabled_tools = tools_config.get("enabled", [])

    for tool_name in enabled_tools:
        if tool_name not in VALID_TOOLS:
            warnings.append(f"Unknown tool '{tool_name}' - skipping")

    safety_config = config.get("safety", {})
    workspace = safety_config.get("workspace", ".")

    if workspace != ".":
        workspace_path = Path(workspace)
        if not workspace_path.exists():
            warnings.append(
                f"Workspace directory '{workspace}' does not exist - will be created on first use"
            )
        elif not workspace_path.is_dir():
            errors.append(
                ValidationError(
                    field="safety.workspace",
                    message=f"Workspace path '{workspace}' exists but is not a directory",
                )
            )

    max_iterations = config.get("agent", {}).get("max_iterations", 50)
    if max_iterations < 1:
        errors.append(
            ValidationError(
                field="agent.max_iterations",
                message=f"max_iterations must be at least 1, got {max_iterations}",
            )
        )
    elif max_iterations > 1000:
        warnings.append(
            f"max_iterations is very high ({max_iterations}) - may cause long-running agents"
        )

    return ConfigValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def log_config_validation(result: ConfigValidationResult) -> None:
    """Log validation results."""
    if result.warnings:
        for warning in result.warnings:
            logger.warning(f"Config warning: {warning}")

    if not result.valid:
        for error in result.errors:
            logger.error(f"Config error [{error.field}]: {error.message}")
