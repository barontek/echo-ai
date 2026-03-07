# Technology Stack

**Analysis Date:** 2026-03-08

## Languages

**Primary:**
- Python 3.11+ - Core language for all agent framework functionality

**Secondary:**
- JavaScript/TypeScript - Minimal (`.opencode/package.json` for OpenCode plugin)

## Runtime

**Environment:**
- Python 3.11+ with asyncio for async/await patterns
- uv as package manager (detected from requirements.txt header)

**Package Manager:**
- uv (via `uv pip compile`)
- Lockfile: `requirements.txt` (auto-generated)

## Frameworks

**Core:**
- FastAPI 0.135.1+ - REST API server for agent capabilities
- Streamlit 1.55.0+ - Web UI dashboard
- Textual 8.0.2+ - Terminal UI
- Pydantic 2.0+ - Data validation and settings

**Testing:**
- pytest 7.0.0+ - Test runner
- pytest-asyncio 0.21.0+ - Async test support
- pytest-httpx 0.30.0+ - HTTP mocking

**Build/Dev:**
- hatchling - Build backend
- ruff 0.3.0+ - Linting
- pyright 1.1.300+ - Type checking
- mkdocs 1.5.0+ - Documentation

## Key Dependencies

**AI Providers (Critical):**
- anthropic 0.25.0+ - Claude API SDK
- openai 1.0.0+ - OpenAI API SDK
- instructor 1.14.5+ - Structured output from LLMs (wraps OpenAI/Anthropic)
- tiktoken 0.7.0+ - Token counting

**HTTP & Networking:**
- httpx 0.27.0+ - Async HTTP client for web fetching
- aiohttp 3.9.0+ - Async HTTP (alternative/underlying)

**Data Storage:**
- chromadb 1.5.3+ - Vector database for semantic memory/RAG
- sqlalchemy 2.0.48+ - SQL ORM
- aiosqlite 0.22.1+ - Async SQLite driver
- sqlite3 (stdlib) - Native SQLite for session storage

**Web Scraping:**
- beautifulsoup4 4.12.0+ - HTML parsing
- markdownify 0.14.0+ - HTML to Markdown conversion

**Search:**
- ddgs 9.0.0+ - DuckDuckGo search API

**CLI & UI:**
- rich 13.0.0+ - Rich terminal output
- prompt_toolkit 3.0.0+ - Interactive CLI prompts

**Utilities:**
- pyyaml 6.0+ - YAML configuration
- tenacity 8.0.0+ - Retry logic for API calls

## Configuration

**Environment:**
- YAML-based config via `config.yaml`
- Environment variables for API keys:
  - `ANTHROPIC_API_KEY`
  - `OPENAI_API_KEY`
  - `OLLAMA_HOST` (default: http://localhost:11434)
- Config search paths (in order):
  1. `config.yaml` in current working directory
  2. `config.yaml` in project root
  3. `~/vibe-ai/config.yaml`

**Build:**
- `pyproject.toml` - Primary project configuration
- `config.yaml` - Runtime configuration

## Platform Requirements

**Development:**
- Python 3.11+
- uv or pip for package management

**Production:**
- FastAPI server (via uvicorn) for API endpoints
- Streamlit standalone for web UI
- SQLite for local data persistence

---

*Stack analysis: 2026-03-08*
