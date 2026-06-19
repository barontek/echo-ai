# Echo AI

> **Disclaimer**: This project is entirely vibecoded. Don't use for anything important.

A standalone AI agent framework built from scratch.

## Features

- **Multiple LLM Providers**: Anthropic, OpenAI, Ollama
- **Tool Calling**: bash, file I/O, glob, grep, web search, web fetch, deep search (LLM-filtered), git, memory, notes, humanizer
- **Modern Web UI**: React + Vite frontend with WebSocket streaming, markdown rendering, tool call display, dark/light theme
- **Safety**: Workspace confinement, command allowlisting, path traversal prevention, and dangerous pattern blocking
- **Sessions**: Save/load conversations, session renaming, and automatic titling
- **Chat Mode**: Interactive continuous conversation with command history and WebSocket streaming
- **Observability**: Prometheus metrics export, correlation IDs for logging, OpenTelemetry support

## Quick Start

```bash
# NixOS (primary)
nix develop    # Enter dev shell (auto-runs uv sync)
make test      # Run tests
nix build      # Build fullstack binary
nix run .      # Run the web server

# Non-NixOS
uv sync                          # Install Python deps
PYTHONPATH=src .venv/bin/agent   # Run CLI agent
```

## Environment Variables

Override config.yaml settings with environment variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `ECHO_PROVIDER` | LLM provider | `ollama`, `openai`, `anthropic` |
| `ECHO_MODEL` | Model name | `qwen3:4b-instruct` |
| `ECHO_BASE_URL` | Ollama base URL | `http://localhost:11434` |
| `ECHO_TEMPERATURE` | Model temperature | `0.1` |
| `ECHO_API_KEY` | Bearer token for API authentication | `my-secret-token` |
| `ECHO_WORKSPACE` | Workspace directory | `/home/user/workspace` |
| `ECHO_SESSION_DIR` | Session storage directory | `~/.echo-ai/sessions` |
| `ECHO_MAX_ITERATIONS` | Max agent iterations | `50` |
| `ECHO_ALLOW_NETWORK` | Enable network access | `true`, `false` |
| `ANTHROPIC_API_KEY` | Anthropic API key | `sk-ant-...` |
| `OPENAI_API_KEY` | OpenAI API key | `sk-...` |

Example:
```bash
export ECHO_PROVIDER=openai
export ECHO_MODEL=gpt-4
export OPENAI_API_KEY=sk-...
```

## Configuration

Edit `config.yaml`:

```yaml
model:
  provider: ollama
  name: gemma4:e4b
  base_url: http://localhost:11434
  temperature: 0.1
  num_ctx: 32768

tools:
  enabled:
    - bash
    - read_file
    - write_file
    - list_dir
    - glob
    - grep
    - git
    - web_fetch
    - web_search
    - memory
    - notes
    - humanizer
    - deep_search
```

### Recommended Models

| Model | Description |
|-------|-------------|
| `gemma4:e4b` | Best for following instructions and tool calling (default) |
| `qwen3:4b-instruct` | Strong instruction following |
| `qwen3:4b` | General purpose with reasoning |
| `llama3.2` | Meta's lightweight model |

## API Endpoints

The web server exposes REST and WebSocket endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Basic health check |
| `/health/detailed` | GET | Detailed health with component status |
| `/api/chat` | POST | Synchronous chat |
| `/api/stream` | GET | Streaming chat (SSE) |
| `/api/sessions` | GET | List sessions |
| `/api/sessions` | POST | Create session |
| `/api/sessions/{id}` | GET | Load session |
| `/api/models` | GET | List available models |
| `/ws/chat` | WS | WebSocket chat |

### Health Checks

```bash
# Basic health
curl http://localhost:8080/health

# Detailed health
curl http://localhost:8080/health/detailed
```

## Commands

