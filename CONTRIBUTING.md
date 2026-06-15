# Contributing to Echo AI

Thank you for your interest in contributing!

## Development Setup

```bash
# Clone the repository
git clone https://github.com/barontek/echo-ai.git
cd echo-ai

# NixOS
nix develop    # Enter dev shell

# Non-NixOS
uv sync                          # Install dependencies
PYTHONPATH=src .venv/bin/agent   # Run the CLI

# Run tests
make test

# Run linter
make lint
```

## Code Style

We use:
- **ruff** for linting and formatting
- **type hints** for all function signatures
- **docstrings** for public APIs (Google style)

```bash
# Run all checks
make lint
make test

# Auto-fix linting issues
ruff check --fix src/
```

## Project Structure

```
echo-ai/
├── src/agentframework/     # Core agent framework
│   ├── core/              # Agent loop, tool runtime, callbacks
│   ├── providers/         # Ollama, OpenAI, Anthropic
│   ├── tools/             # Tool implementations
│   │   └── search_providers/  # Brave, DuckDuckGo, Tavily
│   ├── web_api.py         # FastAPI endpoints
│   ├── session.py         # Session management
│   ├── safety.py          # Security validation
│   └── ...
├── frontend/               # React + Vite + TypeScript
├── tests/                  # Test suite
├── config.yaml             # Configuration
├── flake.nix               # Nix flake
└── docs/                   # Documentation
```

## Adding a New Tool

1. Create a new file in `src/agentframework/tools/`

```python
"""My custom tool."""

import logging
from typing import Any

from pydantic import BaseModel

from . import Tool, ToolResult

logger = logging.getLogger(__name__)

class MyToolParams(BaseModel):
    query: str

class MyTool(Tool):
    """Description of what this tool does."""

    parameters_model = MyToolParams

    def __init__(self, provider=None, safety_config=None, limits=None):
        super().__init__(
            name="my_tool",
            description="Fetches information based on a query.",
        )
        self._safety_config = safety_config
        self._limits = limits

    async def execute(self, query: str, **kwargs) -> ToolResult:
        try:
            result = await do_something(query)
            return ToolResult(content=str(result))
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return ToolResult(error=str(e))
```

2. Register it in `src/agentframework/tools/__init__.py` (`TOOL_REGISTRY` dict)

3. Add tests in `tests/test_my_tool.py`

4. Update tools configuration in `config.yaml` (add to `tools.enabled`)

## Adding a New LLM Provider

1. Create a new file in `src/agentframework/providers/`

```python
"""My custom provider."""

from typing import Any

from . import LLMProvider, LLMResponse, LLMToolCall


class MyProvider(LLMProvider):
    """Description of the provider."""

    def __init__(self, model: str, api_key: str | None = None, **kwargs):
        super().__init__(model, api_key, **kwargs)
        # Initialize your client here

    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
    ) -> LLMResponse:
        # Implement the chat method
        ...

    async def chat_streaming(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        on_chunk: Any | None = None,
    ) -> LLMResponse:
        # Implement streaming if supported
        ...

    async def list_models(self) -> list[str]:
        # Return available models
        ...
```

2. Register in `src/agentframework/providers/__init__.py`

3. Update `src/agentframework/agent.py` to recognize the new provider

## Commit Messages

Use clear, descriptive commit messages:

```
feat: add web_search tool for internet queries
fix: resolve session merge for tool calls
docs: add contribution guidelines
refactor: extract common LLM call logic
test: add integration tests for WebSocket
```

## Pull Request Process

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Run tests: `make test lint`
5. Commit with a clear message
6. Push to your fork
7. Open a Pull Request

## Questions?

Open an issue or reach out to the maintainers.
