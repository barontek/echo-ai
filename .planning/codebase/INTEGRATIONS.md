# External Integrations

**Analysis Date:** 2026-03-08

## APIs & External Services

**LLM Providers:**

- **Anthropic (Claude)** - Primary cloud LLM provider
  - SDK: `anthropic` Python package
  - Auth: `ANTHROPIC_API_KEY` environment variable
  - Implementation: `src/agentframework/providers/anthropic.py`
  - Features: chat, streaming, structured extraction via instructor

- **OpenAI (GPT)** - Alternative cloud LLM provider
  - SDK: `openai` Python package
  - Auth: `OPENAI_API_KEY` environment variable
  - Implementation: `src/agentframework/providers/openai.py`
  - Features: chat, streaming, structured extraction via instructor

- **Ollama** - Local LLM runtime
  - SDK: Native HTTP API via httpx
  - Auth: No auth (local)
  - Default endpoint: `http://localhost:11434`
  - Implementation: `src/agentframework/providers/ollama.py`

**Search:**

- **DuckDuckGo** - Web search via ddgs package
  - Implementation: `src/agentframework/tools/web.py` - WebSearchTool
  - Used by: web_search tool
  - Note: ddgs package wraps DuckDuckGo HTML results

## Data Storage

**SQLite:**
- Type: Local file-based relational database
- Client: `sqlite3` (stdlib) for sync, `aiosqlite` for async
- Used by:
  - `src/agentframework/tools/db.py` - SQLiteQueryTool, SQLiteSchemaTool
  - `src/agentframework/session.py` - Session storage/history
- Connection: Direct file path (user-provided)

**Vector Database (ChromaDB):**
- Type: Embedding vector store for semantic search
- Client: `chromadb` Python package
- Implementation: `src/agentframework/vector.py`
- Default location: `.agent_vector_db/` directory
- Used by:
  - `src/agentframework/tools/rag.py` - RAG tool
  - `src/agentframework/tools/memory.py` - Semantic memory

**Session Storage:**
- Type: SQLite via SQLAlchemy
- Location: `sessions.db` (configurable)
- Implementation: `src/agentframework/session.py`, `src/agentframework/session_runtime.py`

## Authentication & Identity

**API Key Authentication:**
- Approach: Environment variables for cloud providers
- Providers: Anthropic, OpenAI
- Keys required:
  - `ANTHROPIC_API_KEY` - For Claude API
  - `OPENAI_API_KEY` - For OpenAI API

**No User Authentication:**
- The framework itself does not implement user authentication
- Deployed APIs may need external auth layer for production use

## Monitoring & Observability

**Logging:**
- Approach: Python standard logging module
- Implementation: `src/agentframework/logging_utils.py`
- Log levels: Configurable via Python logging

**OpenTelemetry:**
- Implementation: `src/agentframework/otel.py`
- Status: Present but usage details not fully explored

## CI/CD & Deployment

**Hosting:**
- Multiple deployment options:
  - FastAPI server (uvicorn) - API at `/chat`, `/route`, `/stream`
  - Streamlit app - Web dashboard
  - CLI - Terminal interface

**Development Tools:**
- pre-commit hooks configured (`.prettierrc` exists)
- pytest for testing

## Environment Configuration

**Required env vars:**
- `ANTHROPIC_API_KEY` - Anthropic Claude API key
- `OPENAI_API_KEY` - OpenAI API key
- `OLLAMA_HOST` - Ollama server URL (optional, default: http://localhost:11434)

**Optional env vars:**
- `OPENCODE_AI_API_KEY` - For OpenCode plugin integration

**Configuration file:**
- `config.yaml` in project root or working directory
- Sections: model, tools, safety, agent, api_keys

## Webhooks & Callbacks

**Incoming:**
- FastAPI endpoints:
  - `POST /chat` - Chat completion
  - `POST /route` - Semantic routing
  - `GET /stream` - Server-Sent Events streaming

**Outgoing:**
- Web fetch tool: `src/agentframework/tools/web.py` - WebFetchTool
- Network requests controlled by safety config:
  - `allow_network` boolean
  - `allowed_domains` whitelist
  - `require_approval_for` list

---

*Integration audit: 2026-03-08*
