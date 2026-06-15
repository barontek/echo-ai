# Echo AI

A standalone AI agent framework built from scratch, similar to OpenCode but simpler.

## Features

- **Multiple LLM Providers**: Anthropic, OpenAI, Ollama.
- **Tool Calling**: bash, read/write files, list directories, glob, grep, web fetch, web search, git, memory, notes.
- **Modern Web UI**: Responsive interface with streaming metrics, collapsible thought process, sources dropdown, and mobile support.
- **Safety**: Workspace confinement, command allowlisting, and dangerous pattern blocking.
- **Sessions**: Save/load conversations, session renaming, and automatic titling.
- **Chat Mode**: Interactive continuous conversation with command history and WebSocket streaming.

## Quick Start

```bash
# NixOS (primary)
nix develop      # Enter dev shell
make test        # Run tests
nix build        # Build fullstack binary
nix run .        # Run web server

# Non-NixOS
uv sync
PYTHONPATH=src uv run python -m agentframework.chat
```

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
