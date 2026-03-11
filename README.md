# Echo AI

A standalone AI agent framework built from scratch, similar to OpenCode but simpler.

## Features

- **Multiple LLM Providers**: Anthropic, OpenAI, Ollama
- **Tool Calling**: bash, read/write files, list directories, glob, grep, web fetch, web search, git, memory, notes
- **Safety**: Workspace confinement, command allowlisting, dangerous pattern blocking
- **Sessions**: Save/load conversations, undo file changes
- **Chat Mode**: Interactive continuous conversation with command history

## Quick Start

```bash
# Clone and setup
git clone https://github.com/barontek/echo-ai.git
cd echo-ai
make install

# Run in chat mode (continuous conversation)
./chat

# Or run single command
./agent "your task"
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

## Configuration

Edit `config.yaml`:

```yaml
model:
  provider: ollama      # anthropic, openai, or ollama
  name: qwen3:4b-instruct  # default model
  base_url: http://localhost:11434
  temperature: 0.1

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
```

### Recommended Models

| Model | Description |
|-------|-------------|
| `qwen3:4b-instruct` | Best for following instructions (default) |
| `qwen2.5-coder:3b` | Best for strict tool calling and coding |
| `qwen3:4b` | General purpose with strong reasoning |
| `llama3.2` | Meta's lightweight model |
| `phi3.5` | Microsoft's highly stable model |

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

## Safety

- Workspace confinement (files outside workspace blocked)
- Command allowlisting
- Dangerous pattern blocking (rm -rf, curl|sh, etc.)
- Approval prompts for sensitive operations
- Network access controls

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

## Changelog

- See [`CHANGELOG.md`](./CHANGELOG.md) for release notes and the unreleased change log.

## Benchmarks

- Basic benchmark harness: `python scripts/benchmarks/basic_benchmark.py --iterations 50`

## Development

```bash
# Install in development mode
pip install -e .

# Run tests (if available)
pytest
```

## Architecture

```
src/agentframework/
├── agent.py          # Main agent logic
├── chat.py          # Interactive chat interface
├── cli.py           # CLI for single commands
├── providers/      # LLM provider implementations
│   └── ollama.py    # Ollama provider
├── safety.py        # Security validation
├── session.py      # Chat session management
└── tools/          # Tool implementations
    ├── bash.py
    ├── file.py
    ├── web.py
    ├── git.py
    ├── search.py
    ├── memory.py
    └── notes.py
```
