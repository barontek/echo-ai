"""Bootstrap utilities for initializing the agent environment."""

import atexit
import os
import sys
from pathlib import Path

from rich.console import Console

from .core import Agent, AgentConfig, create_agent
from .config import (
    DEFAULT_SESSION_DIR,
    find_config_path,
    get_safety_config,
    get_tools,
    load_config,
    validate_config,
    log_config_validation,
)
from .db_crypto import is_first_run, prompt_create_password, prompt_for_fernet
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

    validation_result = validate_config(config)
    log_config_validation(validation_result)

    agent_cfg = config.get("agent", {})
    if not isinstance(agent_cfg, dict):
        agent_cfg = {}
    model_cfg = config.get("model", {})
    if not isinstance(model_cfg, dict):
        model_cfg = {}

    session_enabled = (
        True
        if force_session_enabled
        else agent_cfg.get("session_enabled", True)
    )

    agent_config = AgentConfig(
        provider=model_cfg.get("provider", "ollama"),
        model=model_cfg.get("name", ""),
        temperature=model_cfg.get("temperature", 0.3),
        timeout=model_cfg.get("timeout", 60),
        max_iterations=agent_cfg.get("max_iterations", 50),
        system_prompt=agent_cfg.get("system_prompt", ""),
        tools=get_tools(config, safety_config),
        base_url=model_cfg.get("base_url"),
        session_enabled=session_enabled,
        session_dir=agent_cfg.get("session_dir", DEFAULT_SESSION_DIR),
        num_ctx=model_cfg.get("num_ctx"),
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

    # Resolve the Fernet encryption key once per process start, before
    # SessionManager is constructed (which would otherwise prompt for each
    # instance).  The salt file lives alongside the session database.
    session_dir_path = Path(agent_cfg.get("session_dir", DEFAULT_SESSION_DIR))
    salt_path = session_dir_path / ".db_salt"
    db_path = session_dir_path / "agent_sessions.db"

    if is_first_run(salt_path, db_path):
        fernet = prompt_create_password(salt_path)
    else:
        fernet = prompt_for_fernet(salt_path)

    try:
        agent = create_agent(agent_config, api_key, fernet=fernet)
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

    # Initialize OpenTelemetry if enabled
    obs_config = config.get("observability", {})
    if obs_config.get("otel_enabled", False):
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import (
                BatchSpanProcessor,
                ConsoleSpanExporter,
            )
            from .otel import OpenTelemetryCallback

            # Setup provider if not already setup
            if not isinstance(trace.get_tracer_provider(), TracerProvider):
                resource = Resource.create(
                    {"service.name": obs_config.get("service_name", "echo-ai")}
                )
                provider = TracerProvider(resource=resource)

                if obs_config.get("console_export", False):
                    processor = BatchSpanProcessor(ConsoleSpanExporter())
                    provider.add_span_processor(processor)

                otlp_endpoint = obs_config.get("otlp_endpoint")
                if otlp_endpoint:
                    try:
                        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                            OTLPSpanExporter,
                        )

                        otlp_processor = BatchSpanProcessor(
                            OTLPSpanExporter(
                                endpoint=otlp_endpoint, insecure=True, timeout=1
                            )
                        )
                        provider.add_span_processor(otlp_processor)
                        console.print(
                            f"[dim]Observability: OTLP exporter enabled ({otlp_endpoint})[/dim]"
                        )
                    except Exception as e:
                        console.print(
                            f"[yellow]Warning: Could not initialize OTLP exporter: {e}[/yellow]"
                        )

                trace.set_tracer_provider(provider)
                atexit.register(provider.shutdown)

            agent.add_callback(OpenTelemetryCallback())
            console.print("[dim]Observability: OpenTelemetry enabled[/dim]")
        except ImportError as e:
            console.print(
                f"[yellow]Warning: Could not initialize OpenTelemetry: {e}[/yellow]"
            )

    return agent
