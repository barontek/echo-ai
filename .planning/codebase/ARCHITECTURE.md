# Architecture

**Analysis Date:** 2026-03-08

## Pattern Overview

**Overall:** Agentic Tool-Calling Framework with Multi-Provider LLM Support

This is an AI agent framework that orchestrates conversations between a user, an LLM, and a suite of tools. The agent uses a REPL-style loop: receive user input → query LLM → execute tool calls → repeat until final response.

**Key Characteristics:**
- **Reactive Tool Execution**: Agent iterates until LLM returns no more tool calls (max iterations configurable Abstraction**: Pl)
- **Provideruggable LLM providers (OpenAI, Anthropic, Ollama) via `LLMProvider` interface
- **Session Persistence**: SQLite-backed conversation sessions with undo/redo capability
- **Safety First**: Security validation and approval workflows before dangerous operations
- **Sub-Agent Delegation**: Dynamic routing to specialized sub-agents via `SemanticRouter`

## Layers

### Core Layer
**Location:** `src/agentframework/`

**Files:** `agent.py`, `conversation.py`, `session.py`, `tool_runtime.py`

- **Purpose:** Main agent loop and state management
- **Depends on:** Providers, tools, session, callbacks
- **Used by:** CLI, bootstrap, chat interfaces

### Provider Layer
**Location:** `src/agentframework/providers/`

**Files:** `__init__.py`, `anthropic.py`, `openai.py`, `ollama.py`

- **Purpose:** Abstract LLM interactions behind a common interface
- **Interface:** `LLMProvider` abstract class with `chat()`, `chat_streaming()`, `extract_structured()` methods
- **Depends on:** External API SDKs (anthropic, openai, httpx)
- **Used by:** Agent core

### Tool Layer
**Location:** `src/agentframework/tools/`

**Files:** `__init__.py`, `bash.py`, `file.py`, `search.py`, `web.py`, `git.py`, `memory.py`, `notes.py`, `python.py`, `api.py`, `db.py`, `human.py`, `rag.py`, `delegate.py`

- **Purpose:** Action executors available to the LLM
- **Interface:** `Tool` abstract class with `execute()` method and JSON schema
- **Registry:** `TOOL_REGISTRY` dictionary for dynamic tool lookup
- **Tool Runtime:** `tool_runtime.py` handles validation, execution, error categorization, and parallel execution
- **Used by:** Agent core via tool map

### Session & State Layer
**Locationagentframework/session.py`

- **:** `src/Purpose:** Persist conversation history to SQLite, track file changes for undo/redo
- **Components:** `SessionManager`, `ChangeTracker`, `DBSessionModel` (SQLAlchemy)
- **Depends on:** SQLAlchemy, SQLite

### Safety Layer
**Location:** `src/agentframework/safety.py`

- **Purpose:** Validate operations against security policies, require user approval for dangerous actions
- **Components:** `SafetyConfig`, `SecurityValidator`
- **Used by:** Tool runtime, config loader

### Configuration Layer
**Location:** `src/agentframework/config.py`, `config.yaml`

- **Purpose:** Load YAML configuration, instantiate tools with config, build safety config
- **Lookup:** `find_config_path()` searches cwd, script dir, ~/vibe-ai/

### Bootstrap Layer
**Location:** `src/agentframework/bootstrap.py`

- **Purpose:** Wire up all components: load config → create provider → instantiate tools → create agent
- **Entry point:** `setup_agent()` returns fully configured `Agent` instance
- **Used by:** CLI, chat runtime

### CLI Layer
**Location:** `src/agentframework/cli.py`

- **Purpose:** Command-line interface with interactive mode and streaming output
- **Entry point:** `main()` - handles `--debug`, `--debug-json` flags
- **Commands:** `/save`, `/load`, `/chats`, `/undo`, `/redo`, `/help`, `/exit`

## Data Flow

**Single Turn Execution:**

1. **User Input** → CLI (`cli.py`) receives text
2. **Session Record** → `SessionManager.add_message()` persists user message
3. **Message Preparation** → `Agent._prepare_messages()` applies context window (sliding window + summarization)
4. **LLM Query** → `llm.chat()` with tool schemas returns `LLMResponse` (content + tool_calls)
5. **Tool Execution** (loop until no tool_calls):
   - `tool_runtime.execute_tool_calls()` validates args via Pydantic
   - Executes tool via `Tool.execute()`
   - Records file changes in `ChangeTracker` for undo
   - Returns tool result as `Message`
6. **Final Response** → Assembled from last assistant message
7. **Session Persist** → `SessionManager.add_message()` saves assistant response

**Session Persistence:**

- Sessions stored in `.agent_sessions/agent_sessions.db` (SQLite)
- Messages serialized via `serialize_messages()` / `deserialize_messages()`

## Key Abstractions

**Agent Configuration:**
- Dataclass `AgentConfig` in `agent.py` holds: provider, model, temperature, max_iterations, tools, session settings
- Dataclass `SubAgentConfig` for sub-agent registration

**Message Model:**
- Dataclass `Message` in `conversation.py`: role (user/assistant/system/tool), content, tool_call_id, tool_name, tool_arguments, error_category
- Helper functions: `create_assistant_message()`, `format_messages_for_llm()`, `sanitize_json()`

**Tool Interface:**
- Abstract class `Tool` in `tools/__init__.py`: name, description, schema property, `execute()` async method
- `ToolResult` dataclass: content, error
- Pydantic `parameters_model` for JSON schema generation

**LLM Response:**
- Dataclass `LLMResponse`: content (str), tool_calls (list[LLMToolCall])
- Dataclass `LLMToolCall`: id, name, arguments

**Provider Interface:**
- Abstract class `LLMProvider`: `chat()`, `chat_streaming()`, `extract_structured()`
- Factory `get_provider(name, model, api_key, base_url)` returns configured provider

## Entry Points

**CLI Entry:**
- `src/agentframework/cli.py:main()` - invoked via `agent` script or `python -m agentframework.cli`
- Shell scripts: `agent`, `chat` (in project root)

**Programmatic Entry:**
- `src/agentframework/bootstrap.py:setup_agent()` - recommended entry point
- `src/agentframework.agent:create_agent()` - lower-level factory

**Module Entry:**
- `python -m agentframework.cli` - runs main()
- `python -m agentframework.web_ui` - optional web UI

## Error Handling

**Strategy:** Categorized tool errors with graceful degradation

**Patterns:**
- `ToolError` dataclass with category: `validation_error`, `policy_denied`, `execution_error`, `tool_not_found`
- `format_tool_failure()` returns categorized error message
- Validation via Pydantic `parameters_model.model_validate()`
- LLM failures logged but don't crash agent loop
- Max iterations limit prevents infinite loops

## Cross-Cutting Concerns

**Logging:** Uses Python `logging` module with structured extras (request_id, iteration, timings)
- Configured in `logging_utils.py`

**Validation:** Pydantic models for tool parameters, LLM response extraction

**Authentication:** API keys from environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`)
- Credentials checked in `bootstrap.py:ensure_provider_credentials()`

**Security:**
- Workspace confinement via `SafetyConfig`
- Approval callbacks for dangerous tools
- Blocked command lists
- Audit logging to file

---

*Architecture analysis: 2026-03-08*
