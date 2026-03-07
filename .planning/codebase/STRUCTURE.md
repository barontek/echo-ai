# Codebase Structure

**Analysis Date:** 2026-03-08

## Directory Layout

```
/home/barontek/opencode-project/
├── src/agentframework/          # Main package
│   ├── providers/               # LLM provider implementations
│   ├── tools/                  # Tool implementations
│   ├── __init__.py              # Public API exports
│   ├── agent.py                 # Core Agent class
│   ├── bootstrap.py             # Setup and wiring
│   ├── callbacks.py             # Event callbacks
│   ├── chat.py                  # Chat UI components
│   ├── chat_commands.py         # Slash commands
│   ├── chat_render.py           # Rendering helpers
│   ├── chat_runtime.py          # Undo/redo runtime
│   ├── cli.py                   # CLI entry point
│   ├── config.py                # Configuration loader
│   ├── conversation.py          # Message handling
│   ├── logging_utils.py          # Logging setup
│   ├── router.py                # Semantic routing
│   ├── safety.py                # Security validation
│   ├── session.py               # Session management
│   ├── session_runtime.py       # Session serialization
│   ├── tool_runtime.py          # Tool execution
│   ├── vector.py                # Vector DB helpers
│   ├── workflow.py               # Workflow helpers
│   └── web_ui.py                # Web UI entry
├── tests/                       # Test suite
│   ├── eval/                    # Evaluation helpers
│   ├── conftest.py              # Pytest fixtures
│   └── test_*.py                # Test modules
├── config.yaml                  # Default configuration
├── requirements.txt            # Runtime dependencies
├── requirements-dev.txt         # Dev dependencies
├── agent                       # Shell launcher script
├── chat                        # Chat shell script
├── Makefile                    # Build tasks
├── pyproject.toml              # Project metadata
└── mkdocs.yml                  # Documentation config
```

## Directory Purposes

**`src/agentframework/`:**
- Purpose: Main Python package containing all framework code
- Contains: Core agent, tools, providers, session, CLI, config
- Key files: `agent.py`, `cli.py`, `bootstrap.py`

**`src/agentframework/providers/`:**
- Purpose: LLM provider implementations
- Contains: `anthropic.py`, `openai.py`, `ollama.py`
- Pattern: Each file implements `LLMProvider` interface

**`src/agentframework/tools/`:**
- Purpose: Tool implementations available to the agent
- Contains: 14+ tool modules (bash, file, web, git, memory, notes, etc.)
- Key files: `__init__.py` (registry), `bash.py`, `file.py`, `memory.py`

**`tests/`:**
- Purpose: Test suite using pytest
- Contains: Unit tests, integration tests, E2E tests
- Pattern: `test_<module>.py` naming

**`scripts/`:**
- Purpose: Utility scripts (if present)

**`docs/`:**
- Purpose: Documentation source

**`site/`:**
- Purpose: Built documentation (mkdocs output)

## Key File Locations

**Entry Points:**
- `src/agentframework/cli.py`: CLI interface (`python -m agentframework.cli`)
- `src/agentframework/bootstrap.py`: `setup_agent()` factory
- `src/agentframework/agent.py`: `Agent` class and `create_agent()` factory

**Configuration:**
- `config.yaml`: Default configuration file
- `src/agentframework/config.py`: Configuration loader

**Core Logic:**
- `src/agentframework/agent.py`: Main agent loop (`run()`, `run_streaming()`)
- `src/agentframework/conversation.py`: Message handling
- `src/agentframework/session.py`: Session persistence
- `src/agentframework/tool_runtime.py`: Tool execution

**Testing:**
- `tests/conftest.py`: Pytest fixtures and setup
- `tests/test_agent.py`: Core agent tests
- `tests/test_tools.py`: Tool tests

## Naming Conventions

**Files:**
- Modules: `snake_case.py` (e.g., `agent.py`, `tool_runtime.py`)
- Tests: `test_<module>.py` (e.g., `test_agent.py`, `test_tools.py`)
- Private: Leading underscore for internal modules

**Functions:**
- Functions: `snake_case` (e.g., `setup_agent`, `execute_tool_calls`)
- Methods: `snake_case` (e.g., `run()`, `_prepare_messages()`)
- Private: Leading underscore (e.g., `_execute_tool_calls()`)

**Classes:**
- Classes: `PascalCase` (e.g., `Agent`, `Tool`, `LLMProvider`)
- Dataclasses: `PascalCase` (e.g., `AgentConfig`, `Message`)

**Constants:**
- Constants: `UPPER_SNAKE_CASE` (e.g., `TOOL_REGISTRY`)

## Where to Add New Code

**New Tool:**
- Implementation: `src/agentframework/tools/<tool_name>.py`
- Registration: Add to `TOOL_REGISTRY` in `src/agentframework/tools/__init__.py`
- Config keys: Add to `TOOL_CONFIG_KEYS` in same file
- Tests: `tests/test_<tool_name>_tool.py`

**New LLM Provider:**
- Implementation: `src/agentframework/providers/<provider_name>.py`
- Registration: Add to `get_provider()` factory in `src/agentframework/providers/__init__.py`
- Must implement `LLMProvider` abstract class

**New Feature:**
- Core logic: Add to appropriate module in `src/agentframework/`
- Configuration: Add to `config.yaml` schema and `src/agentframework/config.py`
- Tests: Add to `tests/`

**New CLI Command:**
- Implementation: `src/agentframework/chat_commands.py`
- Handler: Add branch in `src/agentframework/cli.py:interactive_mode()`

**Utilities:**
- Shared helpers: Add to existing module or create new module in `src/agentframework/`

## Special Directories

**`.agent_sessions/`:**
- Purpose: SQLite database for session persistence
- Generated: Yes (runtime)
- Committed: No (in .gitignore)

**`.test_agent_vector_db/`:**
- Purpose: Chroma vector database for RAG tests
- Generated: Yes (tests)
- Committed: No

**`.venv/`:**
- Purpose: Python virtual environment
- Generated: Yes
- Committed: No

**`site/`:**
- Purpose: Built documentation
- Generated: Yes (mkdocs build)
- Committed: Yes (for GitHub Pages)

## Project Structure Notes

**Layer Dependencies (Inbound):**
```
CLI → Bootstrap → Agent → Providers/Tools/Session/Callbacks
```

**No cyclic dependencies:** Tools are registered, not imported eagerly. Provider factory pattern defers imports.

**Configuration-driven:** Tools are instantiated based on `config.yaml` - no hardcoded tool lists.

---

*Structure analysis: 2026-03-08*
