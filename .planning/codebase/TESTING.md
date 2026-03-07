# Testing Patterns

**Analysis Date:** 2026-03-08

## Test Framework

**Runner:**
- pytest 7.0.0+
- pytest-asyncio 0.21.0+ for async test support
- Config: `pyproject.toml` `[tool.pytest.ini_options]`

**Assertion Library:**
- pytest built-in assertions (`assert`, `assert ... in ...`)

**Run Commands:**
```bash
pytest                    # Run all tests
pytest -v                 # Verbose output
pytest -m asyncio         # Run only async tests
pytest --cov=src          # With coverage
pytest tests/test_agent.py  # Specific file
```

## Test File Organization

**Location:**
- Co-located with source in `tests/` directory (separate from `src/`)
- Parallel structure: `tests/test_<module>.py` maps to `src/agentframework/<module>.py`

**Naming:**
- Test files: `test_<feature>.py` (e.g., `test_agent.py`, `test_tools.py`)
- Test classes: `Test<ClassName>` (e.g., `TestAgent`, `TestSanitizeJson`)
- Test methods: `test_<description>` (snake_case, descriptive)

**Structure:**
```
tests/
├── __init__.py
├── conftest.py           # Bootstrap helpers
├── test_agent.py         # Agent tests
├── test_tools.py         # Tool system tests
├── test_providers.py     # LLM provider tests
├── test_api_tool.py      # API tool tests
└── ...                   # More test files
```

## Test Structure

**Suite Organization:**
```python
"""Tests for Agent class."""  # Module docstring

import pytest

from src.agentframework.agent import Agent, AgentConfig
from src.agentframework.tools import Tool, ToolResult
from src.agentframework.providers import LLMProvider, LLMResponse, LLMToolCall


class MockProvider(LLMProvider):
    """Mock LLM provider for testing."""

    def __init__(self, responses: list[LLMResponse] | None = None):
        self.responses = responses or []
        self.call_count = 0

    async def chat(self, messages, tools=None, temperature=0.3) -> LLMResponse:
        # Implementation
        return LLMResponse(content="Done")


class TestSanitizeJson:
    """Tests for _sanitize_json method."""

    def test_strips_json_code_block(self):
        json_str = '```json\n{"key": "value"}\n```'
        result = Agent._sanitize_json(json_str)
        assert '{"key": "value"}' in result
```

**Patterns:**
- Fixtures for test data and common setup
- Class-based test organization with `Test<ClassName>`
- Method-based tests within classes
- Async tests marked with `@pytest.mark.asyncio`

## Mocking

**Framework:** unittest.mock (Python standard library)

**Patterns:**

1. **Mock LLM Provider:**
   ```python
   class MockProvider(LLMProvider):
       """Mock LLM provider for testing."""

       def __init__(self, responses: list[LLMResponse] | None = None):
           self.responses = responses or []
           self.call_count = 0

       async def chat(self, messages, tools=None, temperature=0.3) -> LLMResponse:
           if self.responses and self.call_count < len(self.responses):
               resp = self.responses[self.call_count]
               self.call_count += 1
               return resp
           return LLMResponse(content="Done")
   ```

2. **Mock Tool:**
   ```python
   class MockTool(Tool):
       """Mock tool for testing."""

       parameters_model = MockToolParams

       def __init__(self):
           super().__init__(name="mock", description="A mock tool")
           self.executed = False

       async def execute(self, command: str, count: int = 1, **kwargs) -> ToolResult:
           self.executed = True
           return ToolResult(content=f"Executed {command} {count} times")
   ```

3. **Mock with unittest.mock.patch:**
   ```python
   from unittest.mock import AsyncMock, patch, MagicMock

   @pytest.mark.asyncio
   async def test_openai_chat():
       with patch("agentframework.providers.openai.AsyncOpenAI") as mock_openai:
           mock_client = mock_openai.return_value
           mock_response = AsyncMock()
           mock_msg = MagicMock()
           mock_msg.content = "OpenAI Response"
           mock_msg.tool_calls = None
           mock_response.choices = [MagicMock(message=mock_msg)]
           mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

           provider = OpenAIProvider(model="gpt-4", api_key="test-key")
           resp = await provider.chat([{"role": "user", "content": "hi"}])
           assert resp.content == "OpenAI Response"
   ```

4. **respx for HTTP mocking:**
   ```python
   import respx
   import httpx

   @pytest.mark.asyncio
   @respx.mock
   async def test_ollama_chat():
       provider = OllamaProvider(model="llama3")

       respx.post("http://localhost:11434/api/chat").mock(
           return_value=httpx.Response(
               200,
               json={
                   "message": {
                       "role": "assistant",
                       "content": "Ollama Response",
                   }
               }
           )
       )

       resp = await provider.chat([{"role": "user", "content": "hi"}])
       assert resp.content == "Ollama Response"
   ```

**What to Mock:**
- LLM providers (API calls)
- HTTP responses (respx)
- External services
- Database connections (via fixtures with temp directories)

**What NOT to Mock:**
- Internal logic being tested
- Tool execution (test real tools with fixtures)
- Pydantic validation (test with real validation)

## Fixtures and Factories

**Test Data:**
```python
@pytest.fixture
def temp_dir(self):
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir

@pytest.fixture
def tool(self, temp_dir):
    config = SafetyConfig(workspace=temp_dir)
    return ReadFileTool(base_dir=temp_dir, safety_config=config)

@pytest.fixture
def test_file(self, temp_dir):
    path = Path(temp_dir) / "test.txt"
    path.write_text("Hello, World!")
    return path
```

**Location:**
- Inline fixtures in test files (co-located with tests)
- `tests/conftest.py` for bootstrap helpers

## Coverage

**Requirements:** No strict target enforced

**View Coverage:**
```bash
pytest --cov=src --cov-report=html
```

**Coverage packages:**
- pytest-cov 4.1.0

## Test Types

**Unit Tests:**
- Test individual methods: `test_sanitize_json()`, `test_tool_schema()`
- Mock external dependencies (LLM providers, HTTP)
- Fast execution, isolated

**Integration Tests:**
- `test_integration_agent_flow.py` - end-to-end agent flows
- Real tool execution with temporary directories
- Test file system tools with temp files/dirs

**E2E Tests:**
- `test_agent_e2e.py` - full agent workflows
- More comprehensive, slower

**Test Markers:**
- `@pytest.mark.asyncio` - async test functions
- Custom marker: `asyncio` registered in pytest config

## Common Patterns

**Async Testing:**
```python
@pytest.mark.asyncio
async def test_read_file(tool, test_file):
    result = await tool.execute(path="test.txt")
    assert result.error is None
    assert "Hello, World!" in result.content
```

**Error Testing:**
```python
@pytest.mark.asyncio
async def test_read_nonexistent_file(tool):
    result = await tool.execute(path="does_not_exist.txt")
    assert result.error is not None
    assert "not found" in result.error.lower()
```

**Fixture-based Isolation:**
```python
@pytest.fixture
def temp_dir(self):
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir
```

**Parameterized Testing:** Not observed in codebase

---

*Testing analysis: 2026-03-08*
