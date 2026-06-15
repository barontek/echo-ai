# Development

## Setup

```bash
# NixOS
nix develop    # Enter dev shell (auto-runs uv sync)

# Non-NixOS
uv sync
```

## Commands

```bash
make test      # Run pytest with coverage
make verify    # Quality gate: pytest → ruff → pyright
make lint      # ruff check
make typecheck # pyright src/
```

## Architecture

```
src/agentframework/
├── core/               # Agent loop, tool runtime, callbacks
├── providers/          # Ollama, Anthropic, OpenAI
├── tools/              # bash, file, web, deep_search, ...
│   └── search_providers/  # Brave, DuckDuckGo, Tavily
├── conversation.py     # Message formatting + token trimming
├── session.py          # SQLite session manager
├── web_api.py          # FastAPI backend
└── safety.py           # Security validation
```