Chat mode:
- `/new` - Start new chat
- `/save <name>` - Save chat
- `/load <name>` - Load saved chat
- `/chats` - List saved chats
- `/model <name>` - Switch to a different model
- `/undo` - Undo last file change
- `/redo` - Redo last undone change
- `/clear` - Clear screen
- `/help` - Show help
- `/exit` - Exit

## Chat Features

- **Command History**: Use up/down arrows to navigate previous commands
- **Tool Usage**: Shows which tools were used after each response (e.g., `Used: web_search, list_dir`)
- **Markdown Support**: Responses support markdown formatting
- **Thinking Process**: View the agent's reasoning with collapsible `<think>` blocks

## Safety

- **Workspace confinement**: Files outside workspace blocked
- **Command allowlisting**: Only pre-approved commands allowed
- **Dangerous pattern blocking**: `rm -rf`, `curl|sh`, fork bombs, etc.
- **Sensitive file protection**: `.env`, `.key`, `.pem`, `.aws` files blocked
- **Approval prompts**: Confirm sensitive operations before execution
- **Network access controls**: Configurable domain allowlisting
- **Rate limiting**: 60 requests/minute per IP

## Project Status

- **Maturity**: Beta-quality, fast-moving standalone agent framework
- **Supported providers**: Ollama, Anthropic, OpenAI
- **Known limitations**:
  - Terminal/chat runtime is still being modularized
  - Some advanced observability and CI quality gates are still evolving
- **Near-term roadmap**:
  - Unified runtime/config bootstrap across entrypoints
  - Stronger integration scenarios and contributor verify workflow
  - Improved structured debug telemetry

## Compatibility Policy

- **Python**: 3.11+ is required at runtime.
- **Providers**:
  - `ollama` works without cloud API keys (requires local Ollama server).
  - `anthropic` requires `ANTHROPIC_API_KEY`.
  - `openai` requires `OPENAI_API_KEY`.
- **Tooling**: `make verify` is the baseline quality gate for local and CI checks.

## Troubleshooting

- **Error: Python 3.11+ is required**
  - Use `python3.11` (or newer) and recreate your environment.
- **Provider key errors for Anthropic/OpenAI**
  - Export the required key (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) or switch to `ollama`.
- **Ollama connection failures**
  - Ensure Ollama is running and `model.base_url` in `config.yaml` is correct.
- **Need full diagnostics**
  - Run with `--debug` for detailed logs, or `--debug-json` for machine-readable logs.

## Requirements

- Python 3.11+
- Ollama (for local models) or API keys for Anthropic/OpenAI

## Benchmarks

```bash
# Run basic benchmark
python scripts/benchmarks/basic_benchmark.py --iterations 50
```

## Development

```bash
# Enter dev environment
nix develop

# Run all tests
make test

# Run linting and type checking
make verify

# Run security checks
make security
```

## Architecture

```
src/agentframework/
├── core/               # Core agent loop, tool runtime, callbacks
│   ├── agent.py
│   ├── tool_runtime.py
│   └── callback_manager.py
├── providers/          # LLM provider implementations
│   ├── ollama.py       # Default provider
│   ├── anthropic.py
│   └── openai.py
├── tools/              # Tool implementations
│   ├── web.py          # WebSearchTool, WebFetchTool
│   ├── deep_search.py  # Multi-stage LLM-filtered search
│   ├── search_providers/  # Brave, DuckDuckGo, Tavily
│   ├── bash.py
│   ├── file.py
│   ├── git.py
│   ├── memory.py
│   ├── notes.py
│   └── humanizer.py
├── conversation.py     # Message formatting + token trimming
├── config.py           # Configuration loading
├── session.py          # SQLite session manager
├── memory.py           # Memory persistence
├── safety.py           # Security validation
├── web_api.py          # FastAPI backend
├── web_utils.py        # Web utilities
└── constants.py        # Shared constants

frontend/            # React + Vite + TypeScript frontend
├── src/
│   ├── components/ # React UI components
│   ├── context/   # Chat state management
│   └── api/       # API client
```
