# Coding Conventions

**Analysis Date:** 2026-03-08

## Naming Patterns

**Files:**
- Python snake_case: `agent.py`, `session_manager.py`, `tool_runtime.py`
- Test files: `test_agent.py`, `test_tools.py`, `test_api_tool.py`

**Classes:**
- PascalCase: `Agent`, `ToolResult`, `SessionManager`, `ReadFileTool`
- Base classes end with base class name: `Tool` (base), `FileSystemTool` (base for file tools)
- Test classes: `TestAgent`, `TestTool`, `TestSanitizeJson`

**Functions/Methods:**
- snake_case: `create_agent()`, `execute_tool_calls()`, `_sanitize_json()`
- Private methods: prefix with underscore: `_execute_tool_calls()`, `_prepare_messages()`
- Async functions: always `async def`

**Variables:**
- snake_case: `llm_provider`, `current_session`, `tool_map`
- Constants: UPPER_SNAKE_CASE for true constants
- Type hints: used extensively throughout codebase

**Types:**
- Pydantic models: `AgentConfig`, `ReadFileParams`, `WriteFileParams`
- Dataclasses: `Session`, `ToolResult`
- Type aliases: defined inline or with `TypeAlias`

## Code Style

**Formatting:**
- No explicit formatter configured (no ruff formatter, no black)
- 4-space indentation
- Maximum line length: not enforced but typically under 100 chars

**Linting:**
- ruff is configured in dev dependencies but no `.ruff.toml` found
- Manual lint with `ruff check`
- Example linting in `src/agentframework/tools/__init__.py`:
  ```python
  # ruff: noqa: E402
  # Imports must be after class definitions to avoid circular import issues
  ```

**Type Checking:**
- pyright configured (`pyrightconfig.json` present)
- Python 3.11+ required (`requires-python = ">=3.11"` in `pyproject.toml`)
- Type hints used extensively: `list[str]`, `dict[str, Any]`, `Callable[[str], None]`

## Import Organization

**Order:**
1. Standard library: `import asyncio`, `from pathlib import Path`
2. Third-party: `from pydantic import BaseModel`, `import pytest`
3. Local relative: `from .tools import Tool`, `from ..safety import SafetyConfig`

**Path Aliases:**
- No path aliases configured
- Relative imports from package root: `from src.agentframework.agent import Agent`

**Example from `src/agentframework/agent.py`:**
```python
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, overload
from uuid import uuid4

from .providers import LLMProvider, get_provider, LLMToolCall
from .tools import Tool, ToolResult
from .session import SessionManager, ChangeTracker
from .conversation import Message, apply_context_window, ...
```

## Error Handling

**Patterns:**
- Tools return `ToolResult` with either `content` or `error`:
  ```python
  from src.agentframework.tools import ToolResult

  async def execute(self, path: str, **kwargs) -> ToolResult:
      if not self.validator.check_path_traversal(path):
          return ToolResult(error="Path traversal blocked")
      try:
          content = full_path.read_text()
          return ToolResult(content=content)
      except Exception as e:
          return ToolResult(error=str(e))
  ```

- Agent catches exceptions and returns error messages:
  ```python
  err_msg = "Max iterations reached. The agent could not complete the task."
  self.callback_manager.on_run_error(request_id, Exception(err_msg))
  return (err_msg, current_messages)
  ```

- Validation errors from Pydantic bubble up as error strings in ToolResult

**Error Types:**
- Return `ToolResult(error="message")` for failures
- Raise exceptions for truly exceptional cases
- No custom exception classes defined

## Logging

**Framework:** Python standard library `logging`

**Patterns:**
- Module-level logger: `logger = logging.getLogger(__name__)`
- Structured logging with `extra` dict for contextual data:
  ```python
  logger.debug(
      "tool_execution",
      extra={
          "request_id": request_id,
          "iteration": iteration,
          "timings": timings,
          "total_latency": total_latency,
      },
  )
  ```

- JsonFormatter available in `src/agentframework/logging_utils.py` for structured JSON logs
- Configuration via `configure_logging(debug_enabled, debug_json=False)`

**Log Levels:**
- `logger.debug()` for detailed execution flow
- No `logger.info()` observed in core code
- No `logger.warning()` or `logger.error()` in core code

## Comments

**When to Comment:**
- Docstrings on classes and public methods:
  ```python
  class Agent:
      """An AI agent with tool-calling capabilities."""

      async def run(self, user_input: str) -> str:
          """Run the agent with user input and return the response."""
  ```
- Inline comments explaining workarounds or complex logic
- Type hints on function signatures (not redundant docstring params)

**JSDoc/TSDoc:**
- Not applicable (Python project)
- Use Google-style docstrings for complex methods

**Ruff disable comments:**
```python
# ruff: noqa: E402
```

## Function Design

**Size:**
- No strict limits
- Core methods in `Agent` class: 50-100 lines for `_run_loop()`
- Tool execute methods: typically 30-70 lines

**Parameters:**
- Type annotated
- Default values when optional
- `**kwargs` accepted but not overused

**Return Values:**
- Always type annotated
- Dataclasses for complex returns: `ToolResult`, `tuple[str, list[Message]]`
- Union types: `ToolResult(content=str) | ToolResult(error=str)`

## Module Design

**Exports:**
- Explicit `__all__` not used
- Public API via `__init__.py` imports

**Barrel Files:**
- `src/agentframework/tools/__init__.py` - imports all tools and exports `TOOL_REGISTRY`
- `src/agentframework/providers/__init__.py` - exports providers

**Package Structure:**
```
src/agentframework/
├── __init__.py
├── agent.py
├── tools/
│   ├── __init__.py    # Barrel
│   ├── file.py
│   ├── bash.py
│   └── ...
└── providers/
    ├── __init__.py    # Barrel
    ├── anthropic.py
    └── ...
```

---

*Convention analysis: 2026-03-08*
