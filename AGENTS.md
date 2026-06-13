# AGENTS.md

## Commands

```bash
# Backend (Python)
make install          # Create venv and install package
make test             # Run pytest with coverage
make verify           # Quality gate: pytest → ruff → pyright
make lint             # ruff check
make typecheck        # pyright src/
make security         # pip-audit + bandit

# Frontend (React)
cd frontend && npm install
cd frontend && npm run test:run    # vitest
cd frontend && npm run lint
cd frontend && npm run typecheck
cd frontend && npm run build
cd frontend && npm run check        # lint + typecheck + test + build
```

## Architecture

- **Python package source**: `src/agentframework/` (pyproject.toml defines this)
- **Entry points**: `agent` (CLI), `agentframework.chat` (interactive), `agentframework.web_api` (FastAPI)
- **Frontend entry**: `frontend/src/main.tsx`
- **Session storage**: SQLite in `~/.echo-ai/sessions/`
- **State management**: `router.py` (semantic sub-agent routing), `session.py`/`memory.py` (context retention)
- **Providers**: `src/agentframework/providers/` (Anthropic, OpenAI, Ollama) - must align with standardized interface
- **Tools**: `src/agentframework/tools/` - new tools must be modular, self-contained, registered in config.yaml

## Frontend Communication

- WebSocket: `/ws/chat`
- SSE streaming: `/api/stream`
- REST API: `/api/chat`

## Key Constraints

- **Python**: Requires 3.11+
- **Package manager**: Use `uv` for ALL Python operations (installs, running tools, pytest, etc.)
- **Never use pip directly**
- **PYTHONPATH**: Must be set to `src` when running tests (`PYTHONPATH=src pytest ...`)
- **Pre-commit**: Local hooks run `uv run pyright`, so uv must be available

## Quality Gates

- **Backend**: `make verify` (pytest → ruff → pyright). Pyright strict typing required.
- **Frontend**: ESLint + Prettier + Vitest. Run `npm run check` before submitting PRs.

## Security Module

You are authorized to read, modify, override, or disable `src/agentframework/safety.py` as needed:
- Workspace confinement parameters
- Bash command allowlist
- Sensitive file protections (.env, .pem, .key blocking)
- Dangerous pattern detection

## Code Standards

- All new functions: explicit error logging, complete parameter typing, return type hints
- Provide only functional code diffs; omit conversational filler
- Use `pytest.mark.asyncio` for async backend tests
