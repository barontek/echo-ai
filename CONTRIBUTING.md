# Contributing to Echo AI

Thank you for your interest in contributing!

## Development Setup

```bash
# Clone the repository
git clone https://github.com/barontek/echo-ai.git
cd echo-ai

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or: .venv\Scripts\activate  # Windows

# Install dependencies
pip install -e .

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
│   ├── agent.py            # Main Agent class
│   ├── web_api.py         # FastAPI endpoints
│   ├── session.py         # Session management
│   ├── safety.py          # Security validation
│   ├── providers/         # LLM providers
│   │   └── ollama.py      # Ollama implementation
│   └── tools/             # Agent tools
│       ├── bash.py
│       ├── file.py
│       ├── web.py
│       └── search.py
├── static/                 # Frontend
│   ├── js/               # JavaScript modules
│   └── css/              # Stylesheets
├── tests/                 # Test suite
├── config.yaml           # Configuration
└── docs/                # Documentation
```

## Adding a New Tool

1. Create a new file in `src/agentframework/tools/`

```python
"""My custom tool."""

import logging
from typing import Any

from ..safety import SafetyValidator
from .base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class MyTool(BaseTool):
    """Description of what this tool does."""

    def __init__(self, validator: SafetyValidator):
        super().__init__("my_tool", validator)

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given arguments."""
        try:
            # Your implementation here
            result = do_something(**kwargs)
            return ToolResult(success=True, output=result)
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return ToolResult(success=False, error=str(e))
```

2. Register it in `src/agentframework/tools/__init__.py`

```python
from .my_tool import MyTool

__all__ = ["MyTool", ...]
```

3. Add tests in `tests/test_my_tool.py`

4. Update tools configuration in `config.yaml`

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
